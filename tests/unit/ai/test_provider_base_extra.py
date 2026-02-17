"""
Targeted tests for ai/providers/base.py uncovered lines (231-235, 243-258).

Covers:
- _get_session: creating and reusing aiohttp sessions
- _http_post_with_retry: successful POST and error handling
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.ai.providers.base import BaseLLMProvider, _HttpError


# ---------------------------------------------------------------------------
# Concrete subclass for testing abstract base
# ---------------------------------------------------------------------------

class ConcreteProvider(BaseLLMProvider):
    """Minimal concrete implementation for testing base methods."""

    async def generate_signal(self, prompt, market_data, temperature=0.3):
        pass

    async def test_connection(self):
        return True

    @classmethod
    def get_model_name(cls):
        return "test-model"

    @classmethod
    def get_display_name(cls):
        return "Test Provider"


# ---------------------------------------------------------------------------
# Tests: _get_session (lines 231-235)
# ---------------------------------------------------------------------------


class TestGetSession:
    @pytest.mark.asyncio
    async def test_creates_session_when_none(self):
        """_get_session creates aiohttp.ClientSession when none exists."""
        provider = ConcreteProvider(api_key="test-key")
        assert provider._session is None

        with patch("aiohttp.ClientSession") as mock_cs:
            mock_instance = MagicMock()
            mock_instance.closed = False
            mock_cs.return_value = mock_instance

            session = await provider._get_session()
            assert session is mock_instance
            mock_cs.assert_called_once()

    @pytest.mark.asyncio
    async def test_reuses_existing_session(self):
        """_get_session returns existing session if not closed."""
        provider = ConcreteProvider(api_key="test-key")
        mock_session = MagicMock()
        mock_session.closed = False
        provider._session = mock_session

        with patch("aiohttp.ClientSession") as mock_cs:
            session = await provider._get_session()
            assert session is mock_session
            mock_cs.assert_not_called()

    @pytest.mark.asyncio
    async def test_recreates_closed_session(self):
        """_get_session creates new session if existing one is closed."""
        provider = ConcreteProvider(api_key="test-key")
        old_session = MagicMock()
        old_session.closed = True
        provider._session = old_session

        with patch("aiohttp.ClientSession") as mock_cs:
            new_session = MagicMock()
            new_session.closed = False
            mock_cs.return_value = new_session

            session = await provider._get_session()
            assert session is new_session
            mock_cs.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: _http_post_with_retry (lines 243-258)
# ---------------------------------------------------------------------------


class TestHttpPostWithRetry:
    @pytest.mark.asyncio
    async def test_successful_post(self):
        """_http_post_with_retry returns JSON on 200 response."""
        provider = ConcreteProvider(api_key="test-key")
        expected = {"result": "ok"}

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=expected)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)
        mock_session.closed = False
        provider._session = mock_session

        result = await provider._http_post_with_retry("https://api.example.com/v1", json={"test": True})
        assert result == expected

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        """_http_post_with_retry raises _HttpError on non-200 response."""
        provider = ConcreteProvider(api_key="test-key")

        mock_resp = AsyncMock()
        mock_resp.status = 401
        mock_resp.text = AsyncMock(return_value="Unauthorized")

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)
        mock_session.closed = False
        provider._session = mock_session

        with pytest.raises(_HttpError) as exc_info:
            await provider._http_post_with_retry("https://api.example.com/v1")

        assert exc_info.value.status == 401
        assert "Unauthorized" in exc_info.value.body
