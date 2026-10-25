"""Offline evidence tests; no merchant availability is implied by these fixtures."""
import json
import unittest

from app.search.extraction import detect_block_page, extract_candidates, extract_product, infer_category
from app.search.sources import BASE_SOURCES, DISCOVERY_SEEDS, SourceDefinition, host_matches


URL = "https://shop.example/product/hoodie-42/"
SOURCE = SourceDefinition("shop", "Example", ("shop.example",), "https://shop.example/search?q={query}")


def document(product):
    return '<script type="application/ld+json">' + json.dumps(product) + "</script>"


def product(**overrides):
    data = {
        "@type": "Product", "url": URL, "name": "Худи оверсайз чёрное", "size": "M",
        "description": "Хлопок, свободный крой", "itemCondition": "https://schema.org/NewCondition",
        "offers": {"@type": "Offer", "price": "4 990,00", "priceCurrency": "RUB", "availability": "https://schema.org/InStock"},
    }
    data.update(overrides)
    return data


class SourceTests(unittest.TestCase):
    def test_base_registry_exact_twelve_distinct_sources(self):
        self.assertEqual(len(BASE_SOURCES), 12)
        self.assertEqual(len({s.id for s in BASE_SOURCES}), 12)
        self.assertEqual({s.hosts[0] for s in BASE_SOURCES}, {"ozon.ru", "sportmaster.ru", "stockmann.ru", "ostin.com", "limestore.com", "befree.ru", "sela.ru", "zarina.ru", "loverepublic.ru", "zolla.com", "tvoe.ru", "finn-flare.ru"})

    def test_discovery_seeds_separate_and_not_base_hosts(self):
        self.assertEqual(len(DISCOVERY_SEEDS), 7)
        self.assertFalse({s.id for s in BASE_SOURCES} & {s.id for s in DISCOVERY_SEEDS})

    def test_query_encoded_not_interpolated_as_host(self):
        url = SOURCE.build_search_url("чёрное &url=https://evil.example/#")
        self.assertTrue(url.startswith("https://shop.example/search?q="))
        self.assertIn("%26url%3Dhttps%3A%2F%2Fevil.example%2F%23", url)

    def test_host_boundary(self):
        self.assertTrue(host_matches("https://www.shop.example/x", SOURCE.hosts))
        self.assertFalse(host_matches("https://shop.example.evil.com/x", SOURCE.hosts))
        self.assertFalse(host_matches("https://evilshop.example/x", SOURCE.hosts))


