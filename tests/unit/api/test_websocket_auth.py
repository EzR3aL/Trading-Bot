"""Tests for /api/ws authentication (SEC-013).

Covers:
- Missing token → close 1008 before handshake is accepted by the client
- Invalid token → close 1008
- Wrong token type (refresh instead of access) → close 1008
- Valid token → connection is accepted

Uses starlette.testclient.TestClient for synchronous WebSocket testing
(httpx has no native WS support, and the project has no ``httpx-ws``
dependency).
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest
from fastapi import FastAPI
from starlette.status import WS_1008_POLICY_VIOLATION
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.routers import websocket as ws_router
from src.auth.jwt_handler import create_access_token, create_refresh_token


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def test_app(monkeypatch):
    """FastAPI app with the ws router and a mocked ``get_session``.

    The endpoint calls ``async with get_session() as db: db.execute(...)``
    to look up the user. Instead of spinning up a real aiosqlite engine
    per test — which previously caused flaky ``thread.join()`` hangs in
    CI when the starlette portal's loop disposed connections that were
    bound to the fixture's own loop — we patch ``get_session`` with a
    tiny stub that yields a fake session. User lookups for ``id=1``
    return an active in-memory user; any other id returns ``None`` so
    the "unknown user" path closes with 1008.
    """
    active_user = SimpleNamespace(
        id=1,
        username="tester",
        role="user",
        is_active=True,
        token_version=0,
        is_deleted=False,
        language="en",
    )

    def _fake_execute(stmt):
        # The endpoint passes ``select(User).where(User.id == user_id)``.
        # Extract the literal ``user_id`` from the compiled WHERE clause
        # so the stub can return the right row.
        try:
            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            sql = str(compiled)
        except Exception:
            sql = ""
        user = active_user if "id = 1" in sql else None
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=user)
        return result

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(side_effect=_fake_execute)

    @asynccontextmanager
    async def fake_get_session():
        yield fake_session

    monkeypatch.setattr(ws_router, "get_session", fake_get_session)

    # The ws endpoint publishes metrics and uses the connection manager —
    # swap the manager for a fresh instance so other tests can't interfere.
    from src.api.websocket.manager import ConnectionManager

    fresh_mgr = ConnectionManager()
    monkeypatch.setattr(ws_router, "ws_manager", fresh_mgr)

    app = FastAPI()
    app.include_router(ws_router.router)

    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


# ── Auth failure paths — close 1008 ──────────────────────────────────


def test_ws_connect_without_token_is_rejected(client):
    """No ``?token=`` and no cookie → close 1008."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ws"):
            pass
    assert exc.value.code == WS_1008_POLICY_VIOLATION


def test_ws_connect_with_invalid_token_is_rejected(client):
    """Malformed / unsigned JWT → close 1008."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ws?token=not-a-valid-jwt"):
            pass
    assert exc.value.code == WS_1008_POLICY_VIOLATION


def test_ws_connect_with_refresh_token_is_rejected(client):
    """Refresh token must NOT be accepted for WS auth — only ``access``."""
    refresh = create_refresh_token({"sub": "1", "role": "user"})
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/ws?token={refresh}"):
            pass
    assert exc.value.code == WS_1008_POLICY_VIOLATION


def test_ws_connect_with_unknown_user_is_rejected(client):
    """Valid signature but user does not exist → close 1008."""
    token = create_access_token({"sub": "99999", "role": "user", "tv": 0})
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/ws?token={token}"):
            pass
    assert exc.value.code == WS_1008_POLICY_VIOLATION


# ── Auth success path ─────────────────────────────────────────────────


def test_ws_connect_with_valid_token_succeeds(client):
    """Valid access token → handshake accepted, server sends 'authenticated'."""
    token = create_access_token({"sub": "1", "role": "user", "tv": 0})
    with client.websocket_connect(f"/api/ws?token={token}") as ws:
        msg = ws.receive_text()
        assert msg == "authenticated"


def test_ws_ping_pong_after_auth(client):
    token = create_access_token({"sub": "1", "role": "user", "tv": 0})
    with client.websocket_connect(f"/api/ws?token={token}") as ws:
        ws.receive_text()  # "authenticated"
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
