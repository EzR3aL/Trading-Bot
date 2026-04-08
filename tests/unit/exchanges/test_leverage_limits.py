"""Tests for the static leverage limits lookup."""
import pytest
from src.exchanges.leverage_limits import get_max_leverage, ExchangeNotSupported


def test_bitget_btc_default():
    assert get_max_leverage("bitget", "BTCUSDT") == 125


def test_bitget_unknown_symbol_falls_back_to_default():
    assert get_max_leverage("bitget", "UNKNOWN") == 50


def test_hyperliquid_btc():
    assert get_max_leverage("hyperliquid", "BTC") == 50


def test_unknown_exchange_raises():
    with pytest.raises(ExchangeNotSupported):
        get_max_leverage("kraken", "BTCUSDT")


def test_case_insensitive_exchange_name():
    assert get_max_leverage("BITGET", "BTCUSDT") == 125
