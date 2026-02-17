"""Tests for the DeepSeek LLM provider."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


class TestDeepSeekProviderInit:
    """Tests for DeepSeekProvider initialization and class attributes."""

    def test_base_url(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        assert DeepSeekProvider.BASE_URL == "https://api.deepseek.com/chat/completions"

    def test_model(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        assert DeepSeekProvider.MODEL == "deepseek-chat"

    def test_get_model_name(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        assert DeepSeekProvider.get_model_name() == "deepseek-chat"

    def test_get_display_name(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        assert DeepSeekProvider.get_display_name() == "DeepSeek V3"

    def test_active_model_default(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="test-key")
        assert provider.active_model == "deepseek-chat"

    def test_active_model_override(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="test-key", model_override="deepseek-reasoner")
        assert provider.active_model == "deepseek-reasoner"


class TestGenerateSignal:
    """Tests for the generate_signal method."""

    async def test_successful_signal_generation(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="test-key")

        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": "DIRECTION: LONG\nCONFIDENCE: 75\nREASONING: Market shows bullish momentum"
                    }
                }
            ],
            "usage": {"total_tokens": 150},
        }

        with patch.object(provider, "_http_post_with_retry", new_callable=AsyncMock, return_value=mock_response), \
             patch.object(provider, "_get_rate_limiter") as mock_rl:
            mock_limiter = MagicMock()
            mock_limiter.check.return_value = True
            mock_rl.return_value = mock_limiter

            result = await provider.generate_signal(
                prompt="Analyze the market",
                market_data={"price": 50000, "volume": 1000},
            )

            assert result.direction == "LONG"
            assert result.confidence == 75
            assert "bullish" in result.reasoning.lower()
            assert result.model_used == "deepseek-chat"
            assert result.tokens_used == 150

    async def test_signal_with_model_override(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="test-key", model_override="deepseek-reasoner")

        mock_response = {
            "choices": [
                {"message": {"content": "DIRECTION: SHORT\nCONFIDENCE: 60\nREASONING: Bearish trend"}}
            ],
            "usage": {"total_tokens": 100},
        }

        with patch.object(provider, "_http_post_with_retry", new_callable=AsyncMock, return_value=mock_response), \
             patch.object(provider, "_get_rate_limiter") as mock_rl:
            mock_limiter = MagicMock()
            mock_limiter.check.return_value = True
            mock_rl.return_value = mock_limiter

            result = await provider.generate_signal(
                prompt="Analyze",
                market_data={"price": 50000},
            )

            assert result.direction == "SHORT"
            assert result.model_used == "deepseek-reasoner"

    async def test_rate_limit_exceeded(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="test-key")

        with patch.object(provider, "_get_rate_limiter") as mock_rl:
            mock_limiter = MagicMock()
            mock_limiter.check.return_value = False
            mock_rl.return_value = mock_limiter

            with pytest.raises(Exception, match="Rate limit exceeded"):
                await provider.generate_signal(
                    prompt="Analyze",
                    market_data={"price": 50000},
                )

    async def test_http_error_raises_sanitized_exception(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        from src.ai.providers.base import _HttpError
        provider = DeepSeekProvider(api_key="test-key")

        with patch.object(provider, "_http_post_with_retry", new_callable=AsyncMock) as mock_post, \
             patch.object(provider, "_get_rate_limiter") as mock_rl:
            mock_limiter = MagicMock()
            mock_limiter.check.return_value = True
            mock_rl.return_value = mock_limiter
            mock_post.side_effect = _HttpError(429, "Too many requests")

            with pytest.raises(Exception, match="DeepSeek API error"):
                await provider.generate_signal(
                    prompt="Analyze",
                    market_data={"price": 50000},
                )

    async def test_signal_uses_correct_payload_structure(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="test-key")

        mock_response = {
            "choices": [{"message": {"content": "DIRECTION: LONG\nCONFIDENCE: 50\nREASONING: ok"}}],
            "usage": {"total_tokens": 50},
        }

        with patch.object(provider, "_http_post_with_retry", new_callable=AsyncMock, return_value=mock_response) as mock_post, \
             patch.object(provider, "_get_rate_limiter") as mock_rl:
            mock_limiter = MagicMock()
            mock_limiter.check.return_value = True
            mock_rl.return_value = mock_limiter

            await provider.generate_signal(
                prompt="Test prompt",
                market_data={"price": 100},
                temperature=0.5,
            )

            call_args = mock_post.call_args
            assert call_args[0][0] == "https://api.deepseek.com/chat/completions"
            payload = call_args[1]["json"]
            assert payload["model"] == "deepseek-chat"
            assert payload["temperature"] == 0.5
            assert payload["max_tokens"] == 500
            assert len(payload["messages"]) == 2
            assert payload["messages"][0]["role"] == "system"
            assert payload["messages"][1]["role"] == "user"

    async def test_signal_headers_include_auth(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="my-secret-key")

        mock_response = {
            "choices": [{"message": {"content": "DIRECTION: LONG\nCONFIDENCE: 50\nREASONING: ok"}}],
            "usage": {"total_tokens": 50},
        }

        with patch.object(provider, "_http_post_with_retry", new_callable=AsyncMock, return_value=mock_response) as mock_post, \
             patch.object(provider, "_get_rate_limiter") as mock_rl:
            mock_limiter = MagicMock()
            mock_limiter.check.return_value = True
            mock_rl.return_value = mock_limiter

            await provider.generate_signal(
                prompt="Test prompt",
                market_data={},
            )

            call_args = mock_post.call_args
            headers = call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer my-secret-key"
            assert headers["Content-Type"] == "application/json"


class TestTestConnection:
    """Tests for the test_connection method."""

    async def test_connection_success(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="test-key")

        mock_resp = AsyncMock()
        mock_resp.status = 200

        mock_get_ctx = AsyncMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        mock_cs = AsyncMock()
        mock_cs.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cs.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_cs):
            result = await provider.test_connection()
            assert result is True

    async def test_connection_failure_non_200(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="bad-key")

        mock_resp = AsyncMock()
        mock_resp.status = 401

        mock_get_ctx = AsyncMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        mock_cs = AsyncMock()
        mock_cs.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cs.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_cs):
            result = await provider.test_connection()
            assert result is False

    async def test_connection_exception_returns_false(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="test-key")

        with patch("aiohttp.ClientSession", side_effect=Exception("Network error")):
            result = await provider.test_connection()
            assert result is False
