"""Tests for Bitget risk-state readback methods (#191).

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
from src.exchanges.bitget.client import BitgetExchangeClient


@pytest.fixture
def client():
    return BitgetExchangeClient(
        api_key="test", api_secret="test", passphrase="test", demo_mode=True,
    )


# ==================== get_position_tpsl ====================


@pytest.mark.asyncio
async def test_get_position_tpsl_returns_both_tp_and_sl(client):
    """Active TP+SL plans yield a fully populated snapshot."""

    async def mock_request(method, endpoint, **kwargs):
        assert "orders-plan-pending" in endpoint
        assert kwargs.get("params", {}).get("planType") == "profit_loss"
        return {
            "entrustedList": [
                {
                    "orderId": "tp-1",
                    "planType": "pos_profit",
                    "holdSide": "long",
                    "executePrice": "72500.5",
                    "triggerType": "mark_price",
                },
                {
                    "orderId": "sl-1",
                    "planType": "pos_loss",
                    "holdSide": "long",
                    "executePrice": "68000.0",
                    "triggerType": "fill_price",
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_position_tpsl("BTCUSDT", "long")

    assert isinstance(snap, PositionTpSlSnapshot)
    assert snap.symbol == "BTCUSDT"
    assert snap.side == "long"
    assert snap.tp_price == 72500.5
    assert snap.tp_order_id == "tp-1"
    assert snap.tp_trigger_type == "mark_price"
    assert snap.sl_price == 68000.0
    assert snap.sl_order_id == "sl-1"
    assert snap.sl_trigger_type == "fill_price"


@pytest.mark.asyncio
async def test_get_position_tpsl_with_only_tp_sets_sl_fields_to_none(client):
    """TP-only position → sl_price/order_id/trigger_type all None."""

    async def mock_request(method, endpoint, **kwargs):
        return {
            "entrustedList": [
                {
                    "orderId": "tp-1",
                    "planType": "pos_profit",
                    "holdSide": "long",
                    "executePrice": "72500",
                    "triggerType": "mark_price",
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_position_tpsl("BTCUSDT", "long")

    assert snap.tp_price == 72500.0
    assert snap.tp_order_id == "tp-1"
    assert snap.sl_price is None
    assert snap.sl_order_id is None
    assert snap.sl_trigger_type is None


@pytest.mark.asyncio
async def test_get_position_tpsl_with_no_plans_returns_empty_snapshot(client):
    """No plans in response → empty snapshot (all fields None, not error)."""

    client._request = AsyncMock(return_value={"entrustedList": []})

    snap = await client.get_position_tpsl("BTCUSDT", "long")

    assert isinstance(snap, PositionTpSlSnapshot)
    assert snap.symbol == "BTCUSDT"
    assert snap.side == "long"
    assert snap.tp_price is None
    assert snap.tp_order_id is None
    assert snap.sl_price is None
    assert snap.sl_order_id is None


@pytest.mark.asyncio
async def test_get_position_tpsl_filters_by_hold_side(client):
    """Plans for the opposite side must not leak into the snapshot."""

    async def mock_request(method, endpoint, **kwargs):
        return {
            "entrustedList": [
                {"orderId": "tp-short", "planType": "pos_profit",
                 "holdSide": "short", "executePrice": "65000"},
                {"orderId": "tp-long", "planType": "pos_profit",
                 "holdSide": "long", "executePrice": "72500"},
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_position_tpsl("BTCUSDT", "long")
    assert snap.tp_order_id == "tp-long"
    assert snap.tp_price == 72500.0


# ==================== get_trailing_stop ====================


@pytest.mark.asyncio
async def test_get_trailing_stop_returns_snapshot_for_active_track_plan(client):
    """Active track_plan → populated TrailingStopSnapshot with % callback rate."""

    async def mock_request(method, endpoint, **kwargs):
        assert kwargs.get("params", {}).get("planType") == "track_plan"
        return {
            "entrustedList": [
                {
                    "orderId": "trail-1",
                    "planType": "track_plan",
                    "holdSide": "long",
                    "callbackRatio": "0.014",  # decimal form → 1.4%
                    "triggerPrice": "70000.0",
                    "cTime": "1710000000000",
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_trailing_stop("BTCUSDT", "long")

    assert isinstance(snap, TrailingStopSnapshot)
    assert snap.symbol == "BTCUSDT"
    assert snap.side == "long"
    assert snap.callback_rate == pytest.approx(1.4, rel=1e-6)
    assert snap.activation_price == 70000.0
    assert snap.order_id == "trail-1"


@pytest.mark.asyncio
async def test_get_trailing_stop_returns_none_when_no_plan(client):
    """No track_plan → None (not an empty snapshot)."""

    client._request = AsyncMock(return_value={"entrustedList": []})

    result = await client.get_trailing_stop("BTCUSDT", "long")
    assert result is None


@pytest.mark.asyncio
async def test_get_trailing_stop_returns_newest_when_multiple_plans(client):
    """Multiple track_plan entries → newest by cTime wins."""

    async def mock_request(method, endpoint, **kwargs):
        return {
            "entrustedList": [
                {"orderId": "old", "planType": "track_plan",
                 "holdSide": "long", "callbackRatio": "0.02",
                 "triggerPrice": "69000", "cTime": "1710000000000"},
                {"orderId": "newest", "planType": "track_plan",
                 "holdSide": "long", "callbackRatio": "0.03",
                 "triggerPrice": "70000", "cTime": "1710000999000"},
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_trailing_stop("BTCUSDT", "long")
    assert snap is not None
    assert snap.order_id == "newest"


# ==================== get_close_reason_from_history ====================


@pytest.mark.asyncio
async def test_get_close_reason_from_history_returns_triggered_plan(client):
    """Triggered pos_profit plan → CloseReasonSnapshot with plan_type=pos_profit."""

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-history" in endpoint:
            return {
                "entrustedList": [
                    {
                        "orderId": "tp-triggered",
                        "planType": "pos_profit",
                        "planStatus": "triggered",
                        "executePrice": "72500",
                        "triggerType": "mark_price",
                        "uTime": "1710001000000",
                    },
                ],
            }
        # orders-history: no manual close
        return {"entrustedList": []}

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_close_reason_from_history("BTCUSDT", since_ts_ms=1700000000000)

    assert isinstance(snap, CloseReasonSnapshot)
    assert snap.symbol == "BTCUSDT"
    assert snap.closed_by_plan_type == "pos_profit"
    assert snap.closed_by_order_id == "tp-triggered"
    assert snap.closed_by_trigger_type == "mark_price"
    assert snap.fill_price == 72500.0
    assert snap.closed_at is not None


@pytest.mark.asyncio
async def test_get_close_reason_from_history_returns_manual_close(client):
    """Filled reduce-only market close → plan_type=manual."""

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-history" in endpoint:
            return {"entrustedList": []}
        # orders-history: manual close
        return {
            "entrustedList": [
                {
                    "orderId": "manual-close",
                    "tradeSide": "close_long",
                    "orderType": "market",
                    "state": "filled",
                    "priceAvg": "70000",
                    "uTime": "1710002000000",
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_close_reason_from_history("BTCUSDT", since_ts_ms=1700000000000)

    assert isinstance(snap, CloseReasonSnapshot)
    assert snap.closed_by_plan_type == "manual"
    assert snap.closed_by_order_id == "manual-close"
    assert snap.fill_price == 70000.0


@pytest.mark.asyncio
async def test_get_close_reason_from_history_returns_none_when_nothing(client):
    """Both endpoints empty → None."""

    client._request = AsyncMock(return_value={"entrustedList": []})

    result = await client.get_close_reason_from_history("BTCUSDT", since_ts_ms=1700000000000)
    assert result is None
