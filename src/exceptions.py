"""
Centralized exception hierarchy for the Trading Bot.

Provides a structured base for all application-specific exceptions.
Exchange-specific errors (BitgetClientError, HyperliquidClientError,
WeexClientError) inherit from ExchangeError. DataFetchError inherits
from DataSourceError. CircuitBreakerError inherits from TradingBotError.
"""

from typing import Optional


class TradingBotError(Exception):
    """Base exception for all trading bot errors."""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        self.original_error = original_error
        super().__init__(message)


# --- Exchange errors ---

class ExchangeError(TradingBotError):
    """Error communicating with an exchange API."""

    def __init__(self, exchange: str, message: str, original_error: Optional[Exception] = None):
        self.exchange = exchange
        super().__init__(f"[{exchange}] {message}", original_error)


class ExchangeConnectionError(ExchangeError):
    """Exchange API is unreachable or timed out."""
    pass


class ExchangeRateLimitError(ExchangeError):
    """Exchange rate limit exceeded."""
    pass


class OrderError(ExchangeError):
    """Error placing, modifying, or cancelling an order."""
    pass


# --- Data source errors ---

class DataSourceError(TradingBotError):
    """Error fetching or processing market data."""

    def __init__(self, source: str, message: str, original_error: Optional[Exception] = None):
        self.source = source
        self.message = message
        super().__init__(f"[{source}] {message}", original_error)


class DataQualityError(DataSourceError):
    """Fetched data is incomplete, stale, or inconsistent."""
    pass


# --- Strategy errors ---

class StrategyError(TradingBotError):
    """Error in strategy computation or signal generation."""
    pass


class LLMProviderError(StrategyError):
    """Error from an LLM provider (timeout, bad response, quota)."""

    def __init__(self, provider: str, message: str, original_error: Optional[Exception] = None):
        self.provider = provider
        super().__init__(f"[{provider}] {message}", original_error)


# --- Configuration errors ---

class ConfigError(TradingBotError):
    """Invalid or missing configuration."""
    pass


# --- Validation errors ---

class ValidationError(TradingBotError):
    """Input validation failed (API request, user input, etc.)."""
    pass


# --- Auth errors ---

class AuthError(TradingBotError):
    """Authentication or authorization failure."""
    pass


# --- Bot lifecycle errors ---

class BotError(TradingBotError):
    """Error in bot lifecycle (start, stop, state transitions)."""
    pass


class BotNotFoundError(BotError):
    """Requested bot does not exist."""
    pass


# --- Database errors ---

class DatabaseUnavailableError(TradingBotError):
    """Database circuit breaker is open — too many recent failures."""
    pass
