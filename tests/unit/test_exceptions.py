"""
Unit tests for the centralized exception hierarchy.

Tests cover:
- Exception inheritance chain
- Exception attributes (message, original_error)
- String representation
- All exception subclasses
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.exceptions import (
    TradingBotError,
    ExchangeError,
    ExchangeConnectionError,
    ExchangeRateLimitError,
    OrderError,
    DataSourceError,
    DataQualityError,
    StrategyError,
    LLMProviderError,
    ConfigError,
    ValidationError,
    AuthError,
    BotError,
    BotNotFoundError,
)


class TestTradingBotError:
    """Tests for the base exception."""

    def test_is_exception(self):
        assert issubclass(TradingBotError, Exception)

    def test_message(self):
        err = TradingBotError("something failed")
        assert str(err) == "something failed"

    def test_original_error(self):
        cause = ValueError("root cause")
        err = TradingBotError("wrapper", original_error=cause)
        assert err.original_error is cause

    def test_original_error_default_none(self):
        err = TradingBotError("no cause")
        assert err.original_error is None


class TestExchangeError:
    """Tests for exchange-related exceptions."""

    def test_inherits_from_base(self):
        assert issubclass(ExchangeError, TradingBotError)

    def test_exchange_attribute(self):
        err = ExchangeError("bitget", "rate limit hit")
        assert err.exchange == "bitget"
        assert "[bitget]" in str(err)

    def test_with_original_error(self):
        cause = ConnectionError("timeout")
        err = ExchangeError("bitget", "failed", original_error=cause)
        assert err.original_error is cause

    def test_connection_error_inherits(self):
        assert issubclass(ExchangeConnectionError, ExchangeError)

    def test_rate_limit_error_inherits(self):
        assert issubclass(ExchangeRateLimitError, ExchangeError)

    def test_order_error_inherits(self):
        assert issubclass(OrderError, ExchangeError)


class TestDataSourceError:
    """Tests for data source exceptions."""

    def test_inherits_from_base(self):
        assert issubclass(DataSourceError, TradingBotError)

    def test_source_attribute(self):
        err = DataSourceError("binance_api", "HTTP 503")
        assert err.source == "binance_api"
        assert "[binance_api]" in str(err)

    def test_data_quality_error_inherits(self):
        assert issubclass(DataQualityError, DataSourceError)


class TestStrategyError:
    """Tests for strategy exceptions."""

    def test_inherits_from_base(self):
        assert issubclass(StrategyError, TradingBotError)

    def test_llm_provider_error(self):
        err = LLMProviderError("groq", "quota exceeded")
        assert err.provider == "groq"
        assert "[groq]" in str(err)
        assert issubclass(LLMProviderError, StrategyError)


class TestOtherErrors:
    """Tests for Config, Validation, Auth, Bot errors."""

    def test_config_error(self):
        assert issubclass(ConfigError, TradingBotError)
        err = ConfigError("missing DATABASE_URL")
        assert "DATABASE_URL" in str(err)

    def test_validation_error(self):
        assert issubclass(ValidationError, TradingBotError)

    def test_auth_error(self):
        assert issubclass(AuthError, TradingBotError)

    def test_bot_error(self):
        assert issubclass(BotError, TradingBotError)

    def test_bot_not_found_error(self):
        assert issubclass(BotNotFoundError, BotError)
        err = BotNotFoundError("Bot 42 not found")
        assert "42" in str(err)


class TestExceptionCatchability:
    """Test that exceptions can be caught at various levels."""

    def test_catch_exchange_error_as_base(self):
        with pytest.raises(TradingBotError):
            raise ExchangeError("bitget", "fail")

    def test_catch_data_error_as_base(self):
        with pytest.raises(TradingBotError):
            raise DataSourceError("binance", "timeout")

    def test_catch_llm_error_as_strategy(self):
        with pytest.raises(StrategyError):
            raise LLMProviderError("groq", "rate limited")

    def test_catch_bot_not_found_as_bot(self):
        with pytest.raises(BotError):
            raise BotNotFoundError("not found")

    def test_catch_connection_error_as_exchange(self):
        with pytest.raises(ExchangeError):
            raise ExchangeConnectionError("weex", "unreachable")
