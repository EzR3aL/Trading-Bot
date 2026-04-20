"""Tests for Weex leg-specific cancel: ``cancel_tp_only`` and ``cancel_sl_only``.

Epic #188 follow-up to #192: clearing one leg via the dashboard must not
collateral-cancel the other. Weex V3 stores TP and SL as separate
conditional orders distinguished by ``planType`` (``TAKE_PROFIT`` vs
``STOP_LOSS``), so role-based filtering is a clean mechanical match and
does not require trigger-price inference.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.weex.client import WeexClient


@pytest.fixture
def client():
    return WeexClient(api_key="test", api_secret="test", demo_mode=True)


def _mock_pending_request(pending_orders, cancel_ids):
    """Build an AsyncMock side_effect that mimics Weex's pending + cancel endpoints."""

    async def side_effect(method, endpoint, **kwargs):
        if "pending" in endpoint.lower():
            return pending_orders
        if "cancel" in endpoint.lower():
            cancel_ids.append(kwargs.get("data", {}).get("orderId"))
            return {"success": True}
        return {}

    return side_effect


# ── cancel_tp_only ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_tp_only_cancels_only_take_profit_orders(client):
    """Only planType=TAKE_PROFIT orders are cancelled; STOP_LOSS stays."""
    pending = [
        {"orderId": "tp_long", "symbol": "BTCUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
        {"orderId": "sl_long", "symbol": "BTCUSDT", "planType": "STOP_LOSS", "positionSide": "LONG"},
    ]
    cancel_ids: list = []
    client._request = AsyncMock(side_effect=_mock_pending_request(pending, cancel_ids))

    result = await client.cancel_tp_only("BTCUSDT", side="long")

    assert result is True
    assert cancel_ids == ["tp_long"]


@pytest.mark.asyncio
async def test_cancel_tp_only_ignores_other_position_side(client):
    """TP orders on the SHORT side of the same symbol are left untouched."""
    pending = [
        {"orderId": "tp_long", "symbol": "BTCUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
        {"orderId": "tp_short", "symbol": "BTCUSDT", "planType": "TAKE_PROFIT", "positionSide": "SHORT"},
    ]
    cancel_ids: list = []
    client._request = AsyncMock(side_effect=_mock_pending_request(pending, cancel_ids))

    result = await client.cancel_tp_only("BTCUSDT", side="long")

    assert result is True
    assert cancel_ids == ["tp_long"]


# ── cancel_sl_only ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_sl_only_cancels_only_stop_loss_orders(client):
    """Only planType=STOP_LOSS orders are cancelled; TAKE_PROFIT stays."""
    pending = [
        {"orderId": "tp_long", "symbol": "ETHUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
        {"orderId": "sl_long", "symbol": "ETHUSDT", "planType": "STOP_LOSS", "positionSide": "LONG"},
    ]
    cancel_ids: list = []
    client._request = AsyncMock(side_effect=_mock_pending_request(pending, cancel_ids))

    result = await client.cancel_sl_only("ETHUSDT", side="long")

    assert result is True
    assert cancel_ids == ["sl_long"]


# ── no-op path ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_tp_only_returns_true_when_no_matching_orders(client):
    """Empty pending list must resolve cleanly to True without calling cancel."""
    cancel_ids: list = []

    async def side_effect(method, endpoint, **kwargs):
        if "pending" in endpoint.lower():
            return []
        if "cancel" in endpoint.lower():
            cancel_ids.append(kwargs.get("data", {}).get("orderId"))
            return {"success": True}
        return {}

    client._request = AsyncMock(side_effect=side_effect)

    result = await client.cancel_tp_only("BTCUSDT", side="long")

    assert result is True
    assert cancel_ids == []


# ── set_position_tpsl pre-place sweep (Issue #216 S2 audit) ─────────────


def _build_tpsl_mock(pending_orders: list, cancel_ids: list, place_ids: list):
    """Mock Weex endpoints: pending query, cancel, and placeTpSlOrder.

    ``place_ids`` collects the ``planType`` for each placeTpSlOrder POST
    so the caller can assert TP / SL were actually re-placed after sweep.
    """

    async def side_effect(method, endpoint, **kwargs):
        ep = endpoint.lower()
        if "pending" in ep:
            return list(pending_orders)
        if "cancel" in ep:
            cancel_ids.append(kwargs.get("data", {}).get("orderId"))
            return {"success": True}
        if "placetpsl" in ep.replace("/", "").replace("_", ""):
            plan = kwargs.get("data", {}).get("planType")
            place_ids.append(plan)
            return [{"success": True, "orderId": f"new_{plan}"}]
        return {}

    return side_effect


@pytest.mark.asyncio
async def test_set_position_tpsl_tp_only_does_not_cancel_sl_leg(client):
    """Setting only TP must not collateral-cancel the existing SL order.

    Issue #216 S2 audit: the pre-#216 ``_cancel_existing_tpsl(symbol)``
    wiped every TP+SL row before placing, silently dropping the SL the
    user just set via the dashboard. The fix scopes the sweep to
    ``{TAKE_PROFIT}`` when only ``take_profit`` is passed.
    """
    pending = [
        {"orderId": "tp_stale", "symbol": "BTCUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
        {"orderId": "sl_live", "symbol": "BTCUSDT", "planType": "STOP_LOSS", "positionSide": "LONG"},
    ]
    cancel_ids: list = []
    place_ids: list = []
    client._request = AsyncMock(
        side_effect=_build_tpsl_mock(pending, cancel_ids, place_ids)
    )

    await client.set_position_tpsl(
        "BTCUSDT", take_profit=50000.0, side="long", size=0.1,
    )

    assert cancel_ids == ["tp_stale"], (
        f"SL leg must survive a TP-only update, got cancels={cancel_ids}"
    )
    assert place_ids == ["TAKE_PROFIT"]


@pytest.mark.asyncio
async def test_set_position_tpsl_sl_only_does_not_cancel_tp_leg(client):
    """Setting only SL must not collateral-cancel the existing TP order."""
    pending = [
        {"orderId": "tp_live", "symbol": "BTCUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
        {"orderId": "sl_stale", "symbol": "BTCUSDT", "planType": "STOP_LOSS", "positionSide": "LONG"},
    ]
    cancel_ids: list = []
    place_ids: list = []
    client._request = AsyncMock(
        side_effect=_build_tpsl_mock(pending, cancel_ids, place_ids)
    )

    await client.set_position_tpsl(
        "BTCUSDT", stop_loss=45000.0, side="long", size=0.1,
    )

    assert cancel_ids == ["sl_stale"], (
        f"TP leg must survive an SL-only update, got cancels={cancel_ids}"
    )
    assert place_ids == ["STOP_LOSS"]


@pytest.mark.asyncio
async def test_set_position_tpsl_both_legs_cancels_both(client):
    """Passing both TP and SL sweeps both legs (legacy full-reset behaviour)."""
    pending = [
        {"orderId": "tp_stale", "symbol": "BTCUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
        {"orderId": "sl_stale", "symbol": "BTCUSDT", "planType": "STOP_LOSS", "positionSide": "LONG"},
    ]
    cancel_ids: list = []
    place_ids: list = []
    client._request = AsyncMock(
        side_effect=_build_tpsl_mock(pending, cancel_ids, place_ids)
    )

    await client.set_position_tpsl(
        "BTCUSDT", take_profit=50000.0, stop_loss=45000.0, side="long", size=0.1,
    )

    assert sorted(cancel_ids) == ["sl_stale", "tp_stale"]
    assert sorted(place_ids) == ["STOP_LOSS", "TAKE_PROFIT"]


@pytest.mark.asyncio
async def test_cancel_existing_tpsl_default_sweeps_both_legs(client):
    """``_cancel_existing_tpsl`` without target_types keeps legacy behaviour.

    External callers that relied on the full-reset semantics before #216
    must still see both legs cancelled when they don't pass a filter.
    """
    pending = [
        {"orderId": "tp", "planType": "TAKE_PROFIT"},
        {"orderId": "sl", "planType": "STOP_LOSS"},
        {"orderId": "other", "planType": "TRIGGER"},
    ]
    cancel_ids: list = []
    client._request = AsyncMock(
        side_effect=_mock_pending_request(pending, cancel_ids)
    )

    await client._cancel_existing_tpsl("BTCUSDT")

    # TP + SL cancelled, unrelated TRIGGER plan left untouched.
    assert sorted(cancel_ids) == ["sl", "tp"]
