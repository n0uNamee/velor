"""Bounded, ordinary network diagnostic; synthetic query, no credentials.

Run explicitly: PYTHONPATH=backend python -m app.search.diagnose_network
This is never run by the API/demo or the offline test suite.
"""
from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timezone

from app.models import StyleBrief

from .extraction import extract_candidates
from .sources import BASE_SOURCES
from .transport import AsyncFetcher, FetchError
from .verifier import ProductVerifier


class DiagnosticFetcher(AsyncFetcher):
    def __init__(self) -> None:
        self.dns_events: list[dict] = []
        self.requests: list[dict] = []
        self.pages: dict[str, object] = {}
        super().__init__(timeout_seconds=8, resolver=self.resolve_observed)

    def resolve_observed(self, host: str, port: int, **kwargs):
        event = {"host": host, "port": port, "stage": "dns"}
        self.dns_events.append(event)
        try:
            answers = socket.getaddrinfo(host, port, **kwargs)
        except OSError as exc:
            event.update(outcome="failed", error_type=type(exc).__name__, errno=exc.errno,
                         detail=str(exc))
            raise
        event.update(outcome="resolved", answers=len(answers))
        return answers

    async def fetch(self, url):
        record = {"requested_url": url}
        self.requests.append(record)
        try:
            page = await super().fetch(url)
        except FetchError as exc:
            record.update(outcome=exc.state, detail=exc.detail, http_status=exc.status,
                          stage=getattr(exc, "stage", None), error_code=getattr(exc, "error_code", None))
            raise
        record.update(outcome="response", actual_url=page.url, http_status=page.status,
                      text_characters=len(page.text))
        self.pages[url] = page
        return page


async def diagnose() -> dict:
    fetcher = DiagnosticFetcher()
    source = next(s for s in BASE_SOURCES if s.id == "sela")
    report = {"observed_at": datetime.now(timezone.utc).isoformat(),
              "purpose": "ordinary official HTTPS control and SELA search-to-card diagnostic",
              "official": {}, "source": {"id": source.id}, "card": {"outcome": "not_run"}}
    try:
        await fetcher.fetch("https://www.python.org/")
    except FetchError:
        pass
    report["official"] = dict(fetcher.requests[-1])
    try:
        page = await fetcher.fetch(source.build_search_url("худи"))
    except FetchError:
        page = None
    report["source"].update(fetcher.requests[-1])
    if page:
        candidates = extract_candidates(page.text, page.url, source, limit=1)
        report["source"]["observed_product_links"] = len(candidates)
        if candidates:
            brief = StyleBrief(id="explicit-network-diagnostic", profile_id="synthetic",
                               original_profile_text="", original_request_text="худи",
                               search_queries=["худи"], categories=["tops"], mode="live")
            result = await ProductVerifier(fetcher).verify(candidates[0], brief)
            report["card"] = {**fetcher.requests[-1], "candidate_url": candidates[0].url,
                              "valid": result.valid, "reasons": result.reasons}
            if result.product:
                report["card"]["facts"] = result.product.model_dump()
    report["dns"] = fetcher.dns_events
    report["requests"] = fetcher.requests
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(diagnose()), ensure_ascii=False, indent=2))
