"""Tests for src/exchanges/factory.py - exchange client factory."""

from unittest.mock import patch, MagicMock

import pytest

from src.exchanges.factory import (
    create_exchange_client,
    get_exchange_info,
    get_supported_exchanges,
)


class TestCreateExchangeClient:
    @patch("src.exchanges.factory.BitgetExchangeClient", create=True)
    @patch("src.exchanges.bitget.client.BitgetExchangeClient", create=True)
    def test_create_bitget_client(self, mock_cls_module, mock_cls_factory):
        """Factory returns a BitgetExchangeClient for exchange_type='bitget'."""
        # The factory does a lazy import, so we patch at the source module
        mock_instance = MagicMock()
        mock_cls_module.return_value = mock_instance

        with patch(
            "src.exchanges.bitget.client.BitgetExchangeClient",
            return_value=mock_instance,
        ):
            client = create_exchange_client(
                exchange_type="bitget",
                api_key="key",
                api_secret="secret",
                passphrase="pass",
                demo_mode=True,
            )
        assert client is mock_instance

    @patch("src.exchanges.weex.client.WeexClient", create=True)
    def test_create_weex_client(self, mock_cls):
        """Factory returns a WeexClient for exchange_type='weex'."""
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        client = create_exchange_client(
            exchange_type="weex",
            api_key="key",
            api_secret="secret",
            passphrase="pass",
            demo_mode=True,
        )
        assert client is mock_instance

    @patch("src.exchanges.hyperliquid.client.HyperliquidClient", create=True)
    def test_create_hyperliquid_client(self, mock_cls):
        """Factory returns a HyperliquidClient for exchange_type='hyperliquid'."""
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        client = create_exchange_client(
            exchange_type="hyperliquid",
            api_key="key",
            api_secret="secret",
            demo_mode=True,
        )
        assert client is mock_instance

    @patch("src.exchanges.bitunix.client.BitunixClient.__init__", return_value=None)
    def test_create_bitunix_client(self, mock_cls):
        """Factory returns a BitunixClient for exchange_type='bitunix'."""
        client = create_exchange_client(
            exchange_type="bitunix",
            api_key="key",
            api_secret="secret",
            passphrase="pass",
            demo_mode=True,
        )
        assert client is not None

    @patch("src.exchanges.bingx.client.BingXClient.__init__", return_value=None)
    def test_create_bingx_client(self, mock_cls):
        """Factory returns a BingXClient for exchange_type='bingx'."""
        client = create_exchange_client(
            exchange_type="bingx",
            api_key="key",
            api_secret="secret",
            demo_mode=True,
        )
        assert client is not None

    def test_create_unsupported_exchange_raises(self):
        """Requesting an unsupported exchange must raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported exchange"):
            create_exchange_client(
                exchange_type="kraken",
                api_key="key",
                api_secret="secret",
            )


class TestGetSupportedExchanges:
    def test_get_supported_exchanges(self):
        """Should return all supported exchange identifiers."""
        exchanges = get_supported_exchanges()
        assert exchanges == ["bitget", "weex", "hyperliquid", "bitunix", "bingx"]


class TestGetExchangeInfo:
    def test_get_exchange_info_bitget(self):
        """get_exchange_info('bitget') returns correct metadata."""
        info = get_exchange_info("bitget")
        assert info["name"] == "bitget"
        assert info["display_name"] == "Bitget"
        assert info["supports_demo"] is True
        assert info["requires_passphrase"] is True

    def test_get_exchange_info_bitunix(self):
        """get_exchange_info('bitunix') returns correct metadata."""
        info = get_exchange_info("bitunix")
        assert info["name"] == "bitunix"
        assert info["display_name"] == "Bitunix"
        assert info["requires_passphrase"] is True

    def test_get_exchange_info_bingx(self):
        """get_exchange_info('bingx') returns correct metadata."""
        info = get_exchange_info("bingx")
        assert info["name"] == "bingx"
        assert info["display_name"] == "BingX"

    def test_get_exchange_info_unknown_raises(self):
        """Requesting info for an unknown exchange must raise ValueError."""
        with pytest.raises(ValueError, match="Unknown exchange"):
            get_exchange_info("kraken")
