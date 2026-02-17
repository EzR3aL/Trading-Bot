"""Tests for the LLM provider registry and helper functions."""

import pytest
from unittest.mock import AsyncMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


class TestProviderRegistry:
    """Tests for PROVIDER_REGISTRY."""

    def test_registry_contains_all_providers(self):
        from src.ai.providers import PROVIDER_REGISTRY
        expected = {"groq", "gemini", "gemini_pro", "openai", "anthropic", "deepseek", "mistral", "xai", "perplexity"}
        assert set(PROVIDER_REGISTRY.keys()) == expected

    def test_all_registry_entries_are_subclasses(self):
        from src.ai.providers import PROVIDER_REGISTRY, BaseLLMProvider
        for name, cls in PROVIDER_REGISTRY.items():
            assert issubclass(cls, BaseLLMProvider), f"{name} is not a BaseLLMProvider subclass"

    def test_groq_provider_registered(self):
        from src.ai.providers import PROVIDER_REGISTRY
        from src.ai.providers.groq import GroqProvider
        assert PROVIDER_REGISTRY["groq"] is GroqProvider

    def test_deepseek_provider_registered(self):
        from src.ai.providers import PROVIDER_REGISTRY
        from src.ai.providers.deepseek import DeepSeekProvider
        assert PROVIDER_REGISTRY["deepseek"] is DeepSeekProvider


class TestLLMProvidersInfo:
    """Tests for LLM_PROVIDERS_INFO."""

    def test_info_has_all_providers(self):
        from src.ai.providers import LLM_PROVIDERS_INFO
        expected = {"groq", "gemini", "gemini_pro", "openai", "anthropic", "deepseek", "mistral", "xai", "perplexity"}
        assert set(LLM_PROVIDERS_INFO.keys()) == expected

    def test_each_entry_has_name_and_free(self):
        from src.ai.providers import LLM_PROVIDERS_INFO
        for key, info in LLM_PROVIDERS_INFO.items():
            assert "name" in info, f"{key} missing 'name'"
            assert "free" in info, f"{key} missing 'free'"
            assert isinstance(info["free"], bool)

    def test_groq_is_free(self):
        from src.ai.providers import LLM_PROVIDERS_INFO
        assert LLM_PROVIDERS_INFO["groq"]["free"] is True

    def test_openai_is_not_free(self):
        from src.ai.providers import LLM_PROVIDERS_INFO
        assert LLM_PROVIDERS_INFO["openai"]["free"] is False


class TestModelCatalog:
    """Tests for MODEL_CATALOG."""

    def test_catalog_has_all_providers(self):
        from src.ai.providers import MODEL_CATALOG
        expected = {"groq", "gemini", "gemini_pro", "openai", "anthropic", "deepseek", "mistral", "xai", "perplexity"}
        assert set(MODEL_CATALOG.keys()) == expected

    def test_each_family_has_required_keys(self):
        from src.ai.providers import MODEL_CATALOG
        for key, family in MODEL_CATALOG.items():
            assert "family_name" in family, f"{key} missing family_name"
            assert "free" in family, f"{key} missing free"
            assert "models" in family, f"{key} missing models"
            assert isinstance(family["models"], list)
            assert len(family["models"]) >= 1

    def test_each_model_has_id_and_name(self):
        from src.ai.providers import MODEL_CATALOG
        for key, family in MODEL_CATALOG.items():
            for model in family["models"]:
                assert "id" in model, f"{key} model missing 'id'"
                assert "name" in model, f"{key} model missing 'name'"

    def test_each_family_has_exactly_one_default(self):
        from src.ai.providers import MODEL_CATALOG
        for key, family in MODEL_CATALOG.items():
            defaults = [m for m in family["models"] if m.get("default")]
            assert len(defaults) == 1, f"{key} has {len(defaults)} defaults, expected 1"


