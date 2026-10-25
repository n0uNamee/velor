import asyncio
import base64
import json
import io

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.models import Profile, RequestInput
from app.brief import build_brief
from app.providers import OpenRouterProvider, ProviderUnavailable
from app.store import Store


def run(coro):
    return asyncio.run(coro)


def settings(tmp_path, **kwargs):
    return Settings(environment="test", mode="live", data_dir=tmp_path, openrouter_api_key="mock-key-never-real",
                    allow_paid_requests=True, provider_budget_usd=0.20, analysis_reserve_usd=0.10, render_reserve_usd=0.10, **kwargs)


def test_disabled_adapter_makes_no_requests(tmp_path):
    calls = []
    provider = OpenRouterProvider(Settings(data_dir=tmp_path), Store(tmp_path), httpx.MockTransport(lambda req: calls.append(req)))
    with pytest.raises(ProviderUnavailable):
        run(provider._post("chat/completions", {}, 0.1, "test"))
    assert calls == [] and provider.store.provider_usage()["calls"] == 0


def test_shared_budget_cache_no_double_charge_and_no_retries(tmp_path):
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"value": "ok", "usage": {"cost": 0.01}})

    store = Store(tmp_path)
    provider = OpenRouterProvider(settings(tmp_path), store, httpx.MockTransport(transport))
    first = run(provider._post("chat/completions", {"model": "test"}, 0.1, "one"))
    assert run(provider._post("chat/completions", {"model": "test"}, 0.1, "one")) == first
    run(provider._post("chat/completions", {"model": "test"}, 0.1, "two"))
    with pytest.raises(ProviderUnavailable):
        run(provider._post("images", {}, 0.1, "three"))
    assert len(calls) == 2
    assert store.provider_usage() == {"reserved_or_charged_usd": 0.2, "calls": 2}


def test_unknown_failed_call_keeps_reservation(tmp_path):
    calls = []

    def failure(request):
        calls.append(request)
        return httpx.Response(500, text="sensitive provider detail")

    provider = OpenRouterProvider(settings(tmp_path), Store(tmp_path), httpx.MockTransport(failure))
    with pytest.raises(ProviderUnavailable) as error:
        run(provider._post("images", {}, 0.1, "x"))
    assert "sensitive" not in str(error.value) and len(calls) == 1
    assert provider.store.provider_usage()["reserved_or_charged_usd"] == 0.1


def test_reported_overrun_stops_further_calls(tmp_path):
    provider = OpenRouterProvider(settings(tmp_path), Store(tmp_path), httpx.MockTransport(lambda req: httpx.Response(200, json={"usage": {"cost": 0.11}})))
    with pytest.raises(ProviderUnavailable):
        run(provider._post("images", {}, 0.1, "x"))
    assert provider.store.provider_usage()["reserved_or_charged_usd"] > 0.2
    with pytest.raises(ProviderUnavailable):
        run(provider._post("images", {}, 0.1, "y"))
    assert provider.store.provider_usage()["calls"] == 1
    assert provider.store.provider_actual_cost() == 0.11


def test_brief_structured_output_schema_and_no_user_photos(tmp_path):
    captured = []

    def reply(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"constraints": [], "preferences": [], "exclusions": [], "categories": ["tops", "bottoms", "shoes"], "unknowns": ["fit unknown"]})}}], "usage": {"cost": 0.01}})

    provider = OpenRouterProvider(settings(tmp_path), Store(tmp_path), httpx.MockTransport(reply))
    profile = Profile(id="profile", style_text="minimal", created_at="now", updated_at="now")
    request = RequestInput(text="office")
    brief = run(provider.analyze_brief(profile, request, build_brief(profile, request, "live")))
    assert brief.profile_id == "profile" and brief.budget_rub is None
    assert captured[0]["response_format"]["json_schema"]["strict"] is True
    assert captured[0]["provider"]["require_parameters"] is True
    assert captured[0]["max_tokens"] == 1500
    assert "image_url" not in json.dumps(captured)


def test_image_endpoint_reference_payload_and_local_validation(tmp_path):
    captured = []
    output = io.BytesIO()
    Image.new("RGB", (2, 2), "black").save(output, "PNG")
    image = base64.b64encode(output.getvalue()).decode()

    def reply(request):
        captured.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"data": [{"b64_json": image, "media_type": "image/png"}], "usage": {"cost": 0.01}})

    provider = OpenRouterProvider(settings(tmp_path), Store(tmp_path), httpx.MockTransport(reply))
    reference = "data:image/png;base64," + image
    assert run(provider.render_image("synthetic test", "outfit:1", [reference])) == reference
    url, body = captured[0]
    assert url == "https://openrouter.ai/api/v1/images"
    assert body["input_references"] == [{"type": "image_url", "image_url": {"url": reference}}]
    assert body["resolution"] == "1K" and body["aspect_ratio"] == "3:4" and body["n"] == 1
    assert "messages" not in body and "modalities" not in body
    with pytest.raises(ProviderUnavailable):
        run(provider.render_image("bad reference", "2", ["http://127.0.0.1/private"]))
    with pytest.raises(ProviderUnavailable):
        run(provider.render_image("no reference", "3", []))
    assert len(captured) == 1
