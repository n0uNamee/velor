"""Offline behavioral checks for the shared queue and finite search lifecycle."""
from __future__ import annotations

import asyncio
import time
import unittest
from urllib.parse import urlsplit

from app.models import Product, StyleBrief
from app.search.discovery import DiscoveryBatch
from app.search.extraction import ProductCandidate
from app.search.pipeline import SEARCH_WORKERS, SearchBudgets, SearchPipeline
from app.search.sources import BASE_SOURCES, SourceDefinition
from app.search.transport import FetchError, FetchPage
from app.search.verifier import VerificationResult


def brief(mode="live", **updates):
    return StyleBrief(id="brief", profile_id="profile", original_profile_text="",
                      original_request_text="чёрная футболка", search_queries=["чёрная футболка"],
                      mode=mode, **updates)


def sources(count=6):
    return tuple(SourceDefinition(f"s{n}", f"Source {n}", (f"s{n}.example.com",),
                                  f"https://s{n}.example.com/search?q={{query}}") for n in range(count))


def product(candidate, **updates):
    fields = dict(id="fixture", title="Чёрная футболка", category="tops",
                  source_id=candidate.source_id, source_url=candidate.url,
                  price_rub=1000, sizes=["M"], availability="in_stock",
                  verified_at="2026-10-25T12:00:00+00:00", verification="verified",
                  evidence=["Offline test: title/ordinary price/inventory/style/condition evidence"], is_demo=False)
    fields.update(updates)
    return Product(**fields)


class FakeFetcher:
    def __init__(self, *, delays=None, errors=None, links=1, challenge=False):
        self.delays = delays or {}
        self.errors = errors or {}
        self.links = links
        self.challenge = challenge
        self.active = self.peak = self.cancelled = 0
        self.started = []
        self.finished = []
        self.worker_names = set()

    async def fetch(self, url):
        host = urlsplit(url).hostname
        source_id = host.split(".")[0]
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.started.append((source_id, time.monotonic()))
        self.worker_names.update(t.get_name() for t in asyncio.all_tasks() if t.get_name().startswith("velor-base-search-"))
        try:
            await asyncio.sleep(self.delays.get(source_id, .001))
            if source_id in self.errors:
                raise self.errors[source_id]
            html = "<title>captcha</title>" if self.challenge else "".join(
                f'<a href="https://{host}/product/{n}">Чёрная футболка {n}</a>' for n in range(self.links))
            self.finished.append((source_id, time.monotonic()))
            return FetchPage(url, 200, html, {"content-type": "text/html"})
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1


class FakeVerifier:
    def __init__(self, *, delay=.001, result=None):
        self.delay, self.result = delay, result
        self.calls = []
        self.cancelled = False
        self.active = self.peak = 0

    async def verify(self, candidate, request):
        self.calls.append((candidate, time.monotonic()))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.active -= 1
        if self.result is not None:
            return self.result(candidate)
        return VerificationResult(product(candidate), True)


