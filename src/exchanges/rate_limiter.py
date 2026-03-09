"""Token bucket rate limiter shared across all clients for one exchange.

Each exchange has its own singleton limiter so that multiple bots trading
on the same exchange collectively respect the API rate limits.
"""

import asyncio
import time
from typing import ClassVar, Dict

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Per-exchange request limits (conservative defaults)
EXCHANGE_LIMITS: Dict[str, Dict[str, int]] = {
    "bitget": {"requests_per_second": 10, "burst": 15},
    "weex": {"requests_per_second": 10, "burst": 15},
    "hyperliquid": {"requests_per_second": 5, "burst": 10},
    "bitunix": {"requests_per_second": 10, "burst": 15},
    "bingx": {"requests_per_second": 10, "burst": 15},
}


class ExchangeRateLimiter:
    """Token bucket rate limiter — one instance per exchange type."""

    _instances: ClassVar[Dict[str, "ExchangeRateLimiter"]] = {}

    @classmethod
    def get(cls, exchange_type: str) -> "ExchangeRateLimiter":
        """Get or create the singleton limiter for an exchange."""
        if exchange_type not in cls._instances:
            cls._instances[exchange_type] = cls(exchange_type)
        return cls._instances[exchange_type]

    @classmethod
    def reset_all(cls) -> None:
        """Reset all limiters (for testing)."""
        cls._instances.clear()

    def __init__(self, exchange_type: str):
        limits = EXCHANGE_LIMITS.get(exchange_type, {"requests_per_second": 5, "burst": 10})
        self._rate = limits["requests_per_second"]
        self._burst = limits["burst"]
        self._tokens = float(self._burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._exchange_type = exchange_type

    async def acquire(self) -> None:
        """Wait until a request token is available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self._rate
                logger.debug(
                    "Rate limiter [%s]: throttling %.3fs",
                    self._exchange_type,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
                self._tokens = 0
            else:
                self._tokens -= 1
