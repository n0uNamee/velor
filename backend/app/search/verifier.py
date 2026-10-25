"""Conservative product re-fetching and evidence-based verification.

This module does not interpret user images or pretend to be an LLM. The local
style matcher only accepts explicitly recognized lexical requirements. Complex
or unknown hard requirements stay unverified rather than becoming valid items.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from app.models import Product, StyleBrief

from .extraction import ExtractedProduct, ProductCandidate, extract_product
from .sources import BASE_SOURCES, host_matches
from .transport import AsyncFetcher, FetchError


@dataclass(frozen=True)
class VerificationResult:
    product: Product | None = None
    valid: bool = False
    reasons: tuple[str, ...] = ()
    state: str = "complete"

    @property
    def detail(self) -> str:
        return "; ".join(self.reasons)


_CATEGORY_TERMS = {
    "headwear": ("шапк", "кепк", "панам", "шляп", "бейсболк", "hat", "cap", "beanie"),
    "tops": ("куртк", "футболк", "рубашк", "худи", "свит", "джемпер", "лонгслив", "толстовк", "топ", "пиджак", "жилет", "блуз", "пальто", "shirt", "hoodie", "jacket", "sweater", "coat", "top"),
    "bottoms": ("брюк", "джинс", "шорт", "юбк", "леггин", "трико", "pants", "trouser", "jeans", "skirt", "shorts"),
    "shoes": ("кроссов", "кед", "ботин", "туфл", "сапог", "лофер", "сандал", "sneaker", "boot", "shoe", "loafer"),
    "accessories": ("сумк", "рюкзак", "ремень", "браслет", "кольц", "шарф", "перчат", "очк", "bag", "belt", "scarf", "glove", "wallet"),
}
_FEATURES = {
    "black": ("черн", "чёрн", "black"),
    "white": ("бел", "white"),
    "grey": ("серый", "серая", "серое", "серые", "серого", "серой", "сером", "серую", "серых", "grey", "gray"),
    "blue": ("синий", "синяя", "синее", "синие", "синего", "синей", "синих", "голуб", "blue"),
    "red": ("красн", "red"),
    "green": ("зелен", "зелён", "green"),
    "beige": ("беж", "beige"),
    "oversize": ("оверсайз", "oversize", "oversized", "свободн"),
    "cotton": ("хлоп", "cotton"),
    "leather": ("кожан", "кожа", "кожи", "натуральная кожа", "leather"),
    "linen": ("льнян", "лён", "лен ", "linen"),
    "wool": ("шерст", "wool"),
    "denim": ("джинсов", "деним", "denim"),
    "waterproof": ("водонепрониц", "непромока", "waterproof"),
    "vintage": ("винтаж", "vintage"),
}
_CONDITION_WORDS = ("новый", "новая", "новое", "новые", "новую", "новых", "new", "подерж", "used", "восстановлен", "refurbished", "поврежден", "damaged", "бу")
_FILLER = {"а", "и", "в", "во", "с", "со", "из", "на", "по", "к", "от", "это", "этот", "эту", "эти", "один", "одну", "я", "мне", "меня", "хочу", "нужен", "нужна", "нужны", "нужно", "найди", "найти", "подбери", "подобрать", "ищу", "пожалуйста", "купить", "только", "обязательно", "одежда", "вещи", "образ", "лук", "стиль", "стиле", "the", "a", "an", "and", "for", "i", "want", "need", "find", "buy", "please", "clothes", "outfit", "style", "must", "required"}


def _unknown_words(text: str) -> list[str]:
    known = [word.replace("ё", "е").strip() for words in (*_FEATURES.values(), *_CATEGORY_TERMS.values(), _CONDITION_WORDS) for word in words]
    return [word for word in re.findall(r"[^\W\d_]+", text) if word not in _FILLER and not any(_contains(word, prefix) for prefix in known if " " not in prefix)]


def _normal(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def _contains(text: str, term: str) -> bool:
    # Stems are intentional for Russian inflections; Latin words use boundaries.
    if term.isascii() and term.isalpha():
        return bool(re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", text))
    return bool(re.search(r"(?<!\w)" + re.escape(term.replace("ё", "е")), text))


def _features(text: str) -> set[str]:
    return {name for name, words in _FEATURES.items() if any(_contains(text, word) for word in words)}


def _requested_size(brief: StyleBrief, category: str | None) -> str | None:
    if not brief.sizes:
        return None
    if category in brief.sizes:
        return brief.sizes[category]
    aliases = {"headwear": ("головной убор", "голова"), "tops": ("верх", "одежда"), "bottoms": ("низ", "брюки"), "shoes": ("обувь",), "accessories": ("аксессуары",)}
    for key, value in brief.sizes.items():
        if key.lower() in aliases.get(category or "", ()):
            return value
    return brief.sizes.get("all") or brief.sizes.get("default")


def _size(value: str) -> str:
    return re.sub(r"\s+", "", value).replace(",", ".").upper()


def _lexical_match(extracted: ExtractedProduct, brief: StyleBrief) -> tuple[bool, list[str]]:
    # Only merchant-authored descriptive fields establish style. Extraction
    # diagnostics (e.g. "city eligibility not confirmed") are not garment text.
    facts = _normal(" ".join((extracted.title or "", extracted.description or "")))
    request = _normal(" ".join([*brief.search_queries, *(item.text for item in brief.preferences)]))
    wanted = _features(request)
    matched = _features(facts)
    reasons: list[str] = []
    # A keyword in a negated statement is not positive evidence of that fact.
    # Reject conservatively rather than infer the scope of arbitrary negation.
    if re.search(r"(?<!\w)(?:не|без|нет|no|not|without)(?!\w)", facts):
        reasons.append("style_match unknown: product evidence contains negation requiring semantic verification")
    missing = wanted - matched
    if missing:
        reasons.append("style_match unknown: product evidence does not support " + ", ".join(sorted(missing)))
    unknown_words = _unknown_words(request)
    if unknown_words:
        reasons.append("style_match unknown: semantic interpretation required for " + ", ".join(dict.fromkeys(unknown_words)))
    requested_garments = {term for terms in _CATEGORY_TERMS.values() for term in terms if _contains(request, term)}
    if requested_garments and not any(_contains(facts, term) for term in requested_garments):
        reasons.append("style_match unknown: requested garment type is absent from product evidence")
    # Exclusions and hard constraints are never discarded based on confidence.
    # Unsupported text remains unknown, even when ordinary style words match.
    for exclusion in brief.exclusions:
        excluded_features = _features(_normal(exclusion.text))
        if not excluded_features:
            reasons.append("hard exclusion is unsupported by local lexical verifier: " + exclusion.text)
        elif excluded_features & matched:
            reasons.append("product conflicts with exclusion: " + exclusion.text)
        elif _normal(exclusion.text) not in facts:
            reasons.append("absence required by exclusion is unknown: " + exclusion.text)
    for constraint in brief.constraints:
        if constraint.strength != "hard":
            continue
        text = _normal(constraint.text)
        if re.match(r"^(общий бюджет|бюджет|размеры?):", text):
            continue
        known_features = _features(text)
        has_category = any(_contains(text, term) for terms in _CATEGORY_TERMS.values() for term in terms)
        # A plain category/color/material constraint has a defensible lexical
        # interpretation. Other requirements cannot be inferred from keywords.
        if _unknown_words(text) or not (known_features or has_category):
            reasons.append("hard constraint needs a semantic verifier: " + constraint.text)
        if known_features - matched:
            reasons.append("hard constraint lacks supporting product evidence: " + constraint.text)
        required_garments = {term for terms in _CATEGORY_TERMS.values() for term in terms if _contains(text, term)}
        if required_garments and not any(_contains(facts, term) for term in required_garments):
            reasons.append("hard constraint garment type lacks supporting product evidence: " + constraint.text)
    category_match = bool(extracted.category and extracted.category in brief.categories)
    request_has_category = any(_contains(request, term) for terms in _CATEGORY_TERMS.values() for term in terms)
    if not category_match:
        reasons.append("category is unknown or outside requested categories")
    # A request containing only an abstract aesthetic (e.g. avant-garde) cannot
    # be marked matched because the title happened to mention a generic item.
    if not wanted and not request_has_category:
        reasons.append("style_match unknown: no supported style or garment term in search queries")
    return not reasons, reasons


class ProductVerifier:
    def __init__(self, fetcher: AsyncFetcher) -> None:
        self.fetcher = fetcher

    async def verify(self, candidate: ProductCandidate, brief: StyleBrief) -> VerificationResult:
        try:
            page = await self.fetcher.fetch(candidate.url)
        except FetchError as exc:
            return VerificationResult(reasons=(exc.detail,), state=exc.state)
        observed_at = datetime.now(timezone.utc).isoformat()
        extracted = extract_product(page.text, page.url)
        if extracted is None or not extracted.title:
            return VerificationResult(reasons=("Fetched URL has no independently extractable product title/schema; a search result is not a verified product.",))
        evidence = [*candidate.evidence, *extracted.evidence, f"Product page fetched: {page.url}", f"Observed at: {observed_at}"]
        reasons: list[str] = []
        source = next((source for source in BASE_SOURCES if source.id == candidate.source_id), None)
        if source and not host_matches(page.url, source.hosts):
            reasons.append("product redirect left the declared source hosts")
        if candidate.source_id == "discovery" and any(host_matches(page.url, source.hosts) for source in BASE_SOURCES):
            reasons.append("discovery redirect resolved to a base source rather than an external store")
        if not extracted.category:
            reasons.append("category unknown")
        requested_size = _requested_size(brief, extracted.category)
        available_sizes = tuple(extracted.available_sizes)
        prices = {_size(size): value for size, value in extracted.size_prices_rub.items() if math.isfinite(value) and value > 0}
        selected_price = prices.get(_size(requested_size)) if requested_size else min((prices[_size(size)] for size in available_sizes if _size(size) in prices), default=None)
        selected_sizes = tuple(size for size in available_sizes if _size(size) in prices and prices[_size(size)] == selected_price and (requested_size is None or _size(size) == _size(requested_size)))
        if selected_price is None:
            reasons.append("ordinary RUB price unknown for the inventory-backed size; conditional or loyalty price alone is insufficient")
        elif brief.budget_rub is not None and selected_price > brief.budget_rub:
            reasons.append("ordinary item price exceeds the complete outfit budget")
        selected_stock = "in_stock" if selected_sizes else extracted.availability
        if selected_stock != "in_stock":
            reasons.append("stock is out_of_stock" if selected_stock == "out_of_stock" else "stock unknown")
        if requested_size:
            if _size(requested_size) not in {_size(item) for item in available_sizes}:
                reasons.append(f"size-specific inventory unknown or unavailable for requested size {requested_size}; size buttons are not inventory")
        elif not available_sizes:
            reasons.append("size-specific inventory unknown; selectable sizes are not stock evidence")
        if brief.sizes and requested_size is None:
            reasons.append("requested size mapping cannot be applied to this product category")
        city_facts = {_size(size): value for size, value in extracted.size_cities.items()}
        delivery_facts = {_size(size): value for size, value in extracted.size_deliveries.items()}
        observed_city = ", ".join(dict.fromkeys(city_facts[_size(size)] for size in selected_sizes if _size(size) in city_facts))
        observed_delivery = ", ".join(dict.fromkeys(delivery_facts[_size(size)] for size in selected_sizes if _size(size) in delivery_facts))
        if brief.city:
            pattern = r"(?<!\w)" + re.escape(_normal(brief.city)) + r"(?!\w)"
            eligible_sizes = tuple(size for size in selected_sizes if re.search(pattern, _normal(city_facts.get(_size(size), ""))) and re.search(pattern, _normal(delivery_facts.get(_size(size), ""))))
            if not observed_city or not re.search(pattern, _normal(observed_city)):
                reasons.append("city-specific availability unknown for " + brief.city)
            if not observed_delivery or not re.search(pattern, _normal(observed_delivery)):
                reasons.append("delivery to requested city is unknown")
            if selected_sizes and not eligible_sizes and not any("city" in reason for reason in reasons):
                reasons.append("city availability and delivery are not coupled to the same priced inventory size")
            selected_sizes = eligible_sizes
        if (not extracted.condition or extracted.condition == "unknown") and candidate.source_id != "okno":
            reasons.append("condition new/used unknown")
        elif extracted.condition not in {"new", "unknown", None}:
            request_text = _normal(" ".join(brief.search_queries))
            accepted = {
                "used": ("б/у", "бу ", "подерж", "used", "винтаж", "vintage", "секонд", "second hand"),
                "refurbished": ("восстановлен", "refurbished"),
                "damaged": ("поврежден", "damaged"),
            }.get(extracted.condition, ())
            if not any(term in request_text for term in accepted):
                reasons.append(extracted.condition + " condition was not explicitly requested")
        condition_request = _normal(" ".join([*brief.search_queries, *(item.text for item in brief.constraints)]))
        required_conditions = {
            name for name, terms in {
                "new": ("новый", "новая", "новое", "новые", "новую", "новых", "new"),
                "used": ("подерж", "used", "б/у", "бу"),
                "refurbished": ("восстановлен", "refurbished"),
                "damaged": ("поврежден", "damaged"),
            }.items() if any(_contains(condition_request, term) for term in terms)
        }
        if required_conditions and required_conditions != {extracted.condition}:
            reasons.append("product condition conflicts with requested condition or request is ambiguous")
        checked_brief = brief
        if candidate.source_id == "okno":
            checked_brief = brief.model_copy(update={"search_queries": [brief.original_request_text], "preferences": []})
            evidence.append("Проверены название/категория/цена/размер/наличие OKNO. Соответствие мягким предпочтениям профиля не подтверждено.")
        style_ok, style_reasons = _lexical_match(extracted, checked_brief)
        reasons.extend(style_reasons)
        if style_ok:
            evidence.append("style_match: supported lexical garment/features only; no image or semantic model analysis")
        evidence.append("condition: " + (extracted.condition or "unknown"))
        evidence.append("price-and-size-coupled city: " + (observed_city or "unknown"))
        evidence.append("price-and-size-coupled delivery: " + (observed_delivery or "unknown"))
        if available_sizes:
            evidence.append("Inventory-backed sizes: " + ", ".join(available_sizes))
        if selected_price is not None:
            evidence.append(f"Ordinary size-coupled price: {selected_price:g} RUB; sizes: {', '.join(selected_sizes) or 'not in stock'}")
        if extracted.conditional_price_rub is not None:
            evidence.append(f"Conditional/loyalty RUB price: {extracted.conditional_price_rub:g}; never substituted for ordinary price")
        evidence.extend("Unverified: " + reason for reason in reasons)
        parsed = urlsplit(page.url)
        canonical = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))
        valid = not reasons
        price_note = extracted.price_note
        if selected_price is not None:
            size_note = f"Обычная цена за подтвержденный размер {', '.join(selected_sizes) or requested_size or 'unknown'}: {selected_price:g} ₽."
            price_note = " ".join(part for part in (size_note, price_note) if part)
        product = Product(
            id="live_" + hashlib.sha256(canonical.encode()).hexdigest()[:20],
            title=extracted.title, category=extracted.category or "tops",
            source_id=candidate.source_id, source_url=canonical,
            image_url=extracted.image_url, price_rub=selected_price if selected_price is not None else extracted.price_rub,
            price_note=price_note, sizes=list(selected_sizes),
            availability=selected_stock, verified_at=observed_at,
            verification="verified" if valid else "unverified", evidence=evidence,
            is_demo=False,
        )
        return VerificationResult(product=product, valid=valid, reasons=tuple(reasons))
