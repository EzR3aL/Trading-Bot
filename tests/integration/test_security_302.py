"""
Regression tests for Issue #302 — SSRF + IP-Spoofing fixes.

Covers:
    1. SSRF: /api/bots/test-discord-direct rejects non-whitelisted webhook URLs (422)
    2. SSRF: /api/bots/test-discord-direct rejects http:// scheme (only https allowed) (422)
    3. SSRF: /api/bots/test-discord-direct accepts whitelisted URLs (200, mocked)
    4. Validation: /api/bots/test-telegram-direct rejects empty bot_token/chat_id (422)
    5. IP-Spoofing: /api/auth/bridge/generate ignores X-Forwarded-For when BEHIND_PROXY unset
    6. IP-Spoofing: /api/auth/bridge/generate honors X-Forwarded-For when BEHIND_PROXY=1
    7. IP-Spoofing: invalid X-Forwarded-For value falls back to request.client.host

Endpoints under test:
    POST /api/bots/test-discord-direct
    POST /api/bots/test-telegram-direct
    POST /api/auth/bridge/generate
"""

import logging
from unittest.mock import MagicMock

import pytest

from tests.integration.conftest import auth_header


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeAsyncCM:
    """Minimal async context manager stand-in for aiohttp response/session."""

    def __init__(self, inner):
        self._inner = inner

    async def __aenter__(self):
        return self._inner

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeResponse:
    def __init__(self, status: int = 204, text: str = ""):
        self.status = status
        self._text = text

    async def text(self):
        return self._text


def _make_fake_aiohttp_session(response_status: int = 204):
    """Return an object that mimics aiohttp.ClientSession() as an async CM.

    Usage:
        async with aiohttp.ClientSession() as http_session:
            async with http_session.post(url, json=payload) as resp:
                ...

    We want both `aiohttp.ClientSession()` and `http_session.post()` to
    produce async context managers.
    """
    fake_resp = _FakeResponse(status=response_status)

    session = MagicMock()
    # session.post(...) returns an async CM wrapping the fake response
    session.post = MagicMock(return_value=_FakeAsyncCM(fake_resp))

    # aiohttp.ClientSession() should itself be an async CM yielding `session`
    def _ctor(*args, **kwargs):
        return _FakeAsyncCM(session)

    return _ctor


# ---------------------------------------------------------------------------
# SSRF regression — /api/bots/test-discord-direct
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_discord_direct_rejects_non_whitelisted_domain(client, user_token):
    """POST /api/bots/test-discord-direct returns 422 when webhook_url host
    is not on the SSRF allow-list (e.g. https://evil.com/x)."""
    assert user_token is not None

    response = await client.post(
        "/api/bots/test-discord-direct",
        json={"webhook_url": "https://evil.com/x"},
        headers=auth_header(user_token),
    )

    assert response.status_code == 422, (
        f"Expected 422 for non-whitelisted webhook domain, got {response.status_code}: {response.text}"
    )


@pytest.mark.integration
async def test_discord_direct_rejects_http_scheme(client, user_token):
    """POST /api/bots/test-discord-direct returns 422 when the webhook URL
    uses http:// instead of https:// (even for a whitelisted domain)."""
    assert user_token is not None

    response = await client.post(
        "/api/bots/test-discord-direct",
        json={"webhook_url": "http://discord.com/api/webhooks/123/abc"},
        headers=auth_header(user_token),
    )

    assert response.status_code == 422, (
        f"Expected 422 for non-HTTPS scheme, got {response.status_code}: {response.text}"
    )


@pytest.mark.integration
async def test_discord_direct_accepts_whitelisted_webhook(
    client, user_token, monkeypatch
):
    """POST /api/bots/test-discord-direct returns 200 for a whitelisted
    Discord webhook domain when the outbound request is mocked to succeed."""
    assert user_token is not None

    # Patch aiohttp.ClientSession at import-site inside the router so the
    # endpoint does not perform a real network call.
    import aiohttp

    monkeypatch.setattr(
        aiohttp, "ClientSession", _make_fake_aiohttp_session(response_status=204)
    )

    response = await client.post(
        "/api/bots/test-discord-direct",
        json={"webhook_url": "https://discord.com/api/webhooks/123/abc"},
        headers=auth_header(user_token),
    )

    assert response.status_code == 200, (
        f"Expected 200 for whitelisted Discord webhook, got {response.status_code}: {response.text}"
    )
    assert response.json()["status"] == "ok"


@pytest.mark.integration
async def test_discord_direct_accepts_subdomain_of_whitelisted(
    client, user_token, monkeypatch
):
    """Subdomains of whitelisted hosts (e.g. ptb.discord.com) must be accepted."""
    assert user_token is not None

    import aiohttp

    monkeypatch.setattr(
        aiohttp, "ClientSession", _make_fake_aiohttp_session(response_status=200)
    )

    response = await client.post(
        "/api/bots/test-discord-direct",
        json={"webhook_url": "https://ptb.discord.com/api/webhooks/123/abc"},
        headers=auth_header(user_token),
    )

    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Validation regression — /api/bots/test-telegram-direct
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_telegram_direct_rejects_empty_bot_token(client, user_token):
    """Empty bot_token is rejected by Pydantic validator (min_length=1)."""
    assert user_token is not None

    response = await client.post(
        "/api/bots/test-telegram-direct",
        json={"bot_token": "", "chat_id": "123456"},
        headers=auth_header(user_token),
    )

    assert response.status_code == 422, (
        f"Expected 422 for empty bot_token, got {response.status_code}: {response.text}"
    )


