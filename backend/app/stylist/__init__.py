"""VÉLOR catalog stylist and matte black mannequin rendering.

Default path is deterministic and local. No provider or credential is discovered.
"""
from .domain import (
    CompositionResult, OutfitValidationError, ProductFacts, StylingOptions,
    ValidationIssue, ValidationReport,
)
from .engine import compose_outfits, compose_outfits_result, replace_outfit_item, validate_outfit
from .providers import OutfitProposal, StylistProvider, StylistRequest, compose_with_provider
from .rendering import (
    ImageRenderProvider, ProviderImage, RenderCoordinator, RenderRequest,
    RenderResult, render_outfit, render_outfit_result, schematic_svg,
)
from .workflow import replace_and_render
from .backend_provider import BackendImageProvider

__all__ = [
    "compose_outfits", "compose_outfits_result", "replace_outfit_item", "validate_outfit",
    "compose_with_provider", "render_outfit", "render_outfit_result", "schematic_svg", "replace_and_render",
    "CompositionResult", "OutfitValidationError", "ProductFacts", "StylingOptions",
    "ValidationIssue", "ValidationReport", "OutfitProposal", "StylistProvider", "StylistRequest",
    "ImageRenderProvider", "ProviderImage", "RenderCoordinator", "RenderRequest", "RenderResult",
    "BackendImageProvider",
]
