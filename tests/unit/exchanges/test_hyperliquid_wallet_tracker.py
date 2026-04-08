"""Tests for the read-only Hyperliquid wallet tracker."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.exchanges.hyperliquid.wallet_tracker import (
    HyperliquidWalletTracker,
    SourceFill,
    SourcePosition,
)


@pytest.fixture
def mock_info():
    """Mock the HL Info SDK object."""
    info = MagicMock()
    info.user_state = MagicMock(return_value={
        "assetPositions": [
            {
                "position": {
                    "coin": "BTC",
                    "szi": "0.5",  # positive = long, negative = short
                    "entryPx": "67000",
                    "leverage": {"value": 5, "type": "cross"},
                }
            }
        ]
    })
    info.user_fills = MagicMock(return_value=[
        {
            "coin": "BTC",
            "side": "B",  # B=buy/long, A=ask/short
            "sz": "0.5",
            "px": "67000",
            "time": 1712568000000,
            "dir": "Open Long",
            "hash": "0xabc",
        },
        {
            "coin": "ETH",
            "side": "A",
            "sz": "5",
            "px": "3500",
            "time": 1712567000000,
            "dir": "Open Short",
            "hash": "0xdef",
        },
    ])
    return info


@pytest.mark.asyncio
async def test_get_open_positions_normalizes_long(mock_info):
    tracker = HyperliquidWalletTracker(info=mock_info)
    positions = await tracker.get_open_positions("0x1234")
    assert len(positions) == 1
    p = positions[0]
    assert p.coin == "BTC"
    assert p.side == "long"
    assert p.size == 0.5
    assert p.entry_price == 67000.0
    assert p.leverage == 5


@pytest.mark.asyncio
async def test_get_open_positions_normalizes_short(mock_info):
    mock_info.user_state.return_value = {
        "assetPositions": [
            {"position": {"coin": "ETH", "szi": "-2.0",
                          "entryPx": "3500", "leverage": {"value": 10}}}
        ]
    }
    tracker = HyperliquidWalletTracker(info=mock_info)
    positions = await tracker.get_open_positions("0x1234")
    assert positions[0].side == "short"
    assert positions[0].size == 2.0


@pytest.mark.asyncio
async def test_get_fills_since_filters_by_timestamp(mock_info):
    tracker = HyperliquidWalletTracker(info=mock_info)
    # since_ms is between the two fills (BTC at 1712568000000, ETH at 1712567000000)
    fills = await tracker.get_fills_since("0x1234", since_ms=1712567500000)
    assert len(fills) == 1
    assert fills[0].coin == "BTC"
    assert fills[0].side == "long"
    assert fills[0].is_entry is True


@pytest.mark.asyncio
async def test_get_fills_since_returns_empty_when_no_new(mock_info):
    tracker = HyperliquidWalletTracker(info=mock_info)
    fills = await tracker.get_fills_since("0x1234", since_ms=9999999999999)
    assert fills == []


@pytest.mark.asyncio
async def test_recent_coins_returns_unique_set(mock_info):
    tracker = HyperliquidWalletTracker(info=mock_info)
    coins = await tracker.recent_coins("0x1234", since_ms=0)
    assert sorted(coins) == ["BTC", "ETH"]


@pytest.mark.asyncio
async def test_get_open_positions_handles_no_positions(mock_info):
    mock_info.user_state.return_value = {"assetPositions": []}
    tracker = HyperliquidWalletTracker(info=mock_info)
    positions = await tracker.get_open_positions("0x1234")
    assert positions == []
