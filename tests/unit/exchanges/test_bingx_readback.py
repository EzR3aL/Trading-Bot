"""Tests for BingX risk-state readback methods (#191).

Covers ``get_position_tpsl``, ``get_trailing_stop``, and
``get_close_reason_from_history`` by mocking ``client._request``. These are
the source-of-truth probes used by RiskStateManager (#190).
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.base import (
    CloseReasonSnapshot,
    PositionTpSlSnapshot,
    TrailingStopSnapshot,
)
from src.exchanges.bingx.client import BingXClient


@pytest.fixture
def client():
    return BingXClient(api_key="test", api_secret="test", demo_mode=True)


# ==================== get_position_tpsl ====================


@pytest.mark.asyncio
async def test_get_position_tpsl_returns_both_tp_and_sl(client):
    """Active TP+SL reduce-only orders → populated snapshot."""

    async def mock_request(method, endpoint, **kwargs):
        assert "openOrders" in endpoint
        return {
            "orders": [
                {
                    "orderId": "tp-1",
                    "symbol": "BTC-USDT",
                    "type": "TAKE_PROFIT_MARKET",
                    "positionSide": "LONG",
                    "stopPrice": "72500.5",
                    "workingType": "MARK_PRICE",
                },
                {
                    "orderId": "sl-1",
                    "symbol": "BTC-USDT",
                    "type": "STOP_MARKET",
                    "positionSide": "LONG",
                    "stopPrice": "68000.0",
                    "workingType": "MARK_PRICE",
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_position_tpsl("BTC-USDT", "long")

    assert isinstance(snap, PositionTpSlSnapshot)
    assert snap.symbol == "BTC-USDT"
    assert snap.side == "long"
    assert snap.tp_price == 72500.5
    assert snap.tp_order_id == "tp-1"
    assert snap.tp_trigger_type == "MARK_PRICE"
    assert snap.sl_price == 68000.0
    assert snap.sl_order_id == "sl-1"


@pytest.mark.asyncio
async def test_get_position_tpsl_with_only_tp_sets_sl_fields_to_none(client):
    """TP-only → sl_price/order_id/trigger_type are None."""

    async def mock_request(method, endpoint, **kwargs):
        return {
            "orders": [
                {
                    "orderId": "tp-1",
                    "symbol": "BTC-USDT",
                    "type": "TAKE_PROFIT_MARKET",
                    "positionSide": "LONG",
                    "stopPrice": "72500",
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_position_tpsl("BTC-USDT", "long")

    assert snap.tp_price == 72500.0
    assert snap.tp_order_id == "tp-1"
    assert snap.sl_price is None
    assert snap.sl_order_id is None


@pytest.mark.asyncio
async def test_get_position_tpsl_with_no_conditional_orders_returns_empty_snapshot(client):
    """No open orders → empty snapshot (not error)."""

    client._request = AsyncMock(return_value={"orders": []})

    snap = await client.get_position_tpsl("BTC-USDT", "long")

    assert isinstance(snap, PositionTpSlSnapshot)
    assert snap.tp_price is None
    assert snap.tp_order_id is None
    assert snap.sl_price is None
    assert snap.sl_order_id is None


@pytest.mark.asyncio
async def test_get_position_tpsl_filters_by_position_side(client):
    """Orders for the opposite side must not leak into the snapshot."""

    async def mock_request(method, endpoint, **kwargs):
        return {
            "orders": [
                {"orderId": "tp-short", "symbol": "BTC-USDT",
                 "type": "TAKE_PROFIT_MARKET", "positionSide": "SHORT",
                 "stopPrice": "65000"},
                {"orderId": "tp-long", "symbol": "BTC-USDT",
                 "type": "TAKE_PROFIT_MARKET", "positionSide": "LONG",
                 "stopPrice": "72500"},
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_position_tpsl("BTC-USDT", "long")
    assert snap.tp_order_id == "tp-long"
    assert snap.tp_price == 72500.0


# ==================== get_trailing_stop ====================


@pytest.mark.asyncio
async def test_get_trailing_stop_returns_snapshot_for_active_trailing(client):
    """TRAILING_STOP_MARKET order → populated snapshot with % callback rate."""

    async def mock_request(method, endpoint, **kwargs):
        return {
            "orders": [
                {
                    "orderId": "trail-1",
                    "symbol": "BTC-USDT",
                    "type": "TRAILING_STOP_MARKET",
                    "positionSide": "LONG",
                    "priceRate": "0.014",  # decimal form → 1.4%
                    "activationPrice": "70000.0",
                    "stopPrice": "69000.0",
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_trailing_stop("BTC-USDT", "long")

    assert isinstance(snap, TrailingStopSnapshot)
    assert snap.symbol == "BTC-USDT"
    assert snap.side == "long"
    assert snap.callback_rate == pytest.approx(1.4, rel=1e-6)
    assert snap.activation_price == 70000.0
    assert snap.trigger_price == 69000.0
    assert snap.order_id == "trail-1"


@pytest.mark.asyncio
async def test_get_trailing_stop_returns_none_when_not_present(client):
    """No TRAILING_STOP_MARKET order → None."""

    async def mock_request(method, endpoint, **kwargs):
        return {
            "orders": [
                {"orderId": "tp-1", "symbol": "BTC-USDT",
                 "type": "TAKE_PROFIT_MARKET", "positionSide": "LONG"},
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.get_trailing_stop("BTC-USDT", "long")
    assert result is None


# ==================== get_close_reason_from_history ====================


@pytest.mark.asyncio
async def test_get_close_reason_from_history_returns_triggered_trailing(client):
    """Filled TRAILING_STOP_MARKET → plan_type=track_plan."""

    async def mock_request(method, endpoint, **kwargs):
        assert "allOrders" in endpoint
        assert kwargs.get("params", {}).get("startTime") == "1700000000000"
        return {
            "orders": [
                {
                    "orderId": "trail-filled",
                    "symbol": "BTC-USDT",
                    "type": "TRAILING_STOP_MARKET",
                    "status": "FILLED",
                    "avgPrice": "71500",
                    "workingType": "MARK_PRICE",
                    "updateTime": 1710001000000,
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_close_reason_from_history("BTC-USDT", since_ts_ms=1700000000000)

    assert isinstance(snap, CloseReasonSnapshot)
    assert snap.symbol == "BTC-USDT"
    assert snap.closed_by_plan_type == "track_plan"
    assert snap.closed_by_order_id == "trail-filled"
    assert snap.fill_price == 71500.0
    assert snap.closed_at is not None


@pytest.mark.asyncio
async def test_close_reason_query_includes_endtime_and_limit(client):
    """allOrders request must pass endTime + limit=1000 (issue #224)."""
    captured = {}

    async def mock_request(method, endpoint, **kwargs):
        captured["params"] = kwargs.get("params", {})
        return {"orders": []}

    client._request = AsyncMock(side_effect=mock_request)
    await client.get_close_reason_from_history("BTC-USDT", since_ts_ms=1700000000000)

    assert captured["params"].get("startTime") == "1700000000000"
    assert "endTime" in captured["params"]
    assert int(captured["params"]["endTime"]) >= 1700000000000
    assert captured["params"].get("limit") == "1000"


@pytest.mark.asyncio
async def test_close_reason_query_honors_until_ts_ms(client):
    """until_ts_ms overrides the endTime default (issue #224, backfill support)."""
    captured = {}

    async def mock_request(method, endpoint, **kwargs):
        captured["params"] = kwargs.get("params", {})
        return {"orders": []}

    client._request = AsyncMock(side_effect=mock_request)
    await client.get_close_reason_from_history(
        "BTC-USDT", since_ts_ms=1700000000000, until_ts_ms=1710000000000,
    )
    assert captured["params"].get("endTime") == "1710000000000"