class TestGetDefaultModel:
    """Tests for get_default_model function."""

    def test_returns_default_for_groq(self):
        from src.ai.providers import get_default_model
        result = get_default_model("groq")
        assert result == "meta-llama/llama-4-maverick-17b-128e-instruct"

    def test_returns_default_for_deepseek(self):
        from src.ai.providers import get_default_model
        result = get_default_model("deepseek")
        assert result == "deepseek-chat"

    def test_returns_default_for_openai(self):
        from src.ai.providers import get_default_model
        result = get_default_model("openai")
        assert result == "gpt-4.1-mini"

    def test_returns_empty_for_unknown_provider(self):
        from src.ai.providers import get_default_model
        result = get_default_model("nonexistent_provider")
        assert result == ""

    def test_returns_first_model_if_no_default_flag(self):
        from src.ai.providers import get_default_model, MODEL_CATALOG
        # Temporarily remove default flag from a family
        import copy
        original = MODEL_CATALOG.get("deepseek")
        try:
            test_family = copy.deepcopy(original)
            for m in test_family["models"]:
                m.pop("default", None)
            MODEL_CATALOG["deepseek"] = test_family
            result = get_default_model("deepseek")
            assert result == "deepseek-chat"  # first model
        finally:
            MODEL_CATALOG["deepseek"] = original


class TestGetProviderClass:
    """Tests for get_provider_class function."""

    def test_returns_groq_provider(self):
        from src.ai.providers import get_provider_class
        from src.ai.providers.groq import GroqProvider
        assert get_provider_class("groq") is GroqProvider

    def test_returns_deepseek_provider(self):
        from src.ai.providers import get_provider_class
        from src.ai.providers.deepseek import DeepSeekProvider
        assert get_provider_class("deepseek") is DeepSeekProvider

    def test_returns_openai_provider(self):
        from src.ai.providers import get_provider_class
        from src.ai.providers.openai_provider import OpenAIProvider
        assert get_provider_class("openai") is OpenAIProvider

    def test_raises_for_unknown_provider(self):
        from src.ai.providers import get_provider_class
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider_class("nonexistent")

    def test_error_message_lists_available_providers(self):
        from src.ai.providers import get_provider_class
        with pytest.raises(ValueError, match="Available:.*groq"):
            get_provider_class("invalid")


class TestBaseProviderHelpers:
    """Tests for base provider utility functions."""

    def test_parse_llm_response_structured(self):
        from src.ai.providers.base import parse_llm_response
        direction, confidence, reasoning = parse_llm_response(
            "DIRECTION: SHORT\nCONFIDENCE: 85\nREASONING: Market is bearish"
        )
        assert direction == "SHORT"
        assert confidence == 85
        assert "bearish" in reasoning.lower()

    def test_parse_llm_response_fallback_direction(self):
        from src.ai.providers.base import parse_llm_response
        direction, confidence, reasoning = parse_llm_response(
            "I think we should go SHORT SHORT SHORT rather than LONG"
        )
        assert direction == "SHORT"

    def test_parse_llm_response_fallback_confidence(self):
        from src.ai.providers.base import parse_llm_response
        direction, confidence, reasoning = parse_llm_response(
            "I am 80% confident we should go long"
        )
        assert confidence == 80

    def test_parse_llm_response_no_structured_defaults(self):
        from src.ai.providers.base import parse_llm_response
        direction, confidence, reasoning = parse_llm_response(
            "I have no opinion on the market"
        )
        assert direction == "LONG"  # default
        assert confidence == 0  # default

    def test_sanitize_text_strips_html(self):
        from src.ai.providers.base import sanitize_text
        result = sanitize_text("<b>Hello</b> <script>alert('xss')</script> world")
        assert "<" not in result
        assert "Hello" in result

    def test_sanitize_text_truncates(self):
        from src.ai.providers.base import sanitize_text
        long_text = "a" * 600
        result = sanitize_text(long_text, max_length=100)
        assert len(result) <= 100
        assert result.endswith("...")

    def test_sanitize_error_redacts_api_keys(self):
        from src.ai.providers.base import sanitize_error
        err = Exception("key=sk_test_1234567890abcdef Bearer sk_test_1234567890abcdef")
        result = sanitize_error(err, "TestProvider")
        assert "sk_test" not in result
        assert "TestProvider" in result

    def test_format_market_data_prompt(self):
        from src.ai.providers.base import format_market_data_prompt
        data = {"price": 50000, "volume": 1000}
        result = format_market_data_prompt(data)
        assert "50000" in result
        assert "1000" in result

    def test_extract_response_text_openai_format(self):
        from src.ai.providers.base import _extract_response_text
        data = {
            "choices": [{"message": {"content": "test text"}}],
            "usage": {"total_tokens": 100},
        }
        text, tokens = _extract_response_text(data, "deepseek")
        assert text == "test text"
        assert tokens == 100

    def test_extract_response_text_empty_choices_raises(self):
        from src.ai.providers.base import _extract_response_text
        with pytest.raises(ValueError, match="empty choices"):
            _extract_response_text({"choices": []}, "deepseek")

    def test_extract_response_text_empty_text_raises(self):
        from src.ai.providers.base import _extract_response_text
        data = {"choices": [{"message": {"content": ""}}], "usage": {"total_tokens": 0}}
        with pytest.raises(ValueError, match="empty text"):
            _extract_response_text(data, "deepseek")

    def test_extract_response_text_gemini_format(self):
        from src.ai.providers.base import _extract_response_text
        data = {
            "candidates": [{"content": {"parts": [{"text": "gemini text"}]}}],
            "usageMetadata": {"totalTokenCount": 200},
        }
        text, tokens = _extract_response_text(data, "gemini")
        assert text == "gemini text"
        assert tokens == 200

    def test_extract_response_text_anthropic_format(self):
        from src.ai.providers.base import _extract_response_text
        data = {
            "content": [{"text": "claude text"}],
            "usage": {"input_tokens": 50, "output_tokens": 75},
        }
        text, tokens = _extract_response_text(data, "anthropic")
        assert text == "claude text"
        assert tokens == 125


