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
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from starlette.status import WS_1008_POLICY_VIOLATION
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.routers import websocket as ws_router
from src.auth.jwt_handler import create_access_token, create_refresh_token


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def test_app(monkeypatch):
    """FastAPI app with the ws router and an in-memory SQLite DB."""
    from src.models.database import Base, User
    from src.auth.password import hash_password
    import src.models.session as session_module

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(
                User(
                    id=1,
                    username="tester",
                    password_hash=hash_password("secret-test-pw"),
                    role="user",
                    is_active=True,
                    language="en",
                    token_version=0,
                )
            )
            await session.commit()

    import asyncio as _asyncio

    _asyncio.get_event_loop().run_until_complete(_init())

    # Point the application session module at our test DB so the
    # endpoint's ``async with get_session()`` uses it.
    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "async_session_factory", factory)

    # The ws endpoint publishes metrics and uses the connection manager —
    # swap the manager for a fresh instance so other tests can't interfere.
    from src.api.websocket.manager import ConnectionManager

    fresh_mgr = ConnectionManager()
    monkeypatch.setattr(ws_router, "ws_manager", fresh_mgr)

    app = FastAPI()
    app.include_router(ws_router.router)

    yield app

    _asyncio.get_event_loop().run_until_complete(engine.dispose())


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
