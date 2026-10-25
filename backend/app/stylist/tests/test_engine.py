"""Catalog safety and revision invariants for the deterministic stylist."""

import pytest

from app.models import Constraint, Product, StyleBrief
from app.stylist.domain import (
    OutfitValidationError,
    ProductFacts,
    StylingOptions,
)
from app.stylist.engine import (
    compose_outfits,
    compose_outfits_result,
    replace_outfit_item,
    validate_outfit,
)


def product(product_id, category, *, price=1000, sizes=None, **changes):
    return Product(
        id=product_id,
        title=f"Verified catalog item {product_id}",
        category=category,
        source_id="shop",
        source_url=f"https://example.com/products/{product_id}",
        price_rub=price,
        sizes=sizes or [],
        availability=changes.pop("availability", "in_stock"),
        verification=changes.pop("verification", "verified"),
        **changes,
    )


def brief(**changes):
    return StyleBrief(
        id="brief-1",
        profile_id="profile-1",
        original_profile_text="",
        original_request_text="",
        categories=changes.pop("categories", ["tops", "bottoms", "shoes"]),
        mode=changes.pop("mode", "live"),
        **changes,
    )


def catalog():
    return [
        product("top-1", "tops", sizes=["M"]),
        product("bottom-1", "bottoms", sizes=["42"]),
        product("shoe-1", "shoes", sizes=["38"]),
    ]


def constraint(text):
    return Constraint(text=text, strength="hard", provenance="request", confidence=1)


def one_outfit(b=None, products=None, options=None):
    outfits = compose_outfits("request-1", b or brief(), products or catalog(), options=options)
    assert len(outfits) == 1
    return outfits[0]


def test_composition_uses_only_catalog_ids_and_reports_rules():
    products = catalog()
    result = compose_outfits_result("request-1", brief(), products)
    assert len(result.outfits) == 1
    outfit = result.outfits[0]
    assert set(outfit.product_ids) == {p.id for p in products}
    assert outfit.request_id == "request-1"
    assert outfit.revision == 1
    assert outfit.render_status == "pending"
    assert result.strategy == "deterministic_rules"
    assert result.provider_status == "not_configured"
    assert result.is_demo is False
    assert outfit.explanation


def test_empty_catalog_returns_no_invented_outfit():
    result = compose_outfits_result("request-1", brief(), [])
    assert result.outfits == []
    assert result.issues


def test_deleted_product_ids_are_never_reintroduced():
    products = catalog() + [product("top-2", "tops")]
    options = StylingOptions(excluded_product_ids=frozenset({"top-1"}))
    outfits = compose_outfits("request-1", brief(), products, options=options)
    assert outfits
    assert all("top-1" not in outfit.product_ids for outfit in outfits)
    assert all("top-2" in outfit.product_ids for outfit in outfits)


def test_duplicate_catalog_identity_fails_closed():
    products = catalog() + [product("top-1", "shoes")]
    result = compose_outfits_result("request-1", brief(), products)
    assert result.outfits == []
    assert result.issues


def test_required_slot_is_not_silently_omitted():
    result = compose_outfits_result("request-1", brief(), catalog()[:-1])
    assert result.outfits == []
    assert result.issues


def test_explicit_item_slots_are_observed():
    options = StylingOptions(item_slots=("tops", "shoes"))
    outfit = one_outfit(options=options)
    assert set(outfit.product_ids) == {"top-1", "shoe-1"}


def test_duplicate_brief_categories_produce_one_item_per_slot():
    outfit = one_outfit(brief(categories=["tops", "tops", "shoes"]))
    assert set(outfit.product_ids) == {"top-1", "shoe-1"}
    assert len(outfit.product_ids) == 2


def test_outfit_count_is_bounded_and_combinations_deduplicated():
    products = catalog() + [product("top-2", "tops"), product("bottom-2", "bottoms")]
    outfits = compose_outfits("request-1", brief(), products, options=StylingOptions(max_outfits=3))
    combinations = [frozenset(outfit.product_ids) for outfit in outfits]
    assert 1 <= len(outfits) <= 3
    assert len(set(combinations)) == len(combinations)
    assert len({outfit.id for outfit in outfits}) == len(outfits)


