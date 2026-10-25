"""Real local adapters, no network or external model calls."""
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_real_demo_profile_catalog_stylist_edit_save_restart(tmp_path):
    settings = Settings(environment="test", data_dir=tmp_path)
    auth = {"X-Dev-User": "integration"}
    with TestClient(create_app(settings)) as client:
        assert client.put("/api/profile", headers=auth, json={"style_text": "Минимализм и свободный крой"}).status_code == 200
        response = client.post("/api/requests", headers=auth, json={"text": "На каждый день"})
        assert response.status_code == 201
        request_id = response.json()["id"]
        url = f"/api/requests/{request_id}"

        def wait(predicate):
            for _ in range(200):
                state = client.get(url, headers=auth).json()
                if predicate(state):
                    return state
                time.sleep(0.005)
            raise AssertionError(state)

        state = wait(lambda state: state["status"] == "selection")
        assert len(state["catalog"]["products"]) == 24
        assert len(state["catalog"]["sources"]) == 13
        removed = state["catalog"]["products"][0]["id"]
        assert client.delete(url + f"/products/{removed}", headers=auth).status_code == 200
        assert client.post(url + "/style", headers=auth, json={}).status_code == 200
        state = wait(lambda state: state["status"] == "ready")
        assert len(state["outfits"]) == 3, state["catalog"]["warnings"]
        outfit = state["outfits"][0]
        assert removed not in outfit["product_ids"]
        assert outfit["render_status"] == "ready" and outfit["render_revision"] == 1
        products = {p["id"]: p for p in state["catalog"]["products"]}
        old = outfit["product_ids"][0]
        category = products[old]["category"]
        new = next(p["id"] for p in products.values() if p["category"] == category and p["id"] not in outfit["product_ids"] + [removed])
        outfit_url = url + f"/outfits/{outfit['id']}"
        response = client.patch(outfit_url, headers=auth, json={"old_product_id": old, "new_product_id": new, "expected_revision": 1})
        assert response.status_code == 200, response.text
        assert response.json()["revision"] == 2
        wait(lambda state: next(o for o in state["outfits"] if o["id"] == outfit["id"])["render_revision"] == 2)
        assert client.post(outfit_url + "/save", headers=auth, json={"expected_revision": 2}).status_code == 200
    with TestClient(create_app(settings)) as client:
        saved = client.get("/api/gallery", headers=auth).json()["outfits"][0]
        assert saved["revision"] == 2 and new in saved["product_ids"] and saved["saved"]
