"""Temporary, local-backed website sessions; no provider or Telegram credentials."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

COOKIE = "velor_web_session"
TTL = 3600


def create_access_code(path: Path, ttl=TTL) -> dict:
    if not 0 < ttl <= TTL:
        raise ValueError("Access code lifetime must be within one hour")
    record = {"code": secrets.token_urlsafe(24), "expires_at": time.time() + ttl}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Invalid access code target")
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(record, output)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return record


class WebSessionManager:
    def __init__(self, data_dir: Path, allowed_origins: tuple[str, ...], code: str,
                 code_expires_at: float, secure_cookie: bool = True):
        self.allowed_origins = frozenset(origin.rstrip("/") for origin in allowed_origins)
        self.code = code
        self.code_expires_at = min(code_expires_at, time.time() + TTL)
        self.secure_cookie = secure_cookie
        self.path = Path(data_dir) / "web_sessions.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,owner TEXT NOT NULL,csrf TEXT NOT NULL,expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts(peer TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS issued(code_hash TEXT PRIMARY KEY,count INTEGER NOT NULL);
            """)
        self.path.chmod(0o600)

    def _db(self):
        return sqlite3.connect(self.path, timeout=5)

    def _origin(self, request):
        if request.headers.get("origin") not in self.allowed_origins:
            raise HTTPException(403, "Origin is not allowed")

    def _session(self, request):
        token = request.cookies.get(COOKIE, "")
        if not token or len(token) > 256:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._db() as db:
            row = db.execute("SELECT owner,csrf,expires FROM sessions WHERE token_hash=? AND expires>?", (digest, time.time())).fetchone()
        return row

    def authenticate(self, request) -> str:
        session = self._session(request)
        if session is None:
            raise HTTPException(401, "Website session required")
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            self._origin(request)
            supplied = request.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(supplied.encode(), session[1].encode()):
                raise HTTPException(403, "CSRF validation failed")
        return session[0]

    def session_info(self, request) -> dict:
        origin = request.headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            raise HTTPException(403, "Origin is not allowed")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Origin is not allowed")
        session = self._session(request)
        if session is None:
            return {"authenticated": False, "csrf_token": None}
        return {"authenticated": True, "owner": session[0], "csrf_token": session[1], "expires_at": session[2]}

    def login(self, request, code) -> JSONResponse:
        self._origin(request)
        now = time.time()
        peer = hashlib.sha256((request.client.host if request.client else "unknown").encode()).hexdigest()
        code_hash = hashlib.sha256(self.code.encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE created<?", (now - 300,))
            total = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            count = db.execute("SELECT COUNT(*) FROM attempts WHERE peer=?", (peer,)).fetchone()[0]
            if count >= 10 or total >= 50:
                raise HTTPException(429, "Too many login attempts")
            db.execute("INSERT INTO attempts VALUES (?,?)", (peer, now))
        if not self.code or now > self.code_expires_at or not isinstance(code, str) or not hmac.compare_digest(code.encode(), self.code.encode()):
            raise HTTPException(401, "Invalid or expired access code")
        existing = self._session(request)
        if existing:
            # Reauthentication retains this browser's profile and requires its CSRF token.
            self.authenticate(request)
            response = JSONResponse({"authenticated": True, "owner": existing[0], "csrf_token": existing[1], "expires_at": existing[2]})
            response.headers["Cache-Control"] = "no-store"
            return response
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        owner, expires = "web:" + uuid4().hex, now + TTL
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT count FROM issued WHERE code_hash=?", (code_hash,)).fetchone()
            if row and row[0] >= 10:
                raise HTTPException(429, "Access code session limit reached")
            db.execute("INSERT INTO issued VALUES (?,1) ON CONFLICT(code_hash) DO UPDATE SET count=count+1", (code_hash,))
            db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), owner, csrf, expires))
        response = JSONResponse({"authenticated": True, "owner": owner, "csrf_token": csrf, "expires_at": expires})
        response.set_cookie(COOKIE, token, max_age=TTL, secure=self.secure_cookie, httponly=True, samesite="strict", path="/")
        response.headers["Cache-Control"] = "no-store"
        return response

    def logout(self, request) -> JSONResponse:
        self._origin(request)
        self.authenticate(request)
        token = request.cookies.get(COOKIE, "")
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        response = JSONResponse({"authenticated": False, "csrf_token": None})
        response.delete_cookie(COOKIE, path="/", secure=self.secure_cookie, httponly=True, samesite="strict")
        response.headers["Cache-Control"] = "no-store"
        return response


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=256)


def install_web_auth_routes(app, manager):
    @app.post("/api/session/login")
    async def login(request: Request, body: LoginBody):
        return manager.login(request, body.code)

    @app.get("/api/session")
    async def session(request: Request):
        return JSONResponse(manager.session_info(request), headers={"Cache-Control": "no-store"})

    @app.post("/api/session/logout")
    async def logout(request: Request):
        return manager.logout(request)
