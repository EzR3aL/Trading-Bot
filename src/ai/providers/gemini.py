"""Google Gemini LLM provider (Gemini 2.0 Flash - free tier)."""

import re

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


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API provider using Gemini 2.0 Flash."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    MODEL = "gemini-2.0-flash"

    def _safe_error(self, error: Exception) -> str:
        """Strip API key from Gemini error messages (key is in URL)."""
        msg = sanitize_error(error, "Gemini")
        msg = re.sub(r"key=[A-Za-z0-9_\-]{10,}", "key=[REDACTED]", msg)
        return msg

    async def generate_signal(
        self, prompt: str, market_data: dict, temperature: float = 0.3
    ) -> LLMResponse:
        if not self._get_rate_limiter("gemini").check("gemini"):
            raise Exception("Rate limit exceeded for Gemini")

        url = f"{self.BASE_URL}/{self.MODEL}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                f"{prompt}\n\n"
                                f"Market Data:\n{format_market_data_prompt(market_data)}\n\n"
                                "Provide your trading signal."
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 500,
            },
        }

        try:
            result = await self._http_post_with_retry(url, json=payload)
        except _HttpError as e:
            # Gemini errors may contain the API key in the URL
            safe_body = re.sub(
                r"key=[A-Za-z0-9_\-]{10,}", "key=[REDACTED]", e.body
            )
            raise Exception(f"Gemini API error {e.status}: {safe_body[:200]}")

        raw_text, tokens = _extract_response_text(result, "gemini")
        direction, confidence, reasoning = parse_llm_response(raw_text)
        return LLMResponse(
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            raw_response=raw_text,
            model_used=self.MODEL,
            tokens_used=tokens,
        )

    async def test_connection(self) -> bool:
        try:
            import aiohttp

            url = f"{self.BASE_URL}?key={self.api_key}"
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    url, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    @classmethod
    def get_model_name(cls) -> str:
        return cls.MODEL

    @classmethod
    def get_display_name(cls) -> str:
        return "Google Gemini 2.0 Flash"
