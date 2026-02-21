"""Tests for all 7 LLM provider implementations with mocked HTTP."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ai.providers.base import _GLOBAL_RATE_LIMITERS, _HttpError


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_global_rate_limiters():
    """Reset shared rate limiters between tests."""
    _GLOBAL_RATE_LIMITERS.clear()
    yield
    _GLOBAL_RATE_LIMITERS.clear()


def _mock_post_success(json_response: dict):
    """Create a mock that makes _http_post_with_retry return json_response."""
    async def _fake_retry(self, url, **kwargs):
        return json_response
    return _fake_retry


def _mock_post_http_error(status: int, body: str = "error"):
    """Create a mock that makes _http_post_with_retry raise _HttpError."""
    async def _fake_retry(self, url, **kwargs):
        raise _HttpError(status, body)
    return _fake_retry


def _mock_aiohttp_session(method: str = "get", status: int = 200):
    """Create a properly mocked aiohttp.ClientSession for test_connection."""
    mock_resp = MagicMock()
    mock_resp.status = status

    # Inner context manager: async with session.get(...) as resp
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_cm.__aexit__.return_value = None

    mock_session = MagicMock()
    getattr(mock_session, method).return_value = mock_cm

    # Outer context manager: async with aiohttp.ClientSession() as s
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__.return_value = mock_session
    mock_session_cm.__aexit__.return_value = None

    return mock_session_cm


# ── Response fixtures ───────────────────────────────────────────────

OPENAI_RESPONSE = {
    "choices": [
        {"message": {"content": "DIRECTION: LONG\nCONFIDENCE: 75\nREASONING: Bullish"}}
    ],
    "usage": {"total_tokens": 120},
}

GEMINI_RESPONSE = {
    "candidates": [
        {"content": {"parts": [{"text": "DIRECTION: SHORT\nCONFIDENCE: 65\nREASONING: Bearish"}]}}
    ],
    "usageMetadata": {"totalTokenCount": 80},
}

ANTHROPIC_RESPONSE = {
    "content": [{"text": "DIRECTION: LONG\nCONFIDENCE: 90\nREASONING: Strong trend"}],
    "usage": {"input_tokens": 50, "output_tokens": 30},
}


# ── Groq ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGroqProvider:
    async def test_generate_signal_success(self):
        from src.ai.providers.groq import GroqProvider
        provider = GroqProvider("test-key")
        with patch.object(GroqProvider, "_http_post_with_retry", _mock_post_success(OPENAI_RESPONSE)):
            result = await provider.generate_signal("prompt", {"symbol": "BTCUSDT"})
        assert result.direction == "LONG"
        assert result.confidence == 75
        assert result.tokens_used == 120
        assert result.model_used == "llama-3.3-70b-versatile"

    async def test_generate_signal_rate_limited(self):
        from src.ai.providers.groq import GroqProvider
        provider = GroqProvider("test-key")
        provider._get_rate_limiter("groq").max_calls = 0
        with pytest.raises(Exception, match="Rate limit"):
            await provider.generate_signal("prompt", {})

    async def test_generate_signal_http_error(self):
        from src.ai.providers.groq import GroqProvider
        provider = GroqProvider("test-key")
        with patch.object(GroqProvider, "_http_post_with_retry", _mock_post_http_error(401)):
            with pytest.raises(Exception, match="Groq API error"):
                await provider.generate_signal("prompt", {})

    async def test_test_connection_success(self):
        from src.ai.providers.groq import GroqProvider
        provider = GroqProvider("test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp_session("get", 200)):
            assert await provider.test_connection() is True


# ── OpenAI ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestOpenAIProvider:
    async def test_generate_signal_success(self):
        from src.ai.providers.openai_provider import OpenAIProvider
        provider = OpenAIProvider("test-key")
        with patch.object(OpenAIProvider, "_http_post_with_retry", _mock_post_success(OPENAI_RESPONSE)):
            result = await provider.generate_signal("prompt", {"symbol": "BTCUSDT"})
        assert result.direction == "LONG"
        assert result.confidence == 75
        assert result.model_used == "gpt-4o-mini"

    async def test_generate_signal_rate_limited(self):
        from src.ai.providers.openai_provider import OpenAIProvider
        provider = OpenAIProvider("test-key")
        provider._get_rate_limiter("openai").max_calls = 0
        with pytest.raises(Exception, match="Rate limit"):
            await provider.generate_signal("prompt", {})

    async def test_generate_signal_http_error(self):
        from src.ai.providers.openai_provider import OpenAIProvider
        provider = OpenAIProvider("test-key")
        with patch.object(OpenAIProvider, "_http_post_with_retry", _mock_post_http_error(401)):
            with pytest.raises(Exception, match="OpenAI API error"):
                await provider.generate_signal("prompt", {})

    async def test_test_connection_success(self):
        from src.ai.providers.openai_provider import OpenAIProvider
        provider = OpenAIProvider("test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp_session("get", 200)):
            assert await provider.test_connection() is True


# ── Gemini (unique format) ──────────────────────────────────────────


@pytest.mark.asyncio
class TestGeminiProvider:
    async def test_generate_signal_success(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider("test-key")
        with patch.object(GeminiProvider, "_http_post_with_retry", _mock_post_success(GEMINI_RESPONSE)):
            result = await provider.generate_signal("prompt", {"symbol": "BTCUSDT"})
        assert result.direction == "SHORT"
        assert result.confidence == 65
        assert result.tokens_used == 80
        assert result.model_used == "gemini-2.0-flash"

    async def test_generate_signal_rate_limited(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider("test-key")
        provider._get_rate_limiter("gemini").max_calls = 0
        with pytest.raises(Exception, match="Rate limit"):
            await provider.generate_signal("prompt", {})

    async def test_generate_signal_strips_key_from_error(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider("AIzaSyTestKey12345")
        with patch.object(
            GeminiProvider, "_http_post_with_retry",
            _mock_post_http_error(400, "Bad request for key=AIzaSyTestKey12345"),
        ):
            with pytest.raises(Exception) as exc_info:
                await provider.generate_signal("prompt", {})
            assert "AIzaSyTestKey12345" not in str(exc_info.value)

    async def test_test_connection_success(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider("test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp_session("get", 200)):
            assert await provider.test_connection() is True


# ── Anthropic (unique format) ───────────────────────────────────────


@pytest.mark.asyncio
class TestAnthropicProvider:
    async def test_generate_signal_success(self):
        from src.ai.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider("test-key")
        with patch.object(AnthropicProvider, "_http_post_with_retry", _mock_post_success(ANTHROPIC_RESPONSE)):
            result = await provider.generate_signal("prompt", {"symbol": "BTCUSDT"})
        assert result.direction == "LONG"
        assert result.confidence == 90
        assert result.tokens_used == 80  # 50 + 30
        assert result.model_used == "claude-haiku-4-5-20251001"

    async def test_generate_signal_rate_limited(self):
        from src.ai.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider("test-key")
        provider._get_rate_limiter("anthropic").max_calls = 0
        with pytest.raises(Exception, match="Rate limit"):
            await provider.generate_signal("prompt", {})

    async def test_generate_signal_http_error(self):
        from src.ai.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider("test-key")
        with patch.object(AnthropicProvider, "_http_post_with_retry", _mock_post_http_error(401)):
            with pytest.raises(Exception, match="Anthropic API error"):
                await provider.generate_signal("prompt", {})

    async def test_test_connection_success(self):
        from src.ai.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider("test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp_session("post", 200)):
            assert await provider.test_connection() is True


# ── Mistral ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestMistralProvider:
    async def test_generate_signal_success(self):
        from src.ai.providers.mistral import MistralProvider
        provider = MistralProvider("test-key")
        with patch.object(MistralProvider, "_http_post_with_retry", _mock_post_success(OPENAI_RESPONSE)):
            result = await provider.generate_signal("prompt", {"symbol": "BTCUSDT"})
        assert result.direction == "LONG"
        assert result.confidence == 75
        assert result.model_used == "mistral-small-latest"

    async def test_generate_signal_rate_limited(self):
        from src.ai.providers.mistral import MistralProvider
        provider = MistralProvider("test-key")
        provider._get_rate_limiter("mistral").max_calls = 0
        with pytest.raises(Exception, match="Rate limit"):
            await provider.generate_signal("prompt", {})

    async def test_generate_signal_http_error(self):
        from src.ai.providers.mistral import MistralProvider
        provider = MistralProvider("test-key")
        with patch.object(MistralProvider, "_http_post_with_retry", _mock_post_http_error(403)):
            with pytest.raises(Exception, match="Mistral API error"):
                await provider.generate_signal("prompt", {})

    async def test_test_connection_success(self):
        from src.ai.providers.mistral import MistralProvider
        provider = MistralProvider("test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp_session("get", 200)):
            assert await provider.test_connection() is True


# ── xAI ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestXAIProvider:
    async def test_generate_signal_success(self):
        from src.ai.providers.xai import XAIProvider
        provider = XAIProvider("test-key")
        with patch.object(XAIProvider, "_http_post_with_retry", _mock_post_success(OPENAI_RESPONSE)):
            result = await provider.generate_signal("prompt", {"symbol": "BTCUSDT"})
        assert result.direction == "LONG"
        assert result.confidence == 75
        assert result.model_used == "grok-2-latest"

    async def test_generate_signal_rate_limited(self):
        from src.ai.providers.xai import XAIProvider
        provider = XAIProvider("test-key")
        provider._get_rate_limiter("xai").max_calls = 0
        with pytest.raises(Exception, match="Rate limit"):
            await provider.generate_signal("prompt", {})

    async def test_generate_signal_http_error(self):
        from src.ai.providers.xai import XAIProvider
        provider = XAIProvider("test-key")
        with patch.object(XAIProvider, "_http_post_with_retry", _mock_post_http_error(500)):
            with pytest.raises(Exception, match="xAI API error"):
                await provider.generate_signal("prompt", {})

    async def test_test_connection_success(self):
        from src.ai.providers.xai import XAIProvider
        provider = XAIProvider("test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp_session("get", 200)):
            assert await provider.test_connection() is True


# ── Perplexity ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPerplexityProvider:
    async def test_generate_signal_success(self):
        from src.ai.providers.perplexity import PerplexityProvider
        provider = PerplexityProvider("test-key")
        with patch.object(PerplexityProvider, "_http_post_with_retry", _mock_post_success(OPENAI_RESPONSE)):
            result = await provider.generate_signal("prompt", {"symbol": "BTCUSDT"})
        assert result.direction == "LONG"
        assert result.confidence == 75
        assert result.model_used == "sonar"

    async def test_generate_signal_rate_limited(self):
        from src.ai.providers.perplexity import PerplexityProvider
        provider = PerplexityProvider("test-key")
        provider._get_rate_limiter("perplexity").max_calls = 0
        with pytest.raises(Exception, match="Rate limit"):
            await provider.generate_signal("prompt", {})

    async def test_generate_signal_http_error(self):
        from src.ai.providers.perplexity import PerplexityProvider
        provider = PerplexityProvider("test-key")
        with patch.object(PerplexityProvider, "_http_post_with_retry", _mock_post_http_error(429)):
            with pytest.raises(Exception, match="Perplexity API error"):
                await provider.generate_signal("prompt", {})

    async def test_test_connection_success(self):
        from src.ai.providers.perplexity import PerplexityProvider
        provider = PerplexityProvider("test-key")
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp_session("post", 200)):
            assert await provider.test_connection() is True


# ── Cross-Provider: Shared Rate Limiter ─────────────────────────────


@pytest.mark.asyncio
class TestSharedRateLimiter:
    async def test_two_instances_share_limiter(self):
        """Two Groq instances should share the same rate limiter."""
        from src.ai.providers.groq import GroqProvider
        p1 = GroqProvider("key1")
        p2 = GroqProvider("key2")
        assert p1._get_rate_limiter("groq") is p2._get_rate_limiter("groq")

    async def test_different_providers_separate_limiters(self):
        """Groq and OpenAI should have separate rate limiters."""
        from src.ai.providers.groq import GroqProvider
        from src.ai.providers.openai_provider import OpenAIProvider
        p1 = GroqProvider("key1")
        p2 = OpenAIProvider("key2")
        assert p1._get_rate_limiter("groq") is not p2._get_rate_limiter("openai")

    async def test_shared_limiter_blocks_across_instances(self):
        """Rate limit on one instance blocks other instances of same provider."""
        from src.ai.providers.groq import GroqProvider
        p1 = GroqProvider("key1")
        p2 = GroqProvider("key2")
        rl = p1._get_rate_limiter("groq")
        rl.max_calls = 2
        assert rl.check("groq") is True
        assert rl.check("groq") is True
        # p2 should now be blocked (same shared limiter)
        assert p2._get_rate_limiter("groq").check("groq") is False


# ── Retry Logic ─────────────────────────────────────────────────────


class TestRetryLogic:
    def test_429_is_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(_HttpError(429, "Too Many Requests")) is True

    def test_500_is_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(_HttpError(500, "Internal Server Error")) is True

    def test_502_is_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(_HttpError(502, "Bad Gateway")) is True

    def test_503_is_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(_HttpError(503, "Service Unavailable")) is True

    def test_504_is_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(_HttpError(504, "Gateway Timeout")) is True

    def test_401_not_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(_HttpError(401, "Unauthorized")) is False

    def test_400_not_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(_HttpError(400, "Bad Request")) is False

    def test_403_not_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(_HttpError(403, "Forbidden")) is False

    def test_timeout_is_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(TimeoutError("Connection timed out")) is True

    def test_client_error_is_retryable(self):
        import aiohttp
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(aiohttp.ClientError("Connection reset")) is True

    def test_http_error_carries_status(self):
        err = _HttpError(503, "Service Unavailable")
        assert err.status == 503
        assert "503" in str(err)
        assert "Service Unavailable" in err.body
