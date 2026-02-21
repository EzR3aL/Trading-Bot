"""Tests for the symbol mapping utility."""


from src.exchanges.symbol_map import (
    SYMBOL_MAP,
    normalize_symbol,
    to_exchange_symbol,
    get_supported_symbols,
)


class TestNormalizeSymbol:
    """Tests for normalize_symbol."""

    def test_bitget_btcusdt(self):
        assert normalize_symbol("BTCUSDT", "bitget") == "BTC"

    def test_bitget_ethusdt(self):
        assert normalize_symbol("ETHUSDT", "bitget") == "ETH"

    def test_weex_btc(self):
        assert normalize_symbol("BTC/USDT:USDT", "weex") == "BTC"

    def test_weex_sol(self):
        assert normalize_symbol("SOL/USDT:USDT", "weex") == "SOL"

    def test_hyperliquid_btc(self):
        assert normalize_symbol("BTC", "hyperliquid") == "BTC"

    def test_bitget_fallback_strips_usdt(self):
        assert normalize_symbol("NEARUSDT", "bitget") == "NEAR"

    def test_weex_fallback_splits_slash(self):
        assert normalize_symbol("NEAR/USDT:USDT", "weex") == "NEAR"

    def test_hyperliquid_fallback_returns_as_is(self):
        assert normalize_symbol("NEAR", "hyperliquid") == "NEAR"

    def test_unknown_exchange_returns_as_is(self):
        assert normalize_symbol("BTCUSDT", "kraken") == "BTCUSDT"


class TestToExchangeSymbol:
    """Tests for to_exchange_symbol."""

    def test_bitget_from_base(self):
        assert to_exchange_symbol("BTC", "bitget") == "BTCUSDT"

    def test_bitget_from_usdt_format(self):
        assert to_exchange_symbol("BTCUSDT", "bitget") == "BTCUSDT"

    def test_weex_from_base(self):
        assert to_exchange_symbol("ETH", "weex") == "ETH/USDT:USDT"

    def test_hyperliquid_from_base(self):
        assert to_exchange_symbol("SOL", "hyperliquid") == "SOL"

    def test_bitget_fallback_for_unknown_symbol(self):
        assert to_exchange_symbol("NEAR", "bitget") == "NEARUSDT"

    def test_weex_fallback_for_unknown_symbol(self):
        assert to_exchange_symbol("NEAR", "weex") == "NEAR/USDT:USDT"

    def test_hyperliquid_fallback_for_unknown_symbol(self):
        assert to_exchange_symbol("NEAR", "hyperliquid") == "NEAR"

    def test_unknown_exchange_returns_base(self):
        assert to_exchange_symbol("BTC", "kraken") == "BTC"


class TestGetSupportedSymbols:
    """Tests for get_supported_symbols."""

    def test_bitget_has_symbols(self):
        symbols = get_supported_symbols("bitget")
        assert "BTC" in symbols
        assert "ETH" in symbols
        assert len(symbols) >= 10

    def test_weex_has_symbols(self):
        symbols = get_supported_symbols("weex")
        assert "BTC" in symbols

    def test_hyperliquid_has_symbols(self):
        symbols = get_supported_symbols("hyperliquid")
        assert "BTC" in symbols

    def test_unknown_exchange_returns_empty(self):
        assert get_supported_symbols("kraken") == []


class TestSymbolMapConsistency:
    """Tests for SYMBOL_MAP consistency."""

    def test_all_exchanges_have_same_base_symbols(self):
        bases = [set(SYMBOL_MAP[ex].keys()) for ex in SYMBOL_MAP]
        assert all(b == bases[0] for b in bases)

    def test_roundtrip_bitget(self):
        for base in SYMBOL_MAP["bitget"]:
            ex_sym = to_exchange_symbol(base, "bitget")
            assert normalize_symbol(ex_sym, "bitget") == base

    def test_roundtrip_weex(self):
        for base in SYMBOL_MAP["weex"]:
            ex_sym = to_exchange_symbol(base, "weex")
            assert normalize_symbol(ex_sym, "weex") == base

    def test_roundtrip_hyperliquid(self):
        for base in SYMBOL_MAP["hyperliquid"]:
            ex_sym = to_exchange_symbol(base, "hyperliquid")
            assert normalize_symbol(ex_sym, "hyperliquid") == base
