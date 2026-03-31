"""Tests for Hyperliquid cancel_position_tpsl."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
        c._cb_state = "closed"
        c._cb_failures = 0
        c._cb_last_failure = 0
        c._cb_threshold = 5
        c._cb_timeout = 60
        c._asset_meta = {"BTC": {"szDecimals": 4}}
        c.demo_mode = False

        # Make _cb_call just call the function directly
        async def direct_call(fn, *args, **kwargs):
            if hasattr(fn, '__call__'):
                result = fn(*args, **kwargs)
                if hasattr(result, '__await__'):
                    return await result
                return result
        c._cb_call = AsyncMock(side_effect=direct_call)

        return c


@pytest.mark.asyncio
async def test_cancel_tpsl_clears_via_empty_position_tpsl(client):
    """Should clear TP/SL by sending empty positionTpsl."""
    client._exchange.bulk_orders = MagicMock(return_value={"status": "ok"})

    async def mock_cb_call(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    client._cb_call = AsyncMock(side_effect=mock_cb_call)

    result = await client.cancel_position_tpsl("BTC", side="long")
    assert result is True
    client._exchange.bulk_orders.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_tpsl_fallback_to_order_cancel(client):
    """If empty positionTpsl fails, should query and cancel trigger orders."""
    call_count = 0

    open_orders = [
        {"coin": "BTC", "oid": 12345, "orderType": "trigger"},
        {"coin": "BTC", "oid": 12346, "orderType": "trigger"},
        {"coin": "ETH", "oid": 99999, "orderType": "trigger"},
    ]
    cancelled_oids = []

    async def mock_cb_call(fn, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("positionTpsl empty not supported")
        if fn == client._info.open_orders:
            return open_orders
        if fn == client._exchange.cancel:
            cancelled_oids.append(kwargs.get("oid") or (args[1] if len(args) > 1 else None))
            return True
        return fn(*args, **kwargs)

    client._cb_call = AsyncMock(side_effect=mock_cb_call)

    result = await client.cancel_position_tpsl("BTC", side="long")
    assert result is True
    assert sorted(cancelled_oids) == [12345, 12346]


@pytest.mark.asyncio
async def test_cancel_tpsl_no_trigger_orders(client):
    """Should return True if no trigger orders found."""
    call_count = 0

    async def mock_cb_call(fn, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("fail")
        return []

    client._cb_call = AsyncMock(side_effect=mock_cb_call)

    result = await client.cancel_position_tpsl("BTC", side="long")
    assert result is True


@pytest.mark.asyncio
async def test_cancel_tpsl_both_strategies_fail(client):
    """Should return False if both strategies fail."""
    async def mock_cb_call(fn, *args, **kwargs):
        raise Exception("All failed")

    client._cb_call = AsyncMock(side_effect=mock_cb_call)

    result = await client.cancel_position_tpsl("BTC", side="long")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_tpsl_with_builder(client):
    """Should pass builder kwargs when builder is configured."""
    client._builder = {"b": "0xbuilder", "f": 10}
    client._exchange.bulk_orders = MagicMock(return_value={"status": "ok"})

    async def mock_cb_call(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    client._cb_call = AsyncMock(side_effect=mock_cb_call)

    result = await client.cancel_position_tpsl("BTC", side="long")
    assert result is True
    client._exchange.bulk_orders.assert_called_once_with(
        [], grouping="positionTpsl", builder={"b": "0xbuilder", "f": 10}
    )
