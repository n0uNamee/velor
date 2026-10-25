#!/usr/bin/env python3
"""Explicit Telegram setup actions. No action runs on import; no secrets are printed."""
import argparse
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "data" / "runtime"
ENV_FILE = ROOT / ".env"
TOKEN_INPUT = RUNTIME / "telegram-token-input.txt"
CHALLENGE_FILE = RUNTIME / "telegram-challenge.json"
TUNNEL_FILE = RUNTIME / "tunnel.json"
BOT_USERNAME = "velorr_bot"
TOKEN_PATTERN = re.compile(r"[0-9]{5,}:[A-Za-z0-9_-]{20,}")
METHODS = {"getMe", "getWebhookInfo", "getUpdates", "getChatMenuButton", "setChatMenuButton"}


class SetupError(Exception):
    """Only fixed, credential-free messages may be exposed to the CLI."""


def token_value(value):
    value = value.strip()
    if not TOKEN_PATTERN.fullmatch(value):
        raise SetupError("Telegram token is absent or invalid")
    return value


def env_value(text, key):
    values = []
    for line in text.splitlines():
        match = re.match(r"^\s*(?:export\s+)?" + re.escape(key) + r"\s*=(.*)$", line)
        if match:
            value = match.group(1).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values.append(value)
    nonempty = set(filter(None, values))
    if len(nonempty) > 1:
        raise SetupError("Conflicting configuration entries; refusing changes")
    return next(iter(nonempty), "")


def updated_env(text, key, value):
    lines, replaced = [], False
    pattern = re.compile(r"^\s*(?:export\s+)?" + re.escape(key) + r"\s*=")
    for line in text.splitlines(keepends=True):
        if pattern.match(line):
            if not replaced:
                lines.append(f"{key}={value}\n")
                replaced = True
        else:
            lines.append(line)
    result = "".join(lines)
    if not replaced:
        result += ("\n" if result and not result.endswith("\n") else "") + f"{key}={value}\n"
    return result


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise SetupError("Refusing a symbolic-link configuration target")
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_local(path, maximum=1024 * 1024):
    if path.is_symlink():
        raise SetupError("Refusing a symbolic-link configuration source")
    try:
        if path.stat().st_size > maximum:
            raise SetupError("Local setup input exceeds the limit")
        return path.read_text()
    except (OSError, UnicodeError):
        raise SetupError("Required local setup input is unavailable") from None


def backup_env(text):
    private_write(RUNTIME / ("env-telegram-backup-" + str(int(time.time())) + "-" + secrets.token_hex(4) + ".txt"), text)


def import_token():
    incoming = read_local(TOKEN_INPUT, 4096).strip()
    parsed = env_value(incoming, "TELEGRAM_BOT_TOKEN")
    if parsed:
        incoming = parsed
    token = token_value(incoming)
    existing_text = read_local(ENV_FILE) if ENV_FILE.exists() else ""
    existing = env_value(existing_text, "TELEGRAM_BOT_TOKEN")
    if existing and existing != token:
        raise SetupError("A different Telegram token already exists; overwrite refused")
    backup_env(existing_text)
    private_write(ENV_FILE, updated_env(existing_text, "TELEGRAM_BOT_TOKEN", token))


def create_challenge(now=None, nonce=None):
    current = int(time.time()) if now is None else now
    value = secrets.token_urlsafe(18) if nonce is None else nonce
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,64}", value):
        raise SetupError("Invalid challenge nonce")
    return {"schema_version": 1, "command": "/start velor_" + value,
            "created_at": current, "expires_at": current + 600}


def validate_challenge(challenge, now):
    if (not isinstance(challenge, dict) or challenge.get("schema_version") != 1
            or not re.fullmatch(r"/start velor(?:_|-)[A-Za-z0-9_-]{4,64}", str(challenge.get("command", "")))
            or type(challenge.get("created_at")) is not int or type(challenge.get("expires_at")) is not int
            or not 0 < challenge["expires_at"] - challenge["created_at"] <= 900
            or challenge["created_at"] > now + 30 or now > challenge["expires_at"]):
        raise SetupError("Challenge is invalid or expired; create a fresh challenge")


def challenge_user(updates, challenge, now):
    validate_challenge(challenge, now)
    if not isinstance(updates, list):
        raise SetupError("Telegram updates failed validation")
    matches = set()
    for update in updates:
        message = update.get("message", {}) if isinstance(update, dict) else {}
        if not isinstance(message, dict):
            continue
        sender, chat, date = message.get("from", {}), message.get("chat", {}), message.get("date")
        if not isinstance(sender, dict) or not isinstance(chat, dict):
            continue
        user_id = sender.get("id")
        if (type(user_id) is int and user_id > 0 and type(chat.get("id")) is int and chat["id"] == user_id
                and chat.get("type") == "private" and not sender.get("is_bot", False)
                and type(date) is int and challenge["created_at"] <= date <= min(now + 30, challenge["expires_at"])
                and message.get("text") == challenge["command"]):
            matches.add(user_id)
    if len(matches) != 1:
        raise SetupError("No unique fresh private challenge response found; no configuration changed")
    return matches.pop()


def merged_ids(existing, verified_id):
    values = re.split(r"[\s,]+", existing.strip()) if existing.strip() else []
    if any(not value.isascii() or not value.isdigit() or int(value) <= 0 for value in values):
        raise SetupError("Existing Telegram allowlist is invalid; refusing changes")
    return ",".join(str(value) for value in sorted({int(value) for value in values} | {verified_id}))