@pytest.mark.parametrize(
    "changes",
    [
        {"availability": "out_of_stock"},
        {"availability": "unknown"},
        {"verification": "unverified"},
        {"verification": "demo", "is_demo": True},
    ],
)
def test_live_composition_rejects_unverified_or_unavailable_products(changes):
    products = catalog()
    products[0] = product("top-1", "tops", **changes)
    assert compose_outfits("request-1", brief(), products) == []


def test_demo_products_are_explicitly_marked():
    products = catalog()
    products[0] = product("top-1", "tops", verification="demo", is_demo=True)
    result = compose_outfits_result("request-1", brief(mode="demo"), products)
    assert result.outfits
    assert result.is_demo is True
    label = (result.outfits[0].explanation + result.outfits[0].render_disclaimer).lower()
    assert "demo" in label or "демонстрационный" in label


def test_size_constraints_require_catalog_evidence():
    b = brief(sizes={"tops": "M", "bottoms": "42", "shoes": "38"})
    outfit = one_outfit(b)
    assert validate_outfit(outfit, b, catalog()).valid
    products = catalog()
    products[0] = product("top-1", "tops", sizes=["S"])
    assert compose_outfits("request-1", b, products) == []
    products[0] = product("top-1", "tops", sizes=[])
    assert compose_outfits("request-1", b, products) == []


def test_overall_budget_is_not_per_item_budget():
    assert compose_outfits("request-1", brief(budget_rub=2500), catalog()) == []
    outfit = one_outfit(brief(budget_rub=3000))
    report = validate_outfit(outfit, brief(budget_rub=3000), catalog())
    assert report.valid
    assert report.purchase_price_rub == 3000
    assert report.total_price_rub == 3000


def test_unknown_purchase_price_cannot_pass_hard_budget():
    products = catalog()
    products[0] = product("top-1", "tops", price=None)
    result = compose_outfits_result("request-1", brief(budget_rub=999999), products)
    assert result.outfits == []
    assert result.issues


def test_owned_catalog_item_has_zero_purchase_cost():
    options = StylingOptions(owned_product_ids=frozenset({"shoe-1"}))
    b = brief(budget_rub=2000)
    outfit = one_outfit(b, options=options)
    report = validate_outfit(outfit, b, catalog(), options=options)
    assert report.valid
    assert report.purchase_price_rub == 2000
    assert report.total_price_rub == 3000


def test_owned_product_must_exist_in_approved_catalog():
    options = StylingOptions(owned_product_ids=frozenset({"imagined-wardrobe-item"}))
    result = compose_outfits_result("request-1", brief(), catalog(), options=options)
    assert result.outfits == []
    assert result.issues


def test_unsupported_hard_text_is_not_silently_treated_as_soft():
    b = brief(constraints=[constraint("Обязательно водонепроницаемые материалы")])
    result = compose_outfits_result("request-1", b, catalog())
    assert result.outfits == []
    assert result.issues


def test_hard_material_exclusion_requires_known_facts():
    b = brief(exclusions=[constraint("без кожи")])
    result = compose_outfits_result("request-1", b, catalog())
    assert result.outfits == []
    facts = {p.id: ProductFacts(materials=("хлопок",)) for p in catalog()}
    options = StylingOptions(facts=facts)
    outfit = one_outfit(b, options=options)
    assert validate_outfit(outfit, b, catalog(), options=options).valid
    facts = dict(facts)
    facts["shoe-1"] = ProductFacts(materials=("кожа",))
    assert compose_outfits("request-1", b, catalog(), options=StylingOptions(facts=facts)) == []


