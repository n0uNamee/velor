"""Stylist-only contracts; shared API models remain owned by the integrator.

Facts are an optional sidecar supplied by the normalized catalog owner, never
inferred from a wardrobe image. None means unknown; an empty tuple is known empty.
"""
from dataclasses import dataclass, field
from typing import Mapping

from ..models import Outfit


@dataclass(frozen=True)
class ProductFacts:
    colors: tuple[str, ...] | None = None
    materials: tuple[str, ...] | None = None
    tags: tuple[str, ...] | None = None


@dataclass(frozen=True)
class StylingOptions:
    excluded_product_ids: frozenset[str] = frozenset()
    owned_product_ids: frozenset[str] = frozenset()
    pinned_product_ids: frozenset[str] = frozenset()
    item_slots: tuple[str, ...] | None = None
    facts: Mapping[str, ProductFacts] = field(default_factory=dict)
    max_outfits: int = 3


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    product_id: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    total_price_rub: float | None = None
    purchase_price_rub: float | None = None
    unknowns: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompositionResult:
    outfits: list[Outfit]
    issues: tuple[ValidationIssue, ...] = ()
    strategy: str = "deterministic_rules"
    provider_status: str = "not_configured"
    is_demo: bool = False


class OutfitValidationError(ValueError):
    def __init__(self, issues: tuple[ValidationIssue, ...]):
        self.issues = issues
        self.code = issues[0].code if issues else "invalid_outfit"
        super().__init__("; ".join(issue.message for issue in issues))
