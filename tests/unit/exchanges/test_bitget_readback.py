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
        # get_trailing_stop queries the umbrella planType=profit_loss and
        # filters for moving_plan locally (Bitget rejects direct queries for
        # planType=moving_plan; see the #174 trailing-readback-crash fix).
        assert kwargs.get("params", {}).get("planType") == "profit_loss"
        return {
            "entrustedList": [
                {
                    "orderId": "trail-1",
                    "planType": "moving_plan",
                    "holdSide": "long",
                    "callbackRatio": "1.4",  # Bitget returns percent (#188 callbackRatio scaling fix)
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
                {"orderId": "old", "planType": "moving_plan",
                 "holdSide": "long", "callbackRatio": "2.0",
                 "triggerPrice": "69000", "cTime": "1710000000000"},
                {"orderId": "newest", "planType": "moving_plan",
                 "holdSide": "long", "callbackRatio": "3.0",
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


@pytest.mark.asyncio
async def test_plan_close_query_uses_required_params(client):
    """orders-plan-history call includes planType=profit_loss + endTime (issue #221)."""
    captured = {}

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-history" in endpoint:
            captured["params"] = kwargs.get("params", {})
            return {"entrustedList": []}
        return {"entrustedList": []}

    client._request = AsyncMock(side_effect=mock_request)

    await client.get_close_reason_from_history("ETHUSDT", since_ts_ms=1710000000000)

    assert captured["params"].get("planType") == "profit_loss"
    assert captured["params"].get("symbol") == "ETHUSDT"
    assert captured["params"].get("startTime") == "1710000000000"
    assert "endTime" in captured["params"]
    assert int(captured["params"]["endTime"]) > 1710000000000


@pytest.mark.asyncio
async def test_plan_close_accepts_executed_status(client):
    """Bitget v2 returns planStatus=executed for fired plans (issue #221)."""

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-history" in endpoint:
            return {
                "entrustedList": [
                    {
                        "orderId": "sl-plan",
                        "executeOrderId": "sl-fill",
                        "planType": "pos_loss",
                        "planStatus": "executed",
                        "executePrice": "2311.9",
                        "triggerType": "fill_price",
                        "uTime": "1710002000000",
                    },
                ],
            }
        return {"entrustedList": []}

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_close_reason_from_history("ETHUSDT", since_ts_ms=1700000000000)

    assert snap is not None
    assert snap.closed_by_plan_type == "pos_loss"
    # executeOrderId is preferred over plan's orderId — that is the fill
    # id referenced by TradeRecord.sl_order_id.
    assert snap.closed_by_order_id == "sl-fill"
    assert snap.fill_price == 2311.9


@pytest.mark.asyncio
async def test_plan_close_failure_does_not_hide_manual_close(client):
    """Plan-history ExchangeError must not suppress manual-close probe (issue #221)."""
    from src.exceptions import ExchangeError

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-history" in endpoint:
            raise ExchangeError("bitget", "Parameter verification failed")
        # orders-history returns a market close
        return {
            "entrustedList": [
                {
                    "orderId": "close-fill",
                    "tradeSide": "close",
                    "orderType": "market",
                    "status": "filled",
                    "priceAvg": "2277.0",
                    "orderSource": "market",
                    "uTime": "1710002000000",
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_close_reason_from_history("ETHUSDT", since_ts_ms=1700000000000)

    assert snap is not None
    assert snap.closed_by_plan_type == "manual"
    assert snap.closed_by_order_id == "close-fill"


@pytest.mark.asyncio
async def test_manual_close_maps_order_source_to_plan_type(client):
    """orderSource=pos_loss_market → plan_type=pos_loss (not manual) (issue #221)."""

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-history" in endpoint:
            return {"entrustedList": []}
        return {
            "entrustedList": [
                {
                    "orderId": "sl-fill",
                    "tradeSide": "close",
                    "orderType": "market",
                    "status": "filled",
                    "priceAvg": "2311.9",
                    "orderSource": "pos_loss_market",
                    "uTime": "1710002000000",
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_close_reason_from_history("ETHUSDT", since_ts_ms=1700000000000)

    assert snap is not None
    assert snap.closed_by_plan_type == "pos_loss"
    assert snap.closed_by_order_id == "sl-fill"


@pytest.mark.asyncio
async def test_manual_close_maps_move_market_to_moving_plan(client):
    """orderSource=move_market (Bitget demo trailing spelling) → moving_plan (issue #221)."""

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-history" in endpoint:
            return {"entrustedList": []}
        return {
            "entrustedList": [
                {
                    "orderId": "trail-fill",
                    "tradeSide": "close",
                    "orderType": "market",
                    "status": "filled",
                    "priceAvg": "2277.0",
                    "orderSource": "move_market",
                    "uTime": "1710002000000",
                },
            ],
        }

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_close_reason_from_history("ETHUSDT", since_ts_ms=1700000000000)

    assert snap is not None
    assert snap.closed_by_plan_type == "moving_plan"


@pytest.mark.asyncio
async def test_plan_close_filters_by_until_ts_ms(client):
    """Rows with uTime past until_ts_ms are filtered client-side (issue #221).

    Bitget v2 orders-plan-history ignores the endTime param in the response —
    without client-side filtering, a newer close on the same symbol leaks
    into an older trade's backfill lookup.
    """

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-history" in endpoint:
            return {
                "entrustedList": [
                    # Past the until window — must be filtered out.
                    {
                        "orderId": "too-new",
                        "executeOrderId": "too-new-fill",
                        "planType": "pos_loss",
                        "planStatus": "executed",
                        "executePrice": "9999",
                        "uTime": "1710099999999",
                    },
                    # Inside the until window — must be picked.
                    {
                        "orderId": "in-window",
                        "executeOrderId": "in-window-fill",
                        "planType": "moving_plan",
                        "planStatus": "executed",
                        "executePrice": "2277",
                        "uTime": "1710002000000",
                    },
                ],
            }
        return {"entrustedList": []}

    client._request = AsyncMock(side_effect=mock_request)

    snap = await client.get_close_reason_from_history(
        "ETHUSDT", since_ts_ms=1700000000000, until_ts_ms=1710005000000,
    )

    assert snap is not None
    assert snap.closed_by_plan_type == "moving_plan"
    assert snap.closed_by_order_id == "in-window-fill"
