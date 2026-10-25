import asyncio
import hashlib
import hmac
import io
import json
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app.auth import validate_init_data
from app.config import Settings
from app.main import create_app
from app.models import Outfit, Product, ProductCatalog, SourceStatus

DEV = {"X-Dev-User": "alice"}
BOB = {"X-Dev-User": "bob"}


def signed_data(token="test-token", user_id=123, issued=None, **extra):
    fields = {"auth_date": str(int(time.time()) if issued is None else issued), "user": json.dumps({"id": user_id}), **extra}
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
def adapters(monkeypatch):
    async def search(brief, on_source=None):
        if on_source:
            await on_source(SourceStatus(source_id="test", name="Test", state="complete", found=6))
        return ProductCatalog(products=[
            Product(id=f"{category}{i}", title=f"{category} {i}", category=category,
                    source_id="test", source_url="https://example.com/product", is_demo=True, verification="demo")
            for category in ["tops", "bottoms", "shoes"] for i in [1, 2]
        ])

    def compose(request_id, brief, products):
        ids = [next(p.id for p in products if p.category == c) for c in ["tops", "bottoms", "shoes"]]
        return [Outfit(id="outfit-" + request_id, request_id=request_id, title="Demo", product_ids=ids, explanation="Test", render_disclaimer="Demo")]

    async def render(outfit, products):
        return f"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'><text>{outfit.revision}</text></svg>"

    search_module = SimpleNamespace(search_catalog=search)
    stylist_module = SimpleNamespace(compose_outfits=compose, render_outfit=render)
    monkeypatch.setitem(sys.modules, "app.search", search_module)
    monkeypatch.setitem(sys.modules, "app.stylist", stylist_module)
    return search_module, stylist_module


@pytest.fixture
def client(tmp_path, adapters):
    with TestClient(create_app(Settings(environment="test", data_dir=tmp_path))) as client:
        yield client


def profile(client, headers=DEV):
    response = client.put("/api/profile", headers=headers, json={"style_text": "Минимализм; без кожи", "images": []})
    assert response.status_code == 200, response.text
    return response.json()


