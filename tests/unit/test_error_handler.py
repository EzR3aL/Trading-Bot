"""Tests for the global error handler middleware."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.middleware.error_handler import global_exception_handler, _resolve_status
from src.exceptions import (
    AuthError,
    BotNotFoundError,
    ConfigError,
    DataSourceError,
    ExchangeError,
    ExchangeRateLimitError,
    LLMProviderError,
    TradingBotError,
    ValidationError,
)


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request."""
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/api/test"
    return request


class TestGlobalExceptionHandler:
    """Tests for global_exception_handler."""

    @pytest.mark.asyncio
    async def test_development_mode_includes_details(self, mock_request):
        """In development, the response should include error details."""
        exc = ValueError("test error message")
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
            response = await global_exception_handler(mock_request, exc)
        assert response.status_code == 500
        import json
        body = json.loads(response.body)
        assert "test error message" in body["detail"]
        assert "traceback" in body

    @pytest.mark.asyncio
    async def test_production_mode_hides_details(self, mock_request):
        """In production, the response should NOT include internal details."""
        exc = RuntimeError("sensitive internal error")
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            response = await global_exception_handler(mock_request, exc)
        assert response.status_code == 500
        import json
        body = json.loads(response.body)
        assert body["detail"] == "Internal server error"
        assert "traceback" not in body
        assert "sensitive" not in body["detail"]

    @pytest.mark.asyncio
    async def test_default_environment_is_development(self, mock_request):
        """Without ENVIRONMENT set, defaults to development mode."""
        exc = ValueError("default env test")
        with patch.dict(os.environ, {}, clear=True):
            # Remove ENVIRONMENT if it exists
            os.environ.pop("ENVIRONMENT", None)
            response = await global_exception_handler(mock_request, exc)
        import json
        body = json.loads(response.body)
        assert "default env test" in body["detail"]


class TestResolveStatus:
    """Tests for exception → HTTP status mapping."""

    def test_unknown_exception_returns_500(self):
        status, msg = _resolve_status(RuntimeError("boom"))
        assert status == 500
        assert msg == "Internal server error"

    def test_exchange_error_returns_502(self):
        status, msg = _resolve_status(ExchangeError("bitget", "timeout"))
        assert status == 502

    def test_exchange_rate_limit_returns_429(self):
        status, msg = _resolve_status(ExchangeRateLimitError("bitget", "slow down"))
        assert status == 429

    def test_auth_error_returns_401(self):
        status, msg = _resolve_status(AuthError("bad token"))
        assert status == 401

    def test_validation_error_returns_422(self):
        status, msg = _resolve_status(ValidationError("invalid input"))
        assert status == 422

    def test_bot_not_found_returns_404(self):
        status, msg = _resolve_status(BotNotFoundError("no such bot"))
        assert status == 404

    def test_config_error_returns_400(self):
        status, msg = _resolve_status(ConfigError("missing field"))
        assert status == 400

    def test_data_source_error_returns_502(self):
        status, msg = _resolve_status(DataSourceError("coinglass", "down"))
        assert status == 502

    def test_llm_provider_error_returns_502(self):
        status, msg = _resolve_status(LLMProviderError("openai", "quota"))
        assert status == 502

    def test_base_trading_bot_error_returns_500(self):
        status, msg = _resolve_status(TradingBotError("generic"))
        assert status == 500

    @pytest.mark.asyncio
    async def test_known_exception_uses_mapped_status(self, mock_request):
        """ExchangeRateLimitError should return 429, not 500."""
        exc = ExchangeRateLimitError("bitget", "rate limited")
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
            response = await global_exception_handler(mock_request, exc)
        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_production_uses_safe_message_for_known_exception(self, mock_request):
        exc = ExchangeError("bitget", "internal detail")
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            response = await global_exception_handler(mock_request, exc)
        assert response.status_code == 502
        import json
        body = json.loads(response.body)
        assert body["detail"] == "Exchange communication error"
        assert "internal detail" not in body["detail"]
