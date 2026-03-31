"""Tests for Bitunix cancel_position_tpsl."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.bitunix.client import BitunixClient


@pytest.fixture
def client():
    return BitunixClient(api_key="test", api_secret="test", demo_mode=True)


@pytest.mark.asyncio
async def test_cancel_tpsl_cancels_matching_orders(client):
    """Should cancel TP/SL orders matching symbol and position side."""
    pending = {
        "data": [
            {"orderId": "aaa", "symbol": "BTCUSDT", "positionSide": "LONG", "type": "TAKE_PROFIT"},
            {"orderId": "bbb", "symbol": "BTCUSDT", "positionSide": "LONG", "type": "STOP_LOSS"},
            {"orderId": "ccc", "symbol": "BTCUSDT", "positionSide": "SHORT", "type": "TAKE_PROFIT"},
        ]
    }
    cancel_ids = []

    async def mock_request(method, endpoint, **kwargs):
        if "get_pending" in endpoint:
            return pending
        if "cancel" in endpoint:
            cancel_ids.append(kwargs.get("data", {}).get("orderId"))
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert result is True
    assert sorted(cancel_ids) == ["aaa", "bbb"]


@pytest.mark.asyncio
async def test_cancel_tpsl_no_pending(client):
    """Should return True if no pending orders."""
    client._request = AsyncMock(return_value={"data": []})
    result = await client.cancel_position_tpsl("BTCUSDT", side="long")
    assert result is True


@pytest.mark.asyncio
async def test_cancel_tpsl_query_fails(client):
    """Should return False on query failure."""
    client._request = AsyncMock(side_effect=Exception("timeout"))
    result = await client.cancel_position_tpsl("BTCUSDT", side="long")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_tpsl_partial_failure(client):
    """Should continue and return True even if one cancel fails."""
    pending = {
        "data": [
            {"orderId": "aaa", "positionSide": "LONG"},
            {"orderId": "bbb", "positionSide": "LONG"},
        ]
    }
    call_count = 0

    async def mock_request(method, endpoint, **kwargs):
        nonlocal call_count
        if "get_pending" in endpoint:
            return pending
        if "cancel" in endpoint:
            call_count += 1
            if call_count == 1:
                raise Exception("cancel failed")
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("BTCUSDT", side="long")
    assert result is True
