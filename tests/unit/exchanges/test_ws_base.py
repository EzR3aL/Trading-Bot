"""Unit tests for :class:`ExchangeWebSocketClient` (#216).

Covers:
* Reconnect backoff schedule progression — ``1, 2, 4, 8, 30, 30, …``.
* ``is_connected`` transitions across connect / drop / reconnect.
* Parse-error isolation (one bad frame doesn't kill the run loop).

We don't speak to any real exchange here. A ``_FakeTransport`` double
drives ``_read_once`` to return scripted messages or raise
``ConnectionError`` so the reconnect path is exercised deterministically.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, List, Optional

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.websockets.base import ExchangeWebSocketClient


class _FakeClient(ExchangeWebSocketClient):
    """Scriptable subclass — connects/reads from canned lists."""

    def __init__(self, *, scripted_reads: List[Any], fail_connect_times: int = 0,
                 on_event=None, on_reconnect=None) -> None:
        async def _noop(user_id, exchange, event_type, payload):
            pass
        super().__init__(
            user_id=1,
            exchange="fake",
            on_event=on_event or _noop,
            on_reconnect=on_reconnect,
        )
        self._scripted_reads = list(scripted_reads)
        self._fail_connect_times = fail_connect_times
        self.connect_attempts = 0
        self.subscribe_calls = 0
        self.parsed: List[Any] = []

    async def _connect_transport(self) -> Any:
        self.connect_attempts += 1
        if self.connect_attempts <= self._fail_connect_times:
            raise ConnectionError("scripted connect failure")
        return object()

    async def _subscribe(self) -> None:
        self.subscribe_calls += 1

    async def _read_once(self) -> Optional[Any]:
        if not self._scripted_reads:
            # Park forever — caller cancels us.
            await asyncio.sleep(3600)
            return None
        value = self._scripted_reads.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def _parse_message(self, raw: Any):
        self.parsed.append(raw)
        if raw == "_bad_":
            raise ValueError("boom")
        if raw == "_drop_":
            return None
        return {"event_type": "plan_triggered", "payload": {"symbol": raw}}


@pytest.mark.asyncio
async def test_is_connected_false_before_connect() -> None:
    """A fresh client reports is_connected=False before connect()."""
    client = _FakeClient(scripted_reads=[])
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_is_connected_transitions_on_connect_and_disconnect() -> None:
    """connect() flips is_connected to True, disconnect() flips it back."""
    client = _FakeClient(scripted_reads=[])
    await client.connect()
    assert client.is_connected is True
    await client.disconnect()
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_backoff_schedule_matches_1_2_4_8_30_cap() -> None:
    """_backoff_delay walks 1s, 2s, 4s, 8s then caps at 30s for every later retry."""
    delays = [_FakeClient._backoff_delay(i) for i in range(7)]
    assert delays[:4] == [1.0, 2.0, 4.0, 8.0]
    # 5th and onwards cap at 30s.
    assert delays[4] == 30.0
    assert delays[5] == 30.0
    assert delays[6] == 30.0


@pytest.mark.asyncio
async def test_run_forever_reconnects_after_connection_loss(monkeypatch) -> None:
    """After a transport ConnectionError, client reconnects + keeps reading.

    We inject a near-zero sleep onto the base module so the backoff is
    observed but doesn't actually wait. Assertion target:
    _connect_transport is called twice (initial + reconnect) and
    on_reconnect fires exactly once.
    """
    reconnect_calls: List[tuple] = []

    async def _on_reconnect(user_id, exchange):
        reconnect_calls.append((user_id, exchange))

    client = _FakeClient(
        scripted_reads=[
            "BTCUSDT",                 # 1st frame — happy path
            ConnectionError("drop"),   # 2nd — transport closed
            "ETHUSDT",                 # 3rd — after reconnect
        ],
        on_reconnect=_on_reconnect,
    )

    recorded_delays: List[float] = []

    def _fast_backoff(attempt: int) -> float:
        delay = ExchangeWebSocketClient._backoff_delay(attempt)
        recorded_delays.append(delay)
        return 0.0  # skip the actual sleep window — keep reading

    # Override only the backoff calculation — the read loop still issues
    # asyncio.sleep(0.0) which is effectively a cooperative yield.
    monkeypatch.setattr(client, "_backoff_delay", _fast_backoff)

    task = client.start()
    # Wait up to ~2s of real time for the reconnect cycle to land.
    for _ in range(200):
        if client.connect_attempts >= 2 and len(reconnect_calls) >= 1:
            break
        await asyncio.sleep(0.01)

    await client.disconnect()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert client.connect_attempts >= 2
    assert reconnect_calls == [(1, "fake")]
    # After the first drop, backoff computed 1.0s (first entry in schedule).
    assert 1.0 in recorded_delays


@pytest.mark.asyncio
async def test_run_forever_handles_parse_error_without_crashing() -> None:
    """A parse exception is swallowed — the loop keeps consuming messages."""
    events: List[tuple] = []

    async def _on_event(user_id, exchange, event_type, payload):
        events.append((event_type, payload.get("symbol")))

    client = _FakeClient(
        scripted_reads=["_bad_", "BTCUSDT"],
        on_event=_on_event,
    )

    task = client.start()
    for _ in range(200):
        if events:
            break
        await asyncio.sleep(0.01)

    await client.disconnect()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert events == [("plan_triggered", "BTCUSDT")]