class LinkTests(unittest.TestCase):
    def test_challenge_detection_does_not_treat_library_as_block(self):
        self.assertIsNotNone(detect_block_page('<title>Доступ ограничен</title>'))
        self.assertIsNotNone(detect_block_page('<title>Just a moment...</title>'))
        self.assertIsNotNone(detect_block_page('<div id="captcha-container">Подтвердите, что вы человек</div>'))
        self.assertIsNone(detect_block_page('<title>Худи</title><script src="https://google.com/recaptcha/api.js"></script>'))

    def test_extract_actual_jsonld_and_hyperlinks_dedup(self):
        html = document({"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "item": product()}]})
        html += '<a href="/product/hoodie-42/#fragment">Худи</a><a href="/product/coat-43/">Пальто</a>'
        candidates = extract_candidates(html, "https://shop.example/search?q=hoodie", SOURCE)
        self.assertEqual([c.url for c in candidates], [URL, "https://shop.example/product/coat-43/"])
        self.assertEqual(candidates[0].source_id, "shop")
        self.assertEqual(candidates[0].hinted_title, "Худи оверсайз чёрное")

    def test_no_invented_urls_from_sku_or_name(self):
        html = document({"@type": "Product", "sku": "123", "name": "Худи"})
        self.assertEqual(extract_candidates(html, "https://shop.example/search", SOURCE), [])

    def test_offsite_credential_and_script_links_ignored(self):
        html = '<a href="https://evil.example/product/1">x</a><a href="https://x:y@shop.example/product/1">x</a><a href="javascript:alert(1)">x</a>'
        self.assertEqual(extract_candidates(html, "https://shop.example/search", SOURCE), [])

    def test_malformed_json_is_ignored(self):
        html = '<script type="application/ld+json">{broken}</script><a href="/product/real">Real</a>'
        self.assertEqual(len(extract_candidates(html, URL, SOURCE)), 1)

    def test_observed_unicode_path_is_encoded(self):
        candidates = extract_candidates('<a href="/product/худи?цвет=чёрный">Худи</a>', URL, SOURCE)
        self.assertEqual(candidates[0].url, "https://shop.example/product/%D1%85%D1%83%D0%B4%D0%B8?%D1%86%D0%B2%D0%B5%D1%82=%D1%87%D1%91%D1%80%D0%BD%D1%8B%D0%B9")

    def test_result_bound(self):
        html = "".join(f'<a href="/product/{n}">{n}</a>' for n in range(20))
        self.assertEqual(len(extract_candidates(html, "https://shop.example/search", SOURCE, 3)), 3)
        self.assertEqual(extract_candidates(html, URL, SOURCE, 0), [])


class ProductTests(unittest.TestCase):
    def test_product_has_typed_facts_and_evidence(self):
        extracted = extract_product(document(product()), URL)
        self.assertEqual(extracted.title, "Худи оверсайз чёрное")
        self.assertEqual(extracted.price_rub, 4990)
        self.assertEqual(extracted.availability, "in_stock")
        self.assertEqual(extracted.size_availability, {"M": "in_stock"})
        self.assertEqual(extracted.available_sizes, ("M",))
        self.assertEqual(extracted.size_prices_rub, {"M": 4990})
        self.assertEqual(extracted.category, "tops")
        self.assertEqual(extracted.condition, "new")
        self.assertIsNone(extracted.city)
        self.assertTrue(any("ordinary price" in e for e in extracted.evidence))

    def test_size_buttons_not_inventory_or_sizes(self):
        data = product()
        data.pop("size")
        data["offers"].pop("availability")
        extracted = extract_product(document(data) + '<button data-size="M">M</button>', URL)
        self.assertEqual(extracted.availability, "unknown")
        self.assertEqual(extracted.available_sizes, ())
        self.assertEqual(extracted.sizes, ())

    def test_options_without_stock_stay_unknown(self):
        data = product(size=["S", "M"])
        data["offers"].pop("availability")
        extracted = extract_product(document(data), URL)
        self.assertEqual(extracted.sizes, ("S", "M"))
        self.assertEqual(extracted.size_availability, {"S": "unknown", "M": "unknown"})

    def test_generic_multiple_size_options_and_stock_not_per_size(self):
        extracted = extract_product(document(product(size=["S", "M"])), URL)
        self.assertEqual(extracted.availability, "in_stock")
        self.assertEqual(extracted.available_sizes, ())
        self.assertEqual(extracted.size_availability, {"S": "unknown", "M": "unknown"})
        self.assertEqual(extracted.size_prices_rub, {})

    def test_variant_stock_per_size(self):
        data = product(size=None, hasVariant=[
            {"@type": "Product", "size": "S", "offers": {"availability": "https://schema.org/OutOfStock"}},
            {"@type": "Product", "size": "M", "offers": {"availability": "https://schema.org/InStock"}},
        ])
        extracted = extract_product(document(data), URL)
        self.assertEqual(extracted.available_sizes, ("M",))
        self.assertEqual(extracted.size_availability, {"S": "out_of_stock", "M": "in_stock"})

    def test_generic_options_refined_by_explicit_variant_stock(self):
        data = product(size=["S", "M"], hasVariant=[{"@type": "Product", "size": "M", "offers": {"availability": "https://schema.org/InStock"}}])
        data.pop("url")
        extracted = extract_product(document(data), URL)
        self.assertEqual(extracted.available_sizes, ("M",))
        self.assertEqual(extracted.size_availability, {"S": "unknown", "M": "in_stock"})

    def test_variant_price_stays_coupled_to_in_stock_size(self):
        data = product(size=["S", "M"], hasVariant=[
            {"@type": "Product", "size": "S", "offers": {"price": 1000, "priceCurrency": "RUB", "availability": "https://schema.org/OutOfStock"}},
            {"@type": "Product", "size": "M", "offers": {"price": 3500, "priceCurrency": "RUB", "availability": "https://schema.org/InStock"}},
        ])
        extracted = extract_product(document(data), URL)
        self.assertEqual(extracted.size_prices_rub, {"M": 3500})

    def test_variant_only_price_can_supply_ruble_price_evidence(self):
        extracted = extract_product(document(product(size=None, offers=None, hasVariant=[
            {"@type": "Product", "size": "M", "offers": {"price": 3500, "priceCurrency": "RUB", "availability": "https://schema.org/InStock"}},
        ])), URL)
        self.assertEqual(extracted.currency, "RUB")
        self.assertEqual(extracted.price_rub, 3500)
        self.assertEqual(extracted.size_prices_rub, {"M": 3500})
        self.assertEqual(extracted.availability, "in_stock")

    def test_conflicting_variant_prices_cannot_be_resurrected(self):
        extracted = extract_product(document(product(size=None, offers=None, hasVariant=[
            {"@type": "Product", "size": "M", "offers": {"price": price, "priceCurrency": "RUB", "availability": "https://schema.org/InStock"}}
            for price in (1000, 5000, 1000)
        ])), URL)
        self.assertEqual(extracted.size_prices_rub, {})

    def test_price_and_stock_on_separate_offers_not_coupled(self):
        extracted = extract_product(document(product(offers=[
            {"price": 1000, "priceCurrency": "RUB", "availability": "https://schema.org/OutOfStock"},
            {"availability": "https://schema.org/InStock"},
        ])), URL)
        self.assertEqual(extracted.size_prices_rub, {})

    def test_direct_jsonld_response_supported(self):
        self.assertEqual(extract_product(json.dumps(product()), URL).price_rub, 4990)

    def test_conditional_price_separate(self):
        extracted = extract_product(document(product(offers=[
            {"price": 1200, "priceCurrency": "RUB", "name": "Цена по карте", "availability": "https://schema.org/InStock"},
            {"price": 1800, "priceCurrency": "RUB", "availability": "https://schema.org/InStock"},
        ])), URL)
        self.assertEqual(extracted.price_rub, 1800)
        self.assertEqual(extracted.conditional_price_rub, 1200)
        self.assertIn("eligibility not confirmed", extracted.price_note)

    def test_member_tier_price_specification_not_ordinary(self):
        extracted = extract_product(document(product(offers={"priceSpecification": {"price": 1000, "priceCurrency": "RUB", "validForMemberTier": "gold"}})), URL)
        self.assertIsNone(extracted.price_rub)
        self.assertEqual(extracted.conditional_price_rub, 1000)

    def test_list_price_not_current_price(self):
        extracted = extract_product(document(product(offers={"priceSpecification": {"price": 4000, "priceCurrency": "RUB", "priceType": "https://schema.org/ListPrice"}})), URL)
        self.assertIsNone(extracted.price_rub)

    def test_missing_currency_foreign_nan_negative_not_rubles(self):
        for offer in ({"price": 500}, {"price": 10, "priceCurrency": "USD"}, {"price": "NaN", "priceCurrency": "RUB"}, {"price": -50, "priceCurrency": "RUB"}):
            with self.subTest(offer=offer):
                self.assertIsNone(extract_product(document(product(offers=offer)), URL).price_rub)

    def test_currency_not_leaked_between_offers(self):
        extracted = extract_product(document(product(offers=[{"price": 5000, "priceCurrency": "RUB"}, {"price": 5}])), URL)
        self.assertEqual(extracted.price_rub, 5000)

    def test_unknown_availability_never_in_stock(self):
        for token in ("https://schema.org/PreOrder", "https://schema.org/BackOrder", "yes", ""):
            with self.subTest(token=token):
                extracted = extract_product(document(product(offers={"availability": token})), URL)
                self.assertEqual(extracted.availability, "unknown")

    def test_conflicting_availability_unknown(self):
        extracted = extract_product(document(product(offers=[{"availability": "https://schema.org/InStock"}, {"availability": "https://schema.org/OutOfStock"}])), URL)
        self.assertEqual(extracted.availability, "unknown")
        self.assertEqual(extracted.available_sizes, ())

    def test_listing_not_product_page(self):
        self.assertIsNone(extract_product(document(product()), "https://shop.example/search"))
        self.assertIsNone(extract_product('<h1>Каталог</h1><div>1200 ₽ В наличии</div>', "https://shop.example/search"))

    def test_semantic_query_identity_mismatch_rejected(self):
        self.assertIsNone(extract_product(document(product(url="https://shop.example/product?id=A")), "https://shop.example/product?id=B"))
        self.assertIsNone(extract_product(document(product(url="https://shop.example/product?id=A")) + '<meta property="og:type" content="product">', "https://shop.example/product?id=B"))

    def test_repeated_query_selector_order_is_preserved(self):
        self.assertIsNone(extract_product(document(product(url=URL + "?a=1&a=2")), URL + "?a=2&a=1"))

    def test_conflicting_variant_color_or_condition_does_not_supply_stock(self):
        for override in ({"color": "white"}, {"name": "Белое худи"}, {"itemCondition": "https://schema.org/UsedCondition"}):
            with self.subTest(override=override):
                extracted = extract_product(document(product(size=["S", "M"], offers=None, hasVariant=[{
                    "@type": "Product", "size": "M", "offers": {"price": 5000, "priceCurrency": "RUB", "availability": "https://schema.org/InStock"}, **override,
                }])), URL)
                self.assertEqual(extracted.available_sizes, ())
                self.assertEqual(extracted.size_prices_rub, {})

    def test_conflicting_offer_condition_unknown(self):
        extracted = extract_product(document(product(offers=[
            {"price": 1000, "priceCurrency": "RUB", "availability": "https://schema.org/InStock", "itemCondition": "https://schema.org/UsedCondition"},
            {"price": 5000, "priceCurrency": "RUB", "availability": "https://schema.org/InStock", "itemCondition": "https://schema.org/NewCondition"},
        ])), URL)
        self.assertEqual(extracted.condition, "unknown")

    def test_price_city_delivery_cannot_be_assembled_from_different_offers(self):
        extracted = extract_product(document(product(offers=[
            {"price": 1000, "priceCurrency": "RUB", "availability": "https://schema.org/InStock"},
            {"price": 5000, "priceCurrency": "RUB", "availability": "https://schema.org/InStock", "availableAtOrFrom": {"name": "Москва"}, "shippingDetails": {"shippingDestination": {"addressLocality": "Москва"}}},
        ])), URL)
        self.assertEqual(extracted.size_prices_rub, {"M": 1000})
        self.assertEqual(extracted.size_cities, {})
        self.assertEqual(extracted.size_deliveries, {})

    def test_city_and_delivery_not_assembled_across_same_price_variants(self):
        extracted = extract_product(document(product(size=None, offers=None, hasVariant=[
            {"@type": "Product", "size": "M", "offers": {"price": 5000, "priceCurrency": "RUB", "availability": "https://schema.org/InStock", "availableAtOrFrom": {"name": "Москва"}}},
            {"@type": "Product", "size": "M", "offers": {"price": 5000, "priceCurrency": "RUB", "availability": "https://schema.org/InStock", "shippingDetails": {"shippingDestination": {"addressLocality": "Москва"}}}},
        ])), URL)
        self.assertFalse(extracted.size_cities and extracted.size_deliveries)

    def test_tracking_query_can_be_ignored_but_variant_kept(self):
        extracted = extract_product(document(product(url=URL + "?variant=M&utm_source=merchant")), URL + "?utm_medium=search&variant=M")
        self.assertEqual(extracted.title, "Худи оверсайз чёрное")

    def test_multiple_unidentified_products_are_not_one_product(self):
        first, second = product(), product(name="Пальто")
        first.pop("url")
        second.pop("url")
        self.assertIsNone(extract_product(document([first, second]), URL))

    def test_open_graph_product_fallback(self):
        html = '<meta property="og:type" content="product"><meta property="og:title" content="Брюки"><meta property="product:price:amount" content="3400"><meta property="product:price:currency" content="RUB"><meta property="og:image" content="/image.jpg">'
        extracted = extract_product(html, URL)
        self.assertEqual(extracted.category, "bottoms")
        self.assertEqual(extracted.price_rub, 3400)
        self.assertEqual(extracted.image_url, "https://shop.example/image.jpg")
        self.assertEqual(extracted.availability, "unknown")

    def test_used_city_delivery_preserved(self):
        data = product(itemCondition="https://schema.org/UsedCondition")
        data["offers"].update({"availableAtOrFrom": {"address": {"addressLocality": "Москва"}}, "shippingDetails": {"shippingDestination": {"addressCountry": "RU"}}})
        extracted = extract_product(document(data), URL)
        self.assertEqual(extracted.condition, "used")
        self.assertEqual(extracted.city, "Москва")
        self.assertEqual(extracted.delivery, "RU")
        self.assertTrue(any("city eligibility not confirmed" in e for e in extracted.evidence))

    def test_category_unknown_no_default_category(self):
        self.assertIsNone(infer_category("Карточка 123"))


if __name__ == "__main__":
    unittest.main()
