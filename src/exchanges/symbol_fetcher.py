"""Fetch available perpetual futures symbols from exchanges (public, no auth).

Uses in-memory cache with configurable TTL to avoid hitting exchange APIs on every request.
"""

import asyncio
import time
from typing import Optional

import aiohttp

from src.exchanges.symbol_map import SYMBOL_MAP
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Cache: exchange_name -> (timestamp, symbols_list)
_cache: dict[str, tuple[float, list[str]]] = {}
_CACHE_TTL = 3600  # 1 hour

# Lock per exchange to prevent concurrent fetches
_locks: dict[str, asyncio.Lock] = {}


def _get_lock(exchange: str) -> asyncio.Lock:
    if exchange not in _locks:
        _locks[exchange] = asyncio.Lock()
    return _locks[exchange]


def _get_cached(exchange: str) -> Optional[list[str]]:
    if exchange in _cache:
        ts, symbols = _cache[exchange]
        if time.time() - ts < _CACHE_TTL:
            return symbols
    return None


def _set_cached(exchange: str, symbols: list[str]) -> None:
    _cache[exchange] = (time.time(), symbols)


def _fallback_symbols(exchange: str) -> list[str]:
    """Return hardcoded symbols from SYMBOL_MAP as fallback."""
    exchange_map = SYMBOL_MAP.get(exchange, {})
    return sorted(exchange_map.values())


async def _fetch_with_timeout(url: str, params: Optional[dict] = None, timeout: int = 10) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            return await resp.json()


async def _fetch_bitget() -> list[str]:
    data = await _fetch_with_timeout(
        "https://api.bitget.com/api/v2/mix/market/contracts",
        params={"productType": "USDT-FUTURES"},
    )
    if data.get("code") != "00000":
        raise ValueError(f"Bitget API error: {data.get('msg')}")
    symbols = []
    for item in data.get("data", []):
        symbol = item.get("symbol", "")
        if symbol and symbol.endswith("USDT"):
            symbols.append(symbol)
    return sorted(symbols)


async def _fetch_weex() -> list[str]:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api-contract.weex.com/capi/v2/market/contracts",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json()
    # Weex returns a plain list of contract objects (not wrapped in {code, data})
    items = data if isinstance(data, list) else data.get("data", [])
    symbols = []
    for item in items:
        symbol = item.get("symbol", "")
        # Weex returns symbols like "cmt_btcusdt" — normalize to BTCUSDT
        if symbol.startswith("cmt_") and symbol.endswith("usdt"):
            normalized = symbol[4:].upper()  # strip cmt_ prefix
            if not normalized.endswith("SUSDT"):  # skip demo symbols
                symbols.append(normalized)
    return sorted(symbols)


async def _fetch_hyperliquid() -> list[str]:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "meta"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json()
    symbols = []
    for asset in data.get("universe", []):
        name = asset.get("name", "")
        if name:
            symbols.append(name)
    return sorted(symbols)


async def _fetch_bitunix() -> list[str]:
    data = await _fetch_with_timeout(
        "https://fapi.bitunix.com/api/v1/futures/market/trading_pairs",
    )
    if data.get("code") != 0:
        raise ValueError(f"Bitunix API error: {data.get('msg')}")
    symbols = []
    for item in data.get("data", []):
        symbol = item.get("symbol", "")
        if symbol:
            symbols.append(symbol)
    return sorted(symbols)


async def _fetch_bingx() -> list[str]:
    data = await _fetch_with_timeout(
        "https://open-api.bingx.com/openApi/swap/v2/quote/contracts",
    )
    if data.get("code") != 0:
        raise ValueError(f"BingX API error: {data.get('msg')}")
    symbols = []
    for item in data.get("data", []):
        symbol = item.get("symbol", "")
        if symbol and "USDT" in symbol:
            symbols.append(symbol)
    return sorted(symbols)


_FETCHERS = {
    "bitget": _fetch_bitget,
    "weex": _fetch_weex,
    "hyperliquid": _fetch_hyperliquid,
    "bitunix": _fetch_bitunix,
    "bingx": _fetch_bingx,
}


async def get_exchange_symbols(exchange: str) -> list[str]:
    """Get all available perpetual futures symbols for an exchange.

    Returns cached data if available, otherwise fetches from the exchange API.
    Falls back to hardcoded SYMBOL_MAP if the API call fails.
    """
    # Check cache first
    cached = _get_cached(exchange)
    if cached is not None:
        return cached

    fetcher = _FETCHERS.get(exchange)
    if not fetcher:
        return _fallback_symbols(exchange)

    lock = _get_lock(exchange)
    async with lock:
        # Double-check cache after acquiring lock
        cached = _get_cached(exchange)
        if cached is not None:
            return cached

        try:
            symbols = await fetcher()
            if symbols:
                _set_cached(exchange, symbols)
                logger.info(f"Fetched {len(symbols)} symbols from {exchange}")
                return symbols
        except Exception as e:
            logger.warning(f"Failed to fetch symbols from {exchange}: {e}")

        # Fallback
        fallback = _fallback_symbols(exchange)
        logger.info(f"Using fallback symbols for {exchange} ({len(fallback)} symbols)")
        return fallback


def clear_cache(exchange: Optional[str] = None) -> None:
    """Clear symbol cache for a specific exchange or all exchanges."""
    if exchange:
        _cache.pop(exchange, None)
    else:
        _cache.clear()