def wait_state(client, request_id, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/requests/{request_id}", headers=DEV)
        assert response.status_code == 200
        state = response.json()
        if predicate(state):
            return state
        time.sleep(0.005)
    pytest.fail(f"State timed out: {state}")


def searched(client):
    profile(client)
    response = client.post("/api/requests", headers=DEV, json={"text": "Нужно для офиса", "budget_rub": 15000})
    assert response.status_code == 201, response.text
    return wait_state(client, response.json()["id"], lambda s: s["status"] == "selection")


def styled(client):
    state = searched(client)
    response = client.post(f"/api/requests/{state['id']}/style", headers=DEV, json={})
    assert response.status_code == 200
    return wait_state(client, state["id"], lambda s: s["status"] == "ready")


def test_health_and_auth_are_explicit(client):
    health = client.get("/api/health").json()
    assert health["mode"] == "demo" and health["search_workers"] == 3
    assert health["providers"]["brief"] == "demo_local"
    assert client.get("/api/profile").status_code == 401
    assert client.get("/api/profile", headers={"Authorization": "tma bad", **DEV}).status_code == 401


def test_telegram_valid_invalid_and_expiry():
    assert validate_init_data(signed_data(issued=1000), "test-token", 3600, now=1100) == "telegram:123"
    for raw in [signed_data(token="wrong", issued=1000), signed_data(issued=1), signed_data(issued=2000), signed_data(issued=1000) + "&user=bad", signed_data(user_id=True, issued=1000)]:
        with pytest.raises(HTTPException) as error:
            validate_init_data(raw, "test-token", 100, now=1100)
        assert error.value.status_code == 401


def test_production_fails_closed_and_rejects_dev(tmp_path):
    with pytest.raises(ValueError):
        create_app(Settings(environment="production", data_dir=tmp_path))
    app = create_app(Settings(environment="production", enable_dev_auth=False, telegram_bot_token="test-token", data_dir=tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/profile", headers=DEV).status_code == 401
        assert client.get("/api/profile", headers={"Authorization": "tma " + signed_data()}).status_code == 200


def test_profile_required_and_isolated(client):
    assert client.post("/api/requests", headers=DEV, json={"text": "hello"}).status_code == 409
    first = profile(client)
    second = profile(client)
    assert first["id"] == second["id"]
    assert client.get("/api/profile", headers=BOB).json() is None
    assert client.put("/api/profile", headers=DEV, json={"style_text": "x", "extra": "bad"}).status_code == 422


def test_brief_provenance_nulls_no_automatic_stylist(client):
    state = searched(client)
    brief = state["brief"]
    assert brief["schema_version"] == "1.0"
    assert brief["sizes"] is None and brief["city"] is None
    assert brief["budget_rub"] == 15000
    assert brief["exclusions"][0]["provenance"] == "profile"
    assert brief["exclusions"][0]["strength"] == "hard"
    assert state["outfits"] == []
    assert all(p["is_demo"] and p["verified_at"] is None for p in state["catalog"]["products"])
    assert client.get(f"/api/requests/{state['id']}", headers=BOB).status_code == 404


def test_excluded_product_never_reaches_stylist(client):
    state = searched(client)
    url = f"/api/requests/{state['id']}"
    response = client.delete(url + "/products/tops1", headers=DEV)
    assert response.status_code == 200
    assert client.post(url + "/style", headers=DEV, json={}).status_code == 200
    state = wait_state(client, state["id"], lambda s: s["status"] == "ready")
    assert "tops1" not in state["outfits"][0]["product_ids"]


def test_replace_save_stale_and_gallery_snapshot(client):
    state = styled(client)
    outfit = state["outfits"][0]
    url = f"/api/requests/{state['id']}/outfits/{outfit['id']}"
    assert client.post(url + "/save", headers=DEV, json={"expected_revision": 1}).status_code == 200
    assert client.get("/api/gallery", headers=BOB).json()["outfits"] == []
    patch = {"old_product_id": "tops1", "new_product_id": "tops2", "expected_revision": 1}
    response = client.patch(url, headers=DEV, json=patch)
    assert response.status_code == 200 and response.json()["revision"] == 2
    assert client.patch(url, headers=DEV, json=patch).status_code == 409
    assert client.post(url + "/save", headers=DEV, json={"expected_revision": 1}).status_code == 409
    state = wait_state(client, state["id"], lambda s: s["outfits"][0]["render_revision"] == 2)
    # Previous explicit save remains a snapshot, even after editing.
    assert client.get("/api/gallery", headers=DEV).json()["outfits"][0]["revision"] == 1
    assert client.post(url + "/save", headers=DEV, json={"expected_revision": 2}).status_code == 200
    assert client.get("/api/gallery", headers=DEV).json()["outfits"][0]["revision"] == 2
    patch.update(expected_revision=2, old_product_id="tops2", new_product_id="shoes2")
    assert client.patch(url, headers=DEV, json=patch).status_code == 422


def test_late_render_cannot_overwrite_new_revision(client, adapters):
    gate = client.portal.call(asyncio.Event)

    async def delayed_render(outfit, products):
        if outfit.revision == 1:
            await gate.wait()
        return f"data:image/svg+xml,<svg>{outfit.revision}</svg>"

    adapters[1].render_outfit = delayed_render
    state = searched(client)
    client.post(f"/api/requests/{state['id']}/style", headers=DEV, json={})
    state = wait_state(client, state["id"], lambda s: bool(s["outfits"]))
    outfit = state["outfits"][0]
    url = f"/api/requests/{state['id']}/outfits/{outfit['id']}"
    assert client.post(url + "/save", headers=DEV, json={"expected_revision": 1}).status_code == 409
    assert client.patch(url, headers=DEV, json={"old_product_id": "tops1", "new_product_id": "tops2", "expected_revision": 1}).status_code == 200
    wait_state(client, state["id"], lambda s: s["outfits"][0]["render_revision"] == 2)
    client.portal.call(gate.set)
    client.portal.call(asyncio.sleep, 0.02)
    result = client.get(f"/api/requests/{state['id']}", headers=DEV).json()["outfits"][0]
    assert result["revision"] == result["render_revision"] == 2
    assert result["render_url"].endswith("2</svg>")


def png_bytes():
    data = io.BytesIO()
    Image.new("RGB", (4, 4), "black").save(data, format="PNG")
    return data.getvalue()


def test_recomposition_with_same_id_revision_rejects_old_render(client, adapters):
    gate = client.portal.call(asyncio.Event)
    started = client.portal.call(asyncio.Event)
    calls = 0

    async def renderer(outfit, products):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await gate.wait()
            return "data:image/svg+xml,<svg>old composition</svg>"
        return "data:image/svg+xml,<svg>new composition</svg>"

    adapters[1].render_outfit = renderer
    state = searched(client)
    url = f"/api/requests/{state['id']}"
    client.post(url + "/style", headers=DEV, json={})
    client.portal.call(started.wait)
    # Remove an unselected item; deterministic stylist reuses the same outfit ID.
    assert client.delete(url + "/products/tops2", headers=DEV).status_code == 200
    assert client.post(url + "/style", headers=DEV, json={}).status_code == 200
    wait_state(client, state["id"], lambda s: s["status"] == "ready")
    client.portal.call(gate.set)
    client.portal.call(asyncio.sleep, 0.02)
    current = client.get(url, headers=DEV).json()["outfits"][0]
    assert current["revision"] == 1
    assert current["render_url"].endswith("new composition</svg>")


def test_upload_ownership_type_and_injected_paths(client):
    response = client.post("/api/uploads", headers=DEV, data={"kind": "wardrobe"}, files={"file": ("photo.png", png_bytes(), "image/png")})
    assert response.status_code == 201, response.text
    ref = response.json()
    assert ref["local_path"] is None
    assert client.get(ref["url"], headers=DEV).content == png_bytes()
    assert client.get(ref["url"], headers=BOB).status_code == 404
    assert client.get(ref["url"]).status_code == 401
    assert client.put("/api/profile", headers=BOB, json={"style_text": "x", "images": [ref]}).status_code == 422
    assert client.put("/api/profile", headers=DEV, json={"style_text": "x", "images": [{**ref, "local_path": "/tmp/fake"}]}).status_code == 422
    assert client.put("/api/profile", headers=DEV, json={"style_text": "x", "images": [{**ref, "url": "http://127.0.0.1/secret"}]}).status_code == 422
    assert client.put("/api/profile", headers=DEV, json={"style_text": "x", "images": [ref]}).status_code == 200
    response = client.post("/api/uploads", headers=DEV, data={"kind": "wardrobe"}, files={"file": ("bad.png", b"not an image", "image/png")})
    assert response.status_code == 415


def test_body_and_upload_limits(tmp_path, adapters):
    with TestClient(create_app(Settings(environment="test", data_dir=tmp_path, upload_max_bytes=64))) as client:
        assert client.put("/api/profile", headers=DEV, content=b"x" * (256 * 1024 + 1)).status_code == 413
        response = client.post("/api/uploads", headers=DEV, data={"kind": "reference"}, files={"file": ("x.png", png_bytes(), "image/png")})
        assert response.status_code == 413


def test_upload_quota(tmp_path, adapters):
    with TestClient(create_app(Settings(environment="test", data_dir=tmp_path, upload_max_count=1))) as client:
        for expected in [201, 413]:
            assert client.post("/api/uploads", headers=DEV, data={"kind": "reference"}, files={"file": ("x.png", png_bytes(), "image/png")}).status_code == expected


def test_persistence_across_restart(tmp_path, adapters):
    settings = Settings(environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        state = styled(client)
        outfit = state["outfits"][0]
        client.post(f"/api/requests/{state['id']}/outfits/{outfit['id']}/save", headers=DEV, json={"expected_revision": 1})
        profile_id = state["profile_id"]
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/profile", headers=DEV).json()["id"] == profile_id
        assert client.get(f"/api/requests/{state['id']}", headers=DEV).json()["status"] == "ready"
        assert client.get("/api/gallery", headers=DEV).json()["outfits"][0]["saved"] is True
