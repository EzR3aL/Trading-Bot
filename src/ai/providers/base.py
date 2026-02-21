"""Base LLM provider interface and shared response parsing."""

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import aiohttp
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Module-level shared rate limiters — one per provider, shared across all bot instances
_GLOBAL_RATE_LIMITERS: Dict[str, "RateLimiter"] = {}


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    direction: str  # "LONG" or "SHORT"
    confidence: int  # 0-100
    reasoning: str  # Explanation text
    raw_response: str  # Full LLM output
    model_used: str  # e.g. "llama-3.3-70b-versatile"
    tokens_used: int = 0


def sanitize_text(text: str, max_length: int = 500) -> str:
    """Strip HTML tags and control characters from LLM output."""
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", "", text)
    # Remove control characters except newlines
    clean = re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", "", clean)
    if len(clean) > max_length:
        clean = clean[: max_length - 3] + "..."
    return clean.strip()


def sanitize_error(error: Exception, provider_name: str) -> str:
    """Create a safe error message without leaking API keys or internals."""
    err_str = str(error)
    # Strip anything that looks like an API key
    err_str = re.sub(r"(key=)[A-Za-z0-9_\-]{10,}", r"\1[REDACTED]", err_str)
    err_str = re.sub(r"(Bearer )[A-Za-z0-9_\-]{10,}", r"\1[REDACTED]", err_str)
    err_str = re.sub(r"(x-api-key:\s*)[A-Za-z0-9_\-]{10,}", r"\1[REDACTED]", err_str)
    # Extract just the status code and high-level message
    status_match = re.search(r"(\d{3})", err_str)
    status = status_match.group(1) if status_match else "unknown"
    return f"{provider_name} API error (status {status})"


def parse_llm_response(text: str) -> Tuple[str, int, str]:
    """Parse LLM output into (direction, confidence, reasoning).

    Expected format:
        DIRECTION: LONG
        CONFIDENCE: 75
        REASONING: The market shows...

    Falls back to heuristics if format doesn't match exactly.
    Defaults to confidence=0 (won't trade) when parsing fails.
    """
    direction = "LONG"
    confidence = 0  # Default 0 = won't pass should_trade threshold
    reasoning = sanitize_text(text)

    # Try structured parsing first
    dir_match = re.search(r"DIRECTION\s*:\s*(LONG|SHORT)", text, re.IGNORECASE)
    if dir_match:
        direction = dir_match.group(1).upper()

    conf_match = re.search(r"CONFIDENCE\s*:\s*(\d{1,3})", text, re.IGNORECASE)
    if conf_match:
        val = int(conf_match.group(1))
        if 0 <= val <= 100:
            confidence = val

    reason_match = re.search(
        r"REASONING\s*:\s*(.+)", text, re.IGNORECASE | re.DOTALL
    )
    if reason_match:
        reasoning = sanitize_text(reason_match.group(1))

    # Fallback: if no structured DIRECTION found, count occurrences
    if not dir_match:
        text_upper = text.upper()
        long_count = len(re.findall(r"\bLONG\b", text_upper))
        short_count = len(re.findall(r"\bSHORT\b", text_upper))
        if short_count > long_count:
            direction = "SHORT"

    # Fallback: if no structured CONFIDENCE, try to find one in context
    if not conf_match:
        # Match numbers near confidence-related words (keyword before or after number)
        ctx_match = re.search(
            r"(?:confidence|confident|certain|probability|likely)\D{0,20}(\d{1,3})%?",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"(\d{1,3})%?\s*(?:confidence|confident|certain|probability|likely|chance)",
            text,
            re.IGNORECASE,
        )
        if ctx_match:
            val = int(ctx_match.group(1))
            if 10 <= val <= 100:
                confidence = val

    return direction, confidence, reasoning


def format_market_data_prompt(market_data: dict) -> str:
    """Format market data dict into readable text for LLM."""
    return json.dumps(market_data, indent=2, default=str)


