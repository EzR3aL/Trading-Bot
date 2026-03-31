"""Tests for Weex cancel_position_tpsl — query pending TP/SL orders, cancel."""

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


@pytest.mark.asyncio
async def test_cancel_tpsl_cancels_matching_orders(client):
    """Should cancel TP/SL orders for the symbol and position side."""
    pending_orders = [
        {"orderId": "aaa", "symbol": "BTCUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
        {"orderId": "bbb", "symbol": "BTCUSDT", "planType": "STOP_LOSS", "positionSide": "LONG"},
        {"orderId": "ccc", "symbol": "ETHUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
    ]
    cancel_ids = []

    async def mock_request(method, endpoint, **kwargs):
        if "pending" in endpoint.lower():
            return pending_orders
        if "cancel" in endpoint.lower():
            data = kwargs.get("data", {})
            cancel_ids.append(data.get("orderId"))
            return {"success": True}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert result is True
    # All 3 orders match positionSide=LONG (ccc has different symbol but endpoint
    # was queried with symbol filter, so it would not appear in real API response.
    # However, our mock returns all 3 - the method filters by positionSide only
    # since the API already filters by symbol)
    assert sorted(cancel_ids) == ["aaa", "bbb", "ccc"]


@pytest.mark.asyncio
async def test_cancel_tpsl_no_pending_orders(client):
    """Should return True if no pending TP/SL orders."""
    client._request = AsyncMock(return_value=[])

    result = await client.cancel_position_tpsl("BTCUSDT", side="long")
    assert result is True


@pytest.mark.asyncio
async def test_cancel_tpsl_query_fails_gracefully(client):
    """Should return False if query fails."""
    client._request = AsyncMock(side_effect=Exception("Network error"))

    result = await client.cancel_position_tpsl("BTCUSDT", side="long")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_tpsl_filters_by_position_side(client):
    """Should only cancel orders matching position side."""
    pending_orders = [
        {"orderId": "aaa", "symbol": "BTCUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
        {"orderId": "bbb", "symbol": "BTCUSDT", "planType": "STOP_LOSS", "positionSide": "SHORT"},
    ]
    cancel_ids = []

    async def mock_request(method, endpoint, **kwargs):
        if "pending" in endpoint.lower():
            return pending_orders
        if "cancel" in endpoint.lower():
            data = kwargs.get("data", {})
            cancel_ids.append(data.get("orderId"))
            return {"success": True}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.cancel_position_tpsl("BTCUSDT", side="long")
    assert result is True
    assert cancel_ids == ["aaa"]
