from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["headwear", "tops", "bottoms", "shoes", "accessories"]
CATEGORIES: list[Category] = ["headwear", "tops", "bottoms", "shoes", "accessories"]
Mode = Literal["demo", "live"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ImageRef(Model):
    id: str
    kind: Literal["wardrobe", "reference"]
    url: str | None = None
    local_path: str | None = None
    mime_type: str | None = None


class Profile(Model):
    id: str
    style_text: str
    images: list[ImageRef] = Field(default_factory=list)
    created_at: str
    updated_at: str


class Constraint(Model):
    text: str
    strength: Literal["hard", "soft"]
    provenance: Literal["profile", "request", "inferred"]
    confidence: float = Field(ge=0, le=1)


class StyleBrief(Model):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    profile_id: str
    original_profile_text: str
    original_request_text: str
    images: list[ImageRef] = Field(default_factory=list)
    categories: list[Category] = Field(default_factory=lambda: list(CATEGORIES))
    search_queries: list[str] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    preferences: list[Constraint] = Field(default_factory=list)
    exclusions: list[Constraint] = Field(default_factory=list)
    budget_rub: float | None = Field(default=None, gt=0)
    sizes: dict[str, str] | None = None
    city: str | None = None
    unknowns: list[str] = Field(default_factory=list)
    mode: Mode


class Product(Model):
    id: str
    title: str
    category: Category
    source_id: str
    source_url: str
    image_url: str | None = None
    price_rub: float | None = Field(default=None, ge=0)
    price_note: str | None = None
    sizes: list[str] = Field(default_factory=list)
    availability: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    verified_at: str | None = None
    verification: Literal["verified", "unverified", "demo"] = "unverified"
    evidence: list[str] = Field(default_factory=list)
    is_demo: bool = False


class SourceStatus(Model):
    source_id: str
    name: str
    state: Literal["queued", "searching", "verifying", "complete", "inaccessible", "unconfigured", "failed"]
    found: int = Field(default=0, ge=0)
    detail: str | None = None


class ProductCatalog(Model):
    schema_version: Literal["1.0"] = "1.0"
    products: list[Product] = Field(default_factory=list)
    sources: list[SourceStatus] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Outfit(Model):
    id: str
    request_id: str
    title: str
    product_ids: list[str]
    revision: int = Field(default=1, ge=1)
    render_revision: int | None = None
    render_status: Literal["pending", "ready", "failed"] = "pending"
    render_url: str | None = None
    saved: bool = False
    explanation: str
    render_disclaimer: str


class RequestState(Model):
    id: str
    profile_id: str
    text: str
    status: Literal["searching", "selection", "styling", "ready", "failed"]
    brief: StyleBrief
    catalog: ProductCatalog = Field(default_factory=ProductCatalog)
    excluded_product_ids: list[str] = Field(default_factory=list)
    outfits: list[Outfit] = Field(default_factory=list)
    created_at: str
    error: str | None = None


class ProfileInput(Model):
    style_text: str = Field(max_length=12000)
    images: list[ImageRef] = Field(default_factory=list, max_length=24)


class RequestInput(Model):
    text: str = Field(min_length=1, max_length=12000)
    images: list[ImageRef] = Field(default_factory=list, max_length=24)
    budget_rub: float | None = Field(default=None, gt=0, le=100000000)
    sizes: dict[Literal["clothing", "headwear", "tops", "bottoms", "shoes", "accessories"], Annotated[str, Field(min_length=1, max_length=60)]] | None = None
    city: str | None = Field(default=None, max_length=120)


class ReplaceInput(Model):
    old_product_id: str
    new_product_id: str
    expected_revision: int = Field(ge=1)


class SaveInput(Model):
    expected_revision: int = Field(ge=1)


class Gallery(Model):
    outfits: list[Outfit]
    products: list[Product]
