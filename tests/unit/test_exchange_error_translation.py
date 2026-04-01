"""
Unit tests for exchange error message translation (English → German).

Tests cover:
- Known error patterns are translated correctly
- Case-insensitive matching works
- Unknown errors are returned unchanged
- Partial/substring matching works (error wrapped in prefix)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.errors import translate_exchange_error


class TestTranslateExchangeError:
    """Tests for the translate_exchange_error function."""

    def test_bitget_tp_long_price(self):
        msg = "Bitget Error: The take profit price of the long position should be greater than the current price"
        result = translate_exchange_error(msg)
        assert result == "Der Take-Profit-Preis der Long-Position muss über dem aktuellen Preis liegen"

    def test_bitget_sl_long_price(self):
        msg = "The stop loss price of the long position should be less than the current price"
        result = translate_exchange_error(msg)
        assert result == "Der Stop-Loss-Preis der Long-Position muss unter dem aktuellen Preis liegen"

    def test_bitget_tp_short_price(self):
        msg = "The take profit price of the short position should be less than the current price"
        result = translate_exchange_error(msg)
        assert result == "Der Take-Profit-Preis der Short-Position muss unter dem aktuellen Preis liegen"

    def test_bitget_sl_short_price(self):
        msg = "The stop loss price of the short position should be greater than the current price"
        result = translate_exchange_error(msg)
        assert result == "Der Stop-Loss-Preis der Short-Position muss über dem aktuellen Preis liegen"

    def test_insufficient_balance(self):
        result = translate_exchange_error("Insufficient balance")
        assert result == "Unzureichendes Guthaben"

    def test_order_does_not_exist(self):
        result = translate_exchange_error("Order does not exist")
        assert result == "Order existiert nicht"

    def test_position_does_not_exist(self):
        result = translate_exchange_error("Position does not exist")
        assert result == "Position existiert nicht"

    def test_price_limit_range(self):
        msg = "The order price is not within the price limit range"
        result = translate_exchange_error(msg)
        assert result == "Der Orderpreis liegt außerhalb des erlaubten Preisbereichs"

    def test_case_insensitive(self):
        result = translate_exchange_error("INSUFFICIENT BALANCE")
        assert result == "Unzureichendes Guthaben"

    def test_unknown_error_unchanged(self):
        msg = "Some completely unrecognized problem xyz123"
        result = translate_exchange_error(msg)
        assert result == msg

    def test_empty_string(self):
        assert translate_exchange_error("") == ""

    def test_wrapped_in_prefix(self):
        """Exchange errors often come wrapped like '[bitget] Bitget Error: ...'"""
        msg = "[bitget] Bitget Error: Insufficient balance"
        result = translate_exchange_error(msg)
        assert result == "Unzureichendes Guthaben"

    def test_invalid_api_key(self):
        result = translate_exchange_error("Invalid API Key")
        assert result == "Ungültiger API-Key"

    def test_rate_limit(self):
        result = translate_exchange_error("Too many requests")
        assert result == "Zu viele Anfragen — bitte kurz warten"

    def test_leverage_too_high(self):
        result = translate_exchange_error("Leverage is too high")
        assert result == "Hebel ist zu hoch"

    def test_hyperliquid_not_enough_margin(self):
        result = translate_exchange_error("not enough margin to place order")
        assert result == "Nicht genug Margin für diese Order"

    def test_order_amount_too_small(self):
        result = translate_exchange_error("Order amount is too small")
        assert result == "Orderbetrag ist zu gering"