def _extract_response_text(result: dict, provider: str) -> Tuple[str, int]:
    """Safely extract text and tokens from provider-specific response JSON.

    Returns (text, tokens_used). Raises ValueError on malformed response.
    """
    if provider == "gemini":
        candidates = result.get("candidates")
        if not candidates or not isinstance(candidates, list):
            raise ValueError("Gemini returned empty candidates")
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise ValueError("Gemini returned empty content parts")
        text = parts[0].get("text", "")
        tokens = result.get("usageMetadata", {}).get("totalTokenCount", 0)
    elif provider == "anthropic":
        content = result.get("content")
        if not content or not isinstance(content, list):
            raise ValueError("Anthropic returned empty content")
        text = content[0].get("text", "")
        usage = result.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    else:
        # OpenAI-compatible: Groq, OpenAI, Mistral, xAI, Perplexity
        choices = result.get("choices")
        if not choices or not isinstance(choices, list):
            raise ValueError(f"{provider} returned empty choices")
        message = choices[0].get("message", {})
        text = message.get("content", "")
        tokens = result.get("usage", {}).get("total_tokens", 0)

    if not text or not text.strip():
        raise ValueError(f"{provider} returned empty text response")

    return text, tokens


class _HttpError(Exception):
    """HTTP error with status code for retry logic."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"{status}: {body[:200]}")


def _is_retryable(exc: BaseException) -> bool:
    """Check if an error should be retried (429, 5xx, connection errors)."""
    if isinstance(exc, _HttpError):
        return exc.status in (429, 500, 502, 503, 504)
    if isinstance(exc, (aiohttp.ClientError, TimeoutError)):
        return True
    return False


class RateLimiter:
    """Simple per-provider rate limiter (token bucket)."""

    def __init__(self, max_calls_per_hour: int = 60):
        self.max_calls = max_calls_per_hour
        self.window = 3600  # 1 hour
        self._calls: list[float] = []

    def check(self, provider_name: str) -> bool:
        """Return True if call is allowed, False if rate limited."""
        now = time.time()
        # Prune old entries
        self._calls = [t for t in self._calls if now - t < self.window]
        if len(self._calls) >= self.max_calls:
            logger.warning(
                f"[RateLimit] {provider_name}: {self.max_calls} calls/hour "
                f"limit reached. Skipping LLM call."
            )
            return False
        self._calls.append(now)
        return True


class BaseLLMProvider(ABC):
    """Base interface for all LLM providers."""

    TIMEOUT = 30  # seconds
    MODEL = ""  # subclasses override

    def __init__(self, api_key: str, model_override: Optional[str] = None):
        self.api_key = api_key
        self.model_override = model_override
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Async context manager entry — ensures session is created."""
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit — ensures session is closed."""
        await self.close()

    @property
    def active_model(self) -> str:
        """Return the model to use: override if set, otherwise class default."""
        return self.model_override or self.MODEL

    def _get_rate_limiter(self, provider_name: str) -> RateLimiter:
        """Get or create a shared rate limiter for this provider type."""
        if provider_name not in _GLOBAL_RATE_LIMITERS:
            _GLOBAL_RATE_LIMITERS[provider_name] = RateLimiter(
                max_calls_per_hour=60
            )
        return _GLOBAL_RATE_LIMITERS[provider_name]

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create a reusable aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.TIMEOUT)
            )
        return self._session

    async def _http_post_with_retry(self, url: str, **kwargs) -> dict:
        """POST with 3 retries on transient errors (429/5xx/timeout).

        Returns parsed JSON dict on success.
        Raises _HttpError on non-200 (after retries if retryable).
        """
        session = await self._get_session()

        @retry(
            retry=retry_if_exception(_is_retryable),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            stop=stop_after_attempt(3),
            reraise=True,
        )
        async def _do_post() -> dict:
            async with session.post(url, **kwargs) as resp:
                if resp.status == 200:
                    return await resp.json()
                body = await resp.text()
                raise _HttpError(resp.status, body)

        return await _do_post()

    async def close(self) -> None:
        """Close the HTTP session and clear sensitive data."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self.api_key = ""

    @abstractmethod
    async def generate_signal(
        self,
        prompt: str,
        market_data: dict,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Send prompt + market data to LLM, return parsed response."""
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test if the API key is valid. Returns True on success."""
        ...

    @classmethod
    @abstractmethod
    def get_model_name(cls) -> str:
        """Return the model identifier (e.g. 'gpt-4o-mini')."""
        ...

    @classmethod
    @abstractmethod
    def get_display_name(cls) -> str:
        """Return human-readable provider name."""
        ...
