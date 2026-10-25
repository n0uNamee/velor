"""A bounded, credential-free web discovery provider with explicit failure states.

Only text search terms are sent. User image URLs and local image paths are never
included. Search result URLs are candidates, not evidence that a product exists.
The pipeline must pass every candidate to the ordinary product verifier.
"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from app.models import StyleBrief

from .extraction import ProductCandidate
from .sources import BASE_SOURCES, host_matches
from .transport import AsyncFetcher, FetchError


@dataclass(frozen=True)
class DiscoveryBatch:
    candidates: tuple[ProductCandidate, ...] = ()
    state: str = "complete"
    detail: str = ""


class DiscoveryProvider(Protocol):
    async def discover(self, brief: StyleBrief, *, limit: int = 12) -> DiscoveryBatch: ...


class UnconfiguredDiscoveryProvider:
    """Explicit opt-out for installations without an approved search provider."""

    async def discover(self, brief: StyleBrief, *, limit: int = 12) -> DiscoveryBatch:
        return DiscoveryBatch(state="unsupported", detail="External internet search provider is not configured; no discovery was run.")


class _ResultLinks(HTMLParser):
    """Read direct links from search result headings, never construct item URLs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.heading_depth = 0
        self.current_url = ""
        self.current_title: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "h2":
            self.heading_depth += 1
        if tag.lower() == "a" and self.heading_depth:
            self.current_url = dict(attrs).get("href") or ""
            self.current_title = []

    def handle_data(self, data: str) -> None:
        if self.current_url:
            self.current_title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self.current_url:
            self.links.append((self.current_url, " ".join(" ".join(self.current_title).split())))
            self.current_url = ""
            self.current_title = []
        if tag.lower() == "h2":
            self.heading_depth = max(0, self.heading_depth - 1)


class PublicWebDiscoveryProvider:
    """One ordinary public Bing HTML request; no keys, login, proxy or retries.

    Bing may deny automated access or return only redirect links. Those cases are
    reported as inaccessible/unsupported instead of using another access path.
    Niche store names may appear naturally in results; there is no seed allowlist.
    """

    def __init__(self, fetcher: AsyncFetcher) -> None:
        self.fetcher = fetcher

    async def discover(self, brief: StyleBrief, *, limit: int = 12) -> DiscoveryBatch:
        # Prefer the last focused query (the local normalizer appends the current
        # request after the profile). Never serialize the brief or its images.
        query = next((" ".join(item.split())[:220] for item in reversed(brief.search_queries) if item.strip()), "")
        if not query:
            return DiscoveryBatch(state="unsupported", detail="No textual search query was supplied by the normalizer.")
        if limit <= 0:
            return DiscoveryBatch(detail="Discovery candidate limit is zero.")
        query += " одежда купить"
        url = "https://www.bing.com/search?" + urlencode({"q": query, "count": min(limit * 2, 30), "setlang": "ru"})
        try:
            page = await self.fetcher.fetch(url)
        except FetchError as exc:
            return DiscoveryBatch(state=exc.state, detail=exc.detail)
        parser = _ResultLinks()
        parser.feed(page.text)
        candidates: list[ProductCandidate] = []
        seen: set[str] = set()
        base_hosts = tuple(host for source in BASE_SOURCES for host in source.hosts)
        for target, title in parser.links:
            try:
                parsed = urlsplit(target)
            except ValueError:
                continue
            host = (parsed.hostname or "").lower().rstrip(".")
            if parsed.scheme.lower() not in {"http", "https"} or not host or parsed.username or parsed.password:
                continue
            if host == "bing.com" or host.endswith(".bing.com"):
                continue
            if host_matches(target, base_hosts) or target in seen:
                continue
            seen.add(target)
            candidates.append(ProductCandidate(
                url=target, source_id="discovery", hinted_title=title,
                evidence=(f"Direct external search result observed at {page.url}",),
            ))
            if len(candidates) >= min(limit, 30):
                break
        if not candidates:
            return DiscoveryBatch(state="unsupported", detail="Public search HTML contained no usable direct links outside the 12 base sources; no redirected URL was guessed.")
        return DiscoveryBatch(tuple(candidates), detail=f"Observed {len(candidates)} external result URLs; each requires product verification.")


# Backwards-compatible descriptive alias for integrations that prefer the name.
NoSearchProvider = UnconfiguredDiscoveryProvider
