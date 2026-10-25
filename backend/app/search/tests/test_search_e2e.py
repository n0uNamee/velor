"""Offline full-path fixtures, never a claim of live retailer accessibility."""
import json
import unittest
from urllib.parse import urlsplit

from app.models import StyleBrief
from app.search.discovery import DiscoveryBatch
from app.search.extraction import ProductCandidate
from app.search.pipeline import SearchBudgets, SearchPipeline
from app.search.sources import BASE_SOURCES
from app.search.transport import FetchPage


def html_schema(node):
    return '<script type="application/ld+json">' + json.dumps(node, ensure_ascii=False) + "</script>"


class OfflineDocuments:
    def __init__(self):
        self.search_urls = []
        self.card_urls = []

    async def fetch(self, url):
        parts = urlsplit(url)
        if "/search" in parts.path:
            self.search_urls.append(url)
            target = f"https://{parts.netloc}/product/observed-fixture-link?size=M"
            node = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
                {"@type": "ListItem", "item": {"@type": "Product", "name": "Чёрный худи", "url": target}}
            ]}
        else:
            self.card_urls.append(url)
            node = {"@context": "https://schema.org", "@type": "Product", "url": url,
                    "name": "Чёрный худи", "description": "Чёрный худи", "size": "M",
                    "itemCondition": "https://schema.org/NewCondition", "offers": {
                        "@type": "Offer", "price": "1300", "priceCurrency": "RUB",
                        "availability": "https://schema.org/InStock",
                        "itemCondition": "https://schema.org/NewCondition",
                        "availableAtOrFrom": {"@type": "Place", "address": {"addressLocality": "Москва"}},
                        "shippingDetails": {"@type": "OfferShippingDetails", "shippingDestination": {"addressLocality": "Москва"}},
                    }}
        return FetchPage(url, 200, html_schema(node), {"content-type": "text/html"})


class OfflineDiscovery:
    async def discover(self, brief, *, limit=12):
        return DiscoveryBatch((ProductCandidate("https://independent.example.org/product/observed-fixture-link?size=M", "discovery"),),
                              detail="Offline provider fixture: one observed external URL.")


class SearchEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_twelve_searches_and_discovery_reach_real_verifier_and_parser(self):
        documents = OfflineDocuments()
        request = StyleBrief(id="offline-e2e", profile_id="fixture", original_profile_text="",
                             original_request_text="Чёрный худи", search_queries=["Чёрный худи"],
                             categories=["tops"], sizes={"tops": "M"}, city="Москва", budget_rub=2000,
                             mode="live")
        pipeline = SearchPipeline(fetcher=documents, discovery_provider=OfflineDiscovery(),
                                  budgets=SearchBudgets(total_seconds=2))
        catalog = await pipeline.search(request)
        self.assertEqual(len(documents.search_urls), len(BASE_SOURCES))
        self.assertEqual(len(documents.card_urls), 13)
        self.assertEqual(len(catalog.products), 13, catalog.model_dump_json(indent=2))
        self.assertTrue(all(p.verification == "verified" and not p.is_demo for p in catalog.products))
        self.assertTrue(all(p.price_rub == 1300 and p.sizes == ["M"] and p.verified_at for p in catalog.products))
        self.assertTrue(all(p.source_url in documents.card_urls for p in catalog.products))
        self.assertTrue(all(s.state == "complete" and s.found == 1 for s in catalog.sources))
        self.assertTrue(all(any("style_match:" in e for e in p.evidence) for p in catalog.products))
