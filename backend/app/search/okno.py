"""Narrow OKNO public SSR adapter; no fetching or invented product links."""
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from .extraction import ExtractedProduct, ProductCandidate, _clean, _number, _url, infer_category
from .sources import host_matches


class _Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.data, self.anchor = None, None
        self.links, self.parts = [], []
        self.script, self.length = False, 0
        self.feed(html[:2_000_000])
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("id") == "__NEXT_DATA__":
            self.script, self.parts, self.length = True, [], 0
        elif tag == "a" and attrs.get("href"):
            self.anchor = (attrs["href"], [attrs.get("title") or "", attrs.get("aria-label") or ""])
        elif tag == "img" and self.anchor:
            self.anchor[1].append(attrs.get("alt") or "")

    def handle_data(self, text):
        if self.script:
            self.length += len(text)
            if self.length <= 1_000_000:
                self.parts.append(text)
        elif self.anchor:
            self.anchor[1].append(text)

    def handle_endtag(self, tag):
        if tag == "script" and self.script:
            if self.length <= 1_000_000:
                try:
                    self.data = json.loads("".join(self.parts))
                except (ValueError, RecursionError):
                    pass
            self.script = False
        elif tag == "a" and self.anchor:
            if len(self.links) < 10_000:
                self.links.append((self.anchor[0], _clean(" ".join(self.anchor[1])) or ""))
            self.anchor = None


def _item_url(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme in {"https", "http"} and host_matches(url, ("okno.store",))
                and not parts.username and not parts.password
                and parts.port in {None, 80 if parts.scheme == "http" else 443}
                and bool(re.fullmatch(r"/item/[^/]+/?", parts.path)))
    except ValueError:
        return False


def extract_okno_candidates(html: str, url: str, query: str, limit: int = 4) -> list[ProductCandidate]:
    """Filter observed /item/ anchors locally; no remote search endpoint."""
    if not host_matches(url, ("okno.store",)) or limit <= 0:
        return []
    terms = re.findall(r"[^\W_]+", query.casefold().replace("ё", "е"))
    found = {}
    for href, title in _Document(html).links:
        actual = _url(href, url)
        if not actual or not _item_url(actual):
            continue
        words = re.findall(r"[^\W_]+", title.casefold().replace("ё", "е"))
        if terms and not all(any(word.startswith(term) for word in words) for term in terms):
            continue
        found.setdefault(actual, ProductCandidate(actual, "okno", title, ("OKNO actual public catalog /item/ hyperlink; local lexical query filter",)))
        if len(found) >= min(limit, 100):
            break
    return list(found.values())


def extract_okno_product(html: str, url: str) -> ExtractedProduct | None:
    if not _item_url(url):
        return None
    parsed = urlsplit(url)
    if any(not key.lower().startswith("utm_") and key.lower() not in {"gclid", "fbclid", "yclid", "_openstat"}
           for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        return None
    data = _Document(html).data
    props = data.get("props") if isinstance(data, dict) else None
    page = props.get("pageProps") if isinstance(props, dict) else None
    item = page.get("item") if isinstance(page, dict) else None
    if not isinstance(item, dict):
        return None
    code = item.get("code")
    if not isinstance(code, str) or not code or unquote(parsed.path).rstrip("/") != "/item/" + code:
        return None
    title = _clean(item.get("title"))
    if not title:
        return None
    currency_proof = _clean(item.get("formatRubPrice")) or ""
    price = _number(item.get("price"))
    if not re.search(r"(?:\bRUB\b|\bRUR\b|руб|₽)", currency_proof, re.I):
        price = None
    availability = "in_stock" if item.get("available") is True and item.get("isHidden") is False else "out_of_stock" if item.get("available") is False else "unknown"
    variants = item.get("variants")
    variants = variants if isinstance(variants, list) else []
    sizes = tuple(dict.fromkeys(size for variant in variants if isinstance(variant, dict) and (size := _clean(variant.get("title"), 40))))
    coupled = len(variants) == 1 and len(sizes) == 1 and availability == "in_stock"
    canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    evidence = [f"OKNO fetched item URL: {canonical}", f"title: {title}; __NEXT_DATA__.props.pageProps.item.title", f"item code matches fetched /item/ path: {code}", f"availability: {availability}; explicit item.available and item.isHidden"]
    if price is not None:
        evidence.append(f"ordinary price: {price:g} RUB; item.price and item.formatRubPrice={currency_proof}")
    evidence.append(f"size-specific stock: {sizes[0]}; exactly one item.variants entry and item.available=true, item.isHidden=false" if coupled else "size-specific stock unknown; multiple variant options are not per-size inventory")
    condition_value = item.get("itemCondition") or item.get("condition")
    condition = {"new": "new", "used": "used", "newcondition": "new", "usedcondition": "used"}.get(str(condition_value or "").rsplit("/", 1)[-1].lower(), "unknown")
    evidence.append(f"condition: {condition}; " + ("explicit item field" if condition != "unknown" else "not stated in observed item payload"))
    for characteristic in page.get("characteristics", []) if isinstance(page.get("characteristics"), list) else []:
        if not isinstance(characteristic, dict) or "достав" not in str(characteristic.get("title", "")).lower():
            continue
        text = characteristic.get("text")
        content = " ".join(value for chunk in (text if isinstance(text, list) else [text]) if (value := _clean(chunk, 300)))[:1000]
        if content:
            evidence.append(f"unverified general delivery context: {content}")
    return ExtractedProduct(
        url=canonical, title=title, price_rub=price, currency="RUB" if price is not None else None,
        sizes=sizes, available_sizes=sizes if coupled else (),
        size_availability={size: "in_stock" if coupled else "unknown" for size in sizes},
        size_prices_rub={sizes[0]: price} if coupled and price is not None else {},
        availability=availability, image_url=_url(item.get("previewUrl"), url), category=infer_category(title),
        condition=condition, city=None, delivery=None,
        price_note="OKNO public item payload; condition and city-specific delivery require independent evidence.", evidence=tuple(evidence),
    )
