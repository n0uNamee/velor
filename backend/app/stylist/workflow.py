"""Revision then render, for the API's single-item edit action."""
from ..models import Outfit, Product, StyleBrief
from .domain import StylingOptions
from .engine import replace_outfit_item
from .rendering import ImageRenderProvider, RenderCoordinator, RenderResult


async def replace_and_render(
    outfit: Outfit, brief: StyleBrief, products: list[Product],
    old_product_id: str, new_product_id: str, expected_revision: int, *,
    coordinator: RenderCoordinator, options: StylingOptions | None = None,
    provider: ImageRenderProvider | None = None, allow_external: bool = False,
    fallback: bool = True, timeout_seconds: float = 30.0,
) -> tuple[Outfit, RenderResult]:
    """Validate a replacement, preserve all other IDs, then render new revision.

    Caller owns persistence and its atomic expected-revision compare-and-set.
    Reuse one coordinator for the request lifetime. A rejected replacement does
    not invoke the renderer. This function never modifies the saved old object.
    """
    revised = replace_outfit_item(
        outfit, brief, products, old_product_id, new_product_id,
        expected_revision, options=options,
    )
    result = await coordinator.render(
        revised, products, provider=provider, allow_external=allow_external,
        fallback=fallback, timeout_seconds=timeout_seconds,
    )
    return revised, result
