"""Tests for src/exchanges/symbol_map.py - symbol normalization across exchanges."""

from src.exchanges.symbol_map import (
    get_supported_symbols,
    normalize_symbol,
    to_exchange_symbol,
)


class TestNormalizeSymbol:
    def test_normalize_symbol_bitget(self):
        """Bitget's 'BTCUSDT' normalizes to 'BTC'."""
        assert normalize_symbol("BTCUSDT", "bitget") == "BTC"

    def test_normalize_symbol_weex(self):
        """Weex's 'BTC/USDT:USDT' normalizes to 'BTC'."""
        assert normalize_symbol("BTC/USDT:USDT", "weex") == "BTC"

    def test_normalize_symbol_hyperliquid(self):
        """Hyperliquid's 'BTC' normalizes to 'BTC'."""
        assert normalize_symbol("BTC", "hyperliquid") == "BTC"

    def test_normalize_unknown_symbol_fallback(self):
        """An unknown Bitget symbol falls back to stripping the USDT suffix."""
        assert normalize_symbol("FOOUSDT", "bitget") == "FOO"


class TestToExchangeSymbol:
    def test_to_exchange_symbol_bitget(self):
        """'BTC' converts to 'BTCUSDT' for Bitget."""
        assert to_exchange_symbol("BTC", "bitget") == "BTCUSDT"

    def test_to_exchange_symbol_weex(self):
        """'BTC' converts to 'BTC/USDT:USDT' for Weex."""
        assert to_exchange_symbol("BTC", "weex") == "BTC/USDT:USDT"

    def test_to_exchange_symbol_hyperliquid(self):
        """'BTC' converts to 'BTC' for Hyperliquid."""
        assert to_exchange_symbol("BTC", "hyperliquid") == "BTC"


class TestGetSupportedSymbols:
    def test_get_supported_symbols(self):
        """get_supported_symbols should return a list that includes BTC and ETH."""
        symbols = get_supported_symbols("bitget")
        assert isinstance(symbols, list)
        assert "BTC" in symbols
        assert "ETH" in symbols
        assert len(symbols) >= 10
