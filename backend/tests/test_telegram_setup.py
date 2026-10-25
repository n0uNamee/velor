"""Synthetic-only setup tests: no real credentials, configuration reads, or network."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location("velor_telegram_setup", Path(__file__).resolve().parents[2] / "scripts" / "telegram_setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)
FAKE_TOKEN = "123456789:" + "synthetic_credential_0000000000000"
OTHER_FAKE_TOKEN = "987654321:" + "another_synthetic_credential_00000"
BOT = {"is_bot": True, "username": "velorr_bot", "id": 123456789}
NOW = 1700000300


def challenge():
    return setup.create_challenge(now=NOW - 100, nonce="a" * 24)


def message(user=42, text=None, date=NOW - 10, chat_type="private", chat_id=None):
    return {"update_id": 9, "message": {"text": challenge()["command"] if text is None else text,
            "date": date, "from": {"id": user, "is_bot": False},
            "chat": {"id": user if chat_id is None else chat_id, "type": chat_type}}}


def api_with(results, captured=None):
    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        assert request.method == "POST"
        assert request.url.scheme == "https" and request.url.host == "api.telegram.org"
        if captured is not None:
            captured.append((method, json.loads(request.content)))
        result = results[method]
        return httpx.Response(200, json={"ok": True, "result": result})
    return setup.TelegramAPI(FAKE_TOKEN, transport=httpx.MockTransport(handler))


def test_env_update_preserves_unrelated_values_and_existing_ids():
    before = "# local\nOPENROUTER_API_KEY=synthetic-other\nTELEGRAM_BOT_TOKEN=\nVELOR_MODE=demo\n"
    after = setup.updated_env(before, "TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    assert "OPENROUTER_API_KEY=synthetic-other\n" in after
    assert "VELOR_MODE=demo\n" in after
    assert setup.env_value(after, "TELEGRAM_BOT_TOKEN") == FAKE_TOKEN
    assert setup.merged_ids("9, 2,9", 42) == "2,9,42"


def test_import_refuses_different_existing_token_before_any_write(monkeypatch):
    monkeypatch.setattr(setup, "ENV_FILE", SimpleNamespace(exists=lambda: True))
    monkeypatch.setattr(setup, "read_local", lambda path, *args: FAKE_TOKEN if path == setup.TOKEN_INPUT else f"TELEGRAM_BOT_TOKEN={OTHER_FAKE_TOKEN}\n")
    monkeypatch.setattr(setup, "private_write", lambda *args: pytest.fail("Unexpected write"))
    monkeypatch.setattr(setup, "backup_env", lambda *args: pytest.fail("Unexpected backup"))
    with pytest.raises(setup.SetupError, match="overwrite refused"):
        setup.import_token()


def test_generated_challenge_has_ten_minute_expiry():
    value = setup.create_challenge(now=NOW, nonce="a" * 24)
    assert value["expires_at"] == NOW + 600
    assert value["command"] == "/start velor_" + "a" * 24


def test_identify_exact_fresh_private_message_without_consuming_updates():
    captured = []
    api = api_with({"getMe": BOT, "getWebhookInfo": {"url": ""}, "getUpdates": [message()]}, captured)
    assert setup.identify(api, challenge(), NOW) == 42
    assert [method for method, _ in captured] == ["getMe", "getWebhookInfo", "getUpdates"]
    assert captured[-1][1] == {"timeout": 0, "limit": 100}
    assert "offset" not in captured[-1][1]


def test_parent_approved_existing_exact_challenge_is_supported():
    value = {"schema_version": 1, "command": "/start velor-demo-1644", "created_at": NOW - 180, "expires_at": NOW + 600}
    assert setup.challenge_user([message(text=value["command"])], value, NOW) == 42


@pytest.mark.parametrize("update", [message(text="/start wrong"), message(date=NOW - 1000),
                                    message(chat_type="group"), message(chat_id=99)])
def test_identification_rejects_unverified_messages(update):
    with pytest.raises(setup.SetupError):
        setup.challenge_user([update], challenge(), NOW)


def test_identification_rejects_ambiguous_or_expired_challenge():
    with pytest.raises(setup.SetupError):
        setup.challenge_user([message(user=42), message(user=99)], challenge(), NOW)
    with pytest.raises(setup.SetupError):
        setup.challenge_user([message()], challenge(), NOW + 1000)


def test_existing_webhook_stops_before_updates():
    captured = []
    api = api_with({"getMe": BOT, "getWebhookInfo": {"url": "https://existing.invalid/hook"}}, captured)
    with pytest.raises(setup.SetupError, match="webhook"):
        setup.identify(api, challenge(), NOW)
    assert [method for method, _ in captured] == ["getMe", "getWebhookInfo"]


def test_wrong_bot_stops():
    api = api_with({"getMe": {"is_bot": True, "username": "different_bot"}})
    with pytest.raises(setup.SetupError, match="required"):
        setup.check_bot(api)


@pytest.mark.parametrize("url", ["http://example.trycloudflare.com", "https://trycloudflare.com", "https://example.com", "https://example.trycloudflare.com.evil.invalid", "https://user:pass@example.trycloudflare.com", "https://example.trycloudflare.com:8443"])
def test_tunnel_rejects_other_hosts_and_credential_urls(url):
    with pytest.raises(setup.SetupError):
        setup.tunnel_url({"url": url})


def test_menu_backs_up_before_mutation_and_preserves_exact_url():
    url = "https://synthetic-demo.trycloudflare.com"
    assert setup.tunnel_url({"public_url": url}) == url
    events = []
    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        events.append(method)
        if method == "setChatMenuButton":
            assert events[-2] == "backup"
            assert json.loads(request.content)["menu_button"] == {"type": "web_app", "text": "Открыть VÉLOR", "web_app": {"url": url}}
        return httpx.Response(200, json={"ok": True, "result": {"getMe": BOT, "getChatMenuButton": {"type": "default"}, "setChatMenuButton": True}[method]})
    api = setup.TelegramAPI(FAKE_TOKEN, transport=httpx.MockTransport(handler))
    setup.configure_menu(api, url, lambda button: events.append("backup"), 123)
    assert events == ["getMe", "getChatMenuButton", "backup", "setChatMenuButton"]


def test_transport_errors_and_redirects_are_sanitized_no_retry():
    calls = []
    def failed(request):
        calls.append(1)
        raise httpx.ConnectError("secret URL " + str(request.url), request=request)
    api = setup.TelegramAPI(FAKE_TOKEN, transport=httpx.MockTransport(failed))
    with pytest.raises(setup.SetupError) as result:
        api.call("getMe")
    assert FAKE_TOKEN not in str(result.value) and "api.telegram.org/bot" not in str(result.value)
    assert len(calls) == 1
    redirects = []
    def redirect(request):
        redirects.append(str(request.url.host))
        return httpx.Response(302, headers={"Location": "https://must-not-follow.invalid"})
    api = setup.TelegramAPI(FAKE_TOKEN, transport=httpx.MockTransport(redirect))
    with pytest.raises(setup.SetupError):
        api.call("getMe")
    assert redirects == ["api.telegram.org"]
