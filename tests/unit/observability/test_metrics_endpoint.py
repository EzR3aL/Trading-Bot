"""Tests for the flag-gated ``/metrics`` endpoint (#327 PR-1).

Covers the four contract points the endpoint owes its callers:

1. Flag OFF → 404 (existence not leaked).
2. Flag ON, no Authorization header → 401.
3. Flag ON, wrong credentials → 401.
4. Flag ON, correct credentials → 200, Prometheus text content-type,
   and a body that contains at least one metric name from each of the
   HTTP / Bot / Risk / Exchange groups defined in
   ``src/observability/metrics.py``.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Ensure repo root on sys.path before importing src.*
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo=")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _basic_auth_header(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app that mounts only the metrics router.

    Keeping the surface minimal keeps these tests isolated from the
    other routers' startup dependencies (DB, orchestrator, etc.).
    """
    from src.api.routers import metrics as metrics_router

    app = FastAPI()
    app.include_router(metrics_router.router)
    return app


@pytest.fixture
def metrics_app() -> FastAPI:
    return _build_app()


@pytest.fixture
def enable_prometheus(monkeypatch):
    """Turn ``PROMETHEUS_ENABLED`` on for the duration of a single test."""
    from config.settings import settings

    monkeypatch.setattr(settings.monitoring, "prometheus_enabled", True)
    yield


@pytest.fixture
def disable_prometheus(monkeypatch):
    """Force ``PROMETHEUS_ENABLED`` off for the duration of a single test."""
    from config.settings import settings

    monkeypatch.setattr(settings.monitoring, "prometheus_enabled", False)
    yield


@pytest.fixture
def configured_credentials(monkeypatch):
    """Seed the METRICS_BASIC_AUTH_* env vars with a known pair."""
    monkeypatch.setenv("METRICS_BASIC_AUTH_USER", "prom-scraper")
    monkeypatch.setenv("METRICS_BASIC_AUTH_PASSWORD", "s3cret-long-enough")
    yield ("prom-scraper", "s3cret-long-enough")


# ---------------------------------------------------------------------------
# Flag OFF → 404
# ---------------------------------------------------------------------------

async def test_flag_off_returns_404(metrics_app, disable_prometheus, configured_credentials):
    """Flag off MUST return 404, not 403 or 401 — we do not leak existence."""
    transport = ASGITransport(app=metrics_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
    assert resp.status_code == 404


async def test_flag_off_returns_404_even_with_correct_credentials(
    metrics_app, disable_prometheus, configured_credentials
):
    """Correct credentials do not bypass the flag gate."""
    user, password = configured_credentials
    transport = ASGITransport(app=metrics_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics", headers=_basic_auth_header(user, password))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Flag ON, no auth → 401
# ---------------------------------------------------------------------------

async def test_flag_on_no_auth_header_returns_401(
    metrics_app, enable_prometheus, configured_credentials
):
    transport = ASGITransport(app=metrics_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate", "").lower().startswith("basic")


async def test_flag_on_no_credentials_configured_returns_401(
    metrics_app, enable_prometheus, monkeypatch
):
    """Flag on but env vars unset → endpoint rejects every request."""
    monkeypatch.delenv("METRICS_BASIC_AUTH_USER", raising=False)
    monkeypatch.delenv("METRICS_BASIC_AUTH_PASSWORD", raising=False)

    transport = ASGITransport(app=metrics_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/metrics", headers=_basic_auth_header("someone", "something")
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Flag ON, wrong credentials → 401
# ---------------------------------------------------------------------------

async def test_flag_on_wrong_user_returns_401(
    metrics_app, enable_prometheus, configured_credentials
):
    _, password = configured_credentials
    transport = ASGITransport(app=metrics_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/metrics", headers=_basic_auth_header("wrong-user", password)
        )
    assert resp.status_code == 401


async def test_flag_on_wrong_password_returns_401(
    metrics_app, enable_prometheus, configured_credentials
):
    user, _ = configured_credentials
    transport = ASGITransport(app=metrics_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/metrics", headers=_basic_auth_header(user, "wrong-password")
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Flag ON, correct credentials → 200 + exposition body
# ---------------------------------------------------------------------------

async def test_flag_on_correct_credentials_returns_exposition_body(
    metrics_app, enable_prometheus, configured_credentials
):
    user, password = configured_credentials
    transport = ASGITransport(app=metrics_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics", headers=_basic_auth_header(user, password))

    assert resp.status_code == 200

    # Prometheus text exposition format content-type. The exact
    # ``version=`` value is chosen by the installed ``prometheus_client``
    # (0.0.4 on client ~0.20, 1.0.0 on client >=0.21), so we only assert
    # the stable prefix and that a version negotiation token is present.
    content_type = resp.headers.get("content-type", "")
    assert "text/plain" in content_type
    assert "version=" in content_type

    body = resp.text
    # At least one metric name from each group must show up in the
    # exposition body (HELP/TYPE lines count).
    assert "http_requests_total" in body                   # HTTP group
    assert "bot_signals_generated_total" in body           # Bot group
    assert "risk_trade_gate_decisions_total" in body       # Risk group
    assert "exchange_api_requests_total" in body           # Exchange group
