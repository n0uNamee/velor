"""Offline evidence-boundary tests: no provider or network calls."""
import json
import unittest
from unittest.mock import patch

from app.models import Constraint, StyleBrief
from app.search.extraction import ExtractedProduct, ProductCandidate
from app.search.transport import FetchError, FetchPage
from app.search.verifier import ProductVerifier


def make_brief(**changes):
    values = dict(id="brief", profile_id="profile", original_profile_text="", original_request_text="черное худи", search_queries=["найди черное худи"], categories=["tops"], sizes={"tops": "M"}, mode="live")
    values.update(changes)
    return StyleBrief(**values)


def facts(**changes):
    values = dict(url="https://shop.example/product/1", title="Черное хлопковое худи", price_rub=3000.0, currency="RUB", sizes=("S", "M"), available_sizes=("M",), size_prices_rub={"M": 3000.0}, availability="in_stock", category="tops", condition="new", evidence=("JSON-LD Product", "Offer size M InStock"))
    values.update(changes)
    return ExtractedProduct(**values)


class FakeFetcher:
    def __init__(self, *, url="https://shop.example/product/1", error=None):
        self.urls = []
        self.url = url
        self.error = error

    async def fetch(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        return FetchPage(self.url, 200, "<html>fixture</html>", {"content-type": "text/html"})


class VerifierTests(unittest.IsolatedAsyncioTestCase):
    async def verify(self, extracted=None, brief=None, *, candidate=None, fetcher=None):
        fetcher = fetcher or FakeFetcher()
        with patch("app.search.verifier.extract_product", return_value=extracted if extracted is not None else facts()):
            result = await ProductVerifier(fetcher).verify(candidate or ProductCandidate("https://shop.example/product/1", "discovery"), brief or make_brief())
        return result, fetcher

    async def test_refetches_actual_candidate_and_timestamps_supported_facts(self):
        result, fetcher = await self.verify()
        self.assertTrue(result.valid)
        self.assertEqual(fetcher.urls, ["https://shop.example/product/1"])
        self.assertEqual(result.product.verification, "verified")
        self.assertIsNotNone(result.product.verified_at)
        self.assertFalse(result.product.is_demo)
        self.assertEqual(result.product.sizes, ["M"])
        self.assertTrue(any("condition: new" in item for item in result.product.evidence))

    async def test_size_buttons_and_generic_stock_do_not_prove_requested_size(self):
        result, _ = await self.verify(facts(available_sizes=()))
        self.assertFalse(result.valid)
        self.assertEqual(result.product.verification, "unverified")
        self.assertIn("size-specific inventory", result.detail)

    async def test_no_requested_size_still_requires_inventory_backed_size(self):
        result, _ = await self.verify(facts(available_sizes=()), make_brief(sizes=None))
        self.assertFalse(result.valid)

    async def test_unknown_stock_and_price_never_become_verified(self):
        result, _ = await self.verify(facts(availability="unknown", available_sizes=(), size_prices_rub={}, price_rub=None, conditional_price_rub=1900))
        self.assertFalse(result.valid)
        self.assertIsNone(result.product.price_rub)
        self.assertIn("ordinary RUB price unknown", result.detail)
        self.assertIn("stock unknown", result.detail)

    async def test_conditional_price_is_separate_and_never_ordinary_price(self):
        result, _ = await self.verify(facts(conditional_price_rub=2500, price_note="Цена с картой: 2500 ₽"))
        self.assertTrue(result.valid)
        self.assertEqual(result.product.price_rub, 3000)
        self.assertTrue(any("Conditional/loyalty RUB price: 2500" in item for item in result.product.evidence))

    async def test_missing_color_or_semantic_style_cannot_pass(self):
        missing_color, _ = await self.verify(facts(title="Белое худи"))
        abstract, _ = await self.verify(brief=make_brief(search_queries=["черное худи в авангардном стиле"]))
        self.assertFalse(missing_color.valid)
        self.assertFalse(abstract.valid)
        self.assertIn("semantic interpretation", abstract.detail)

    async def test_same_category_different_garment_cannot_pass(self):
        result, _ = await self.verify(facts(title="Черная рубашка"))
        self.assertFalse(result.valid)
        self.assertIn("garment type", result.detail)

    async def test_unknown_condition_or_unrequested_used_cannot_pass(self):
        for condition in ("unknown", "used", "refurbished", "damaged"):
            with self.subTest(condition=condition):
                result, _ = await self.verify(facts(condition=condition))
                self.assertFalse(result.valid)

    async def test_city_and_delivery_require_separate_evidence(self):
        result, _ = await self.verify(facts(city="Москва", delivery=None), make_brief(city="Москва"))
        self.assertFalse(result.valid)
        self.assertIn("delivery", result.detail)
        result, _ = await self.verify(facts(city="Томск", delivery="курьер"), make_brief(city="Омск"))
        self.assertFalse(result.valid)
        self.assertIn("city-specific", result.detail)
        result, _ = await self.verify(facts(city="Москва", delivery="DE"), make_brief(city="Москва"))
        self.assertFalse(result.valid)
        self.assertIn("delivery", result.detail)
        result, _ = await self.verify(facts(city="Москва", delivery="Доставка: Москва", size_cities={"M": "Москва"}, size_deliveries={"M": "Доставка: Москва"}), make_brief(city="Москва"))
        self.assertTrue(result.valid)
        result, _ = await self.verify(facts(city="Москва", delivery="Доставка: Москва", size_cities={"S": "Москва"}, size_deliveries={"S": "Доставка: Москва"}), make_brief(city="Москва"))
        self.assertFalse(result.valid)
        self.assertIn("city", result.detail)

    async def test_negated_color_and_ambiguous_variant_price_cannot_pass(self):
        negative, _ = await self.verify(facts(title="Худи не черное"))
        ambiguous, _ = await self.verify(facts(size_prices_rub={}, price_note="Several ordinary offers; displayed value is the lowest observed offer."))
        self.assertFalse(negative.valid)
        self.assertIn("negation", negative.detail)
        self.assertFalse(ambiguous.valid)
        self.assertIn("price unknown", ambiguous.detail)

    async def test_size_specific_price_does_not_reuse_cheaper_other_size(self):
        result, _ = await self.verify(facts(price_rub=1000, size_prices_rub={"S": 1000, "M": 4000}), make_brief(budget_rub=3000))
        self.assertFalse(result.valid)
        self.assertEqual(result.product.price_rub, 4000)
        self.assertIn("budget", result.detail)

    async def test_real_schema_variant_price_is_coupled_end_to_end(self):
        schema = {"@context": "https://schema.org", "@type": "Product", "name": "Черное худи", "url": "https://shop.example/product/1", "size": ["S", "M"], "itemCondition": "https://schema.org/NewCondition", "offers": {"@type": "Offer", "price": 1000, "priceCurrency": "RUB", "availability": "https://schema.org/InStock"}, "hasVariant": [{"@type": "Product", "size": size, "offers": {"@type": "Offer", "price": price, "priceCurrency": "RUB", "availability": "https://schema.org/InStock"}} for size, price in [("S", 1000), ("M", 5000)]]}
        page = FetchPage("https://shop.example/product/1", 200, '<script type="application/ld+json">' + json.dumps(schema) + '</script>', {})
        class SchemaFetcher:
            async def fetch(self, url):
                return page
        result = await ProductVerifier(SchemaFetcher()).verify(ProductCandidate(page.url, "discovery"), make_brief(budget_rub=2000))
        self.assertFalse(result.valid)
        self.assertEqual(result.product.price_rub, 5000)
        self.assertIn("budget", result.detail)

    async def test_budget_exceeded_is_rejected(self):
        result, _ = await self.verify(brief=make_brief(budget_rub=2000))
        self.assertFalse(result.valid)
        self.assertIn("budget", result.detail)

    async def test_hard_semantic_constraint_and_unproven_exclusion_reject(self):
        constraint = Constraint(text="только экологичное производство", strength="hard", provenance="request", confidence=1)
        exclusion = Constraint(text="без кожи", strength="hard", provenance="request", confidence=1)
        result, _ = await self.verify(brief=make_brief(constraints=[constraint], exclusions=[exclusion]))
        self.assertFalse(result.valid)
        self.assertIn("semantic verifier", result.detail)
        self.assertIn("absence", result.detail)

    async def test_hard_garment_constraint_cannot_be_satisfied_by_same_style_other_item(self):
        constraint = Constraint(text="только ботинки", strength="hard", provenance="request", confidence=1)
        result, _ = await self.verify(brief=make_brief(constraints=[constraint], categories=["tops", "shoes"]))
        self.assertFalse(result.valid)
        self.assertIn("hard constraint garment type", result.detail)

    async def test_separate_style_preference_requires_product_evidence(self):
        preference = Constraint(text="белое", strength="soft", provenance="profile", confidence=1)
        result, _ = await self.verify(brief=make_brief(preferences=[preference]))
        self.assertFalse(result.valid)
        self.assertIn("white", result.detail)

    async def test_explicit_new_and_used_conditions_are_not_interchangeable(self):
        valid_new, _ = await self.verify(brief=make_brief(search_queries=["новое черное худи"]))
        wrong_new, _ = await self.verify(brief=make_brief(search_queries=["used черное худи"]))
        valid_used, _ = await self.verify(facts(condition="used"), make_brief(search_queries=["used черное худи"]))
        self.assertTrue(valid_new.valid)
        self.assertFalse(wrong_new.valid)
        self.assertTrue(valid_used.valid)

    async def test_source_redirect_cannot_silently_change_store(self):
        result, _ = await self.verify(candidate=ProductCandidate("https://ozon.ru/product/1", "ozon"))
        self.assertFalse(result.valid)
        self.assertIn("left the declared source", result.detail)

    async def test_discovery_redirect_to_base_is_not_external(self):
        result, _ = await self.verify(fetcher=FakeFetcher(url="https://ozon.ru/product/1"))
        self.assertFalse(result.valid)

    async def test_transport_denial_preserves_state_and_has_no_product(self):
        error = FetchError("blocked", "private IP denied", "http://127.0.0.1/item")
        fetcher = FakeFetcher(error=error)
        result = await ProductVerifier(fetcher).verify(ProductCandidate(error.url, "discovery"), make_brief())
        self.assertFalse(result.valid)
        self.assertIsNone(result.product)
        self.assertEqual(result.state, "blocked")
        self.assertEqual(fetcher.urls, [error.url])

    async def test_listing_without_card_is_not_product(self):
        with patch("app.search.verifier.extract_product", return_value=None):
            result = await ProductVerifier(FakeFetcher()).verify(ProductCandidate("https://shop.example/search", "discovery"), make_brief())
        self.assertIsNone(result.product)
        self.assertFalse(result.valid)


if __name__ == "__main__":
    unittest.main()
