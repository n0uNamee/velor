"""Server-side OpenRouter structured styling transport, disabled by default.

Official contract supplied by the integrator, 2026-10-25:
https://openrouter.ai/docs/guides/features/structured-outputs
Every response is validated locally, irrespective of model JSON guarantees.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Any

import httpx

from .providers import OutfitProposal, StylistRequest
from .spending import BudgetGuard

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["outfits"],
    "properties": {"outfits": {"type": "array", "maxItems": 6, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["product_ids", "title"], "properties": {
            "product_ids": {"type": "array", "maxItems": 16, "uniqueItems": True, "items": {"type": "string"}},
            "title": {"type": "string", "maxLength": 160},
        },
    }}},
}


@dataclass(frozen=True)
class OpenRouterStylistSettings:
    api_key: str = field(default="", repr=False)
    model: str = "google/gemini-3.8-flash"
    paid_action_approved: bool = False
    max_calls: int = 0
    max_output_tokens: int = 1600
    timeout_seconds: float = 40.0


class OpenRouterStylistProvider:
    name = "openrouter"

    def __init__(self, settings: OpenRouterStylistSettings | None = None, *, budget_guard: BudgetGuard | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings or OpenRouterStylistSettings()
        self._budget = budget_guard
        self._transport = transport
        self._lock = asyncio.Lock()
        self._calls = 0
        self._cache: dict[str, list[OutfitProposal]] = {}
        self.last_cost_usd: Decimal | None = None

    async def propose(self, request: StylistRequest) -> list[OutfitProposal]:
        settings = self._settings
        if settings.paid_action_approved is not True or not settings.api_key.strip() or isinstance(settings.max_calls, bool) or not isinstance(settings.max_calls, int) or settings.max_calls <= 0 or self._budget is None:
            raise PermissionError("OpenRouter requires an approved action, configured server key and centralized budget guard.")
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{3,160}", settings.model) or isinstance(settings.max_output_tokens, bool) or not isinstance(settings.max_output_tokens, int) or not 1 <= settings.max_output_tokens <= 4096 or not 0 < settings.timeout_seconds <= 120:
            raise ValueError("Invalid OpenRouter configuration.")
        data = json.dumps({"brief": request.brief_data, "catalog": request.catalog_data}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(data.encode()) > 250_000:
            raise ValueError("Stylist input exceeds the bounded provider envelope.")
        body = {
            "model": settings.model, "stream": False, "max_tokens": settings.max_output_tokens,
            "messages": [{"role": "system", "content": request.instructions}, {"role": "user", "content": data}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "velor_outfits", "strict": True, "schema": _SCHEMA}},
            "provider": {"require_parameters": True},
        }
        key = sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        # Serializes duplicate inputs, caches successful proposals, and prevents
        # concurrent request-count races. Central guard controls app concurrency.
        async with self._lock:
            if key in self._cache:
                return list(self._cache[key])
            if self._calls >= settings.max_calls:
                raise PermissionError("Approved OpenRouter call count exhausted.")
            try:
                reservation = await self._budget.reserve(operation="stylist", request_key=key, model=settings.model)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise PermissionError("The central spending reservation was denied.") from None
            if reservation is None or not callable(getattr(reservation, "settle", None)):
                raise PermissionError("The central spending reservation was denied.")
            self._calls += 1
            cost: Decimal | None = None
            try:
                async with httpx.AsyncClient(transport=self._transport, timeout=settings.timeout_seconds,
                                            follow_redirects=False, trust_env=False) as client:
                    async with client.stream("POST", _ENDPOINT, headers={"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json"}, json=body) as response:
                        if response.status_code != 200:
                            raise ValueError("OpenRouter request failed.")
                        chunks, count = [], 0
                        async for chunk in response.aiter_bytes():
                            count += len(chunk)
                            if count > 128_000:
                                raise ValueError("OpenRouter response exceeds limit.")
                            chunks.append(chunk)
                payload = json.loads(b"".join(chunks))
                cost = _usage_cost(payload)
                content = payload["choices"][0]["message"]["content"]
                if not isinstance(content, str) or len(content) > 32_000:
                    raise ValueError("Invalid OpenRouter content.")
                proposals = _parse_proposals(json.loads(content))
            except asyncio.CancelledError:
                raise
            except Exception:
                raise ValueError("OpenRouter styling failed or returned invalid structured output.") from None
            finally:
                self.last_cost_usd = cost
                try:
                    await asyncio.shield(reservation.settle(cost))
                except Exception:
                    raise ValueError("Central usage settlement failed; keep the cost reservation.") from None
            self._cache[key] = proposals
            return list(proposals)


def _usage_cost(payload: Any) -> Decimal | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("usage"), dict):
        return None
    raw = payload["usage"].get("cost")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        cost = Decimal(str(raw))
        return cost if cost.is_finite() and cost >= 0 else None
    except InvalidOperation:
        return None


def _parse_proposals(payload: Any) -> list[OutfitProposal]:
    if not isinstance(payload, dict) or set(payload) != {"outfits"} or not isinstance(payload["outfits"], list) or len(payload["outfits"]) > 6:
        raise ValueError("Invalid structured response.")
    result = []
    for row in payload["outfits"]:
        if not isinstance(row, dict) or set(row) != {"product_ids", "title"}:
            raise ValueError("Invalid structured outfit.")
        ids, title = row["product_ids"], row["title"]
        if not isinstance(ids, list) or len(ids) > 16 or any(not isinstance(pid, str) or not pid or len(pid) > 200 for pid in ids) or len(set(ids)) != len(ids):
            raise ValueError("Invalid structured product IDs.")
        if not isinstance(title, str) or len(title) > 160:
            raise ValueError("Invalid structured title.")
        result.append(OutfitProposal(tuple(ids), title))
    return result
