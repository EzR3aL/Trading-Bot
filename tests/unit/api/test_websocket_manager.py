"""
Tests for the WebSocket ConnectionManager.

Covers connect/disconnect, per-user broadcasting, broadcast-all,
connection limits, dead connection cleanup, and concurrent operations.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from src.api.websocket.manager import ConnectionManager, MAX_CONNECTIONS_PER_USER, MAX_TOTAL_CONNECTIONS


def _make_ws() -> AsyncMock:
    """Create a mock WebSocket object with send_text."""
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


# ── Connect / Disconnect ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_adds_connection():
    mgr = ConnectionManager()
    ws = _make_ws()
    result = await mgr.connect(ws, user_id=1)
    assert result is True
    assert mgr.total_connections == 1


@pytest.mark.asyncio
async def test_disconnect_removes_connection():
    mgr = ConnectionManager()
    ws = _make_ws()
    await mgr.connect(ws, user_id=1)
    await mgr.disconnect(ws, user_id=1)
    assert mgr.total_connections == 0


@pytest.mark.asyncio
async def test_disconnect_nonexistent_user_is_noop():
    mgr = ConnectionManager()
    ws = _make_ws()
    # Should not raise
    await mgr.disconnect(ws, user_id=999)
    assert mgr.total_connections == 0


@pytest.mark.asyncio
async def test_disconnect_removes_user_entry_when_empty():
    mgr = ConnectionManager()
    ws = _make_ws()
    await mgr.connect(ws, user_id=1)
    await mgr.disconnect(ws, user_id=1)
    # Internal dict should not keep empty sets
    assert 1 not in mgr._connections


# ── Multiple Connections Per User ─────────────────────────────────────


@pytest.mark.asyncio
async def test_multiple_connections_per_user():
    mgr = ConnectionManager()
    sockets = [_make_ws() for _ in range(3)]
    for ws in sockets:
        result = await mgr.connect(ws, user_id=1)
        assert result is True
    assert mgr.total_connections == 3


@pytest.mark.asyncio
async def test_disconnect_one_of_multiple_keeps_others():
    mgr = ConnectionManager()
    ws1, ws2 = _make_ws(), _make_ws()
    await mgr.connect(ws1, user_id=1)
    await mgr.connect(ws2, user_id=1)
    await mgr.disconnect(ws1, user_id=1)
    assert mgr.total_connections == 1
    # User entry should still exist
    assert 1 in mgr._connections


# ── Broadcast to User ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_broadcast_to_user_sends_to_all_user_connections():
    mgr = ConnectionManager()
    ws1, ws2 = _make_ws(), _make_ws()
    await mgr.connect(ws1, user_id=1)
    await mgr.connect(ws2, user_id=1)

    await mgr.broadcast_to_user(1, "trade_opened", {"symbol": "BTCUSDT"})

    expected = json.dumps({"type": "trade_opened", "data": {"symbol": "BTCUSDT"}})
    ws1.send_text.assert_awaited_once_with(expected)
    ws2.send_text.assert_awaited_once_with(expected)


@pytest.mark.asyncio
async def test_broadcast_to_user_does_not_send_to_other_users():
    mgr = ConnectionManager()
    ws_user1, ws_user2 = _make_ws(), _make_ws()
    await mgr.connect(ws_user1, user_id=1)
    await mgr.connect(ws_user2, user_id=2)

    await mgr.broadcast_to_user(1, "bot_started", {})

    ws_user1.send_text.assert_awaited_once()
    ws_user2.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_broadcast_to_nonexistent_user_is_noop():
    mgr = ConnectionManager()
    # Should not raise
    await mgr.broadcast_to_user(999, "event", {"foo": "bar"})


# ── Broadcast All ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_broadcast_all_sends_to_every_connection():
    mgr = ConnectionManager()
    ws1, ws2, ws3 = _make_ws(), _make_ws(), _make_ws()
    await mgr.connect(ws1, user_id=1)
    await mgr.connect(ws2, user_id=1)
    await mgr.connect(ws3, user_id=2)

    await mgr.broadcast_all("system_update", {"version": "4.17"})

    expected = json.dumps({"type": "system_update", "data": {"version": "4.17"}})
    ws1.send_text.assert_awaited_once_with(expected)
    ws2.send_text.assert_awaited_once_with(expected)
    ws3.send_text.assert_awaited_once_with(expected)


# ── Connection Limits ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_per_user_connection_limit():
    mgr = ConnectionManager()
    sockets = []
    for _ in range(MAX_CONNECTIONS_PER_USER):
        ws = _make_ws()
        result = await mgr.connect(ws, user_id=1)
        assert result is True
        sockets.append(ws)

    # Next connection for same user should be rejected
    extra_ws = _make_ws()
    result = await mgr.connect(extra_ws, user_id=1)
    assert result is False
    assert mgr.total_connections == MAX_CONNECTIONS_PER_USER


@pytest.mark.asyncio
async def test_total_connection_limit():
    mgr = ConnectionManager()
    # Fill up to MAX_TOTAL_CONNECTIONS using different users
    for i in range(MAX_TOTAL_CONNECTIONS):
        ws = _make_ws()
        result = await mgr.connect(ws, user_id=i)
        assert result is True

    # Next connection should be rejected regardless of user
    extra_ws = _make_ws()
    result = await mgr.connect(extra_ws, user_id=MAX_TOTAL_CONNECTIONS + 1)
    assert result is False
    assert mgr.total_connections == MAX_TOTAL_CONNECTIONS


# ── Dead Connection Handling ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_broadcast_to_user_removes_dead_connections():
    mgr = ConnectionManager()
    ws_good = _make_ws()
    ws_dead = _make_ws()
    ws_dead.send_text.side_effect = RuntimeError("Connection closed")

    await mgr.connect(ws_good, user_id=1)
    await mgr.connect(ws_dead, user_id=1)
    assert mgr.total_connections == 2

    await mgr.broadcast_to_user(1, "event", {})

    # Dead connection should have been cleaned up
    assert mgr.total_connections == 1
    ws_good.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_broadcast_all_removes_dead_connections():
    mgr = ConnectionManager()
    ws_good = _make_ws()
    ws_dead = _make_ws()
    ws_dead.send_text.side_effect = RuntimeError("Connection closed")

    await mgr.connect(ws_good, user_id=1)
    await mgr.connect(ws_dead, user_id=2)
    assert mgr.total_connections == 2

    await mgr.broadcast_all("event", {})

    # Dead connection for user 2 should be removed
    assert mgr.total_connections == 1
    ws_good.send_text.assert_awaited_once()


# ── Concurrent Connect / Disconnect ───────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_connect_disconnect():
    """Multiple concurrent connect/disconnect ops should not corrupt state."""
    mgr = ConnectionManager()
    sockets = [_make_ws() for _ in range(20)]

    # Connect all concurrently
    results = await asyncio.gather(
        *[mgr.connect(ws, user_id=i % 5) for i, ws in enumerate(sockets)]
    )
    assert all(r is True for r in results)
    assert mgr.total_connections == 20

    # Disconnect all concurrently
    await asyncio.gather(
        *[mgr.disconnect(ws, user_id=i % 5) for i, ws in enumerate(sockets)]
    )
    assert mgr.total_connections == 0


@pytest.mark.asyncio
async def test_concurrent_connect_respects_per_user_limit():
    """Concurrent connects for the same user should respect the limit."""
    mgr = ConnectionManager()
    # Try to connect more than the limit concurrently for the same user
    sockets = [_make_ws() for _ in range(MAX_CONNECTIONS_PER_USER + 5)]
    results = await asyncio.gather(
        *[mgr.connect(ws, user_id=1) for ws in sockets]
    )
    accepted = sum(1 for r in results if r is True)
    rejected = sum(1 for r in results if r is False)

    assert accepted == MAX_CONNECTIONS_PER_USER
    assert rejected == 5
    assert mgr.total_connections == MAX_CONNECTIONS_PER_USER


# ── Properties ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_total_connections_property():
    mgr = ConnectionManager()
    assert mgr.total_connections == 0

    await mgr.connect(_make_ws(), user_id=1)
    await mgr.connect(_make_ws(), user_id=1)
    await mgr.connect(_make_ws(), user_id=2)
    assert mgr.total_connections == 3


@pytest.mark.asyncio
async def test_user_count():
    """Verify we can determine how many distinct users are connected."""
    mgr = ConnectionManager()
    await mgr.connect(_make_ws(), user_id=1)
    await mgr.connect(_make_ws(), user_id=1)
    await mgr.connect(_make_ws(), user_id=2)
    await mgr.connect(_make_ws(), user_id=3)

    # user_count = number of keys in _connections
    assert len(mgr._connections) == 3
