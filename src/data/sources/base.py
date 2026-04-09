"""Shared utilities for data source modules.

Contains the HTTP helper mixin and symbol normalization used by all sources.
"""

import asyncio
import re
from typing import Optional, Dict, Any

import aiohttp

from src.utils.logger import get_logger
from src.utils.circuit_breaker import with_retry

logger = get_logger(__name__)

# Regex to strip quote suffixes for symbol normalization
_QUOTE_SUFFIXES_RE = re.compile(r"[-_/]?(USDT|USDC|USD|PERP|BUSD)$", re.IGNORECASE)


def to_binance_symbol(symbol: str) -> str:
    """Normalize any exchange symbol format to Binance Futures format (e.g. BTCUSDT).

    Handles: "BTC" -> "BTCUSDT", "BTC-USDT" -> "BTCUSDT",
             "BTCUSDT" -> "BTCUSDT" (no-op).
    """
    s = symbol.upper().strip()
    # Already in Binance format (ends with USDT without separator)
    if s.endswith("USDT") and not any(sep in s for sep in ("-", "_", "/")):
        return s
    # Strip any quote suffix + separator, then append USDT
    base = _QUOTE_SUFFIXES_RE.sub("", s)
    return f"{base}USDT"


class HttpMixin:
    """Mixin providing HTTP GET with retry for data source classes.

    Requires self._session (aiohttp.ClientSession) and self._ensure_session().
    These are provided by MarketDataFetcher which owns the session lifecycle.
    """

    _session: Optional[aiohttp.ClientSession]

    async def _ensure_session(self):
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def _get(self, url: str, params: Optional[Dict] = None, timeout: int = 10) -> Dict[str, Any]:
        """Make a GET request with error handling."""
        await self._ensure_session()
        try:
            async with self._session.get(url, params=params, timeout=timeout) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    raise aiohttp.ClientResponseError(
                        response.request_info,
                        response.history,
                        status=429,
                        message="Rate limited"
                    )
                else:
                    logger.error(f"HTTP {response.status} from {url}")
                    return {}
        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching {url}: {e}")
            raise
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {url}")
            raise
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return {}

    @with_retry(max_attempts=3, min_wait=1.0, max_wait=5.0, retry_on=(aiohttp.ClientError, asyncio.TimeoutError))
    async def _get_with_retry(self, url: str, params: Optional[Dict] = None, timeout: int = 10) -> Dict[str, Any]:
        """Make a GET request with automatic retry on failure."""
        return await self._get(url, params, timeout=timeout)
