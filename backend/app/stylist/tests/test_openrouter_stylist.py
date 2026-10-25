"""OpenRouter transport verification using in-process HTTP mocks only."""

import asyncio
from decimal import Decimal
import json

import httpx
import pytest

from app.stylist.openrouter_stylist import OpenRouterStylistProvider, OpenRouterStylistSettings
from app.stylist.providers import OutfitProposal, StylistRequest


class Reservation:
    def __init__(self):
        self.settlements = []

    async def settle(self, actual_cost_usd):
        self.settlements.append(actual_cost_usd)


class Guard:
    def __init__(self, error=None):
        self.reserves = []
        self.reservations = []
        self.error = error

    async def reserve(self, **kwargs):
        self.reserves.append(kwargs)
        if self.error:
            raise self.error
        reservation = Reservation()
        self.reservations.append(reservation)
        return reservation


def settings(**changes):
    values = dict(api_key="test-key-not-a-live-credential", model="test/model", paid_action_approved=True,
                  max_calls=3, max_output_tokens=400, timeout_seconds=1)
    values.update(changes)
    return OpenRouterStylistSettings(**values)


def request(marker="first"):
    return StylistRequest(
        brief_data={"request_text": marker, "item_slots": ["tops"], "budget_rub": 3000},
        catalog_data=({"id": "top-1", "title": "Catalog top", "category": "tops", "price_rub": 1000},),
    )


def response(content=None, cost="0.000123"):
    content = content if content is not None else {"outfits": [{"product_ids": ["top-1"], "title": "Look"}]}
    return {"choices": [{"message": {"content": json.dumps(content)}}], "usage": {"cost": cost}}


def transport(payload=None, status=200):
    calls = []

    async def handle(req):
        calls.append(req)
        return httpx.Response(status, json=payload if payload is not None else response())

    return httpx.MockTransport(handle), calls


@pytest.mark.parametrize(
    "changes,with_guard",
    [({"paid_action_approved": False}, True), ({"api_key": ""}, True),
     ({"max_calls": 0}, True), ({}, False)],
)
def test_missing_permission_key_or_central_guard_sends_no_request(changes, with_guard):
    mocked, calls = transport()
    guard = Guard() if with_guard else None
    provider = OpenRouterStylistProvider(settings(**changes), budget_guard=guard, transport=mocked)
    with pytest.raises(PermissionError):
        asyncio.run(provider.propose(request()))
    assert calls == []
    if guard:
        assert guard.reserves == []


def test_unconfigured_defaults_cannot_spend_and_settings_repr_hides_key():
    mocked, calls = transport()
    provider = OpenRouterStylistProvider(transport=mocked)
    with pytest.raises(PermissionError):
        asyncio.run(provider.propose(request()))
    assert calls == []
    assert "test-key-not-a-live-credential" not in repr(settings())


