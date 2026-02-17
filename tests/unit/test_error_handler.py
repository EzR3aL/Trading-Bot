"""Tests for the global error handler middleware."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.middleware.error_handler import global_exception_handler


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