class FakeDiscovery:
    def __init__(self, batch=None, delay=0):
        self.batch = batch if batch is not None else DiscoveryBatch()
        self.delay, self.calls, self.cancelled = delay, 0, False

    async def discover(self, request, *, limit=12):
        self.calls += 1
        try:
            await asyncio.sleep(self.delay)
            return self.batch
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def make_pipeline(self, fetcher=None, verifier=None, discovery=None, source_count=6, **budgets):
        settings = dict(total_seconds=1, source_seconds=.4, verification_seconds=.2,
                        discovery_seconds=.2, callback_seconds=.02)
        settings.update(budgets)
        return SearchPipeline(fetcher=fetcher or FakeFetcher(), verifier=verifier or FakeVerifier(),
                              discovery_provider=discovery or FakeDiscovery(), sources=sources(source_count),
                              budgets=SearchBudgets(**settings))

    async def test_exactly_three_workers_share_queue_and_verification_streams(self):
        fetcher = FakeFetcher(delays={"s0": .003, "s1": .06, "s2": .06})
        verifier = FakeVerifier()
        catalog = await self.make_pipeline(fetcher, verifier, source_count=12).search(brief())
        self.assertEqual(SEARCH_WORKERS, 3)
        self.assertEqual(fetcher.peak, 3)
        self.assertEqual(fetcher.worker_names, {f"velor-base-search-{n}" for n in (1, 2, 3)})
        starts, finishes = dict(fetcher.started), dict(fetcher.finished)
        self.assertLess(starts["s3"], finishes["s1"], "free worker must take next source before slow worker finishes")
        self.assertLess(verifier.calls[0][1], max(finishes.values()), "verification must begin while base search is running")
        self.assertEqual(verifier.peak, 1, "all base/discovery candidates must use a separate single verifier")
        self.assertEqual(len(catalog.products), 12)
        self.assertTrue(all(s.state == "complete" for s in catalog.sources))

    async def test_discovery_candidates_use_same_verifier(self):
        candidate = ProductCandidate("https://new-store.example.org/product/real-observed-link", "discovery")
        discovery = FakeDiscovery(DiscoveryBatch((candidate,), detail="Observed external link"))
        verifier = FakeVerifier()
        catalog = await self.make_pipeline(verifier=verifier, discovery=discovery, source_count=1).search(brief())
        self.assertIn(candidate, [c for c, _ in verifier.calls])
        self.assertEqual({p.source_id for p in catalog.products}, {"s0", "discovery"})
        report = next(s for s in catalog.sources if s.source_id == "discovery")
        self.assertEqual((report.state, report.found), ("complete", 1))

    async def test_callback_reports_queue_search_verification_and_completion(self):
        updates = []

        async def on_source(status):
            updates.append(status)

        catalog = await self.make_pipeline(source_count=1).search(brief(), on_source)
        states = [s.state for s in updates if s.source_id == "s0"]
        self.assertEqual(states[0], "queued")
        self.assertIn("searching", states)
        self.assertIn("verifying", states)
        self.assertEqual(states[-1], "complete")
        self.assertEqual(catalog.sources[0].found, 1)
        self.assertEqual(catalog.sources[0].detail.count("Ссылок:"), 1, "completion counts must be appended exactly once")
        self.assertEqual(updates[0].found, 0, "callbacks must receive snapshots, not mutable report references")

    async def test_source_failure_does_not_discard_other_sources(self):
        fetcher = FakeFetcher(errors={"s0": FetchError("inaccessible", "HTTP 403; no bypass", status=403)})
        catalog = await self.make_pipeline(fetcher=fetcher, source_count=3).search(brief())
        self.assertEqual(len(catalog.products), 2)
        self.assertEqual(catalog.sources[0].state, "inaccessible")
        self.assertIn("403", catalog.sources[0].detail)
        self.assertTrue(any("403" in w for w in catalog.warnings))

    async def test_200_access_challenge_is_inaccessible(self):
        catalog = await self.make_pipeline(fetcher=FakeFetcher(challenge=True), source_count=1).search(brief())
        self.assertEqual(catalog.sources[0].state, "inaccessible")
        self.assertFalse(catalog.products)

    async def test_unsupported_discovery_state_is_explicit(self):
        discovery = FakeDiscovery(DiscoveryBatch(state="unsupported", detail="Provider is not configured"))
        catalog = await self.make_pipeline(discovery=discovery, source_count=1).search(brief())
        report = next(s for s in catalog.sources if s.source_id == "discovery")
        self.assertEqual(report.state, "unconfigured")
        self.assertIn("not configured", report.detail)
        self.assertEqual(len(catalog.products), 1)

    async def test_per_source_timeout_finishes_with_source_errors(self):
        fetcher = FakeFetcher(delays={f"s{n}": 10 for n in range(3)})
        started = time.monotonic()
        catalog = await self.make_pipeline(fetcher=fetcher, source_count=3, source_seconds=.015).search(brief())
        self.assertLess(time.monotonic() - started, .3)
        self.assertTrue(all(s.state == "failed" for s in catalog.sources[:3]))
        self.assertFalse(catalog.products)
        await asyncio.sleep(0)
        self.assertEqual(fetcher.cancelled, 3)

    async def test_global_timeout_returns_verified_partial_catalog(self):
        fetcher = FakeFetcher(delays={"s0": .001, **{f"s{n}": 10 for n in range(1, 6)}})
        started = time.monotonic()
        catalog = await self.make_pipeline(fetcher=fetcher, total_seconds=.035).search(brief())
        self.assertLess(time.monotonic() - started, .3)
        self.assertEqual(len(catalog.products), 1)
        self.assertTrue(any("общий бюджет" in w.lower() for w in catalog.warnings))
        self.assertTrue(any(s.state == "failed" for s in catalog.sources))
        await asyncio.sleep(0)
        self.assertFalse([t for t in asyncio.all_tasks() if t.get_name().startswith("velor-")])

    async def test_external_cancellation_stops_owned_workers(self):
        fetcher = FakeFetcher(delays={f"s{n}": 10 for n in range(6)})
        discovery = FakeDiscovery(delay=10)
        task = asyncio.create_task(self.make_pipeline(fetcher=fetcher, discovery=discovery).search(brief()))
        for _ in range(100):
            if fetcher.active == 3:
                break
            await asyncio.sleep(.001)
        self.assertEqual(fetcher.active, 3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        self.assertEqual(fetcher.cancelled, 3)
        self.assertTrue(discovery.cancelled)
        self.assertFalse([t for t in asyncio.all_tasks() if t.get_name().startswith("velor-")])

    async def test_verifier_timeout_rejects_unknown_candidate(self):
        verifier = FakeVerifier(delay=10)
        catalog = await self.make_pipeline(verifier=verifier, source_count=1, verification_seconds=.015).search(brief())
        self.assertFalse(catalog.products)
        self.assertEqual(catalog.sources[0].state, "complete")
        self.assertIn("бюджет проверки", catalog.sources[0].detail)
        await asyncio.sleep(0)
        self.assertTrue(verifier.cancelled)

    async def test_unverified_unknown_is_not_admitted(self):
        verifier = FakeVerifier(result=lambda c: VerificationResult(product(c, verification="unverified", availability="unknown"), False, ("size inventory unknown",)))
        catalog = await self.make_pipeline(verifier=verifier, source_count=1).search(brief())
        self.assertFalse(catalog.products)
        self.assertEqual(catalog.sources[0].found, 0)
        self.assertIn("inventory unknown", catalog.sources[0].detail)
        self.assertTrue(any("unknown" in w for w in catalog.warnings))

    async def test_valid_flag_cannot_admit_product_marked_unverified(self):
        verifier = FakeVerifier(result=lambda c: VerificationResult(product(c, verification="unverified"), True))
        catalog = await self.make_pipeline(verifier=verifier, source_count=1).search(brief())
        self.assertFalse(catalog.products)

    async def test_callback_exception_cannot_fail_search(self):
        async def failing(_):
            raise RuntimeError("callback failed")

        catalog = await self.make_pipeline(source_count=1).search(brief(), failing)
        self.assertEqual(len(catalog.products), 1)
        self.assertEqual(len([w for w in catalog.warnings if "callback" in w]), 1)

    async def test_hung_callback_is_bounded(self):
        async def hanging(_):
            await asyncio.sleep(10)

        started = time.monotonic()
        catalog = await self.make_pipeline(source_count=1, callback_seconds=.002).search(brief(), hanging)
        self.assertLess(time.monotonic() - started, .25)
        self.assertEqual(len(catalog.products), 1)
        self.assertTrue(any("callback" in w for w in catalog.warnings))

    async def test_candidate_and_catalog_caps_leave_terminal_sources(self):
        verifier = FakeVerifier()
        catalog = await self.make_pipeline(fetcher=FakeFetcher(links=8), verifier=verifier,
                                           source_count=1, candidates_per_source=3, max_products=1).search(brief())
        self.assertEqual(len(catalog.products), 1)
        self.assertEqual(len(verifier.calls), 1)
        self.assertEqual(catalog.sources[0].state, "complete")
        self.assertIn("Ссылок: 3", catalog.sources[0].detail)

    async def test_demo_never_uses_any_live_provider(self):
        class Forbidden:
            calls = 0

            async def fetch(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("network forbidden in demo")

            async def verify(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("live verifier forbidden in demo")

            async def discover(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("discovery forbidden in demo")

        forbidden = Forbidden()
        pipeline = SearchPipeline(fetcher=forbidden, verifier=forbidden, discovery_provider=forbidden)
        catalog = await pipeline.search(brief("demo"))
        self.assertEqual(forbidden.calls, 0)
        self.assertEqual(len(catalog.sources), len(BASE_SOURCES) + 1)
        self.assertGreater(len(catalog.products), 0)
        self.assertTrue(all(p.is_demo and p.verification == "demo" and p.availability == "unknown" for p in catalog.products))
        self.assertTrue(all(urlsplit(p.source_url).hostname == "demo.velor.invalid" for p in catalog.products))
        self.assertTrue(all(p.verified_at is None for p in catalog.products))
        self.assertIn("ДЕМОНСТРАЦИЯ", catalog.warnings[0])

    async def test_demo_respects_requested_categories(self):
        catalog = await self.make_pipeline().search(brief("demo", categories=["shoes"]))
        self.assertTrue(catalog.products)
        self.assertEqual({p.category for p in catalog.products}, {"shoes"})

    def test_invalid_budgets_and_duplicate_sources_are_rejected(self):
        for fields in ({"total_seconds": 0}, {"source_seconds": float("inf")}, {"callback_seconds": -1}, {"max_products": 0}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                SearchBudgets(**fields)
        with self.assertRaises(ValueError):
            SearchPipeline(sources=(sources(1)[0], sources(1)[0]))


if __name__ == "__main__":
    unittest.main()
