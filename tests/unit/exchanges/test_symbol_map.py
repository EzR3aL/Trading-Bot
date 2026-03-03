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
        """Weex's 'BTCUSDT' normalizes to 'BTC'."""
        assert normalize_symbol("BTCUSDT", "weex") == "BTC"

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
        """'BTC' converts to 'BTCUSDT' for Weex."""
        assert to_exchange_symbol("BTC", "weex") == "BTCUSDT"

    def test_to_exchange_symbol_hyperliquid(self):
        """'BTC' converts to 'BTC' for Hyperliquid."""
        assert to_exchange_symbol("BTC", "hyperliquid") == "BTC"


class TestNormalizeSymbolBitunix:
    def test_normalize_symbol_bitunix(self):
        """Bitunix's 'BTCUSDT' normalizes to 'BTC'."""
        assert normalize_symbol("BTCUSDT", "bitunix") == "BTC"

    def test_normalize_unknown_bitunix_fallback(self):
        """An unknown Bitunix symbol falls back to stripping USDT suffix."""
        assert normalize_symbol("FOOUSDT", "bitunix") == "FOO"


class TestNormalizeSymbolBingX:
    def test_normalize_symbol_bingx(self):
        """BingX's 'BTC-USDT' normalizes to 'BTC'."""
        assert normalize_symbol("BTC-USDT", "bingx") == "BTC"

    def test_normalize_unknown_bingx_fallback(self):
        """An unknown BingX symbol falls back to splitting on hyphen."""
        assert normalize_symbol("FOO-USDT", "bingx") == "FOO"


class TestToExchangeSymbolBitunix:
    def test_to_exchange_symbol_bitunix(self):
        """'BTC' converts to 'BTCUSDT' for Bitunix."""
        assert to_exchange_symbol("BTC", "bitunix") == "BTCUSDT"


class TestToExchangeSymbolBingX:
    def test_to_exchange_symbol_bingx(self):
        """'BTC' converts to 'BTC-USDT' for BingX."""
        assert to_exchange_symbol("BTC", "bingx") == "BTC-USDT"


class TestGetSupportedSymbols:
    def test_get_supported_symbols(self):
        """get_supported_symbols should return a list that includes BTC and ETH."""
        symbols = get_supported_symbols("bitget")
        assert isinstance(symbols, list)
        assert "BTC" in symbols
        assert "ETH" in symbols
        assert len(symbols) >= 10

    def test_get_supported_symbols_bitunix(self):
        """get_supported_symbols returns symbols for bitunix."""
        symbols = get_supported_symbols("bitunix")
        assert "BTC" in symbols
        assert "ETH" in symbols

    def test_get_supported_symbols_bingx(self):
        """get_supported_symbols returns symbols for bingx."""
        symbols = get_supported_symbols("bingx")
        assert "BTC" in symbols
        assert "ETH" in symbols
