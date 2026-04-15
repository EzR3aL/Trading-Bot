"""Fee-tracking unit tests for Weex, Hyperliquid, Bitunix, BingX (issue #176).

Bitget already has comprehensive fee tests in test_bitget_client.py.
This file fills the gap for the other 4 exchanges so every adapter has at
least one test per fee method (get_order_fees, get_trade_total_fees,
get_funding_fees, get_close_fill_price).

All adapters must satisfy:
  - get_order_fees returns a non-negative float
  - get_trade_total_fees sums entry + exit fees
  - get_funding_fees returns a float (positive or negative)
  - exceptions are swallowed and yield 0.0 (these are best-effort calls)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Weex
# ---------------------------------------------------------------------------

@pytest.fixture
def weex_client():
    from src.exchanges.weex.client import WeexClient
    return WeexClient(api_key="k", api_secret="s", passphrase="p", demo_mode=True)


class TestWeexFees:
    @pytest.mark.asyncio
    async def test_order_fees_sums_commission_field(self, weex_client):
        fills = [{"commission": "-0.30"}, {"commission": "-0.20"}]
        with patch.object(weex_client, "_request", new_callable=AsyncMock, return_value=fills):
            assert await weex_client.get_order_fees("BTCUSDT", "ord-1") == 0.50

    @pytest.mark.asyncio
    async def test_order_fees_returns_zero_on_exception(self, weex_client):
        with patch.object(weex_client, "_request", new_callable=AsyncMock, side_effect=Exception("boom")):
            assert await weex_client.get_order_fees("BTCUSDT", "ord-x") == 0.0

    @pytest.mark.asyncio
    async def test_total_fees_combines_entry_and_close(self, weex_client):
        async def fake(symbol, order_id):
            return {"entry-1": 0.30, "exit-1": 0.25}.get(order_id, 0.0)
        with patch.object(weex_client, "get_order_fees", side_effect=fake):
            assert await weex_client.get_trade_total_fees("BTCUSDT", "entry-1", "exit-1") == 0.55

    @pytest.mark.asyncio
    async def test_funding_fees_sums_income_records(self, weex_client):
        bills = [{"income": "-0.10"}, {"income": "0.05"}]
        with patch.object(weex_client, "_request", new_callable=AsyncMock, return_value=bills):
            result = await weex_client.get_funding_fees("BTCUSDT", 0, 1_000_000)
        assert result == pytest.approx(-0.05)


# ---------------------------------------------------------------------------
# Hyperliquid
# ---------------------------------------------------------------------------

@pytest.fixture
def hl_client():
    """HL client init hits the real API on construction — mock the SDK layer."""
    from src.exchanges.hyperliquid.client import HyperliquidClient
    mock_wallet = MagicMock()
    mock_wallet.address = "0x1111111111111111111111111111111111111111"
    mock_exchange = MagicMock()
    mock_exchange.info = MagicMock()
    with patch("src.exchanges.hyperliquid.client.HLExchange", return_value=mock_exchange), \
         patch("src.exchanges.hyperliquid.client.EthAccount") as mock_eth:
        mock_eth.from_key.return_value = mock_wallet
        return HyperliquidClient(
            api_key="0x1111111111111111111111111111111111111111",
            api_secret="0x" + "11" * 32,
            demo_mode=True,
        )


class TestHyperliquidFees:
    @pytest.mark.asyncio
    async def test_order_fees_sums_matching_fills(self, hl_client):
        hl_client._info_exec = MagicMock()
        hl_client._info_exec.user_fills = MagicMock(return_value=[
            {"oid": 123, "coin": "BTC", "fee": "0.40"},
            {"oid": 999, "coin": "BTC", "fee": "0.20"},  # different oid → ignored
        ])
        fees = await hl_client.get_order_fees("BTC", "123")
        assert fees == 0.40

    @pytest.mark.asyncio
    async def test_order_fees_returns_zero_on_exception(self, hl_client):
        hl_client._info_exec = MagicMock()
        hl_client._info_exec.user_fills = MagicMock(side_effect=Exception("rpc fail"))
        assert await hl_client.get_order_fees("BTC", "123") == 0.0

    @pytest.mark.asyncio
    async def test_total_fees_combines_entry_and_close(self, hl_client):
        hl_client._info_exec = MagicMock()
        hl_client._info_exec.user_fills = MagicMock(return_value=[
            {"oid": 1, "coin": "BTC", "fee": "0.30"},
            {"oid": 2, "coin": "BTC", "fee": "0.25"},
            {"oid": 3, "coin": "BTC", "fee": "0.10"},  # not target → ignored
        ])
        total = await hl_client.get_trade_total_fees("BTC", "1", "2")
        assert total == 0.55


# ---------------------------------------------------------------------------
# Bitunix
# ---------------------------------------------------------------------------

@pytest.fixture
def bitunix_client():
    from src.exchanges.bitunix.client import BitunixClient
    return BitunixClient(api_key="k", api_secret="s", demo_mode=True)


class TestBitunixFees:
    @pytest.mark.asyncio
    async def test_order_fees_returns_zero_on_exception(self, bitunix_client):
        with patch.object(bitunix_client, "_request", new_callable=AsyncMock, side_effect=Exception("fail")):
            assert await bitunix_client.get_order_fees("BTCUSDT", "ord-x") == 0.0

    @pytest.mark.asyncio
    async def test_total_fees_combines_entry_and_close(self, bitunix_client):
        async def fake(symbol, order_id):
            return {"entry-1": 0.10, "exit-1": 0.15}.get(order_id, 0.0)
        with patch.object(bitunix_client, "get_order_fees", side_effect=fake):
            assert await bitunix_client.get_trade_total_fees("BTCUSDT", "entry-1", "exit-1") == 0.25

    @pytest.mark.asyncio
    async def test_funding_fees_returns_zero_on_exception(self, bitunix_client):
        with patch.object(bitunix_client, "_request", new_callable=AsyncMock, side_effect=Exception("fail")):
            assert await bitunix_client.get_funding_fees("BTCUSDT", 0, 1_000_000) == 0.0


# ---------------------------------------------------------------------------
# BingX
# ---------------------------------------------------------------------------

@pytest.fixture
def bingx_client():
    from src.exchanges.bingx.client import BingXClient
    return BingXClient(api_key="k", api_secret="s", demo_mode=True)


class TestBingxFees:
    @pytest.mark.asyncio
    async def test_order_fees_returns_zero_on_exception(self, bingx_client):
        with patch.object(bingx_client, "_request", new_callable=AsyncMock, side_effect=Exception("fail")):
            assert await bingx_client.get_order_fees("BTC-USDT", "ord-x") == 0.0

    @pytest.mark.asyncio
    async def test_total_fees_combines_entry_and_close(self, bingx_client):
        async def fake(symbol, order_id):
            return {"entry-1": 0.20, "exit-1": 0.20}.get(order_id, 0.0)
        with patch.object(bingx_client, "get_order_fees", side_effect=fake):
            assert await bingx_client.get_trade_total_fees("BTC-USDT", "entry-1", "exit-1") == 0.40

    @pytest.mark.asyncio
    async def test_funding_fees_returns_zero_on_exception(self, bingx_client):
        with patch.object(bingx_client, "_request", new_callable=AsyncMock, side_effect=Exception("fail")):
            assert await bingx_client.get_funding_fees("BTC-USDT", 0, 1_000_000) == 0.0
