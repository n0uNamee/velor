"""Synthetic offline SSR fixtures; not live merchant verification."""
import json
import unittest
from app.search.okno import extract_okno_candidates, extract_okno_product

URL = "https://okno.store/item/bryuki-miss-sixty"


def html(**fields):
    item = {"title": "брюки miss sixty", "code": "bryuki-miss-sixty", "price": 4200, "formatRubPrice": "4200 RUB", "available": True, "isHidden": False, "variants": [{"variantId": 2364652673, "title": "s"}]}
    item.update(fields)
    data = {"props": {"pageProps": {"item": item, "characteristics": [{"title": "Доставка и оплата", "text": ["Москва: самовывоз", "Москва: курьер", "СДЭК"]}]}}}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + '</script>'


class OknoTests(unittest.TestCase):
    def test_single_variant_coupling_unknown_condition_delivery(self):
        product = extract_okno_product(html(), URL)
        self.assertEqual(product.title, "брюки miss sixty")
        self.assertEqual(product.price_rub, 4200)
        self.assertEqual(product.available_sizes, ("s",))
        self.assertEqual(product.size_prices_rub, {"s": 4200})
        self.assertEqual(product.condition, "unknown")
        self.assertIsNone(product.city)
        self.assertIsNone(product.delivery)
        self.assertEqual(product.size_cities, {})
        self.assertTrue(any("unverified general delivery" in e for e in product.evidence))

    def test_multiple_variants_not_size_stock(self):
        product = extract_okno_product(html(variants=[{"title": "s"}, {"title": "m"}]), URL)
        self.assertEqual(product.sizes, ("s", "m"))
        self.assertEqual(product.available_sizes, ())
        self.assertEqual(product.size_prices_rub, {})

    def test_hidden_unavailable_or_unknown_flags(self):
        for fields in ({"isHidden": True}, {"available": False}, {"available": "true"}, {"isHidden": None}):
            with self.subTest(fields=fields):
                self.assertEqual(extract_okno_product(html(**fields), URL).available_sizes, ())

    def test_identity_checks(self):
        for url in ("https://okno.store/item/other", URL + "?variant=other", "https://evil.example/item/bryuki-miss-sixty"):
            with self.subTest(url=url):
                self.assertIsNone(extract_okno_product(html(), url))
        self.assertIsNotNone(extract_okno_product(html(), URL + "?utm_source=test"))

    def test_currency_and_condition_explicit(self):
        self.assertIsNone(extract_okno_product(html(formatRubPrice="4200 USD"), URL).price_rub)
        self.assertEqual(extract_okno_product(html(itemCondition="https://schema.org/UsedCondition"), URL).condition, "used")

    def test_actual_local_catalog_link_query_filter(self):
        content = '<a href="/item/bryuki-miss-sixty">брюки miss sixty</a><a href="/item/hudi">худи</a><a href="https://evil.example/item/no">брюки</a><a href="/lookbook/2026">брюки</a>'
        result = extract_okno_candidates(content, "https://okno.store/", "брюки")
        self.assertEqual([candidate.url for candidate in result], [URL])
        self.assertEqual(result[0].source_id, "okno")

    def test_invalid_payload(self):
        self.assertIsNone(extract_okno_product('<script id="__NEXT_DATA__">bad</script>', URL))
        self.assertIsNone(extract_okno_product('<script id="__NEXT_DATA__">' + ' ' * 1_000_001 + '</script>', URL))


if __name__ == "__main__":
    unittest.main()


class OknoVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_condition_allowed_unless_new_is_required(self):
        from app.models import StyleBrief
        from app.search.extraction import ProductCandidate, extract_product
        from app.search.transport import FetchPage
        from app.search.verifier import ProductVerifier
        class Fetcher:
            async def fetch(self, url):
                return FetchPage(url, 200, html(), {})
        self.assertEqual(extract_product(html(), URL).price_rub, 4200)
        brief = StyleBrief(id="test", profile_id="test", original_profile_text="минимализм",
            original_request_text="брюки", search_queries=["минимализм", "брюки"], categories=["bottoms"], mode="live")
        candidate = ProductCandidate(URL, "okno")
        result = await ProductVerifier(Fetcher()).verify(candidate, brief)
        self.assertTrue(result.valid, result.detail)
        self.assertFalse(result.product.is_demo)
        self.assertTrue(any("condition: unknown" in x for x in result.product.evidence))
        strict = brief.model_copy(update={"original_request_text": "новые брюки", "search_queries": ["новые брюки"]})
        self.assertFalse((await ProductVerifier(Fetcher()).verify(candidate, strict)).valid)
