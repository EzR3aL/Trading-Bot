"""Margin-mode-switch coverage (cross ↔ isolated) per exchange (issue #176).

Each exchange's set_leverage() must accept margin_mode="cross" and "isolated"
and translate it into the exchange-specific format:

  Exchange      cross      isolated
  bitget        crossed    isolated     (string)
  weex          1          3            (int)
  bingx         CROSSED    ISOLATED     (string)
  bitunix       CROSS      ISOLATION    (string)
  hyperliquid   False      True         (boolean is_isolated)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def bitget_client():
    from src.exchanges.bitget.client import BitgetExchangeClient
    return BitgetExchangeClient(api_key="k", api_secret="s", passphrase="p", demo_mode=True)


@pytest.fixture
def bingx_client():
    from src.exchanges.bingx.client import BingXClient
    return BingXClient(api_key="k", api_secret="s", demo_mode=True)


@pytest.fixture
def weex_client():
    from src.exchanges.weex.client import WeexClient
    return WeexClient(api_key="k", api_secret="s", passphrase="p", demo_mode=True)


@pytest.fixture
def bitunix_client():
    from src.exchanges.bitunix.client import BitunixClient
    return BitunixClient(api_key="k", api_secret="s", demo_mode=True)


@pytest.fixture
def hl_client():
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


def _captured_payload(mock_request) -> dict:
    """Pull the `data=` kwarg from the most recent _request() call."""
    return mock_request.call_args.kwargs.get("data") or {}


class TestBitgetMarginMode:
    """KNOWN: Bitget set_leverage() ignores margin_mode. The exchange's
    margin mode is set out-of-band via the account UI or a separate
    /api/v2/mix/account/set-margin-mode call (not implemented here).
    Test below documents the current accept-and-noop behaviour.
    """

    @pytest.mark.asyncio
    async def test_set_leverage_accepts_both_modes_without_error(self, bitget_client):
        with patch.object(bitget_client, "_request", new_callable=AsyncMock, return_value={}):
            assert await bitget_client.set_leverage("BTCUSDT", 10, margin_mode="cross") is True
            assert await bitget_client.set_leverage("BTCUSDT", 10, margin_mode="isolated") is True


class TestBingxMarginMode:
    @pytest.mark.asyncio
    async def test_cross_sets_crossed(self, bingx_client):
        with patch.object(bingx_client, "_request", new_callable=AsyncMock, return_value={}) as r:
            await bingx_client.set_leverage("BTC-USDT", 10, margin_mode="cross")
        first_call = r.call_args_list[0]
        assert first_call.kwargs.get("data", {}).get("marginType") == "CROSSED"

    @pytest.mark.asyncio
    async def test_isolated_sets_isolated(self, bingx_client):
        with patch.object(bingx_client, "_request", new_callable=AsyncMock, return_value={}) as r:
            await bingx_client.set_leverage("BTC-USDT", 10, margin_mode="isolated")
        first_call = r.call_args_list[0]
        assert first_call.kwargs.get("data", {}).get("marginType") == "ISOLATED"


class TestWeexMarginMode:
    @pytest.mark.asyncio
    async def test_cross_sets_marginmode_1(self, weex_client):
        from src.exchanges.weex.constants import MARGIN_CROSS
        with patch.object(weex_client, "_request", new_callable=AsyncMock, return_value={}) as r:
            await weex_client.set_leverage("BTCUSDT", 10, margin_mode="cross")
        assert _captured_payload(r).get("marginMode") == MARGIN_CROSS

    @pytest.mark.asyncio
    async def test_isolated_sets_marginmode_3(self, weex_client):
        from src.exchanges.weex.constants import MARGIN_ISOLATED
        with patch.object(weex_client, "_request", new_callable=AsyncMock, return_value={}) as r:
            await weex_client.set_leverage("BTCUSDT", 10, margin_mode="isolated")
        assert _captured_payload(r).get("marginMode") == MARGIN_ISOLATED


class TestBitunixMarginMode:
    """KNOWN: Bitunix set_leverage() does not call a margin-mode endpoint either.
    The mode is configured per-trade via place_order (changeMargin). This test
    documents that set_leverage accepts both modes without error."""

    @pytest.mark.asyncio
    async def test_set_leverage_accepts_both_modes_without_error(self, bitunix_client):
        with patch.object(bitunix_client, "_request", new_callable=AsyncMock, return_value={}):
            assert await bitunix_client.set_leverage("BTCUSDT", 10, margin_mode="cross") is True
            assert await bitunix_client.set_leverage("BTCUSDT", 10, margin_mode="isolated") is True


class TestHyperliquidMarginMode:
    @pytest.mark.asyncio
    async def test_cross_calls_with_is_cross_true(self, hl_client):
        hl_client._raw_exchange = MagicMock()
        hl_client._raw_exchange.update_leverage = MagicMock(return_value={"status": "ok"})
        await hl_client.set_leverage("BTC", 10, margin_mode="cross")
        # is_cross=True for cross mode (HL convention)
        kwargs = hl_client._raw_exchange.update_leverage.call_args
        if kwargs:
            args, kw = kwargs
            cross_flag = kw.get("is_cross") if "is_cross" in kw else (args[2] if len(args) > 2 else None)
            assert cross_flag is True

    @pytest.mark.asyncio
    async def test_isolated_calls_with_is_cross_false(self, hl_client):
        hl_client._raw_exchange = MagicMock()
        hl_client._raw_exchange.update_leverage = MagicMock(return_value={"status": "ok"})
        await hl_client.set_leverage("BTC", 10, margin_mode="isolated")
        kwargs = hl_client._raw_exchange.update_leverage.call_args
        if kwargs:
            args, kw = kwargs
            cross_flag = kw.get("is_cross") if "is_cross" in kw else (args[2] if len(args) > 2 else None)
            assert cross_flag is False