def tunnel_url(metadata):
    if not isinstance(metadata, dict):
        raise SetupError("Tunnel metadata is invalid")
    values = {metadata[key] for key in ("url", "public_url") if isinstance(metadata.get(key), str)}
    if len(values) != 1:
        raise SetupError("Tunnel metadata must contain one exact public URL")
    url = values.pop()
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if (parts.scheme != "https" or parts.username or parts.password or parts.port not in {None, 443}
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com", host)
                or "\\" in url or any(ord(char) <= 32 for char in url)):
            raise ValueError
    except ValueError:
        raise SetupError("Tunnel URL must be a public HTTPS trycloudflare.com address") from None
    return url


@contextmanager
def quiet_http_logs():
    loggers = [logging.getLogger(name) for name in ("httpx", "httpcore")]
    previous = [logger.disabled for logger in loggers]
    try:
        for logger in loggers:
            logger.disabled = True
        yield
    finally:
        for logger, disabled in zip(loggers, previous):
            logger.disabled = disabled


class TelegramAPI:
    def __init__(self, token, transport=None):
        self._token = token_value(token)
        self._transport = transport

    def call(self, method, payload=None):
        if method not in METHODS:
            raise SetupError("Unsupported Telegram setup operation")
        try:
            with quiet_http_logs(), httpx.Client(transport=self._transport, timeout=15, trust_env=False,
                                                follow_redirects=False) as client:
                with client.stream("POST", "https://api.telegram.org/bot" + self._token + "/" + method,
                                   json={} if payload is None else payload) as response:
                    if response.status_code != 200:
                        raise ValueError
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 2 * 1024 * 1024:
                            raise ValueError
            data = json.loads(content)
            if not isinstance(data, dict) or data.get("ok") is not True or "result" not in data:
                raise ValueError
            return data["result"]
        except Exception:
            raise SetupError("Telegram API action failed; no automatic retry, mutation outcome may be uncertain") from None


def check_bot(api):
    bot = api.call("getMe")
    if not isinstance(bot, dict) or bot.get("is_bot") is not True or bot.get("username") != BOT_USERNAME:
        raise SetupError("Token does not identify the required @velorr_bot; stopped")
    return bot


def identify(api, challenge, now=None):
    current = int(time.time()) if now is None else now
    validate_challenge(challenge, current)
    check_bot(api)
    webhook = api.call("getWebhookInfo")
    if not isinstance(webhook, dict) or webhook.get("url"):
        raise SetupError("A webhook exists or webhook status is invalid; stopped without changing it")
    updates = api.call("getUpdates", {"timeout": 0, "limit": 100})
    return challenge_user(updates, challenge, current)


def configure_menu(api, url, backup, chat_id):
    if type(chat_id) is not int or chat_id <= 0:
        raise SetupError("A verified private Telegram chat ID is required")
    check_bot(api)
    current = api.call("getChatMenuButton", {"chat_id": chat_id})
    if not isinstance(current, dict):
        raise SetupError("Existing menu failed validation; no menu change attempted")
    backup(current)
    desired = {"type": "web_app", "text": "Открыть VÉLOR", "web_app": {"url": url}}
    if current != desired and api.call("setChatMenuButton", {"chat_id": chat_id, "menu_button": desired}) is not True:
        raise SetupError("Telegram did not confirm the menu change")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("import-token", "check", "challenge", "identify", "menu"))
    action = parser.parse_args().action
    try:
        if action == "challenge":
            challenge = create_challenge()
            private_write(CHALLENGE_FILE, json.dumps(challenge) + "\n")
            print(challenge["command"])
            return 0
        if action == "import-token":
            import_token()
            print("Telegram token imported locally")
            return 0
        text = read_local(ENV_FILE)
        api = TelegramAPI(env_value(text, "TELEGRAM_BOT_TOKEN"))
        if action == "check":
            check_bot(api)
            print("Verified @velorr_bot")
        elif action == "identify":
            user_id = identify(api, json.loads(read_local(CHALLENGE_FILE)))
            allowed = merged_ids(env_value(text, "VELOR_TELEGRAM_ALLOWED_USER_IDS"), user_id)
            backup_env(text)
            private_write(ENV_FILE, updated_env(text, "VELOR_TELEGRAM_ALLOWED_USER_IDS", allowed))
            private_write(RUNTIME / "telegram-verified-user.json", json.dumps({"user_id": user_id, "chat_id": user_id, "verified_at": int(time.time())}) + "\n")
            print(user_id)
        elif action == "menu":
            url = tunnel_url(json.loads(read_local(TUNNEL_FILE)))
            identity = json.loads(read_local(RUNTIME / "telegram-verified-user.json"))
            chat_id = identity.get("chat_id")
            def backup(button):
                path = RUNTIME / ("telegram-menu-backup-" + str(int(time.time())) + "-" + secrets.token_hex(4) + ".json")
                private_write(path, json.dumps({"chat_id": chat_id, "menu_button": button}, ensure_ascii=False) + "\n")
            configure_menu(api, url, backup, chat_id)
            print("Personal menu configured for verified @velorr_bot chat; global menu unchanged")
        return 0
    except SetupError as error:
        print(str(error))
        return 1
    except Exception:
        # Even unexpected filesystem/transport exceptions must not print credentials.
        print("Telegram setup stopped. Check the requested local input and action; no automatic retry.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
