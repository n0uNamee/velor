"""Bounded, conservative extraction from fetched HTML and schema.org JSON-LD.

This module never fetches, invents product paths, or equates size selectors with
stock. Unknown facts remain None/unknown and must not pass verification.
"""
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
import json
import math
import re
from typing import Any, Iterator
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit

from .sources import SourceDefinition, host_matches

MAX_HTML_CHARS = 2_000_000
MAX_JSON_CHARS = 1_000_000


@dataclass(frozen=True)
class ProductCandidate:
    url: str
    source_id: str
    hinted_title: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractedProduct:
    url: str
    title: str | None = None
    description: str | None = None
    price_rub: float | None = None
    conditional_price_rub: float | None = None
    price_note: str | None = None
    currency: str | None = None
    sizes: tuple[str, ...] = ()
    available_sizes: tuple[str, ...] = ()
    size_availability: dict[str, str] = field(default_factory=dict)
    size_prices_rub: dict[str, float] = field(default_factory=dict)
    size_cities: dict[str, str] = field(default_factory=dict)
    size_deliveries: dict[str, str] = field(default_factory=dict)
    availability: str = "unknown"
    image_url: str | None = None
    category: str | None = None
    condition: str = "unknown"
    city: str | None = None
    delivery: str | None = None
    evidence: tuple[str, ...] = ()


def _clean(value: Any, limit: int = 500) -> str | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    text = re.sub(r"\s+", " ", unescape(str(value))).strip()
    return text[:limit] if text else None


def _url(value: Any, base: str) -> str | None:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        return None
    try:
        parts = urlsplit(urljoin(base, unescape(value.strip())))
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        # Encoding an observed Unicode link does not invent a product URL and
        # ensures it can be sent by the transport's strict ASCII HTTP request.
        path = quote(parts.path or "/", safe="/%:@-._~!$&'()*+,;=")
        query = quote(parts.query, safe="/%?:@-._~!$&'()*+,;=")
        return urlunsplit((parts.scheme, parts.netloc, path, query, ""))
    except ValueError:
        return None


class _Document(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.links: list[tuple[str, str]] = []
        self.jsonld: list[Any] = []
        self._script = False
        self._chunks: list[str] = []
        self._chunk_size = 0
        self._anchor: tuple[str, list[str]] | None = None
        self._h1 = False
        self.h1: list[str] = []
        self._title = False
        self.title: list[str] = []
        raw = html.lstrip()
        if len(raw) <= MAX_JSON_CHARS and raw.startswith(("{", "[")):
            try:
                self.jsonld.append(json.loads(raw))
            except (ValueError, RecursionError):
                pass
        self.feed(html[:MAX_HTML_CHARS])
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): v or "" for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag == "script" and a.get("type", "").split(";")[0].strip().lower() == "application/ld+json":
            self._script, self._chunks, self._chunk_size = True, [], 0
        elif tag == "a" and a.get("href"):
            self._anchor = (a["href"], [a.get("title", ""), a.get("aria-label", "")])
        elif tag == "img" and self._anchor:
            self._anchor[1].append(a.get("alt", ""))
        elif tag == "h1":
            self._h1 = True
        elif tag == "title":
            self._title = True

    def handle_data(self, data: str) -> None:
        if self._script:
            self._chunk_size += len(data)
            if self._chunk_size <= MAX_JSON_CHARS:
                self._chunks.append(data)
        elif self._anchor:
            self._anchor[1].append(data)
        if self._h1:
            self.h1.append(data)
        if self._title:
            self.title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script:
            if self._chunk_size <= MAX_JSON_CHARS:
                try:
                    self.jsonld.append(json.loads("".join(self._chunks)))
                except (ValueError, RecursionError):
                    pass
            self._script, self._chunks = False, []
        elif tag == "a" and self._anchor:
            if len(self.links) < 10_000:
                self.links.append((self._anchor[0], _clean(" ".join(self._anchor[1])) or ""))
            self._anchor = None
        elif tag == "h1":
            self._h1 = False
        elif tag == "title":
            self._title = False


def _walk(value: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    if depth > 20:
        return
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child, depth + 1)
    elif isinstance(value, list):
        for child in value[:1000]:
            yield from _walk(child, depth + 1)


