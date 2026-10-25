import hashlib
import json
import sqlite3
import time

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.web_auth import COOKIE, WebSessionManager, create_access_code, install_web_auth_routes

ORIGIN = "https://example.test"
HEADERS = {"Origin": ORIGIN}


def application(tmp_path, **kwargs):
    manager = WebSessionManager(tmp_path, (ORIGIN,), "synthetic-code", time.time() + 3600, **kwargs)
    app = FastAPI()
    install_web_auth_routes(app, manager)
    @app.post("/mutation")
    def mutation(request: Request):
        return {"owner": manager.authenticate(request)}
    return app, manager


def login(client):
    return client.post("/api/session/login", json={"code": "synthetic-code"}, headers=HEADERS)


def test_isolated_hashed_secure_sessions(tmp_path):
    app, manager = application(tmp_path)
    with TestClient(app, base_url=ORIGIN) as first, TestClient(app, base_url=ORIGIN) as second:
        one, two = login(first), login(second)
        assert one.status_code == two.status_code == 200
        assert one.json()["owner"] != two.json()["owner"]
        assert one.json()["owner"].startswith("web:")
        cookie = one.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        assert "Max-Age=3600" in cookie and "Path=/" in cookie
        token = first.cookies.get(COOKIE)
        with sqlite3.connect(manager.path) as db:
            hashes = [row[0] for row in db.execute("SELECT token_hash FROM sessions")]
        assert token not in hashes and hashlib.sha256(token.encode()).hexdigest() in hashes
        assert first.get("/api/session").json()["csrf_token"] == one.json()["csrf_token"]


def test_csrf_origin_logout_and_reauthentication(tmp_path):
    app, manager = application(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        result = login(client).json()
        csrf = {**HEADERS, "X-CSRF-Token": result["csrf_token"]}
        assert client.post("/mutation", headers=HEADERS).status_code == 403
        assert client.post("/mutation", headers={**csrf, "Origin": "https://evil.test"}).status_code == 403
        assert client.post("/mutation", headers=csrf).json()["owner"] == result["owner"]
        assert client.post("/api/session/login", json={"code": "synthetic-code"}, headers=csrf).json()["owner"] == result["owner"]
        assert client.get("/api/session", headers={"Origin": "https://evil.test"}).status_code == 403
        assert client.post("/api/session/logout", headers=HEADERS).status_code == 403
        assert client.post("/api/session/logout", headers=csrf).status_code == 200
        assert client.get("/api/session").json() == {"authenticated": False, "csrf_token": None}
        assert client.post("/mutation", headers=csrf).status_code == 401


def test_login_rate_limit_expiry_and_exact_origin(tmp_path):
    app, manager = application(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.post("/api/session/login", json={"code": "synthetic-code"}).status_code == 403
        for _ in range(10):
            assert client.post("/api/session/login", json={"code": "wrong"}, headers=HEADERS).status_code == 401
        assert login(client).status_code == 429
    other_app, other = application(tmp_path / "other")
    other.code_expires_at = time.time() - 1
    with TestClient(other_app, base_url=ORIGIN) as client:
        assert login(client).status_code == 401


def test_session_expiry_and_ten_session_bound(tmp_path):
    app, manager = application(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        login(client)
        with sqlite3.connect(manager.path) as db:
            db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
        assert client.get("/api/session").json()["authenticated"] is False
        with sqlite3.connect(manager.path) as db:
            db.execute("DELETE FROM attempts")
            db.execute("UPDATE issued SET count=10")
        assert login(client).status_code == 429


def test_code_file_permissions_and_no_plaintext_session_token(tmp_path):
    path = tmp_path / "synthetic-access.json"
    record = create_access_code(path)
    assert 3500 < record["expires_at"] - time.time() <= 3600
    assert json.loads(path.read_text()) == record
    assert path.stat().st_mode & 0o777 == 0o600
