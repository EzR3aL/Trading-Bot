"""Anthropic LLM provider (Claude Haiku 4.5)."""

from src.ai.providers.base import (
    BaseLLMProvider,
    LLMResponse,
    _HttpError,
    _extract_response_text,
    format_market_data_prompt,
    parse_llm_response,
    sanitize_error,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AnthropicProvider(BaseLLMProvider):
    """Anthropic API provider using Claude Haiku 4.5."""

    BASE_URL = "https://api.anthropic.com/v1/messages"
    MODEL = "claude-haiku-4-5-20251001"

    async def generate_signal(
        self, prompt: str, market_data: dict, temperature: float = 0.3
    ) -> LLMResponse:
        if not self._get_rate_limiter("anthropic").check("anthropic"):
            raise Exception("Rate limit exceeded for Anthropic")

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.active_model,
            "max_tokens": 500,
            "temperature": temperature,
            "system": prompt,
            "messages": [
                {
                    "role": "user",
                    "content": f"Market Data:\n{format_market_data_prompt(market_data)}\n\nProvide your trading signal.",
                }
            ],
        }

        try:
            result = await self._http_post_with_retry(
                self.BASE_URL, headers=headers, json=payload,
            )
        except _HttpError as e:
            raise Exception(sanitize_error(e, "Anthropic"))

        raw_text, tokens = _extract_response_text(result, "anthropic")
        direction, confidence, reasoning = parse_llm_response(raw_text)
        return LLMResponse(
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            raw_response=raw_text,
            model_used=self.active_model,
            tokens_used=tokens,
        )

    async def test_connection(self) -> bool:
        try:
            import aiohttp

            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.active_model,
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Hi"}],
            }
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    self.BASE_URL, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.warning("Provider validation failed: %s", e)
            return False

    @classmethod
    def get_model_name(cls) -> str:
        return cls.MODEL

    @classmethod
    def get_display_name(cls) -> str:
        return "Anthropic Claude Haiku 4.5"
