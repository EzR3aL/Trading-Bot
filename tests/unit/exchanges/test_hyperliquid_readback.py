"""Tests for Hyperliquid risk-state readback methods (#191).

Covers ``get_position_tpsl``, ``get_trailing_stop`` (always None on HL),
and ``get_close_reason_from_history`` by mocking the SDK's Info endpoints.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.base import (
    CloseReasonSnapshot,
    PositionTpSlSnapshot,
)


@pytest.fixture
def client():
    """HyperliquidClient with mocked SDK."""
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


# ==================== get_position_tpsl ====================


@pytest.mark.asyncio
async def test_get_position_tpsl_returns_both_tp_and_sl(client):
    """Active TP+SL triggers on a long position → populated snapshot.

    For a LONG position, close orders are SELL (HL side='A').
    """

    client._info.frontend_open_orders = MagicMock(return_value=[
        {
            "coin": "BTC",
            "oid": 1111,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Take Profit Market",
            "side": "A",  # ask = sell
            "triggerPx": "72500.5",
            "limitPx": "72500.5",
        },
        {
            "coin": "BTC",
            "oid": 2222,
            "isTrigger": True,
            "isPositionTpsl": True,
            "orderType": "Stop Loss Market",
            "side": "A",
            "triggerPx": "68000.0",
            "limitPx": "68000.0",
        },
    ])

    snap = await client.get_position_tpsl("BTCUSDT", "long")

    assert isinstance(snap, PositionTpSlSnapshot)
    assert snap.symbol == "BTC"  # normalized from BTCUSDT
    assert snap.side == "long"
    assert snap.tp_price == 72500.5
    assert snap.tp_order_id == "1111"
    assert snap.sl_price == 68000.0
    assert snap.sl_order_id == "2222"


@pytest.mark.asyncio
async def test_get_position_tpsl_with_only_tp_sets_sl_fields_to_none(client):
    """Only a TP trigger → sl_price None."""

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
    ])

    snap = await client.get_position_tpsl("BTC", "long")
    assert snap.tp_price == 72500.0
    assert snap.tp_order_id == "1111"
    assert snap.sl_price is None
    assert snap.sl_order_id is None


@pytest.mark.asyncio
async def test_get_position_tpsl_with_no_triggers_returns_empty_snapshot(client):
    """No trigger orders → empty snapshot."""

    client._info.frontend_open_orders = MagicMock(return_value=[])

    snap = await client.get_position_tpsl("BTC", "long")
    assert isinstance(snap, PositionTpSlSnapshot)
    assert snap.tp_price is None
    assert snap.sl_price is None


# ==================== get_trailing_stop ====================


@pytest.mark.asyncio
async def test_get_trailing_stop_always_returns_none_on_hyperliquid(client):
    """HL has no native trailing primitive → always None."""

    result = await client.get_trailing_stop("BTC", "long")
    assert result is None


# ==================== get_close_reason_from_history ====================


@pytest.mark.asyncio
async def test_get_close_reason_from_history_returns_manual_close(client):
    """Recent 'Close Long' fill → plan_type=manual (no isTpsl flag)."""

    client._info.user_fills = MagicMock(return_value=[
        {
            "coin": "BTC",
            "oid": 9999,
            "dir": "Close Long",
            "px": "70000",
            "time": 1710001000000,
        },
    ])

    snap = await client.get_close_reason_from_history("BTC", since_ts_ms=1700000000000)

    assert isinstance(snap, CloseReasonSnapshot)
    assert snap.symbol == "BTC"
    assert snap.closed_by_plan_type == "manual"
    assert snap.closed_by_order_id == "9999"
    assert snap.fill_price == 70000.0
    assert snap.closed_at is not None


@pytest.mark.asyncio
async def test_close_reason_returns_tpsl_ambiguous_for_isTpsl_fill(client):
    """isTpsl fills cannot be split TP-vs-SL at the fill level on HL (issue #224).

    The adapter now emits ``tpsl_ambiguous`` so RiskStateManager can
    disambiguate via order-id match or price crossover instead of the
    previous blind ``pos_profit`` default.
    """
    client._info.user_fills = MagicMock(return_value=[
        {
            "coin": "BTC",
            "oid": 7777,
            "dir": "Close Long",
            "isTpsl": True,
            "px": "68000",
            "time": 1710001000000,
        },
    ])

    snap = await client.get_close_reason_from_history("BTC", since_ts_ms=1700000000000)
    assert snap is not None
    assert snap.closed_by_plan_type == "tpsl_ambiguous"
    assert snap.closed_by_order_id == "7777"


@pytest.mark.asyncio
async def test_close_reason_filters_by_until_ts_ms(client):
    """Fills past until_ts_ms are filtered client-side (issue #224, backfill)."""
    client._info.user_fills = MagicMock(return_value=[
        # Past the window — must be skipped.
        {"coin": "BTC", "oid": 1, "dir": "Close Long", "px": "70000", "time": 1720000000000},
        # Inside the window — must be picked.
        {"coin": "BTC", "oid": 2, "dir": "Close Long", "px": "68000", "time": 1710001000000},
    ])

    snap = await client.get_close_reason_from_history(
        "BTC", since_ts_ms=1700000000000, until_ts_ms=1715000000000,
    )
    assert snap is not None
    assert snap.closed_by_order_id == "2"
    assert snap.fill_price == 68000.0


@pytest.mark.asyncio
async def test_close_reason_isolates_sdk_probe_failure(client):
    """SDK failure on user_fills must not bubble — returns None (issue #224)."""
    client._info.user_fills = MagicMock(side_effect=RuntimeError("HL SDK transient"))

    snap = await client.get_close_reason_from_history("BTC", since_ts_ms=1700000000000)
    assert snap is None
