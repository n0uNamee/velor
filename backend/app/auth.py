"""Telegram token-based validation per core.telegram.org/bots/webapps.

No initData, tokens, or user payloads are logged.
"""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request


def validate_init_data(raw: str, token: str, max_age: int, now: int | None = None) -> str:
    try:
        if not raw or len(raw) > 16384:
            raise ValueError
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError
        received_hash = fields.pop("hash")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", received_hash):
            raise ValueError
        check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash.lower()):
            raise ValueError
        issued = int(fields["auth_date"])
        current = int(time.time()) if now is None else now
        if issued > current + 30 or current - issued > max_age:
            raise ValueError
        user_id = json.loads(fields["user"])["id"]
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ValueError
        return f"telegram:{user_id}"
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "Invalid or expired Telegram initData") from None


async def current_user(request: Request) -> str:
    settings = request.app.state.settings
    if settings.auth_mode == "web":
        return request.app.state.web_sessions.authenticate(request)
    if settings.locked_preview:
        raise HTTPException(401, "Telegram access is not configured; public entry is locked")
    authorization = request.headers.get("Authorization", "")
    dev_user = request.headers.get("X-Dev-User")
    # A supplied Telegram credential is always validated; never fall back on failure.
    if authorization:
        if dev_user or not authorization.startswith("tma ") or not settings.telegram_bot_token:
            raise HTTPException(401, "Telegram authentication unavailable or ambiguous")
        identity = validate_init_data(authorization[4:], settings.telegram_bot_token, settings.telegram_max_age_seconds)
        if settings.telegram_allowed_user_ids and int(identity.split(":", 1)[1]) not in settings.telegram_allowed_user_ids:
            raise HTTPException(403, "This Telegram user is not enabled for VÉLOR")
        return identity
    if dev_user and settings.environment != "production" and settings.enable_dev_auth:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", dev_user):
            raise HTTPException(401, "Invalid local development user")
        return f"dev:{dev_user}"
    raise HTTPException(401, "Use Telegram initData or explicitly enabled local dev authentication")
