"""Boss1: conservative local adapter, retaining sources and unknowns.

No visual interpretation or live LLM call is implied by the local adapter.
"""
import re
from uuid import uuid4

from .models import CATEGORIES, Constraint, Profile, RequestInput, StyleBrief


def build_brief(profile: Profile, request: RequestInput, mode: str) -> StyleBrief:
    constraints, preferences, exclusions = [], [], []
    sizes = dict(request.sizes) if request.sizes else None
    if sizes and "clothing" in sizes:
        clothing = sizes.pop("clothing")
        sizes.setdefault("tops", clothing)
        sizes.setdefault("bottoms", clothing)
    for provenance, text in (("profile", profile.style_text), ("request", request.text)):
        for chunk in re.split(r"[\n;.!?]+", text):
            chunk = chunk.strip()
            if not chunk:
                continue
            is_exclusion = bool(re.search(r"\b(без|исключить|не хочу|не надо|никаких|no|without|avoid)\b", chunk, re.I))
            hard = is_exclusion or bool(re.search(r"\b(обязательно|только|нужно|must|required)\b", chunk, re.I))
            item = Constraint(text=chunk, strength="hard" if hard else "soft", provenance=provenance, confidence=1.0 if hard else 0.7)
            (exclusions if is_exclusion else constraints if hard else preferences).append(item)
    budget = request.budget_rub
    if budget is not None:
        constraints.append(Constraint(text=f"Общий бюджет: до {budget:g} ₽", strength="hard", provenance="request", confidence=1.0))
    if sizes:
        constraints.append(Constraint(text="Размеры: " + ", ".join(f"{k}: {v}" for k, v in sizes.items()), strength="hard", provenance="request", confidence=1.0))
    unknowns = []
    if budget is None:
        unknowns.append("Бюджет не задан отдельным полем; число из свободного текста не считается подтвержденным бюджетом.")
    if not request.sizes:
        unknowns.append("Размеры не указаны.")
    if not request.city:
        unknowns.append("Город и доставка не подтверждены.")
    if profile.images or request.images:
        unknowns.append("Изображения сохранены локально; содержимое не анализировалось внешним AI.")
    unknowns.append("Свободный текст сохранен с происхождением; точное понимание стиля требует подтверждения человеком.")
    return StyleBrief(
        id=uuid4().hex, profile_id=profile.id,
        original_profile_text=profile.style_text, original_request_text=request.text,
        images=list({image.id: image for image in profile.images + request.images}.values()),
        categories=list(CATEGORIES), search_queries=[x for x in [profile.style_text.strip(), request.text.strip()] if x],
        constraints=constraints, preferences=preferences, exclusions=exclusions,
        budget_rub=budget, sizes=sizes, city=request.city or None,
        unknowns=unknowns, mode=mode,
    )
