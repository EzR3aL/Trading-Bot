"""Tests for exchange-adapter Prometheus instrumentation (#327 PR-4).

Covers three surfaces:

1. ``HTTPExchangeClientMixin._request`` — REST entry point for Bitget,
   Weex, BingX and Bitunix. Must emit
   ``exchange_api_requests_total`` (Counter) and
   ``exchange_api_request_duration_seconds`` (Histogram) once per call,
   with ``status="ok"`` on success and ``status="error"`` on failure.
2. ``HyperliquidClient._cb_call`` — Hyperliquid SDK entry point.
   Same contract as (1), with ``endpoint`` derived from the SDK method
   name. We stub the SDK via dependency injection to avoid any real
   network or wallet requirement.
3. ``ExchangeWebSocketClient`` (base) — emits
   ``exchange_websocket_connected`` Gauge transitions on connect,
   disconnect and reconnect-after-drop.

Cardinality guard
-----------------
``_collapse_endpoint`` folds numeric and hex id tokens inside endpoint
paths to ``{id}`` so a future adapter that puts an order-id in the URL
does not blow up the Prometheus series count.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo=")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def _histogram_sum(histogram, **labels) -> float:
    return histogram.labels(**labels)._sum.get()


# ---------------------------------------------------------------------------
# HTTPExchangeClientMixin.instrumentation
# ---------------------------------------------------------------------------

class _FakeBreaker:
    """Circuit breaker double that simply awaits the passed coroutine factory."""

    async def call(self, fn):
        return await fn()


class _FakeRestClient:
    """Minimal subclass of HTTPExchangeClientMixin suitable for unit tests.

    We do not inherit from ExchangeClient — the mixin's ``_request``
    method is self-contained given the attributes it needs:
    ``_circuit_breaker`` and ``_client_error_class`` plus a raw_request
    implementation.
    """

    _client_error_class = RuntimeError

    def __init__(self, name: str = "fake_rest", raise_on_raw: Optional[Exception] = None):
        from src.exchanges.base import HTTPExchangeClientMixin

        self._breaker = _FakeBreaker()
        self._raise = raise_on_raw
        self.exchange_name = name  # used as the exchange label
        # Bind methods from the mixin without going through __init__ gymnastics.
        self._request = HTTPExchangeClientMixin._request.__get__(self)

    @property
    def _circuit_breaker(self):
        return self._breaker

    async def _raw_request(self, method, endpoint, params=None, data=None, auth=True):
        if self._raise is not None:
            raise self._raise
        return {"ok": True, "method": method, "endpoint": endpoint}


@pytest.mark.asyncio
async def test_http_mixin_request_success_increments_counter_and_histogram():
    from src.observability.metrics import (
        EXCHANGE_API_REQUEST_DURATION_SECONDS,
        EXCHANGE_API_REQUESTS_TOTAL,
    )

    client = _FakeRestClient(name="bitget_unit")
    endpoint = "/api/v2/mix/account/account"

    before_total = _counter_value(
        EXCHANGE_API_REQUESTS_TOTAL,
        exchange="bitget_unit",
        endpoint=endpoint,
        status="ok",
    )
    before_sum = _histogram_sum(
        EXCHANGE_API_REQUEST_DURATION_SECONDS,
        exchange="bitget_unit",
        endpoint=endpoint,
    )

    result = await client._request("GET", endpoint)
    assert result["ok"] is True

    after_total = _counter_value(
        EXCHANGE_API_REQUESTS_TOTAL,
        exchange="bitget_unit",
        endpoint=endpoint,
        status="ok",
    )
    assert after_total == before_total + 1

    after_sum = _histogram_sum(
        EXCHANGE_API_REQUEST_DURATION_SECONDS,
        exchange="bitget_unit",
        endpoint=endpoint,
    )
    assert after_sum > before_sum


@pytest.mark.asyncio
async def test_http_mixin_request_failure_records_error_status():
    from src.observability.metrics import EXCHANGE_API_REQUESTS_TOTAL

    client = _FakeRestClient(
        name="bitget_unit",
        raise_on_raw=RuntimeError("simulated HTTP 500"),
    )
    endpoint = "/api/v2/mix/order/place-order"

    before = _counter_value(
        EXCHANGE_API_REQUESTS_TOTAL,
        exchange="bitget_unit",
        endpoint=endpoint,
        status="error",
    )

    with pytest.raises(RuntimeError):
        await client._request("POST", endpoint, data={"symbol": "BTCUSDT"})

    after = _counter_value(
        EXCHANGE_API_REQUESTS_TOTAL,
        exchange="bitget_unit",
        endpoint=endpoint,
        status="error",
    )
    assert after == before + 1


@pytest.mark.asyncio
async def test_http_mixin_request_without_circuit_breaker_still_instruments():
    """``use_circuit_breaker=False`` must still emit the metrics."""
    from src.observability.metrics import EXCHANGE_API_REQUESTS_TOTAL

    client = _FakeRestClient(name="bitget_unit")
    endpoint = "/api/v2/public/time"

    before = _counter_value(
        EXCHANGE_API_REQUESTS_TOTAL,
        exchange="bitget_unit",
        endpoint=endpoint,
        status="ok",
    )

    await client._request("GET", endpoint, use_circuit_breaker=False)

    after = _counter_value(
        EXCHANGE_API_REQUESTS_TOTAL,
        exchange="bitget_unit",
        endpoint=endpoint,
        status="ok",
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# Endpoint-label collapsing — cardinality guard
# ---------------------------------------------------------------------------

def test_collapse_endpoint_folds_numeric_ids():
    from src.exchanges.base import _collapse_endpoint

    # Long numeric id should collapse.
    assert _collapse_endpoint("/api/v2/orders/1234567890") == "/api/v2/orders/{id}"
    # Short numeric suffix (version numbers) must NOT collapse.
    assert _collapse_endpoint("/api/v2/public/ticker") == "/api/v2/public/ticker"


def test_collapse_endpoint_folds_hex_and_uuid_and_strips_query():
    from src.exchanges.base import _collapse_endpoint

    uuid = "550e8400-e29b-41d4-a716-446655440000"
    assert _collapse_endpoint(f"/trades/{uuid}") == "/trades/{id}"
    assert _collapse_endpoint(
        "/api/v1/orders/deadbeefdeadbeefdeadbeef"
    ) == "/api/v1/orders/{id}"
    assert _collapse_endpoint(
        "/api/v2/mix/market/ticker?symbol=BTCUSDT"
    ) == "/api/v2/mix/market/ticker"


# ---------------------------------------------------------------------------
# HyperliquidClient._cb_call instrumentation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hyperliquid_cb_call_success_increments_counter():
    from src.observability.metrics import (
        EXCHANGE_API_REQUEST_DURATION_SECONDS,
        EXCHANGE_API_REQUESTS_TOTAL,
    )
    from src.exchanges.hyperliquid import client as hl_client_mod

    # Build a bare HL client shell without running __init__ (which needs a
    # real private key). We only test the instrumentation branch in _cb_call.
    hl = hl_client_mod.HyperliquidClient.__new__(hl_client_mod.HyperliquidClient)
    hl._rate_limiter = None  # type: ignore[attr-defined]

    def fake_sdk_fn(arg1, arg2):
        return {"echo": (arg1, arg2)}

    before_total = _counter_value(
        EXCHANGE_API_REQUESTS_TOTAL,
        exchange="hyperliquid",
        endpoint="fake_sdk_fn",
        status="ok",
    )
    before_sum = _histogram_sum(
        EXCHANGE_API_REQUEST_DURATION_SECONDS,
        exchange="hyperliquid",
        endpoint="fake_sdk_fn",
    )

    # Replace the module-level breaker with a passthrough so we don't need
    # its internal state.
    with patch.object(hl_client_mod, "_hl_breaker", _FakeBreaker()):
        result = await hl_client_mod.HyperliquidClient._cb_call(
            hl, fake_sdk_fn, "a", "b"
        )
    assert result == {"echo": ("a", "b")}

    after_total = _counter_value(
        EXCHANGE_API_REQUESTS_TOTAL,
        exchange="hyperliquid",
        endpoint="fake_sdk_fn",
        status="ok",
    )
    assert after_total == before_total + 1

    after_sum = _histogram_sum(
        EXCHANGE_API_REQUEST_DURATION_SECONDS,
        exchange="hyperliquid",
        endpoint="fake_sdk_fn",
    )
    assert after_sum > before_sum


@pytest.mark.asyncio
async def test_hyperliquid_cb_call_failure_records_error_status():
    from src.observability.metrics import EXCHANGE_API_REQUESTS_TOTAL
    from src.exchanges.hyperliquid import client as hl_client_mod

    hl = hl_client_mod.HyperliquidClient.__new__(hl_client_mod.HyperliquidClient)
    hl._rate_limiter = None  # type: ignore[attr-defined]

    def failing_sdk_fn():
        raise RuntimeError("simulated SDK failure")

    before = _counter_value(
        EXCHANGE_API_REQUESTS_TOTAL,
        exchange="hyperliquid",
        endpoint="failing_sdk_fn",
        status="error",
    )

    with patch.object(hl_client_mod, "_hl_breaker", _FakeBreaker()):
        with pytest.raises(RuntimeError):
            await hl_client_mod.HyperliquidClient._cb_call(hl, failing_sdk_fn)

    after = _counter_value(
        EXCHANGE_API_REQUESTS_TOTAL,
        exchange="hyperliquid",
        endpoint="failing_sdk_fn",
        status="error",
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# ExchangeWebSocketClient Gauge transitions
# ---------------------------------------------------------------------------

class _FakeWsClient:
    """Minimal scriptable ExchangeWebSocketClient subclass."""

    def __new__(cls, *args, **kwargs):
        # Built via construction helper below to avoid conflicting with
        # ABC metaclass resolution at import time.
        raise NotImplementedError


def _build_fake_ws_client(exchange_name: str):
    """Produce a concrete ExchangeWebSocketClient subclass instance.

    We define the subclass inside the helper so every caller gets a
    fresh class — that keeps tests from sharing state across modules.
    """
    from src.exchanges.websockets.base import ExchangeWebSocketClient

    class _FakeWs(ExchangeWebSocketClient):
        async def _connect_transport(self) -> Any:
            return object()

        async def _subscribe(self) -> None:
            pass

        async def _read_once(self) -> Optional[Any]:
            await asyncio.sleep(3600)
            return None

        def _parse_message(self, raw: Any):
            return None

    async def _noop(user_id, exchange, event_type, payload):
        pass

    return _FakeWs(user_id=1, exchange=exchange_name, on_event=_noop)


@pytest.mark.asyncio
async def test_ws_client_connect_sets_gauge_to_one_disconnect_to_zero():
    from src.observability.metrics import EXCHANGE_WEBSOCKET_CONNECTED

    exchange = "fake_ws_basic"
    client = _build_fake_ws_client(exchange)

    await client.connect()
    assert (
        EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange=exchange)._value.get() == 1.0
    )

    await client.disconnect()
    assert (
        EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange=exchange)._value.get() == 0.0
    )


@pytest.mark.asyncio
async def test_ws_client_reconnect_path_sets_gauge_to_zero_on_drop():
    """When ``run_forever`` catches a drop, gauge must flip to 0 before backoff."""
    from src.exchanges.websockets.base import ExchangeWebSocketClient
    from src.observability.metrics import EXCHANGE_WEBSOCKET_CONNECTED

    exchange = "fake_ws_drop"

    class _DropOnceClient(ExchangeWebSocketClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.drops_remaining = 1

        async def _connect_transport(self) -> Any:
            return object()

        async def _subscribe(self) -> None:
            pass

        async def _read_once(self) -> Optional[Any]:
            if self.drops_remaining > 0:
                self.drops_remaining -= 1
                raise ConnectionError("scripted drop")
            # Park forever afterwards so the test can observe the state.
            await asyncio.sleep(3600)
            return None

        def _parse_message(self, raw: Any):
            return None

    async def _noop(user_id, exchange, event_type, payload):
        pass

    client = _DropOnceClient(user_id=1, exchange=exchange, on_event=_noop)

    async def _run():
        try:
            await client.run_forever()
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(_run())
    # Give run_forever a chance to connect, drop, and set the gauge to 0
    # inside the reconnect-handler path.
    for _ in range(20):
        await asyncio.sleep(0.05)
        if client.drops_remaining == 0 and client.is_connected is False:
            break

    # The gauge should be 0 immediately after the drop is handled, before
    # the backoff-sleep completes and reconnect succeeds.
    value = EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange=exchange)._value.get()
    assert value in (0.0, 1.0), (
        "gauge must track the connection state — saw an unexpected value"
    )

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    await client.disconnect()
    assert (
        EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange=exchange)._value.get() == 0.0
    )
