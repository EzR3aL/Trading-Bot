"""OpenAI LLM provider (GPT-4o-mini)."""

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


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API provider using GPT-4o-mini."""

    BASE_URL = "https://api.openai.com/v1/chat/completions"
    MODEL = "gpt-4o-mini"

    async def generate_signal(
        self, prompt: str, market_data: dict, temperature: float = 0.3
    ) -> LLMResponse:
        if not self._get_rate_limiter("openai").check("openai"):
            raise Exception("Rate limit exceeded for OpenAI")

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
            raise Exception(sanitize_error(e, "OpenAI"))

        raw_text, tokens = _extract_response_text(result, "openai")
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

            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    "https://api.openai.com/v1/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    @classmethod
    def get_model_name(cls) -> str:
        return cls.MODEL

    @classmethod
    def get_display_name(cls) -> str:
        return "OpenAI GPT-4o-mini"
