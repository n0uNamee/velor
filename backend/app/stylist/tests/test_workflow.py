import asyncio
from urllib.parse import unquote

import pytest

from app.models import Constraint, Product, StyleBrief
from app.stylist import (
    OutfitValidationError, ProductFacts, RenderCoordinator, StylingOptions,
    compose_outfits_result, replace_and_render,
)


def fixtures():
    brief = StyleBrief(id="b", profile_id="p", original_profile_text="", original_request_text="",
                       categories=["tops"], mode="live", budget_rub=1500)
    products = [Product(id=pid, title=title, category="tops", source_id="shop", source_url="https://shop.example/p",
                        price_rub=1000, sizes=["M"], availability="in_stock", verification="verified")
                for pid, title in (("a", "Original top"), ("b", "New top"))]
    return brief, products


def test_replace_rerenders_new_revision_and_preserves_saved_previous_object():
    brief, products = fixtures()
    original = compose_outfits_result("r", brief, products).outfits[0]
    original.saved = True
    original.render_url = "old-preview"
    original.render_revision = 1
    original.render_status = "ready"
    replacement_id = next(p.id for p in products if p.id != original.product_ids[0])
    new, result = asyncio.run(replace_and_render(original, brief, products, original.product_ids[0], replacement_id,
                                                1, coordinator=RenderCoordinator()))
    assert new.revision == 2
    assert new.render_revision == 2
    assert new.render_status == "ready"
    assert new.saved is False
    assert result.applied
    assert result.status == "provider_unconfigured"
    assert "revision 2" in unquote(new.render_url)
    assert next(p.title for p in products if p.id == replacement_id) in unquote(new.render_url)
    assert original.saved and original.render_url == "old-preview" and original.revision == 1


def test_rejected_replace_does_not_call_renderer():
    brief, products = fixtures()
    original = compose_outfits_result("r", brief, products).outfits[0]

    class ForbiddenCoordinator:
        async def render(self, *args, **kwargs):
            pytest.fail("Rejected edit must not invoke rendering")

    with pytest.raises(OutfitValidationError):
        asyncio.run(replace_and_render(original, brief, products, original.product_ids[0], "unknown", 1,
                                       coordinator=ForbiddenCoordinator()))


def test_unrecognized_material_cannot_prove_a_negative_hard_constraint():
    brief, products = fixtures()
    brief.exclusions = [Constraint(text="без кожи", strength="hard", provenance="request", confidence=1)]
    options = StylingOptions(facts={p.id: ProductFacts(materials=("genuine_leather",)) for p in products})
    result = compose_outfits_result("r", brief, products, options=options)
    assert result.outfits == []
    assert any(issue.code == "unknown_hard_attribute" for issue in result.issues)


def test_explicit_offline_demo_unknown_stock_is_not_claimed_live():
    brief, products = fixtures()
    brief.mode = "demo"
    products = [p.model_copy(update={"availability": "unknown", "verification": "demo", "is_demo": True}) for p in products]
    result = compose_outfits_result("r", brief, products)
    assert result.outfits and result.is_demo
    assert "Демонстрационный" in result.outfits[0].explanation
    brief.mode = "live"
    assert not compose_outfits_result("r", brief, products).outfits


def test_integrator_backend_bridge_preserves_revision_and_uses_shared_backend():
    from app.stylist import BackendImageProvider, render_outfit_result

    class ExistingBackend:
        calls = []

        async def render_image(self, prompt, cache_key, input_references):
            self.calls.append((prompt, cache_key, input_references))
            return "https://cdn.example/render.png"

    brief, products = fixtures()
    for p in products:
        p.image_url = f"https://shop.example/{p.id}.jpg"
    current = compose_outfits_result("r", brief, products).outfits[0]
    backend = ExistingBackend()
    result = asyncio.run(render_outfit_result(current, products, provider=BackendImageProvider(backend), allow_external=True))
    assert result.status == "ready"
    assert len(backend.calls) == 1
    prompt, key, refs = backend.calls[0]
    assert "matte black" in prompt and '"revision": 1' in prompt
    assert refs == [next(p.image_url for p in products if p.id == current.product_ids[0])]
