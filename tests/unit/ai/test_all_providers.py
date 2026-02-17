"""
Tests for all LLM provider implementations — test_connection, class methods.

Covers the remaining ~12% uncovered lines across all providers:
- groq.py (lines 76-77, 81, 85)
- openai_provider.py (lines 76-77, 81, 85)
- mistral.py (lines 76-77, 81, 85)
- xai.py (lines 76-77, 81, 85)
- perplexity.py (lines 83-84, 88, 92)
- anthropic_provider.py (lines 85-86, 90, 94)
- gemini.py (lines 27-29, 88-89, 93, 97)
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_success_session(status=200):
    """Create mock aiohttp session returning given status."""
    mock_resp = AsyncMock()
    mock_resp.status = status

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_ctx)
    mock_session.post = MagicMock(return_value=mock_ctx)

    mock_cs = AsyncMock()
    mock_cs.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cs.__aexit__ = AsyncMock(return_value=False)
    return mock_cs


# ---------------------------------------------------------------------------
# Groq Provider
# ---------------------------------------------------------------------------


class TestGroqProvider:
    def test_get_model_name(self):
        from src.ai.providers.groq import GroqProvider
        assert GroqProvider.get_model_name() == "llama-3.3-70b-versatile"

    def test_get_display_name(self):
        from src.ai.providers.groq import GroqProvider
        assert GroqProvider.get_display_name() == "Groq (Llama 3.3 70B)"

    async def test_connection_success(self):
        from src.ai.providers.groq import GroqProvider
        provider = GroqProvider(api_key="test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_success_session(200)):
            assert await provider.test_connection() is True

    async def test_connection_failure(self):
        from src.ai.providers.groq import GroqProvider
        provider = GroqProvider(api_key="bad")
        with patch("aiohttp.ClientSession", return_value=_mock_success_session(401)):
            assert await provider.test_connection() is False

    async def test_connection_exception(self):
        from src.ai.providers.groq import GroqProvider
        provider = GroqProvider(api_key="test")
        with patch("aiohttp.ClientSession", side_effect=Exception("Network error")):
            assert await provider.test_connection() is False


# ---------------------------------------------------------------------------
# OpenAI Provider
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    def test_get_model_name(self):
        from src.ai.providers.openai_provider import OpenAIProvider
        assert OpenAIProvider.get_model_name() == OpenAIProvider.MODEL

    def test_get_display_name(self):
        from src.ai.providers.openai_provider import OpenAIProvider
        name = OpenAIProvider.get_display_name()
        assert isinstance(name, str) and len(name) > 0

    async def test_connection_success(self):
        from src.ai.providers.openai_provider import OpenAIProvider
        provider = OpenAIProvider(api_key="test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_success_session(200)):
            assert await provider.test_connection() is True

    async def test_connection_failure(self):
        from src.ai.providers.openai_provider import OpenAIProvider
        provider = OpenAIProvider(api_key="bad")
        with patch("aiohttp.ClientSession", return_value=_mock_success_session(401)):
            assert await provider.test_connection() is False

    async def test_connection_exception(self):
        from src.ai.providers.openai_provider import OpenAIProvider
        provider = OpenAIProvider(api_key="test")
        with patch("aiohttp.ClientSession", side_effect=Exception("err")):
            assert await provider.test_connection() is False


# ---------------------------------------------------------------------------
# Mistral Provider
# ---------------------------------------------------------------------------


class TestMistralProvider:
    def test_get_model_name(self):
        from src.ai.providers.mistral import MistralProvider
        assert MistralProvider.get_model_name() == MistralProvider.MODEL

    def test_get_display_name(self):
        from src.ai.providers.mistral import MistralProvider
        name = MistralProvider.get_display_name()
        assert isinstance(name, str) and len(name) > 0

    async def test_connection_success(self):
        from src.ai.providers.mistral import MistralProvider
        provider = MistralProvider(api_key="test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_success_session(200)):
            assert await provider.test_connection() is True

    async def test_connection_exception(self):
        from src.ai.providers.mistral import MistralProvider
        provider = MistralProvider(api_key="test")
        with patch("aiohttp.ClientSession", side_effect=Exception("err")):
            assert await provider.test_connection() is False


# ---------------------------------------------------------------------------
# xAI Provider
# ---------------------------------------------------------------------------


class TestXAIProvider:
    def test_get_model_name(self):
        from src.ai.providers.xai import XAIProvider
        assert XAIProvider.get_model_name() == XAIProvider.MODEL

    def test_get_display_name(self):
        from src.ai.providers.xai import XAIProvider
        name = XAIProvider.get_display_name()
        assert isinstance(name, str) and len(name) > 0

    async def test_connection_success(self):
        from src.ai.providers.xai import XAIProvider
        provider = XAIProvider(api_key="test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_success_session(200)):
            assert await provider.test_connection() is True

    async def test_connection_exception(self):
        from src.ai.providers.xai import XAIProvider
        provider = XAIProvider(api_key="test")
        with patch("aiohttp.ClientSession", side_effect=Exception("err")):
            assert await provider.test_connection() is False


# ---------------------------------------------------------------------------
# Perplexity Provider
# ---------------------------------------------------------------------------


class TestPerplexityProvider:
    def test_get_model_name(self):
        from src.ai.providers.perplexity import PerplexityProvider
        assert PerplexityProvider.get_model_name() == PerplexityProvider.MODEL

    def test_get_display_name(self):
        from src.ai.providers.perplexity import PerplexityProvider
        name = PerplexityProvider.get_display_name()
        assert isinstance(name, str) and len(name) > 0

    async def test_connection_success(self):
        from src.ai.providers.perplexity import PerplexityProvider
        provider = PerplexityProvider(api_key="test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_success_session(200)):
            assert await provider.test_connection() is True

    async def test_connection_exception(self):
        from src.ai.providers.perplexity import PerplexityProvider
        provider = PerplexityProvider(api_key="test")
        with patch("aiohttp.ClientSession", side_effect=Exception("err")):
            assert await provider.test_connection() is False


# ---------------------------------------------------------------------------
# Anthropic Provider
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    def test_get_model_name(self):
        from src.ai.providers.anthropic_provider import AnthropicProvider
        assert AnthropicProvider.get_model_name() == AnthropicProvider.MODEL

    def test_get_display_name(self):
        from src.ai.providers.anthropic_provider import AnthropicProvider
        name = AnthropicProvider.get_display_name()
        assert isinstance(name, str) and len(name) > 0

    async def test_connection_success(self):
        from src.ai.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(api_key="test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_success_session(200)):
            assert await provider.test_connection() is True

    async def test_connection_exception(self):
        from src.ai.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(api_key="test")
        with patch("aiohttp.ClientSession", side_effect=Exception("err")):
            assert await provider.test_connection() is False


# ---------------------------------------------------------------------------
# Gemini Provider
# ---------------------------------------------------------------------------


class TestGeminiProvider:
    def test_get_model_name(self):
        from src.ai.providers.gemini import GeminiProvider
        assert GeminiProvider.get_model_name() == GeminiProvider.MODEL

    def test_get_display_name(self):
        from src.ai.providers.gemini import GeminiProvider
        name = GeminiProvider.get_display_name()
        assert isinstance(name, str) and len(name) > 0

    async def test_connection_success(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider(api_key="test-key")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"models": []})

        mock_get_ctx = AsyncMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        mock_cs = AsyncMock()
        mock_cs.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cs.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_cs):
            assert await provider.test_connection() is True

    async def test_connection_exception(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider(api_key="test")
        with patch("aiohttp.ClientSession", side_effect=Exception("err")):
            assert await provider.test_connection() is False

    async def test_generate_signal_success(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider(api_key="test-key")

        mock_response = {
            "candidates": [
                {"content": {"parts": [{"text": "DIRECTION: LONG\nCONFIDENCE: 70\nREASONING: Bullish"}]}}
            ],
            "usageMetadata": {"totalTokenCount": 100},
        }

        with patch.object(provider, "_http_post_with_retry", new_callable=AsyncMock, return_value=mock_response), \
             patch.object(provider, "_get_rate_limiter") as mock_rl:
            mock_limiter = MagicMock()
            mock_limiter.check.return_value = True
            mock_rl.return_value = mock_limiter

            result = await provider.generate_signal("Analyze", {"price": 50000})
            assert result.direction == "LONG"
            assert result.confidence == 70
