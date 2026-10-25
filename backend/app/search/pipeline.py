"""Boss2: three shared-queue search workers, verifier, discovery and parser.

All provider calls have finite budgets. Cancellation propagates to the caller;
budget exhaustion returns the facts already verified with per-source errors.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, TypeVar

from app.models import Product, ProductCatalog, SourceStatus, StyleBrief

from .demo import demo_candidates, demo_products
from .discovery import DiscoveryBatch, DiscoveryProvider, PublicWebDiscoveryProvider
from .extraction import ProductCandidate, detect_block_page, extract_candidates
from .parser import canonical_product_url, is_verified_live_product, normalize_catalog
from .sources import BASE_SOURCES, SourceDefinition
from .transport import AsyncFetcher, FetchError
from .verifier import ProductVerifier, VerificationResult

SourceCallback = Callable[[SourceStatus], Awaitable[None]]
T = TypeVar("T")
SEARCH_WORKERS = 3
_TERMINAL = {"complete", "inaccessible", "unconfigured", "failed"}


@dataclass(frozen=True)
class SearchBudgets:
    total_seconds: float = 45.0
    source_seconds: float = 8.0
    verification_seconds: float = 6.0
    discovery_seconds: float = 8.0
    callback_seconds: float = 0.2
    candidates_per_source: int = 4
    discovery_candidates: int = 12
    max_products: int = 40

    def __post_init__(self) -> None:
        for name in ("total_seconds", "source_seconds", "verification_seconds", "discovery_seconds", "callback_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite duration")
        for name in ("candidates_per_source", "discovery_candidates", "max_products"):
            if not 1 <= getattr(self, name) <= 100:
                raise ValueError(f"{name} must be between 1 and 100")


class _CallTimeout(TimeoutError):
    pass


def _consume(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


async def _bounded(awaitable: Awaitable[T], seconds: float) -> T:
    """Do not let a non-cooperative injected callback hold the pipeline open."""
    task = asyncio.ensure_future(awaitable)
    try:
        done, _ = await asyncio.wait({task}, timeout=max(0.001, seconds))
        if task not in done:
            raise _CallTimeout(f"Operation exceeded {seconds:g}s budget")
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            task.add_done_callback(_consume)


def _state(value: str) -> str:
    return {"blocked": "inaccessible", "unsupported": "unconfigured"}.get(
        value, value if value in _TERMINAL else "failed")


@dataclass
class _Report:
    source_id: str
    name: str
    state: str = "queued"
    accepted: int = 0
    candidates: int = 0
    rejected: int = 0
    pending: int = 0
    search_done: bool = False
    finalized: bool = False
    detail: str = ""
    rejection_details: list[str] = field(default_factory=list)

    def snapshot(self) -> SourceStatus:
        return SourceStatus(source_id=self.source_id, name=self.name, state=self.state,
                            found=self.accepted, detail=self.detail or None)


class SearchPipeline:
    """Inject providers for tests/deployments; the base worker count is fixed."""

    def __init__(self, *, fetcher=None, verifier=None,
                 discovery_provider: DiscoveryProvider | None = None,
                 sources: tuple[SourceDefinition, ...] = BASE_SOURCES,
                 budgets: SearchBudgets | None = None) -> None:
        self.budgets = budgets or SearchBudgets()
        self.fetcher = fetcher if fetcher is not None else AsyncFetcher(timeout_seconds=self.budgets.source_seconds)
        self.verifier = verifier if verifier is not None else ProductVerifier(self.fetcher)
        self.discovery_provider = discovery_provider if discovery_provider is not None else PublicWebDiscoveryProvider(self.fetcher)
        self.sources = tuple(sources)
        ids = [s.id for s in self.sources]
        if len(ids) != len(set(ids)) or "discovery" in ids:
            raise ValueError("Source IDs must be unique and may not be discovery")

    async def search(self, brief: StyleBrief, on_source: SourceCallback | None = None) -> ProductCatalog:
        budget = self.budgets
        deadline = time.monotonic() + budget.total_seconds
        reports = {s.id: _Report(s.id, s.name) for s in self.sources}
        reports["discovery"] = _Report("discovery", "Открытый интернет · discovery")
        products: list[Product] = []
        warnings: list[str] = []
        candidate_queue: asyncio.Queue[tuple[ProductCandidate, str] | None] = asyncio.Queue()
        source_queue: asyncio.Queue[tuple[int, SourceDefinition]] = asyncio.Queue()
        for index, source in enumerate(self.sources):
            source_queue.put_nowait((index, source))
        seen: set[str] = set()
        admitted_urls: set[str] = set()
        fixtures: dict[str, Product] = {}

        def remaining(cap: float) -> float:
            return max(0.001, min(cap, deadline - time.monotonic()))

        async def emit(report: _Report) -> None:
            if on_source is None:
                return
            try:
                await _bounded(on_source(report.snapshot()), remaining(budget.callback_seconds))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                note = f"Progress callback failed ({type(exc).__name__}); search continued."
                if note not in warnings:
                    warnings.append(note)

        async def finalize_report(report: _Report) -> None:
            if report.search_done and report.pending == 0 and not report.finalized and report.state not in {"inaccessible", "unconfigured", "failed"}:
                report.finalized = True
                report.state = "complete"
                counts = f"Ссылок: {report.candidates}; подтверждено: {report.accepted}; отклонено: {report.rejected}."
                if brief.mode == "demo":
                    counts = f"Демо: {report.accepted} учебных карточек, без сетевых запросов."
                report.detail = " ".join(x for x in (report.detail, counts) if x)
                if report.rejection_details:
                    report.detail += " " + " | ".join(dict.fromkeys(report.rejection_details))[:900]
                await emit(report)

        def enqueue(candidate: ProductCandidate, report: _Report) -> None:
            try:
                key = canonical_product_url(candidate.url)
            except (ValueError, UnicodeError):
                report.rejected += 1
                report.rejection_details.append("Извлечён некорректный URL; ссылка отклонена.")
                return
            if key in seen:
                return
            seen.add(key)
            report.candidates += 1
            report.pending += 1
            candidate_queue.put_nowait((candidate, report.source_id))

        async def base_worker() -> None:
            while True:
                try:
                    index, source = source_queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                report = reports[source.id]
                report.state = "searching"
                await emit(report)
                try:
                    if brief.mode == "demo":
                        items = demo_products(source.id, index, brief)
                        fixtures.update({p.source_url: p for p in items})
                        candidates = demo_candidates(items)
                    else:
                        query = " ".join(brief.search_queries[-2:]).strip()[:350]
                        if not query:
                            query = brief.original_request_text.strip()[:250] or "одежда"
                        page = await _bounded(self.fetcher.fetch(source.build_search_url(query)), remaining(budget.source_seconds))
                        challenge = detect_block_page(page.text)
                        if challenge:
                            raise FetchError("inaccessible", challenge + "; no bypass attempted", page.url)
                        candidates = extract_candidates(page.text, page.url, source, limit=budget.candidates_per_source)
                    for candidate in list(candidates)[:budget.candidates_per_source]:
                        enqueue(candidate, report)
                    if report.pending:
                        report.state = "verifying"
                        await emit(report)
                    elif brief.mode == "live":
                        report.detail = "Страница получена; доступные для разбора ссылки на товары не найдены (JS/формат может не поддерживаться)."
                except asyncio.CancelledError:
                    raise
                except FetchError as exc:
                    report.state, report.detail = _state(exc.state), str(exc.detail)[:1000]
                except _CallTimeout:
                    report.state, report.detail = "failed", "Истёк бюджет времени поиска источника; обход ограничений не выполнялся."
                except Exception as exc:
                    report.state, report.detail = "failed", f"Ошибка поиска источника: {type(exc).__name__}: {str(exc)[:400]}"
                finally:
                    source_queue.task_done()
                report.search_done = True
                if report.state in {"inaccessible", "unconfigured", "failed"}:
                    await emit(report)
                await finalize_report(report)

        async def discovery_worker() -> None:
            report = reports["discovery"]
            report.state = "searching"
            await emit(report)
            try:
                if brief.mode == "demo":
                    batch = DiscoveryBatch(state="unsupported", detail="Демо: внешний поиск выключен; сетевых запросов нет.")
                else:
                    batch = await _bounded(self.discovery_provider.discover(brief, limit=budget.discovery_candidates), remaining(budget.discovery_seconds))
                if batch.state == "complete":
                    for candidate in batch.candidates[:budget.discovery_candidates]:
                        enqueue(candidate, report)
                    report.state = "verifying" if report.pending else "complete"
                else:
                    report.state = _state(batch.state)
                report.detail = batch.detail[:1000]
            except asyncio.CancelledError:
                raise
            except FetchError as exc:
                report.state, report.detail = _state(exc.state), str(exc.detail)[:1000]
            except _CallTimeout:
                report.state, report.detail = "failed", "Истёк бюджет discovery; сохранены результаты базовых источников."
            except Exception as exc:
                report.state, report.detail = "failed", f"Discovery: {type(exc).__name__}: {str(exc)[:400]}"
            report.search_done = True
            await emit(report)
            await finalize_report(report)

        async def verifier_worker() -> None:
            while True:
                queued = await candidate_queue.get()
                if queued is None:
                    candidate_queue.task_done()
                    return
                candidate, report_id = queued
                report = reports[report_id]
                try:
                    if len(products) >= budget.max_products:
                        report.rejected += 1
                        report.rejection_details.append("Достигнут лимит каталога.")
                    elif brief.mode == "demo":
                        item = fixtures[candidate.url]
                        products.append(item)
                        report.accepted += 1
                    else:
                        result: VerificationResult = await _bounded(self.verifier.verify(candidate, brief), remaining(budget.verification_seconds))
                        if result.valid and result.product is not None and is_verified_live_product(result.product):
                            key = canonical_product_url(result.product.source_url)
                            if key not in admitted_urls:
                                admitted_urls.add(key)
                                products.append(result.product)
                                report.accepted += 1
                            else:
                                report.detail = "Дубликат конечного URL удалён."
                        else:
                            report.rejected += 1
                            detail = result.detail or "Неизвестные обязательные поля; карточка не подтверждена."
                            report.rejection_details.append(detail[:400])
                except asyncio.CancelledError:
                    raise
                except _CallTimeout:
                    report.rejected += 1
                    report.rejection_details.append("Истёк бюджет проверки карточки.")
                except Exception as exc:
                    report.rejected += 1
                    report.rejection_details.append(f"Ошибка verifier: {type(exc).__name__}: {str(exc)[:160]}")
                finally:
                    report.pending -= 1
                    candidate_queue.task_done()
                await finalize_report(report)

        tasks: list[asyncio.Task] = []
        try:
            for report in reports.values():
                await emit(report)
            # Exactly these three tasks consume one common queue. A worker
            # takes the next source as soon as its current source finishes.
            base_tasks = [asyncio.create_task(base_worker(), name=f"velor-base-search-{n + 1}") for n in range(SEARCH_WORKERS)]
            discovery_task = asyncio.create_task(discovery_worker(), name="velor-discovery")
            verifier_task = asyncio.create_task(verifier_worker(), name="velor-verifier")
            tasks.extend([*base_tasks, discovery_task, verifier_task])

            async def finish_producers() -> None:
                await asyncio.gather(*base_tasks, discovery_task)
                candidate_queue.put_nowait(None)

            producers_task = asyncio.create_task(finish_producers(), name="velor-producer-completion")
            tasks.append(producers_task)
            _, pending = await asyncio.wait({producers_task, verifier_task}, timeout=remaining(budget.total_seconds))
            if pending:
                warnings.append("Истёк общий бюджет поиска; возвращены только уже подтверждённые результаты.")
                for report in reports.values():
                    if report.state not in _TERMINAL or report.pending:
                        report.state = "failed"
                        report.detail = f"Общий таймаут; сохранено карточек: {report.accepted}; непроверено: {report.pending}."
            else:
                # Retrieve exceptions instead of silently turning a failed
                # worker into an apparently complete empty catalog.
                for task in (producers_task, verifier_task):
                    task.result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                # Owned workers cooperate with cancellation. Never wait on
                # arbitrary provider cleanup beyond a small finite budget.
                done, pending = await asyncio.wait(tasks, timeout=0.25)
                for task in done:
                    _consume(task)
                for task in pending:
                    task.cancel()
                    task.add_done_callback(_consume)

        for report in reports.values():
            if report.state != "complete":
                warnings.append(f"{report.name}: {report.detail or report.state}")
            if report.rejected:
                warnings.append(f"{report.name}: {report.rejected} карточек не прошли проверку; unknown не считается valid.")
            await emit(report)
        if brief.mode == "demo":
            warnings.insert(0, "ДЕМОНСТРАЦИЯ: вымышленные товары и цены, без live-поиска, проверки остатков и внешней передачи изображений.")
        elif not products:
            warnings.append("Подтверждённых товаров нет. Непроверенные карточки и вымышленные URL не добавлялись.")
        return normalize_catalog(products, [r.snapshot() for r in reports.values()], warnings, demo=brief.mode == "demo")


async def search_catalog(brief: StyleBrief, on_source: SourceCallback | None = None) -> ProductCatalog:
    return await SearchPipeline().search(brief, on_source)
