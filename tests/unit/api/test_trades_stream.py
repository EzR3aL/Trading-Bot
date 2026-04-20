"""Unit tests for the SSE trades stream (Issue #216, Section 2.2).

Covered behaviours:
1. Publishing an event delivers it to a subscriber registered for the
   same user_id.
2. An idle stream generator emits a ``: keepalive`` frame within one
   heartbeat interval.
3. Events are scoped per-user — a subscriber for user B never sees
   events published for user A.

Tests target the event-bus + the ``_event_stream`` generator directly
rather than driving the endpoint through ``httpx.ASGITransport``.
ASGITransport does not reliably pump streaming responses under asyncio
(it batches chunks until the generator exits), so exercising the
underlying pieces gives us deterministic assertions without timing
flake.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.api.routers import trades_stream  # noqa: E402
from src.bot.event_bus import (  # noqa: E402
    EVENT_TRADE_CLOSED,
    EVENT_TRADE_OPENED,
    EventBus,
    get_event_bus,
    reset_event_bus,
)


class _StubRequest:
    """Minimal ``Request`` stand-in with a toggleable ``is_disconnected``."""

    def __init__(self) -> None:
        self._disconnected = False

    def disconnect(self) -> None:
        self._disconnected = True

    async def is_disconnected(self) -> bool:
        return self._disconnected


@pytest.fixture(autouse=True)
def _isolated_bus():
    """Every test gets a pristine bus — no cross-test state leakage."""
    reset_event_bus()
    yield
    reset_event_bus()


@pytest.mark.asyncio
async def test_publish_delivers_event_to_same_user_subscriber():
    """A published event must be delivered to a subscriber scoped to the same user."""
    bus: EventBus = get_event_bus()
    queue = bus.register(user_id=7)

    await bus.publish(
        EVENT_TRADE_OPENED,
        user_id=7,
        trade_id=42,
        data={"symbol": "BTC-USDT", "side": "long"},
    )

    # Queue receive must not block if the event was enqueued correctly.
    raw = await asyncio.wait_for(queue.get(), timeout=1.0)
    payload = json.loads(raw)

    assert payload["event"] == EVENT_TRADE_OPENED
    assert payload["trade_id"] == 42
    assert payload["data"]["symbol"] == "BTC-USDT"
    assert payload["timestamp"]  # ISO 8601 string, non-empty

    bus.unregister(user_id=7, queue=queue)


@pytest.mark.asyncio
async def test_idle_stream_emits_keepalive(monkeypatch):
    """With no events the generator must emit a ``: keepalive`` comment frame."""
    monkeypatch.setattr(trades_stream, "KEEPALIVE_INTERVAL_SECONDS", 0.05)

    request = _StubRequest()
    generator = trades_stream._event_stream(request, user_id=99)

    # First frame is the "connected" handshake.
    first = await asyncio.wait_for(generator.__anext__(), timeout=1.0)
    assert first == b": connected\n\n"

    # Next frame must be a keepalive because no one published anything.
    second = await asyncio.wait_for(generator.__anext__(), timeout=1.0)
    assert second == b": keepalive\n\n"

    # Signal disconnection and drain the generator so cleanup runs.
    request.disconnect()
    with pytest.raises(StopAsyncIteration):
        while True:
            await generator.__anext__()


@pytest.mark.asyncio
async def test_events_are_scoped_to_owning_user(monkeypatch):
    """Bob (user 20) must not receive events published for Alice (user 10)."""
    monkeypatch.setattr(trades_stream, "KEEPALIVE_INTERVAL_SECONDS", 0.05)

    bus: EventBus = get_event_bus()
    request = _StubRequest()
    generator = trades_stream._event_stream(request, user_id=20)

    # Consume the handshake frame so the generator is in its main loop
    # with Bob's subscriber queue registered on the bus.
    first = await asyncio.wait_for(generator.__anext__(), timeout=1.0)
    assert first == b": connected\n\n"

    # Publish only for Alice. Bob's generator must NOT yield a data frame.
    await bus.publish(
        EVENT_TRADE_CLOSED,
        user_id=10,
        trade_id=500,
        data={"symbol": "ETH-USDT"},
    )

    # The next frame Bob's generator yields must be the keepalive — the
    # data: path would indicate a cross-user leak.
    next_frame = await asyncio.wait_for(generator.__anext__(), timeout=1.0)
    assert next_frame.startswith(b":"), (
        "Bob must not receive Alice's events; got data frame instead: "
        f"{next_frame!r}"
    )
    assert not next_frame.startswith(b"data:")

    # Also confirm Alice DOES receive her event via a separate subscriber.
    alice_queue = bus.register(user_id=10)
    await bus.publish(
        EVENT_TRADE_CLOSED,
        user_id=10,
        trade_id=501,
        data={"symbol": "ETH-USDT"},
    )
    alice_raw = await asyncio.wait_for(alice_queue.get(), timeout=1.0)
    alice_payload = json.loads(alice_raw)
    assert alice_payload["trade_id"] == 501

    # Cleanup
    bus.unregister(user_id=10, queue=alice_queue)
    request.disconnect()
    with pytest.raises(StopAsyncIteration):
        while True:
            await generator.__anext__()
