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


def _cache_key(exchange: str, demo_mode: bool = False) -> str:
    """Build cache key with separate namespace for demo vs live."""
    return f"{exchange}_demo" if demo_mode else exchange


def _get_cached(exchange: str, demo_mode: bool = False) -> Optional[list[str]]:
    key = _cache_key(exchange, demo_mode)
    if key in _cache:
        ts, symbols = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return symbols
    return None


def _set_cached(exchange: str, symbols: list[str], demo_mode: bool = False) -> None:
    _cache[_cache_key(exchange, demo_mode)] = (time.time(), symbols)


def _fallback_symbols(exchange: str) -> list[str]:
    """Return hardcoded symbols from SYMBOL_MAP as fallback."""
    exchange_map = SYMBOL_MAP.get(exchange, {})
    return sorted(exchange_map.values())


async def _fetch_with_timeout(
    url: str,
    params: Optional[dict] = None,
    timeout: int = 10,
    headers: Optional[dict] = None,
) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
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


async def _fetch_bingx(demo_mode: bool = False) -> list[str]:
    # BingX demo uses a separate VST API host
    host = "open-api-vst.bingx.com" if demo_mode else "open-api.bingx.com"
    data = await _fetch_with_timeout(
        f"https://{host}/openApi/swap/v2/quote/contracts",
    )
    if data.get("code") != 0:
        raise ValueError(f"BingX API error: {data.get('msg')}")
    symbols = []
    for item in data.get("data", []):
        symbol = item.get("symbol", "")
        if symbol and "USDT" in symbol:
            symbols.append(symbol)
    return sorted(symbols)


async def _fetch_hyperliquid_testnet() -> list[str]:
    """Fetch symbols from the Hyperliquid testnet API."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.hyperliquid-testnet.xyz/info",
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


# Fetchers that accept demo_mode kwarg
_DEMO_AWARE_FETCHERS: dict[str, bool] = {
    "bingx": True,
}

_FETCHERS = {
    "bitget": _fetch_bitget,
    "weex": _fetch_weex,
    "hyperliquid": _fetch_hyperliquid,
    "bitunix": _fetch_bitunix,
    "bingx": _fetch_bingx,
}


async def get_exchange_symbols(exchange: str, demo_mode: bool = False) -> list[str]:
    """Get all available perpetual futures symbols for an exchange.

    Args:
        exchange: Exchange name (e.g. 'bitget', 'bingx').
        demo_mode: When True, fetch from demo/testnet endpoints where applicable.
                   BingX uses a separate VST API host for demo trading.
                   Hyperliquid uses a separate testnet API.
                   Other exchanges share the same symbol list for demo and live.

    Returns cached data if available, otherwise fetches from the exchange API.
    Falls back to hardcoded SYMBOL_MAP if the API call fails.
    """
    # Check cache first (separate cache for demo vs live)
    cached = _get_cached(exchange, demo_mode)
    if cached is not None:
        return cached

    # Hyperliquid testnet has a completely separate API
    if exchange == "hyperliquid" and demo_mode:
        fetcher_fn = _fetch_hyperliquid_testnet
    else:
        fetcher_fn = _FETCHERS.get(exchange)

    if not fetcher_fn:
        return _fallback_symbols(exchange)

    lock_key = _cache_key(exchange, demo_mode)
    lock = _get_lock(lock_key)
    async with lock:
        # Double-check cache after acquiring lock
        cached = _get_cached(exchange, demo_mode)
        if cached is not None:
            return cached

        try:
            # Pass demo_mode to fetchers that support it (e.g. BingX)
            if exchange in _DEMO_AWARE_FETCHERS:
                symbols = await fetcher_fn(demo_mode=demo_mode)
            else:
                symbols = await fetcher_fn()
            if symbols:
                _set_cached(exchange, symbols, demo_mode)
                mode_label = "demo" if demo_mode else "live"
                logger.info(f"Fetched {len(symbols)} symbols from {exchange} ({mode_label})")
                return symbols
        except Exception as e:
            logger.warning(f"Failed to fetch symbols from {exchange}: {e}")

        # Fallback
        fallback = _fallback_symbols(exchange)
        logger.info(f"Using fallback symbols for {exchange} ({len(fallback)} symbols)")
        return fallback


def clear_cache(exchange: Optional[str] = None) -> None:
    """Clear symbol cache for a specific exchange or all exchanges.

    When an exchange name is given, clears both demo and live cache entries.
    """
    if exchange:
        _cache.pop(exchange, None)
        _cache.pop(f"{exchange}_demo", None)
    else:
        _cache.clear()