def _type(node: dict[str, Any], name: str) -> bool:
    types = node.get("@type", [])
    return any(str(t).rsplit("/", 1)[-1] == name for t in (types if isinstance(types, list) else [types]))


def _is_product(node: dict[str, Any]) -> bool:
    return _type(node, "Product") or _type(node, "IndividualProduct")


def _card_products(value: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Product variants belong to their card, not separate listing cards."""
    if depth > 20:
        return
    if isinstance(value, dict):
        if _is_product(value):
            yield value
            return
        for child in value.values():
            yield from _card_products(child, depth + 1)
    elif isinstance(value, list):
        for child in value[:1000]:
            yield from _card_products(child, depth + 1)


def detect_block_page(html: str) -> str | None:
    """Recognize access challenges; never attempt to solve or route around them.

    A normal store may include a CAPTCHA library for checkout, so the presence
    of that library alone is not treated as an access challenge.
    """
    document = _Document(html)
    heading = " ".join(document.title + document.h1).lower()
    if re.search(r"captcha|капч|access denied|доступ (?:ограничен|запрещ[её]н)|доступ к (?:сайту|странице) ограничен|just a moment|checking your browser|проверка браузера|подтвердите.{0,30}(?:человек|не робот)|are you (?:a human|a robot)", heading):
        return "Merchant access challenge/CAPTCHA or denied page; no bypass attempted."
    sample = html[:200_000].lower()
    if any(marker in sample for marker in ("cf-chl-container", "challenge-platform/h/b/orchestrate", 'id="captcha-container"', 'id="captcha-form"', "geo-blocking", "geoblocked")):
        return "Merchant security or geographical access challenge; no bypass attempted."
    if len(html) < 50_000 and re.search(r"(?:пожалуйста.{0,40})?(?:подтвердите|докажите).{0,50}(?:вы.{0,10}человек|не робот)|verify (?:that )?you are (?:human|not a robot)|request (?:was )?blocked|доступ из вашего региона", sample, re.S):
        return "Merchant access or geographical restriction page; no bypass attempted."
    return None


def extract_candidates(html: str, page_url: str, source: SourceDefinition, limit: int = 12) -> list[ProductCandidate]:
    """Extract real same-source links; card verification is always a later fetch."""
    if limit <= 0:
        return []
    document = _Document(html)
    found: dict[str, ProductCandidate] = {}

    def add(raw: Any, title: Any, proof: str, strong: bool = False) -> None:
        url = _url(raw, page_url)
        if not url or not host_matches(url, source.hosts):
            return
        if urlsplit(url).path.rstrip("/") == urlsplit(page_url).path.rstrip("/") and not strong:
            return
        if strong or source.accepts_product_link(url):
            candidate_title = _clean(title) or ""
            previous = found.get(url)
            if previous is None:
                found[url] = ProductCandidate(url, source.id, candidate_title, (proof,))
            elif not previous.hinted_title and candidate_title:
                found[url] = ProductCandidate(url, source.id, candidate_title, tuple(dict.fromkeys((*previous.evidence, proof))))

    for root in document.jsonld:
        for node in _walk(root):
            if _is_product(node):
                add(node.get("url") or node.get("@id"), node.get("name"), "search JSON-LD Product URL", True)
                if not node.get("url") and not node.get("@id"):
                    # A product page may itself be the search provider's returned card.
                    if source.accepts_product_link(page_url):
                        add(page_url, node.get("name"), "fetched JSON-LD Product page", True)
            elif _type(node, "ListItem"):
                item = node.get("item")
                raw = item.get("url") or item.get("@id") if isinstance(item, dict) else item
                add(raw or node.get("url"), (item.get("name") if isinstance(item, dict) else None) or node.get("name"), "search JSON-LD ListItem URL")
    for raw, title in document.links:
        add(raw, title, "fetched search-page hyperlink")
    return list(found.values())[:min(limit, 100)]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        cleaned = re.sub(r"[\s\u00a0\u202f]", "", str(value)).replace(",", ".")
        result = float(cleaned)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value] if value is not None else []


def _availability(value: Any) -> str:
    token = str(value or "").rsplit("/", 1)[-1].lower()
    if token in {"instock", "limitedavailability"}:
        return "in_stock"
    if token in {"outofstock", "soldout", "discontinued"}:
        return "out_of_stock"
    return "unknown"


def _identity(url: str) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """Keep meaningful query selectors; drop only explicit tracking parameters."""
    parts = urlsplit(url)
    tracking = {"gclid", "fbclid", "yclid", "_openstat"}
    query = tuple((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in tracking and not key.lower().startswith("utm_"))
    return (parts.netloc.lower().rstrip("."), parts.path.rstrip("/") or "/", query)


def _conditional_offer(offer: dict[str, Any]) -> bool:
    label = " ".join(str(offer.get(key, "")) for key in ("name", "description", "category", "eligibleCustomerType"))
    return any(key in offer for key in ("eligibleCustomerType", "membershipPointsEarned", "validForMemberTier")) or bool(re.search(r"карт[аеуы]|подписк|клуб|балл|coupon|loyal|member|subscription", label, re.I))


def _stocked_ordinary_price(offers: list[dict[str, Any]]) -> float | None:
    """Only a price and InStock on the same eligible Offer can be coupled."""
    prices: list[float] = []
    for offer in offers:
        if _availability(offer.get("availability")) != "in_stock" or _conditional_offer(offer):
            continue
        currency = str(offer.get("priceCurrency", "")).upper()
        value = _number(offer.get("price"))
        if value is not None and currency in {"RUB", "RUR"}:
            prices.append(value)
        for specification in _list(offer.get("priceSpecification")):
            if not isinstance(specification, dict) or _conditional_offer(specification):
                continue
            spec_type = str(specification.get("priceType", "")).rsplit("/", 1)[-1].lower()
            if spec_type in {"listprice", "msrp", "strikethroughprice"}:
                continue
            spec_currency = str(specification.get("priceCurrency") or currency).upper()
            spec_price = _number(specification.get("price"))
            if spec_price is not None and spec_currency in {"RUB", "RUR"}:
                prices.append(spec_price)
    return min(prices) if prices else None


def _offer_locations(offer: dict[str, Any]) -> tuple[str | None, str | None]:
    cities: list[str] = []
    deliveries: list[str] = []
    for area in _list(offer.get("availableAtOrFrom") or offer.get("areaServed")):
        if not isinstance(area, dict):
            continue
        address = area.get("address")
        city = _clean(address.get("addressLocality")) if isinstance(address, dict) else _clean(area.get("name"))
        if city:
            cities.append(city)
    for shipping in _list(offer.get("shippingDetails")):
        if not isinstance(shipping, dict) or shipping.get("doesNotShip") is True:
            continue
        for destination in _list(shipping.get("shippingDestination")):
            if isinstance(destination, dict):
                delivery = _clean(destination.get("addressLocality") or destination.get("addressRegion") or destination.get("addressCountry"))
                if delivery:
                    deliveries.append(delivery)
    return ("; ".join(dict.fromkeys(cities)) or None, "; ".join(dict.fromkeys(deliveries)) or None)


def _stocked_offer_details(offers: list[dict[str, Any]]) -> tuple[float | None, str | None, str | None]:
    """Locations belong to the very same lowest priced, in-stock Offer."""
    priced = [(price, offer) for offer in offers if (price := _stocked_ordinary_price([offer])) is not None]
    if not priced:
        return None, None, None
    price = min(value for value, _ in priced)
    locations = [_offer_locations(offer) for value, offer in priced if value == price]
    cities, deliveries = {pair[0] for pair in locations}, {pair[1] for pair in locations}
    return price, next(iter(cities)) if len(cities) == 1 else None, next(iter(deliveries)) if len(deliveries) == 1 else None


def _property_token(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("value")
    if isinstance(value, list):
        return ";".join(_property_token(item) for item in value)
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _condition_token(value: Any) -> str:
    return str(value or "").rsplit("/", 1)[-1].lower()


def _variant_compatible(parent: dict[str, Any], variant: dict[str, Any], page_url: str, parent_condition: str) -> bool:
    identity = _url(variant.get("url") or variant.get("@id"), page_url)
    if identity and _identity(identity) != _identity(page_url):
        return False
    # A variant's explicit conflicting facts cannot inherit the root card's
    # style/title/condition. Missing variant facts may inherit root assertions.
    for key in ("name", "color", "material", "pattern", "brand"):
        if variant.get(key) is not None and _property_token(variant[key]) != _property_token(parent.get(key)):
            return False
    conditions = [_condition_token(variant.get("itemCondition"))]
    conditions.extend(_condition_token(offer.get("itemCondition")) for offer in _list(variant.get("offers")) if isinstance(offer, dict))
    return not any(token and token != parent_condition for token in conditions)


def _sizes(value: Any) -> tuple[str, ...]:
    sizes = []
    for item in _list(value):
        text = _clean(item.get("name") or item.get("value")) if isinstance(item, dict) else _clean(item, 40)
        if text and text not in sizes:
            sizes.append(text)
    return tuple(sizes[:100])


def infer_category(text: str | None) -> str | None:
    text = (text or "").lower()
    categories = (
        ("headwear", r"шапк|кепк|панам|шляп|балаклав|beanie|\bcap\b|\bhat\b"),
        ("shoes", r"кроссов|кед[ыа]?\b|ботин|сапог|туфл|лофер|сандал|sneaker|\bshoe|\bboot|loafer"),
        ("bottoms", r"брюк|джинс|шорт|юбк|леггин|джоггер|trouser|\bpants\b|jeans|shorts|skirt"),
        ("accessories", r"сумк|рюкзак|ремень|шарф|перчат|очк[иов]|кольц|украшен|\bbag\b|backpack|\bbelt\b|scarf|jewel"),
        ("tops", r"футбол|рубаш|куртк|пальто|худи|толстов|свит|джемпер|кардиган|жакет|блуз|жилет|плать|топ\b|t-shirt|shirt|jacket|coat|hoodie|sweater|dress"),
    )
    return next((category for category, pattern in categories if re.search(pattern, text)), None)


def extract_product(html: str, page_url: str) -> ExtractedProduct | None:
    """Return only product-bearing pages; OpenGraph can supplement schema data.

    A listing with several Products is not sufficient evidence of one card. A
    product URL in JSON-LD must identify the fetched path and semantic query.
    """
    document = _Document(html)
    products = [node for root in document.jsonld for node in _card_products(root)]
    page_identity = _identity(page_url)
    selected = None
    for node in products:
        identity = _url(node.get("url") or node.get("@id"), page_url)
        if identity and _identity(identity) == page_identity:
            selected = node
            break
    if selected is None and len(products) == 1:
        # Reject a single featured card when its URL identifies another page.
        node = products[0]
        identity = _url(node.get("url") or node.get("@id"), page_url)
        if not identity or _identity(identity) == page_identity:
            selected = node
    og_product = document.meta.get("og:type", "").lower() in {"product", "og:product", "product.item"}
    if products and selected is None:
        return None  # A contradictory Product identity cannot be healed by OG.
    if selected is None and not og_product:
        return None
    node = selected or {}
    evidence: list[str] = ["fetched product page; JSON-LD Product" if selected else "fetched product page; OpenGraph product"]
    title = _clean(node.get("name")) or _clean(document.meta.get("og:title")) or _clean(" ".join(document.h1))
    if title:
        evidence.append(f"title: {title}")
    offers = [offer for offer in _list(node.get("offers")) if isinstance(offer, dict)]
    condition_tokens = {_condition_token(value) for value in [node.get("itemCondition"), *(offer.get("itemCondition") for offer in offers)] if value}
    condition_token = next(iter(condition_tokens)) if len(condition_tokens) == 1 else ""
    regular: list[float] = []
    conditional: list[float] = []
    currency: str | None = None
    availabilities: list[str] = []
    notes: list[str] = []
    city = delivery = None
    for offer in offers:
        offer_currency = (_clean(offer.get("priceCurrency"), 8) or "").upper()
        currency = offer_currency or currency
        price = _number(offer.get("price"))
        restricted = _conditional_offer(offer)
        if price is not None and offer_currency in {"RUB", "RUR"}:
            (conditional if restricted else regular).append(price)
            evidence.append(f"{'conditional' if restricted else 'ordinary'} price: {price:g} {currency}; JSON-LD Offer")
        for spec in _list(offer.get("priceSpecification")):
            if not isinstance(spec, dict):
                continue
            spec_currency = str(spec.get("priceCurrency") or offer_currency or "").upper()
            spec_price = _number(spec.get("price"))
            spec_type = str(spec.get("priceType", "")).rsplit("/", 1)[-1].lower()
            spec_label = " ".join(str(spec.get(key, "")) for key in ("name", "description"))
            spec_conditional = restricted or any(key in spec for key in ("validForMemberTier", "membershipPointsEarned")) or bool(re.search(r"карт[аеуы]|клуб|coupon|loyal|member|subscription", spec_label, re.I))
            # List/MSRP/strikethrough prices are not current transaction prices.
            if spec_price is not None and spec_currency in {"RUB", "RUR"} and spec_type not in {"listprice", "msrp", "strikethroughprice"}:
                (conditional if spec_conditional else regular).append(spec_price)
                evidence.append(f"{'conditional' if spec_conditional else 'ordinary'} price specification: {spec_price:g} {spec_currency}")
        availability = _availability(offer.get("availability"))
        if availability != "unknown":
            availabilities.append(availability)
            evidence.append(f"availability: {offer.get('availability')}; JSON-LD Offer")
    _, city, delivery = _stocked_offer_details(offers)
    if not regular and not conditional:
        amount = _number(document.meta.get("product:price:amount") or document.meta.get("og:price:amount"))
        meta_currency = (document.meta.get("product:price:currency") or document.meta.get("og:price:currency") or "").upper()
        if amount is not None and meta_currency in {"RUB", "RUR"}:
            regular.append(amount)
            currency = meta_currency
            evidence.append(f"ordinary price: {amount:g} {meta_currency}; product price metadata")
    if not availabilities:
        availability = _availability(document.meta.get("product:availability"))
        if availability != "unknown":
            availabilities.append(availability)
            evidence.append(f"availability: {document.meta['product:availability']}; product metadata")
    # Conflicting stock evidence and preorder/backorder remain unknown.
    availability = availabilities[0] if availabilities and len(set(availabilities)) == 1 else "unknown"
    sizes = list(_sizes(node.get("size")))
    available_sizes: list[str] = []
    # A single explicit Product.size couples that variant to its Offer. A list
    # of size options on a generic Product does not prove inventory per size.
    size_availability = {size: availability if len(sizes) == 1 else "unknown" for size in sizes}
    size_prices_rub: dict[str, float] = {}
    size_cities: dict[str, str] = {}
    size_deliveries: dict[str, str] = {}
    if availability == "in_stock" and len(sizes) == 1:
        available_sizes.extend(sizes)
        stocked_price, stocked_city, stocked_delivery = _stocked_offer_details(offers)
        if stocked_price is not None:
            size_prices_rub[sizes[0]] = stocked_price
            if stocked_city:
                size_cities[sizes[0]] = stocked_city
            if stocked_delivery:
                size_deliveries[sizes[0]] = stocked_delivery
            evidence.append(f"size-specific ordinary price: {sizes[0]} = {stocked_price:g} RUB; same in-stock Offer")
    variants = _list(node.get("hasVariant"))
    parent = node.get("isVariantOf")
    if isinstance(parent, dict):
        variants.extend(_list(parent.get("hasVariant")))
    variant_seen: set[str] = set()
    conflicting_size_prices: set[str] = set()
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_sizes = _sizes(variant.get("size"))
        sizes.extend(size for size in variant_sizes if size not in sizes)
        if not _variant_compatible(node, variant, page_url, condition_token):
            notes.append("Variant stock/price ignored: explicit variant identity, style, or condition conflicts with the fetched root Product.")
            continue
        states = [_availability(offer.get("availability")) for offer in _list(variant.get("offers")) if isinstance(offer, dict)]
        variant_state = states[0] if states and len(set(states)) == 1 and len(variant_sizes) == 1 else "unknown"
        for size in variant_sizes:
            previous = size_availability.get(size)
            # Generic size options carry no stock evidence and can be refined
            # by an explicit variant. Conflicting variants remain unknown.
            size_availability[size] = variant_state if previous is None or previous == variant_state or (previous == "unknown" and size not in variant_seen) else "unknown"
            variant_seen.add(size)
        if variant_state == "in_stock":
            available_sizes.extend(size for size in variant_sizes if size not in available_sizes)
            evidence.append(f"size-specific stock: {', '.join(variant_sizes)}; JSON-LD variant offers")
            variant_offers = [offer for offer in _list(variant.get("offers")) if isinstance(offer, dict)]
            variant_price, variant_city, variant_delivery = _stocked_offer_details(variant_offers)
            if variant_price is not None:
                for size in variant_sizes:
                    existing_price = size_prices_rub.get(size)
                    if size in conflicting_size_prices:
                        continue
                    if existing_price is None or existing_price == variant_price:
                        size_prices_rub[size] = variant_price
                        # Replace the complete location pair as a unit. A
                        # pickup city on one variant and shipping destination
                        # on another variant must never be stitched together.
                        size_cities.pop(size, None)
                        size_deliveries.pop(size, None)
                        if variant_city:
                            size_cities[size] = variant_city
                        if variant_delivery:
                            size_deliveries[size] = variant_delivery
                    else:
                        size_prices_rub.pop(size, None)
                        conflicting_size_prices.add(size)
                        notes.append(f"Conflicting ordinary prices for size {size}; size-specific price unknown.")
                evidence.append(f"size-specific ordinary price: {', '.join(variant_sizes)} = {variant_price:g} RUB; same in-stock variant Offer")
    # Explicit microdata size is an option only. No stock is inferred from it.
    if sizes:
        evidence.append(f"listed sizes: {', '.join(sizes)}; JSON-LD size")
    if not available_sizes:
        notes.append("Size-specific stock unknown; size options alone are not availability.")
    if conditional:
        notes.append(f"Conditional/loyalty price: {min(conditional):g} RUB; eligibility not confirmed.")
    if regular and len(set(regular)) > 1:
        notes.append("Several ordinary offers; displayed value is the lowest observed offer.")
    size_prices_rub = {size: price for size, price in size_prices_rub.items() if size_availability.get(size) == "in_stock"}
    size_cities = {size: city for size, city in size_cities.items() if size in size_prices_rub}
    size_deliveries = {size: destination for size, destination in size_deliveries.items() if size in size_prices_rub}
    if not regular and size_prices_rub:
        regular.extend(size_prices_rub.values())
        currency = "RUB"
        evidence.append("ordinary RUB price derived only from explicit in-stock size variant offers")
    if availability == "unknown" and not availabilities and any(state == "in_stock" for state in size_availability.values()):
        availability = "in_stock"
        evidence.append("availability: at least one explicit in-stock size variant Offer")
    condition = {"newcondition": "new", "usedcondition": "used", "refurbishedcondition": "refurbished", "damagedcondition": "damaged"}.get(condition_token, "unknown")
    evidence.append(f"condition: {condition}; " + ("JSON-LD itemCondition" if condition != "unknown" else "not stated"))
    if city:
        evidence.append(f"city: {city}; JSON-LD availableAtOrFrom/areaServed")
    if delivery:
        evidence.append(f"delivery destination: {delivery}; JSON-LD shippingDetails; city eligibility not confirmed")
    image = node.get("image")
    if isinstance(image, list):
        image = next(iter(image), None)
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    image_url = _url(image or document.meta.get("og:image"), page_url)
    category_text = _clean(node.get("category"))
    category = infer_category(" ".join(value for value in (category_text, title) if value))
    return ExtractedProduct(
        url=page_url, title=title, description=_clean(node.get("description") or document.meta.get("og:description") or document.meta.get("description"), 2000), price_rub=min(regular) if regular else None,
        conditional_price_rub=min(conditional) if conditional else None,
        price_note=" ".join(notes) or None, currency=currency,
        sizes=tuple(dict.fromkeys(sizes)), available_sizes=tuple(size for size in dict.fromkeys(available_sizes) if size_availability.get(size) == "in_stock"), size_availability=size_availability, size_prices_rub=size_prices_rub, size_cities=size_cities, size_deliveries=size_deliveries,
        availability=availability, image_url=image_url, category=category,
        condition=condition, city=city, delivery=delivery, evidence=tuple(evidence),
    )
