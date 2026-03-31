"""Tests for Hyperliquid cancel_position_tpsl — queries frontend_open_orders, cancels triggers."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


@pytest.fixture
def client():
    """Create HyperliquidClient with mocked SDK objects."""
    with patch("src.exchanges.hyperliquid.client.HLExchange"), \
         patch("src.exchanges.hyperliquid.client.HLInfo"):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        c = HyperliquidClient.__new__(HyperliquidClient)
        c._exchange = MagicMock()
        c._info = MagicMock()
        c.wallet_address = "0xTestAddress"
        c._wallet = MagicMock()
        c._wallet.address = "0xTestAddress"
        c._builder = None
        c._asset_meta = {"BTC": {"szDecimals": 4}}
        c.demo_mode = False
        return c


@pytest.mark.asyncio
async def test_cancel_tpsl_cancels_trigger_orders(client):
    """Should query frontend_open_orders, filter triggers by coin, cancel each."""
    client._info.frontend_open_orders = MagicMock(return_value=[
        {"coin": "BTC", "oid": 111, "isTrigger": True, "isPositionTpsl": False},
        {"coin": "BTC", "oid": 222, "isTrigger": True, "isPositionTpsl": False},
        {"coin": "ETH", "oid": 333, "isTrigger": True, "isPositionTpsl": False},
    ])
    cancelled = []
    client._exchange.cancel = MagicMock(side_effect=lambda coin, oid: cancelled.append(oid))

    result = await client.cancel_position_tpsl("BTC", side="long")

    assert result is True
    assert sorted(cancelled) == [111, 222]  # ETH filtered out
    client._info.frontend_open_orders.assert_called_once_with("0xtestaddress")


@pytest.mark.asyncio
async def test_cancel_tpsl_includes_position_tpsl_orders(client):
    """Should also cancel orders with isPositionTpsl=True."""
    client._info.frontend_open_orders = MagicMock(return_value=[
        {"coin": "BTC", "oid": 111, "isTrigger": False, "isPositionTpsl": True},
        {"coin": "BTC", "oid": 222, "isTrigger": True, "isPositionTpsl": False},
    ])
    cancelled = []
    client._exchange.cancel = MagicMock(side_effect=lambda coin, oid: cancelled.append(oid))

    result = await client.cancel_position_tpsl("BTC", side="long")

    assert result is True
    assert sorted(cancelled) == [111, 222]


@pytest.mark.asyncio
async def test_cancel_tpsl_no_triggers(client):
    """Should return True if no trigger orders found."""
    client._info.frontend_open_orders = MagicMock(return_value=[
        {"coin": "BTC", "oid": 111, "isTrigger": False, "isPositionTpsl": False},
    ])

    result = await client.cancel_position_tpsl("BTC", side="long")
    assert result is True
    client._exchange.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_tpsl_query_fails(client):
    """Should return False if frontend_open_orders fails."""
    client._info.frontend_open_orders = MagicMock(side_effect=Exception("API error"))

    result = await client.cancel_position_tpsl("BTC", side="long")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_tpsl_partial_cancel_failure(client):
    """Should continue and return True even if one cancel fails."""
    client._info.frontend_open_orders = MagicMock(return_value=[
        {"coin": "BTC", "oid": 111, "isTrigger": True},
        {"coin": "BTC", "oid": 222, "isTrigger": True},
    ])
    call_count = 0

    def mock_cancel(coin, oid):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("cancel failed")

    client._exchange.cancel = MagicMock(side_effect=mock_cancel)

    result = await client.cancel_position_tpsl("BTC", side="long")
    assert result is True
    assert call_count == 2  # Both attempted
