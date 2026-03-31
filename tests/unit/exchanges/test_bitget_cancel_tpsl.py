"""Tests for Bitget cancel_position_tpsl — uses cancel-plan-order with planType."""

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
async def test_cancel_tpsl_sends_all_plan_types(client):
    """Should call cancel-plan-order for pos_profit, pos_loss, and moving_plan."""
    cancelled_types = []

    async def mock_request(method, endpoint, **kwargs):
        if "cancel-plan-order" in endpoint:
            cancelled_types.append(kwargs.get("data", {}).get("planType"))
            return {"successList": [{"orderId": "123"}], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("ETHUSDT", side="long")

    assert result is True
    assert sorted(cancelled_types) == ["moving_plan", "pos_loss", "pos_profit"]


@pytest.mark.asyncio
async def test_cancel_tpsl_returns_true_when_nothing_to_cancel(client):
    """Should return True even when no orders exist to cancel."""
    async def mock_request(method, endpoint, **kwargs):
        if "cancel-plan-order" in endpoint:
            return {"successList": [], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("ETHUSDT", side="long")
    assert result is True


@pytest.mark.asyncio
async def test_cancel_tpsl_handles_api_errors_gracefully(client):
    """Should return True even if individual cancel calls fail (best effort)."""
    call_count = 0

    async def mock_request(method, endpoint, **kwargs):
        nonlocal call_count
        if "cancel-plan-order" in endpoint:
            call_count += 1
            if call_count == 1:
                raise Exception("API error")
            return {"successList": [], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("ETHUSDT", side="long")

    assert result is True
    assert call_count == 3  # All 3 planTypes attempted despite first failure


@pytest.mark.asyncio
async def test_cancel_tpsl_includes_symbol_and_product_type(client):
    """Should pass correct symbol and productType in each cancel call."""
    call_data = []

    async def mock_request(method, endpoint, **kwargs):
        if "cancel-plan-order" in endpoint:
            call_data.append(kwargs.get("data", {}))
            return {"successList": [], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert len(call_data) == 3
    for data in call_data:
        assert data["symbol"] == "BTCUSDT"
        assert "productType" in data