def test_structured_request_and_central_usage_settlement():
    mocked, calls = transport()
    guard = Guard()
    provider = OpenRouterStylistProvider(settings(), budget_guard=guard, transport=mocked)
    proposals = asyncio.run(provider.propose(request()))
    assert proposals == [OutfitProposal(("top-1",), "Look")]
    assert len(calls) == 1
    sent = calls[0]
    assert sent.method == "POST"
    assert str(sent.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert sent.headers["Authorization"] == "Bearer test-key-not-a-live-credential"
    body = json.loads(sent.content)
    assert body["model"] == "test/model"
    assert body["max_tokens"] == 400
    assert body["stream"] is False
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    schema = body["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["outfits"]["maxItems"] == 6
    assert body["provider"]["require_parameters"] is True
    assert body["messages"][0] == {"role": "system", "content": request().instructions}
    data = json.loads(body["messages"][1]["content"])
    assert data["catalog"][0]["id"] == "top-1"
    assert "test-key-not-a-live-credential" not in body["messages"][1]["content"]
    assert guard.reserves == [{"operation": "stylist", "request_key": guard.reserves[0]["request_key"], "model": "test/model"}]
    assert len(guard.reserves[0]["request_key"]) == 64
    assert guard.reservations[0].settlements == [Decimal("0.000123")]
    assert provider.last_cost_usd == Decimal("0.000123")


def test_guard_denial_happens_before_network():
    mocked, calls = transport()
    guard = Guard(PermissionError("Shared cap exhausted"))
    provider = OpenRouterStylistProvider(settings(), budget_guard=guard, transport=mocked)
    with pytest.raises(PermissionError):
        asyncio.run(provider.propose(request()))
    assert len(guard.reserves) == 1
    assert calls == []
    assert guard.reservations == []


@pytest.mark.parametrize("bad_cost", [None, True, "NaN", "Infinity", "-0.01", "not-a-number"])
def test_unknown_or_invalid_usage_keeps_cost_unknown_for_central_guard(bad_cost):
    mocked, calls = transport(response(cost=bad_cost))
    guard = Guard()
    provider = OpenRouterStylistProvider(settings(), budget_guard=guard, transport=mocked)
    assert asyncio.run(provider.propose(request()))
    assert len(calls) == 1
    assert guard.reservations[0].settlements == [None]
    assert provider.last_cost_usd is None


@pytest.mark.parametrize(
    "bad_content",
    [
        {"outfits": [], "extra": "secret-server-value"},
        {"outfits": [{"product_ids": ["top-1"], "title": "Look", "extra": "secret-server-value"}]},
        {"outfits": [{"product_ids": ["top-1", "top-1"], "title": "Look"}]},
        {"outfits": [{"product_ids": [""], "title": "Look"}]},
        {"outfits": [{"product_ids": ["top-1"], "title": 12}]},
        {"outfits": [{"product_ids": ["top-1"]}]},
        {"outfits": [{"product_ids": ["top-1"], "title": "Look"}] * 7},
        ["secret-server-value"],
    ],
)
def test_malformed_structured_output_is_rejected_locally_and_cost_settled(bad_content):
    mocked, calls = transport(response(content=bad_content))
    guard = Guard()
    provider = OpenRouterStylistProvider(settings(), budget_guard=guard, transport=mocked)
    with pytest.raises(ValueError) as error:
        asyncio.run(provider.propose(request()))
    assert "secret-server-value" not in str(error.value)
    assert len(calls) == 1
    assert guard.reservations[0].settlements == [Decimal("0.000123")]


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_http_failure_is_sanitized_consumes_call_and_is_not_retried(status):
    mocked, calls = transport({"error": "secret-server-value test-key-not-a-live-credential"}, status=status)
    guard = Guard()
    provider = OpenRouterStylistProvider(settings(max_calls=1), budget_guard=guard, transport=mocked)

    async def scenario():
        with pytest.raises(ValueError) as error:
            await provider.propose(request())
        assert "secret-server-value" not in str(error.value)
        assert "test-key-not-a-live-credential" not in str(error.value)
        with pytest.raises(PermissionError):
            await provider.propose(request())

    asyncio.run(scenario())
    assert len(calls) == 1
    assert len(guard.reserves) == 1
    assert guard.reservations[0].settlements == [None]


def test_concurrent_duplicates_share_one_request_and_cached_results_are_copied():
    mocked, calls = transport()
    guard = Guard()
    provider = OpenRouterStylistProvider(settings(max_calls=1), budget_guard=guard, transport=mocked)

    async def scenario():
        first, second = await asyncio.gather(provider.propose(request()), provider.propose(request()))
        assert first == second
        assert first is not second
        first.clear()
        third = await provider.propose(request())
        assert len(third) == 1
        with pytest.raises(PermissionError):
            await provider.propose(request("distinct input"))

    asyncio.run(scenario())
    assert len(calls) == 1
    assert len(guard.reserves) == 1
    assert len(guard.reservations[0].settlements) == 1


@pytest.mark.parametrize(
    "changes",
    [{"model": "test/model\nHeader: injection"}, {"max_output_tokens": 0}, {"max_output_tokens": 4097},
     {"timeout_seconds": 0}, {"timeout_seconds": 121}],
)
def test_invalid_configuration_fails_before_reservation_and_network(changes):
    mocked, calls = transport()
    guard = Guard()
    provider = OpenRouterStylistProvider(settings(**changes), budget_guard=guard, transport=mocked)
    with pytest.raises(ValueError):
        asyncio.run(provider.propose(request()))
    assert calls == []
    assert guard.reserves == []


def test_large_input_is_rejected_before_reservation_and_network():
    mocked, calls = transport()
    guard = Guard()
    provider = OpenRouterStylistProvider(settings(), budget_guard=guard, transport=mocked)
    with pytest.raises(ValueError):
        asyncio.run(provider.propose(request("x" * 250001)))
    assert calls == []
    assert guard.reserves == []


def test_oversized_response_is_bounded_and_unknown_cost_is_settled():
    calls = []

    async def handle(req):
        calls.append(req)
        return httpx.Response(200, content=b"x" * 128001)

    guard = Guard()
    provider = OpenRouterStylistProvider(settings(), budget_guard=guard, transport=httpx.MockTransport(handle))
    with pytest.raises(ValueError):
        asyncio.run(provider.propose(request()))
    assert len(calls) == 1
    assert guard.reservations[0].settlements == [None]


def test_network_failure_is_sanitized_and_unknown_charge_is_settled():
    calls = []

    async def handle(req):
        calls.append(req)
        raise httpx.ConnectError("secret-network-details", request=req)

    guard = Guard()
    provider = OpenRouterStylistProvider(settings(), budget_guard=guard, transport=httpx.MockTransport(handle))
    with pytest.raises(ValueError) as error:
        asyncio.run(provider.propose(request()))
    assert "secret-network-details" not in str(error.value)
    assert len(calls) == 1
    assert guard.reservations[0].settlements == [None]
