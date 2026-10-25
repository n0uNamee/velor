"""Offline fictional fixtures. Their URLs are reserved and never live claims."""
from __future__ import annotations

from urllib.parse import quote

from app.models import Product, StyleBrief

from .extraction import ProductCandidate

_ITEMS = (
    ("headwear", "Чёрная шапка бини", 1190, "beanie"),
    ("tops", "Свободная футболка графит", 1790, "shirt"),
    ("bottoms", "Прямые чёрные брюки", 4290, "pants"),
    ("shoes", "Минималистичные кеды", 4990, "shoe"),
    ("accessories", "Компактная сумка через плечо", 2590, "bag"),
    ("tops", "Объёмный чёрный худи", 3990, "hoodie"),
    ("bottoms", "Широкие джинсы графит", 4590, "pants"),
    ("accessories", "Матовый ремень", 1490, "belt"),
    ("tops", "Рубашка свободного кроя", 3290, "shirt"),
    ("shoes", "Ботинки на массивной подошве", 6990, "shoe"),
    ("headwear", "Лаконичная кепка", 1590, "cap"),
    ("tops", "Лёгкая куртка", 5990, "jacket"),
)


def _image(kind: str) -> str:
    shapes = {
        "pants": '<path d="M76 47h88l-8 146h-31l-5-94-5 94H84z"/>',
        "shoe": '<path d="M55 124l40-24 27 27 55 10 9 33H53z"/><path fill="#777" d="M53 167h133v10H53z"/>',
        "beanie": '<path d="M70 124q0-74 50-74t50 74v27H70z"/><rect x="63" y="130" width="114" height="29" rx="9" fill="#555"/>',
        "cap": '<path d="M68 122q5-65 58-57t43 65z"/><path d="M80 124h111q-4 34-92 18z"/>',
        "bag": '<path fill="none" stroke="#555" stroke-width="10" d="M89 97q32-109 65-5"/><rect x="61" y="96" width="119" height="86" rx="18"/>',
        "belt": '<rect x="40" y="105" width="160" height="28" rx="6"/><rect x="143" y="101" width="40" height="36" rx="4" fill="none" stroke="#888" stroke-width="7"/>',
    }
    shape = shapes.get(kind, '<path d="M87 52l-44 30 22 43 23-13v82h65v-82l23 13 22-43-44-30q-33 20-67 0z"/>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" viewBox="0 0 240 240"><rect width="240" height="240" fill="#f2f0eb"/><g fill="#29292b">{shape}</g><text x="120" y="224" font-size="10" font-family="sans-serif" fill="#777" text-anchor="middle">VÉLOR · DEMO</text></svg>'
    return "data:image/svg+xml;charset=utf-8," + quote(svg)


def demo_products(source_id: str, source_index: int, brief: StyleBrief) -> list[Product]:
    products = []
    for offset in (0, 5):
        index = (source_index + offset) % len(_ITEMS)
        category, title, price, kind = _ITEMS[index]
        if category not in brief.categories:
            continue
        products.append(Product(
            id=f"demo-{source_id}-{index}", title=f"Демо · {title}", category=category,
            source_id=source_id,
            source_url=f"https://demo.velor.invalid/catalog/{source_id}/{index}",
            image_url=_image(kind), price_rub=price,
            price_note="Демонстрационная цена; магазин, остатки и доставка не проверялись.",
            sizes=[], availability="unknown", verification="demo", verified_at=None,
            is_demo=True, evidence=[
                "mode=demo; fictional offline fixture; no network request performed",
                "URL uses reserved .invalid domain and is not a real retailer product URL",
                "price/condition/sizes/city/delivery/style_match are demonstration data, not verified facts",
            ],
        ))
    return products


def demo_candidates(products: list[Product]) -> tuple[ProductCandidate, ...]:
    return tuple(ProductCandidate(url=p.source_url, source_id=p.source_id,
                                  hinted_title=p.title, evidence=("Explicit offline demo fixture",)) for p in products)
