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
