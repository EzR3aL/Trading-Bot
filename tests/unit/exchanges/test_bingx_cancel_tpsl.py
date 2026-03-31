"""Tests for BingX cancel_position_tpsl — query open orders, filter conditional, cancel."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.bingx.client import BingXClient


@pytest.fixture
def client():
    return BingXClient(api_key="test", api_secret="test", demo_mode=True)


@pytest.mark.asyncio
async def test_cancel_tpsl_cancels_conditional_orders(client):
    """Should cancel TAKE_PROFIT_MARKET and STOP_MARKET orders for the symbol."""
    open_orders = {
        "orders": [
            {"orderId": "111", "symbol": "BTC-USDT", "type": "TAKE_PROFIT_MARKET", "positionSide": "LONG"},
            {"orderId": "222", "symbol": "BTC-USDT", "type": "STOP_MARKET", "positionSide": "LONG"},
            {"orderId": "333", "symbol": "BTC-USDT", "type": "LIMIT", "positionSide": "LONG"},
            {"orderId": "444", "symbol": "ETH-USDT", "type": "TAKE_PROFIT_MARKET", "positionSide": "LONG"},
        ]
    }
    cancel_results = []

    async def mock_request(method, endpoint, **kwargs):
        if "openOrders" in endpoint:
            return open_orders
        if method == "DELETE":
            cancel_results.append(kwargs.get("params", {}).get("orderId"))
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.cancel_position_tpsl("BTC-USDT", side="long")

    assert result is True
    assert sorted(cancel_results) == ["111", "222"]


@pytest.mark.asyncio
async def test_cancel_tpsl_no_orders(client):
    """Should return True if no conditional orders found."""
    client._request = AsyncMock(return_value={"orders": []})

    result = await client.cancel_position_tpsl("BTC-USDT", side="long")
    assert result is True


@pytest.mark.asyncio
async def test_cancel_tpsl_filters_by_position_side(client):
    """Should only cancel orders matching the position side."""
    open_orders = {
        "orders": [
            {"orderId": "111", "symbol": "BTC-USDT", "type": "TAKE_PROFIT_MARKET", "positionSide": "LONG"},
            {"orderId": "222", "symbol": "BTC-USDT", "type": "STOP_MARKET", "positionSide": "SHORT"},
        ]
    }
    cancel_results = []

    async def mock_request(method, endpoint, **kwargs):
        if "openOrders" in endpoint:
            return open_orders
        if method == "DELETE":
            cancel_results.append(kwargs.get("params", {}).get("orderId"))
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.cancel_position_tpsl("BTC-USDT", side="long")
    assert result is True
    assert cancel_results == ["111"]


@pytest.mark.asyncio
async def test_cancel_tpsl_handles_api_error_gracefully(client):
    """Should return False if open orders query fails."""
    client._request = AsyncMock(side_effect=Exception("API timeout"))

    result = await client.cancel_position_tpsl("BTC-USDT", side="long")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_tpsl_partial_cancel_failure(client):
    """Should return True even if one cancel fails — best effort."""
    open_orders = {
        "orders": [
            {"orderId": "111", "symbol": "BTC-USDT", "type": "TAKE_PROFIT_MARKET", "positionSide": "LONG"},
            {"orderId": "222", "symbol": "BTC-USDT", "type": "STOP_MARKET", "positionSide": "LONG"},
        ]
    }
    call_count = 0

    async def mock_request(method, endpoint, **kwargs):
        nonlocal call_count
        if "openOrders" in endpoint:
            return open_orders
        if method == "DELETE":
            call_count += 1
            if call_count == 1:
                raise Exception("Cancel failed")
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.cancel_position_tpsl("BTC-USDT", side="long")
    assert result is True
