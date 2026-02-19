"""Perplexity LLM provider (Sonar - search-augmented)."""

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


class PerplexityProvider(BaseLLMProvider):
    """Perplexity API provider using Sonar."""

    BASE_URL = "https://api.perplexity.ai/chat/completions"
    MODEL = "sonar"

    async def generate_signal(
        self, prompt: str, market_data: dict, temperature: float = 0.3
    ) -> LLMResponse:
        if not self._get_rate_limiter("perplexity").check("perplexity"):
            raise Exception("Rate limit exceeded for Perplexity")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.active_model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"Market Data:\n{format_market_data_prompt(market_data)}\n\nProvide your trading signal.",
                },
            ],
            "temperature": temperature,
            "max_tokens": 500,
        }

        try:
            result = await self._http_post_with_retry(
                self.BASE_URL, headers=headers, json=payload,
            )
        except _HttpError as e:
            raise Exception(sanitize_error(e, "Perplexity"))

        raw_text, tokens = _extract_response_text(result, "perplexity")
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
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.active_model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 5,
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
        return "Perplexity Sonar"
