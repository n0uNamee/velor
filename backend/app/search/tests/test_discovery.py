"""Offline public search parsing and provider-state tests."""
import unittest
from urllib.parse import parse_qs, urlsplit

from app.models import ImageRef, StyleBrief
from app.search.discovery import PublicWebDiscoveryProvider, UnconfiguredDiscoveryProvider
from app.search.transport import FetchError, FetchPage


def brief(**changes):
    values = dict(id="b", profile_id="p", original_profile_text="private profile", original_request_text="черное худи", search_queries=["черное худи"], mode="live", images=[ImageRef(id="i", kind="reference", local_path="/private/image.png", url="https://private.example/image.png")])
    values.update(changes)
    return StyleBrief(**values)


class FakeSearchFetcher:
    def __init__(self, html="", error=None):
        self.urls = []
        self.html = html
        self.error = error

    async def fetch(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        return FetchPage(url, 200, self.html, {})


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_results_are_not_limited_to_seed_stores(self):
        fetcher = FakeSearchFetcher('<h2><a href="https://new-designer.example/item/42">Черное худи</a></h2><h2><a href="https://ozon.ru/product/1">base</a></h2>')
        result = await PublicWebDiscoveryProvider(fetcher).discover(brief())
        self.assertEqual([item.url for item in result.candidates], ["https://new-designer.example/item/42"])
        self.assertEqual(result.candidates[0].source_id, "discovery")
        self.assertEqual(result.state, "complete")

    async def test_query_never_includes_images_or_full_profile(self):
        fetcher = FakeSearchFetcher('<h2><a href="https://new.example/item">Худи</a></h2>')
        await PublicWebDiscoveryProvider(fetcher).discover(brief(search_queries=["private profile", "черное худи"]))
        query = parse_qs(urlsplit(fetcher.urls[0]).query)["q"][0]
        self.assertIn("черное худи", query)
        self.assertNotIn("private", query)
        self.assertNotIn("image", query)

    async def test_no_direct_result_means_explicit_unsupported(self):
        fetcher = FakeSearchFetcher('<h2><a href="https://www.bing.com/ck/a?target=opaque">redirect</a></h2><a href="https://new.example/item">non-result</a>')
        result = await PublicWebDiscoveryProvider(fetcher).discover(brief())
        self.assertEqual(result.state, "unsupported")
        self.assertFalse(result.candidates)
        self.assertEqual(len(fetcher.urls), 1)

    async def test_limit_and_duplicates_are_bounded(self):
        fetcher = FakeSearchFetcher(''.join(f'<h2><a href="https://new.example/item/{i}">x</a></h2>' for i in [1, 1, 2, 3]))
        result = await PublicWebDiscoveryProvider(fetcher).discover(brief(), limit=2)
        self.assertEqual(len(result.candidates), 2)

    async def test_denial_stops_without_fallback_or_retry(self):
        fetcher = FakeSearchFetcher(error=FetchError("inaccessible", "HTTP 403; no bypass", "https://www.bing.com/search"))
        result = await PublicWebDiscoveryProvider(fetcher).discover(brief())
        self.assertEqual(result.state, "inaccessible")
        self.assertFalse(result.candidates)
        self.assertEqual(len(fetcher.urls), 1)

    async def test_missing_query_and_unconfigured_are_explicit(self):
        fetcher = FakeSearchFetcher()
        result = await PublicWebDiscoveryProvider(fetcher).discover(brief(search_queries=[]))
        self.assertEqual(result.state, "unsupported")
        self.assertEqual(fetcher.urls, [])
        result = await UnconfiguredDiscoveryProvider().discover(brief())
        self.assertEqual(result.state, "unsupported")
        self.assertFalse(result.candidates)

    async def test_observed_unsafe_or_malformed_schemes_are_not_candidates(self):
        fetcher = FakeSearchFetcher('<h2><a href="javascript:alert(1)">x</a></h2><h2><a href="https://user:password@shop.example/item">x</a></h2><h2><a href="https://[invalid/item">x</a></h2>')
        result = await PublicWebDiscoveryProvider(fetcher).discover(brief())
        self.assertFalse(result.candidates)


if __name__ == "__main__":
    unittest.main()
