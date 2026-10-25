"""Catalog admission and dedupe must preserve product variant identity."""
import unittest

from app.models import Product
from app.search.parser import canonical_product_url, normalize_catalog


def product(url="https://store.example.com/product/observed", **updates):
    fields = dict(id="observed", title="Чёрная футболка", category="tops", source_id="store",
                  source_url=url, price_rub=1000, sizes=["M"], availability="in_stock",
                  verified_at="2026-10-25T12:00:00+00:00", verification="verified",
                  evidence=["Observed stock and ordinary price"], is_demo=False)
    fields.update(updates)
    return Product(**fields)


class ParserTests(unittest.TestCase):
    def test_tracking_is_removed_but_variant_and_size_are_preserved(self):
        url = "HTTPS://STORE.EXAMPLE.COM:443/product/7?utm_source=x&size=M&variant=blue&gclid=secret#details"
        self.assertEqual(canonical_product_url(url), "https://store.example.com/product/7?size=M&variant=blue")
        first = product(url)
        second = product("https://store.example.com/product/7?variant=red&size=M")
        catalog = normalize_catalog([first, second], [], [])
        self.assertEqual(len(catalog.products), 2)

    def test_tracking_duplicates_choose_evidence_without_combining_inventory(self):
        first = product("https://store.example.com/product/7?utm_source=a", sizes=["S"], evidence=["one"])
        second = product("https://store.example.com/product/7?utm_source=b", sizes=["M"], evidence=["one", "two"])
        catalog = normalize_catalog([first, second], [], [])
        self.assertEqual(len(catalog.products), 1)
        self.assertEqual(catalog.products[0].sizes, ["M"])
        self.assertEqual(catalog.products[0].source_url, second.source_url,
                         "normalization must preserve the URL actually observed/fetched")

    def test_identity_is_stable_and_whitespace_is_normalized(self):
        first = normalize_catalog([product(title=" Чёрная\n  футболка ", sizes=[" M ", "M", "", " L"])], [], [])
        second = normalize_catalog([product(id="different")], [], [])
        self.assertEqual(first.products[0].id, second.products[0].id)
        self.assertEqual(first.products[0].title, "Чёрная футболка")
        self.assertEqual(first.products[0].sizes, ["M", "L"])

    def test_invalid_absolute_urls_and_credentials_are_rejected(self):
        for url in ("/product/7", "javascript:alert(1)", "ftp://store.example.com/7", "https://user:secret@store.example.com/7"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonical_product_url(url)

    def test_live_admission_needs_verification_stock_price_timestamp_evidence(self):
        for fields in ({"verification": "unverified"}, {"availability": "unknown"}, {"availability": "out_of_stock"},
                       {"price_rub": None}, {"price_rub": 0}, {"verified_at": None}, {"evidence": []}, {"is_demo": True}):
            with self.subTest(fields=fields):
                catalog = normalize_catalog([product(**fields)], [], [])
                self.assertFalse(catalog.products)
                self.assertTrue(catalog.warnings)

    def test_demo_requires_explicit_demo_mode_and_both_flags(self):
        fixture = product("https://demo.velor.invalid/1", is_demo=True, verification="demo", availability="unknown", verified_at=None)
        self.assertFalse(normalize_catalog([fixture], [], []).products)
        catalog = normalize_catalog([fixture], [], [], demo=True)
        self.assertEqual(len(catalog.products), 1)
        self.assertTrue(catalog.products[0].id.startswith("demo-"))
        self.assertFalse(normalize_catalog([product()], [], [], demo=True).products)

    def test_invalid_url_product_is_excluded_and_warning_deduped(self):
        catalog = normalize_catalog([product("file:///etc/passwd")], [], ["same", "same"])
        self.assertFalse(catalog.products)
        self.assertEqual(catalog.warnings.count("same"), 1)
        self.assertTrue(any("URL" in warning for warning in catalog.warnings))

    def test_international_host_is_normalized(self):
        self.assertEqual(canonical_product_url("https://пример.рф/product/7"), "https://xn--e1afmkfd.xn--p1ai/product/7")

    def test_signed_ordered_url_and_generic_ref_selector_are_preserved(self):
        observed = "https://store.example.com/product/7?variant=blue&size=M&size=L&ref=sku-42&signature=abc%2Fdef&utm_source=search"
        catalog = normalize_catalog([product(observed)], [], [])
        self.assertEqual(catalog.products[0].source_url, observed)
        key = canonical_product_url(observed)
        self.assertIn("variant=blue&size=M&size=L&ref=sku-42&signature=", key)
        self.assertNotIn("utm_source", key)
        self.assertNotEqual(canonical_product_url("https://store.example.com/product/7?size=M&variant=blue"),
                            canonical_product_url("https://store.example.com/product/7?variant=blue&size=M"),
                            "query ordering can be significant for signed URLs")


if __name__ == "__main__":
    unittest.main()