@pytest.mark.integration
async def test_telegram_direct_rejects_empty_chat_id(client, user_token):
    """Empty chat_id is rejected by Pydantic validator (min_length=1)."""
    assert user_token is not None

    response = await client.post(
        "/api/bots/test-telegram-direct",
        json={"bot_token": "abc:def", "chat_id": ""},
        headers=auth_header(user_token),
    )

    assert response.status_code == 422, (
        f"Expected 422 for empty chat_id, got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# IP-Spoofing regression — /api/auth/bridge/generate
# ---------------------------------------------------------------------------


def _fake_claims():
    """Return a minimal SupabaseClaims-like object for monkeypatching."""
    from src.auth.supabase_jwt import SupabaseClaims

    return SupabaseClaims(
        sub="supabase-uuid-test-302",
        email="bridge-user@example.com",
        role="authenticated",
        app_role="user",
    )


@pytest.mark.integration
async def test_bridge_generate_ignores_xff_when_proxy_disabled(
    client, monkeypatch, caplog
):
    """When BEHIND_PROXY is not set, X-Forwarded-For must be ignored and
    the logged client IP must come from request.client.host (httpx ASGI
    transport reports 127.0.0.1)."""
    # Ensure _TRUST_PROXY is False regardless of host env
    import src.api.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module, "_TRUST_PROXY", False)

    # Stub Supabase verification so the endpoint progresses past the 401 guard
    import src.api.routers.auth_bridge as auth_bridge_module

    monkeypatch.setattr(
        auth_bridge_module,
        "verify_supabase_token",
        lambda token: _fake_claims(),
    )

    caplog.set_level(logging.INFO, logger="src.api.routers.auth_bridge")

    spoofed_ip = "203.0.113.99"
    response = await client.post(
        "/api/auth/bridge/generate",
        headers={
            "Authorization": "Bearer fake-supabase-jwt",
            "X-Forwarded-For": spoofed_ip,
        },
    )

    assert response.status_code == 200, response.text

    # The spoofed IP must NOT appear in the "Code generated" log message;
    # the real client IP (from ASGI transport: 127.0.0.1) should instead.
    generate_logs = [r.getMessage() for r in caplog.records if "Code generated" in r.getMessage()]
    assert generate_logs, "Expected 'Code generated' log entry"
    joined = " | ".join(generate_logs)
    assert spoofed_ip not in joined, (
        f"X-Forwarded-For leaked into log when BEHIND_PROXY is unset: {joined}"
    )


@pytest.mark.integration
async def test_bridge_generate_honors_xff_when_proxy_enabled(
    client, monkeypatch, caplog
):
    """When BEHIND_PROXY is truthy, the first value from X-Forwarded-For
    is used as the client IP."""
    import src.api.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module, "_TRUST_PROXY", True)

    import src.api.routers.auth_bridge as auth_bridge_module

    monkeypatch.setattr(
        auth_bridge_module,
        "verify_supabase_token",
        lambda token: _fake_claims(),
    )

    caplog.set_level(logging.INFO, logger="src.api.routers.auth_bridge")

    trusted_ip = "203.0.113.42"
    response = await client.post(
        "/api/auth/bridge/generate",
        headers={
            "Authorization": "Bearer fake-supabase-jwt",
            # Multi-hop header — only the first IP must be trusted
            "X-Forwarded-For": f"{trusted_ip}, 10.0.0.1",
        },
    )

    assert response.status_code == 200, response.text

    generate_logs = [r.getMessage() for r in caplog.records if "Code generated" in r.getMessage()]
    assert generate_logs, "Expected 'Code generated' log entry"
    joined = " | ".join(generate_logs)
    assert trusted_ip in joined, (
        f"Expected trusted X-Forwarded-For IP {trusted_ip} in log, got: {joined}"
    )


@pytest.mark.integration
async def test_bridge_generate_rejects_invalid_xff_when_proxy_enabled(
    client, monkeypatch, caplog
):
    """Even when BEHIND_PROXY is set, an invalid IP in X-Forwarded-For
    must NOT be trusted — the endpoint falls back to request.client.host."""
    import src.api.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module, "_TRUST_PROXY", True)

    import src.api.routers.auth_bridge as auth_bridge_module

    monkeypatch.setattr(
        auth_bridge_module,
        "verify_supabase_token",
        lambda token: _fake_claims(),
    )

    caplog.set_level(logging.INFO, logger="src.api.routers.auth_bridge")

    bogus_value = "not-an-ip-address"
    response = await client.post(
        "/api/auth/bridge/generate",
        headers={
            "Authorization": "Bearer fake-supabase-jwt",
            "X-Forwarded-For": bogus_value,
        },
    )

    assert response.status_code == 200, response.text

    generate_logs = [r.getMessage() for r in caplog.records if "Code generated" in r.getMessage()]
    assert generate_logs, "Expected 'Code generated' log entry"
    joined = " | ".join(generate_logs)
    assert bogus_value not in joined, (
        f"Invalid X-Forwarded-For value leaked into log: {joined}"
    )
