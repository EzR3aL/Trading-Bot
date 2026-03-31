"""Tests for Bitget cancel_position_tpsl."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.bitget.client import BitgetExchangeClient


@pytest.fixture
def client():
    return BitgetExchangeClient(api_key="test", api_secret="test", passphrase="test", demo_mode=True)


@pytest.mark.asyncio
async def test_cancel_tpsl_cancels_plan_orders(client):
    """Should cancel TP/SL plan orders matching the position."""
    pending = {
        "entrustedList": [
            {"orderId": "111", "planType": "pos_profit", "holdSide": "long", "symbol": "BTCUSDT"},
            {"orderId": "222", "planType": "pos_loss", "holdSide": "long", "symbol": "BTCUSDT"},
            {"orderId": "333", "planType": "limit", "holdSide": "long", "symbol": "BTCUSDT"},
        ]
    }
    cancel_ids = []

    async def mock_request(method, endpoint, **kwargs):
        if "pending" in endpoint:
            return pending
        if method == "POST" and "cancel" in endpoint:
            data = kwargs.get("data", {})
            cancel_ids.append(data.get("orderId"))
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert result is True
    assert sorted(cancel_ids) == ["111", "222"]


@pytest.mark.asyncio
async def test_cancel_tpsl_no_pending_orders(client):
    """Should return True if no plan orders found."""
    client._request = AsyncMock(return_value={"entrustedList": []})
    result = await client.cancel_position_tpsl("BTCUSDT", side="long")
    assert result is True


@pytest.mark.asyncio
async def test_cancel_tpsl_query_fails(client):
    """Should return False on query failure."""
    client._request = AsyncMock(side_effect=Exception("API error"))
    result = await client.cancel_position_tpsl("BTCUSDT", side="long")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_tpsl_filters_by_hold_side(client):
    """Should only cancel orders matching the hold side."""
    pending = {
        "entrustedList": [
            {"orderId": "111", "planType": "pos_profit", "holdSide": "long"},
            {"orderId": "222", "planType": "pos_loss", "holdSide": "short"},
        ]
    }
    cancel_ids = []

    async def mock_request(method, endpoint, **kwargs):
        if "pending" in endpoint:
            return pending
        if method == "POST" and "cancel" in endpoint:
            cancel_ids.append(kwargs.get("data", {}).get("orderId"))
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert result is True
    assert cancel_ids == ["111"]