def test_hard_color_requires_known_facts():
    b = brief(constraints=[constraint("только черный")])
    assert compose_outfits("request-1", b, catalog()) == []
    facts = {p.id: ProductFacts(colors=("черный",)) for p in catalog()}
    assert compose_outfits("request-1", b, catalog(), options=StylingOptions(facts=facts))
    facts["bottom-1"] = ProductFacts(colors=("белый",))
    assert compose_outfits("request-1", b, catalog(), options=StylingOptions(facts=facts)) == []


def test_synthesized_budget_and_size_constraints_use_structured_values():
    b = brief(
        budget_rub=3000,
        sizes={"tops": "M"},
        constraints=[constraint("Общий бюджет: до 3000 ₽"), constraint("Размеры: tops: M")],
    )
    assert compose_outfits("request-1", b, catalog())


def test_validator_rejects_fabricated_item_id_and_duplicate_slots():
    outfit = one_outfit()
    forged = outfit.model_copy(update={"product_ids": ["top-1", "bottom-1", "not-in-catalog"]})
    assert not validate_outfit(forged, brief(), catalog()).valid
    duplicated = outfit.model_copy(update={"product_ids": ["top-1", "top-1", "shoe-1"]})
    assert not validate_outfit(duplicated, brief(), catalog()).valid


def test_replace_preserves_pinned_others_and_requires_new_render_revision():
    products = catalog() + [product("top-2", "tops", price=1200)]
    original = one_outfit()
    original = original.model_copy(update={
        "render_revision": 1, "render_status": "ready", "render_url": "data:image/svg+xml,old", "saved": True,
    })
    snapshot = original.model_dump()
    options = StylingOptions(pinned_product_ids=frozenset({"bottom-1", "shoe-1"}))
    updated = replace_outfit_item(original, brief(), products, "top-1", "top-2", 1, options=options)
    assert updated.id == original.id
    assert updated.revision == 2
    assert set(updated.product_ids) == {"top-2", "bottom-1", "shoe-1"}
    assert updated.render_status == "pending"
    assert updated.render_revision is None
    assert updated.render_url is None
    assert updated.saved is False
    assert original.model_dump() == snapshot


@pytest.mark.parametrize(
    "old_id,new_id,expected_revision,options",
    [
        ("top-1", "top-2", 99, None),
        ("top-1", "absent", 1, None),
        ("top-1", "shoe-2", 1, None),
        ("absent", "top-2", 1, None),
        ("top-1", "top-2", 1, StylingOptions(excluded_product_ids=frozenset({"top-2"}))),
        ("top-1", "top-2", 1, StylingOptions(pinned_product_ids=frozenset({"top-1"}))),
    ],
)
def test_invalid_replacement_is_rejected(old_id, new_id, expected_revision, options):
    products = catalog() + [product("top-2", "tops"), product("shoe-2", "shoes")]
    outfit = one_outfit()
    snapshot = outfit.model_dump()
    with pytest.raises(OutfitValidationError) as error:
        replace_outfit_item(outfit, brief(), products, old_id, new_id, expected_revision, options=options)
    assert error.value.issues
    assert error.value.code
    assert outfit.model_dump() == snapshot


def test_replacement_rechecks_total_budget():
    products = catalog() + [product("top-2", "tops", price=2000)]
    b = brief(budget_rub=3000)
    outfit = one_outfit(b)
    with pytest.raises(OutfitValidationError):
        replace_outfit_item(outfit, b, products, "top-1", "top-2", 1)


def test_replacement_rechecks_size():
    products = catalog() + [product("top-2", "tops", sizes=["S"])]
    b = brief(sizes={"tops": "M"})
    outfit = one_outfit(b)
    with pytest.raises(OutfitValidationError):
        replace_outfit_item(outfit, b, products, "top-1", "top-2", 1)


def test_composition_does_not_mutate_input_catalog_or_brief():
    products = catalog()
    b = brief()
    snapshot_products = [p.model_dump() for p in products]
    snapshot_brief = b.model_dump()
    compose_outfits("request-1", b, products)
    assert [p.model_dump() for p in products] == snapshot_products
    assert b.model_dump() == snapshot_brief