class TestRateLimiter:
    """Tests for RateLimiter."""

    def test_allows_under_limit(self):
        from src.ai.providers.base import RateLimiter
        rl = RateLimiter(max_calls_per_hour=5)
        assert rl.check("test") is True
        assert rl.check("test") is True

    def test_blocks_at_limit(self):
        from src.ai.providers.base import RateLimiter
        rl = RateLimiter(max_calls_per_hour=2)
        assert rl.check("test") is True
        assert rl.check("test") is True
        assert rl.check("test") is False

    def test_prunes_old_entries(self):
        import time
        from src.ai.providers.base import RateLimiter
        rl = RateLimiter(max_calls_per_hour=1)
        # Manually add an old entry
        rl._calls = [time.time() - 7200]  # 2 hours ago
        assert rl.check("test") is True


class TestHttpError:
    """Tests for _HttpError."""

    def test_stores_status_and_body(self):
        from src.ai.providers.base import _HttpError
        err = _HttpError(404, "Not Found")
        assert err.status == 404
        assert err.body == "Not Found"

    def test_string_representation(self):
        from src.ai.providers.base import _HttpError
        err = _HttpError(500, "Server Error")
        assert "500" in str(err)


class TestIsRetryable:
    """Tests for _is_retryable function."""

    def test_429_is_retryable(self):
        from src.ai.providers.base import _is_retryable, _HttpError
        assert _is_retryable(_HttpError(429, "Rate limited")) is True

    def test_500_is_retryable(self):
        from src.ai.providers.base import _is_retryable, _HttpError
        assert _is_retryable(_HttpError(500, "Server Error")) is True

    def test_502_is_retryable(self):
        from src.ai.providers.base import _is_retryable, _HttpError
        assert _is_retryable(_HttpError(502, "Bad Gateway")) is True

    def test_400_is_not_retryable(self):
        from src.ai.providers.base import _is_retryable, _HttpError
        assert _is_retryable(_HttpError(400, "Bad Request")) is False

    def test_401_is_not_retryable(self):
        from src.ai.providers.base import _is_retryable, _HttpError
        assert _is_retryable(_HttpError(401, "Unauthorized")) is False

    def test_timeout_is_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(TimeoutError("timeout")) is True

    def test_generic_exception_not_retryable(self):
        from src.ai.providers.base import _is_retryable
        assert _is_retryable(ValueError("bad")) is False


class TestBaseLLMProviderClose:
    """Tests for BaseLLMProvider.close method."""

    async def test_close_clears_session_and_key(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="secret-key")
        mock_session = AsyncMock()
        mock_session.closed = False
        provider._session = mock_session

        await provider.close()

        mock_session.close.assert_awaited_once()
        assert provider._session is None
        assert provider.api_key == ""

    async def test_close_when_no_session(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="secret-key")
        provider._session = None

        await provider.close()
        assert provider.api_key == ""

    async def test_close_when_session_already_closed(self):
        from src.ai.providers.deepseek import DeepSeekProvider
        provider = DeepSeekProvider(api_key="secret-key")
        mock_session = AsyncMock()
        mock_session.closed = True
        provider._session = mock_session

        await provider.close()
        mock_session.close.assert_not_awaited()
