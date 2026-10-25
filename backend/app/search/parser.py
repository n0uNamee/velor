"""Final, deterministic catalog normalization. No network or inferred stock."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.models import Product, ProductCatalog, SourceStatus

_TRACKING = {"gclid", "fbclid", "yclid", "ysclid", "_openstat"}


def canonical_product_url(url: str) -> str:
    """Remove attribution only; preserve variant, size and meaningful queries."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Product URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("Product URL must not contain credentials")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    if port and port != (443 if parsed.scheme.lower() == "https" else 80):
        host += f":{port}"
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in _TRACKING]
    # Repeated parameters and their order can identify a variant or be signed.
    # This is a comparison key only, never the URL returned as verified evidence.
    return urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", urlencode(query), ""))


def is_verified_live_product(item: Product) -> bool:
    """Final structural gate, in addition to the verifier's fact checks."""
    return bool(not item.is_demo and item.verification == "verified"
                and item.availability == "in_stock" and item.verified_at is not None
                and item.price_rub is not None and item.price_rub > 0 and item.evidence)


def normalize_catalog(products: list[Product], sources: list[SourceStatus], warnings: list[str], *, demo: bool = False) -> ProductCatalog:
    """Admit verified live records, or explicitly selected demonstration records."""
    deduped: dict[str, Product] = {}
    notes = list(warnings)
    for item in products:
        allowed = (demo and item.is_demo and item.verification == "demo") or (not demo and is_verified_live_product(item))
        if not allowed:
            notes.append(f"{item.source_id}: исключена неподтверждённая карточка {item.id}.")
            continue
        try:
            url = canonical_product_url(item.source_url)
        except (ValueError, UnicodeError):
            notes.append(f"{item.source_id}: исключена карточка с некорректным URL.")
            continue
        title = re.sub(r"\s+", " ", item.title).strip()
        if not title:
            continue
        normalized = item.model_copy(update={
            "id": ("demo-" if demo else "product-") + hashlib.sha256(url.encode()).hexdigest()[:20],
            "title": title,
            "source_url": item.source_url,
            "sizes": list(dict.fromkeys(x.strip() for x in item.sizes if x.strip())),
            "evidence": list(dict.fromkeys(item.evidence)),
        })
        # Never combine stock or sizes across cards/variants. Prefer the record
        # with more explicit evidence if a tracking-only duplicate was observed.
        if url not in deduped or len(normalized.evidence) > len(deduped[url].evidence):
            deduped[url] = normalized
    return ProductCatalog(products=list(deduped.values()), sources=sources,
                          warnings=list(dict.fromkeys(notes)))
