"""Tests for exchange factory module."""

from unittest.mock import patch

import pytest

from src.exchanges.factory import (
    create_exchange_client,
    create_exchange_websocket,
    get_supported_exchanges,
    get_exchange_info,
)


class TestCreateExchangeClient:
    """Tests for create_exchange_client."""

    @patch("src.exchanges.factory.BitgetExchangeClient", create=True)
    def test_creates_bitget_client(self, _mock):
        from src.exchanges.bitget.client import BitgetExchangeClient

        with patch(
            "src.exchanges.factory.BitgetExchangeClient",
            BitgetExchangeClient,
            create=True,
        ):
            client = create_exchange_client(
                "bitget", api_key="k", api_secret="s", passphrase="p", demo_mode=True
            )
        assert client is not None

    @patch("src.exchanges.weex.client.WeexClient.__init__", return_value=None)
    def test_creates_weex_client(self, mock_init):
        client = create_exchange_client(
            "weex", api_key="k", api_secret="s", passphrase="p", demo_mode=True
        )
        assert client is not None

    @patch("src.exchanges.hyperliquid.client.HyperliquidClient.__init__", return_value=None)
    def test_creates_hyperliquid_client(self, mock_init):
        client = create_exchange_client(
            "hyperliquid", api_key="k", api_secret="s", demo_mode=True
        )
        assert client is not None

    def test_unsupported_exchange_raises(self):
        with pytest.raises(ValueError, match="Unsupported exchange.*kraken"):
            create_exchange_client("kraken", api_key="k", api_secret="s")


class TestCreateExchangeWebsocket:
    """Tests for create_exchange_websocket."""

    @patch("src.exchanges.bitget.websocket.BitgetExchangeWebSocket.__init__", return_value=None)
    def test_creates_bitget_websocket(self, mock_init):
        ws = create_exchange_websocket("bitget", api_key="k", api_secret="s")
        assert ws is not None

    @patch("src.exchanges.weex.websocket.WeexWebSocket.__init__", return_value=None)
    def test_creates_weex_websocket(self, mock_init):
        ws = create_exchange_websocket("weex", api_key="k", api_secret="s")
        assert ws is not None

    @patch("src.exchanges.hyperliquid.websocket.HyperliquidWebSocket.__init__", return_value=None)
    def test_creates_hyperliquid_websocket(self, mock_init):
        ws = create_exchange_websocket("hyperliquid", api_key="k", api_secret="s")
        assert ws is not None

    def test_unsupported_exchange_raises(self):
        with pytest.raises(ValueError, match="Unsupported exchange.*binance"):
            create_exchange_websocket("binance")


class TestGetSupportedExchanges:
    """Tests for get_supported_exchanges."""

    def test_returns_all_five(self):
        result = get_supported_exchanges()
        assert "bitget" in result
        assert "weex" in result
        assert "hyperliquid" in result
        assert "bitunix" in result
        assert "bingx" in result
        assert len(result) == 5


class TestGetExchangeInfo:
    """Tests for get_exchange_info."""

    def test_bitget_info(self):
        info = get_exchange_info("bitget")
        assert info["name"] == "bitget"
        assert info["display_name"] == "Bitget"
        assert info["requires_passphrase"] is True
        assert info["supports_demo"] is True

    def test_weex_info(self):
        info = get_exchange_info("weex")
        assert info["name"] == "weex"
        assert info["requires_passphrase"] is True

    def test_hyperliquid_info(self):
        info = get_exchange_info("hyperliquid")
        assert info["name"] == "hyperliquid"
        assert info["auth_type"] == "eth_wallet"
        assert info["requires_passphrase"] is False

    def test_unknown_exchange_raises(self):
        with pytest.raises(ValueError, match="Unknown exchange"):
            get_exchange_info("ftx")
