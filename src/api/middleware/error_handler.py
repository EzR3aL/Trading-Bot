"""
Global exception handler middleware.

In production, returns generic error messages without stack traces.
In development, includes full error details for debugging.
Maps custom exceptions to appropriate HTTP status codes.
"""

import os
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse

from src.api.secret_redaction import redact_lines, redact_secrets
from src.exceptions import (
    AuthError,
    BotError,
    BotNotFoundError,
    ConfigError,
    DatabaseUnavailableError,
    DataSourceError,
    ExchangeError,
    ExchangeRateLimitError,
    LLMProviderError,
    StrategyError,
    TradingBotError,
    ValidationError,
)
from src.errors import translate_exchange_error
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Maps exception types to (HTTP status, user-facing message).
# Order matters: more specific types must come before their parents.
_EXCEPTION_STATUS_MAP: list[tuple[type, int, str]] = [
    (DatabaseUnavailableError, 503, "Database temporarily unavailable"),
    (BotNotFoundError, 404, "Bot not found"),
    (ValidationError, 422, "Validation error"),
    (AuthError, 401, "Authentication error"),
    (ExchangeRateLimitError, 429, "Exchange rate limit exceeded"),
    (ExchangeError, 502, "Exchange communication error"),
    (LLMProviderError, 502, "AI provider error"),
    (DataSourceError, 502, "Data source error"),
    (ConfigError, 400, "Configuration error"),
    (BotError, 400, "Bot error"),
    (StrategyError, 500, "Strategy error"),
    (TradingBotError, 500, "Internal error"),
]


def _resolve_status(exc: Exception) -> tuple[int, str]:
    """Return (status_code, safe_message) for a known exception type."""
    for exc_type, status, safe_msg in _EXCEPTION_STATUS_MAP:
        if isinstance(exc, exc_type):
            return status, safe_msg
    return 500, "Internal server error"


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle unhandled exceptions globally.

    Known TradingBotError subtypes are mapped to appropriate HTTP codes.
    In production (ENVIRONMENT=production), returns a generic error message
    without exposing internal details or stack traces.
    In development, includes the full error detail for debugging.
    """
    environment = os.getenv("ENVIRONMENT", "development").lower()

    status_code, safe_message = _resolve_status(exc)

    # Always log the full error server-side
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )

    # Translate exchange API error messages to German for user-facing display
    exc_detail = str(exc)
    if isinstance(exc, ExchangeError):
        exc_detail = translate_exchange_error(exc_detail)

    if environment == "production":
        return JSONResponse(
            status_code=status_code,
            content={"detail": safe_message},
        )
    else:
        # Dev responses include exc_detail + traceback for debugging. BOTH
        # still pass through redact_secrets so a local .env or DSN leaked
        # into an exception string is never echoed back in the HTTP body
        # (SEC-010). The server log above is gated separately — log-hosts
        # are considered trusted, the HTTP response is not.
        return JSONResponse(
            status_code=status_code,
            content={
                "detail": redact_secrets(f"{safe_message}: {exc_detail}"),
                "traceback": redact_lines(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ),
            },
        )
