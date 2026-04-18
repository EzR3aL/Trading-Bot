"""Tests for Hyperliquid leg-specific cancel: ``cancel_tp_only`` and ``cancel_sl_only``.

Epic #188 follow-up to #192: clearing one leg via the dashboard must not
collateral-cancel the other legs. These tests pin the classifier behaviour
(via ``_classify_tpsl``) so it stays consistent with ``get_position_tpsl``
from #191.
"""

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
    """HyperliquidClient with mocked SDK — mirrors test_hyperliquid_cancel_tpsl."""
    with patch("src.exchanges.hyperliquid.client.HLExchange"), \
         patch("src.exchanges.hyperliquid.client.HLInfo"):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        c = HyperliquidClient.__new__(HyperliquidClient)
        c._exchange = MagicMock()
        c._info = MagicMock()
        c._info_exec = c._info
        c.wallet_address = "0xTestAddress"
        c._wallet = MagicMock()
        c._wallet.address = "0xTestAddress"
        c._builder = None
        c.demo_mode = False
        return c


# ── cancel_tp_only ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_tp_only_targets_only_tp_trigger_orders(client):
    """Only the TP-trigger oid should be sent to cancel; SL + limit untouched."""
    client._info.frontend_open_orders = MagicMock(return_value=[
        {
            "coin": "BTC",
            "oid": 1111,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Take Profit Market",
            "side": "A",
            "triggerPx": "72500",
        },
        {
            "coin": "BTC",
            "oid": 2222,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Stop Market",
            "side": "A",
            "triggerPx": "68000",
        },
        {
            "coin": "BTC",
            "oid": 3333,
            "isTrigger": False,
            "isPositionTpsl": False,
            "orderType": "Limit",
            "side": "B",
            "limitPx": "69000",
        },
    ])
    cancelled = []
    client._exchange.cancel = MagicMock(
        side_effect=lambda coin, oid: cancelled.append((coin, oid)),
    )

    result = await client.cancel_tp_only("BTC", side="long")

    assert result is True
    assert cancelled == [("BTC", 1111)]


@pytest.mark.asyncio
async def test_cancel_sl_only_targets_only_sl_trigger_orders(client):
    """Mirror of cancel_tp_only — only the SL-trigger oid is cancelled."""
    client._info.frontend_open_orders = MagicMock(return_value=[
        {
            "coin": "ETH",
            "oid": 1111,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Take Profit Market",
            "side": "A",
            "triggerPx": "3200",
        },
        {
            "coin": "ETH",
            "oid": 2222,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Stop Loss Market",
            "side": "A",
            "triggerPx": "2800",
        },
        {
            "coin": "ETH",
            "oid": 3333,
            "isTrigger": False,
            "isPositionTpsl": False,
            "orderType": "Limit",
            "side": "B",
            "limitPx": "3000",
        },
    ])
    cancelled = []
    client._exchange.cancel = MagicMock(
        side_effect=lambda coin, oid: cancelled.append((coin, oid)),
    )

    result = await client.cancel_sl_only("ETH", side="long")

    assert result is True
    assert cancelled == [("ETH", 2222)]


@pytest.mark.asyncio
async def test_cancel_tp_only_no_triggers_returns_true(client):
    """Empty openOrders → nothing to cancel → still True (best-effort)."""
    client._info.frontend_open_orders = MagicMock(return_value=[])
    client._exchange.cancel = MagicMock()

    assert await client.cancel_tp_only("BTC", side="long") is True
    client._exchange.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_sl_only_no_triggers_returns_true(client):
    """Empty openOrders → SL variant also returns True without side effects."""
    client._info.frontend_open_orders = MagicMock(return_value=[])
    client._exchange.cancel = MagicMock()

    assert await client.cancel_sl_only("BTC", side="long") is True
    client._exchange.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_tp_only_ignores_other_coins(client):
    """Triggers on another coin must not be cancelled even if they are TP."""
    client._info.frontend_open_orders = MagicMock(return_value=[
        {
            "coin": "BTC",
            "oid": 1111,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Take Profit Market",
            "side": "A",
            "triggerPx": "72500",
        },
        {
            "coin": "ETH",
            "oid": 2222,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Take Profit Market",
            "side": "A",
            "triggerPx": "3200",
        },
    ])
    cancelled = []
    client._exchange.cancel = MagicMock(
        side_effect=lambda coin, oid: cancelled.append((coin, oid)),
    )

    await client.cancel_tp_only("BTC", side="long")

    assert cancelled == [("BTC", 1111)]


@pytest.mark.asyncio
async def test_cancel_tp_only_query_failure_returns_false(client):
    """API failure on frontend_open_orders → False (not silently True)."""
    client._info.frontend_open_orders = MagicMock(side_effect=Exception("boom"))

    assert await client.cancel_tp_only("BTC", side="long") is False


@pytest.mark.asyncio
async def test_cancel_tp_only_matches_existing_get_position_tpsl_mapping(client):
    """Consistency contract: whichever order ``get_position_tpsl`` returns
    as the TP must also be the one ``cancel_tp_only`` targets.

    This guards against drift in the TP/SL classification between the two
    methods — a TP that's "seen" by the readback but not cancelled by the
    leg-clear would leave the dashboard stuck in a desync state.
    """
    orders = [
        {
            "coin": "BTC",
            "oid": 4242,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Take Profit Market",
            "side": "A",
            "triggerPx": "75000",
            "limitPx": "75000",
        },
        {
            "coin": "BTC",
            "oid": 5353,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Stop Loss Market",
            "side": "A",
            "triggerPx": "65000",
            "limitPx": "65000",
        },
    ]
    client._info.frontend_open_orders = MagicMock(return_value=orders)

    snap = await client.get_position_tpsl("BTC", "long")
    assert snap.tp_order_id == "4242"
    assert snap.sl_order_id == "5353"

    cancelled_tp = []
    client._exchange.cancel = MagicMock(
        side_effect=lambda coin, oid: cancelled_tp.append(oid),
    )
    await client.cancel_tp_only("BTC", side="long")
    assert cancelled_tp == [int(snap.tp_order_id)]

    cancelled_sl = []
    client._exchange.cancel = MagicMock(
        side_effect=lambda coin, oid: cancelled_sl.append(oid),
    )
    await client.cancel_sl_only("BTC", side="long")
    assert cancelled_sl == [int(snap.sl_order_id)]


@pytest.mark.asyncio
async def test_cancel_tp_only_partial_failure_still_returns_true(client):
    """If one cancel raises, remaining cancels still attempted; return True."""
    client._info.frontend_open_orders = MagicMock(return_value=[
        {
            "coin": "BTC",
            "oid": 1111,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Take Profit Market",
            "side": "A",
            "triggerPx": "72500",
        },
        {
            "coin": "BTC",
            "oid": 2222,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Take Profit Market",
            "side": "A",
            "triggerPx": "73000",
        },
    ])
    attempts = []

    def flaky_cancel(coin, oid):
        attempts.append(oid)
        if oid == 1111:
            raise Exception("cancel timeout")

    client._exchange.cancel = MagicMock(side_effect=flaky_cancel)

    assert await client.cancel_tp_only("BTC", side="long") is True
    assert attempts == [1111, 2222]
