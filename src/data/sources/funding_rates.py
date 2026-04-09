"""Funding rate data sources (Binance, Bitget, Bybit)."""

import asyncio
from typing import Dict, Any

from src.utils.logger import get_logger
from src.utils.circuit_breaker import CircuitBreakerError
from src.data.sources import breakers as _breakers

from .base import to_binance_symbol

logger = get_logger(__name__)

BINANCE_FUTURES_URL = "https://fapi.binance.com"
BITGET_URL = "https://api.bitget.com/api/v2"
BYBIT_URL = "https://api.bybit.com"


async def fetch_funding_rate_binance(fetcher, symbol: str = "BTCUSDT") -> float:
    """Fetch the current funding rate from Binance Futures.

    Positive rate: Longs pay shorts (bullish sentiment)
    Negative rate: Shorts pay longs (bearish sentiment)

    Returns:
        Funding rate as decimal (e.g., 0.0001 = 0.01%)
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/premiumIndex"
        params = {"symbol": to_binance_symbol(symbol)}

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.binance_breaker.call(_fetch)

        if data:
            rate = float(data.get("lastFundingRate", 0))
            logger.info(f"Funding Rate ({symbol}): {rate:.6f} ({rate*100:.4f}%)")
            return rate

    except CircuitBreakerError as e:
        logger.warning(f"Binance API circuit open for funding rate: {e}")
    except Exception as e:
        logger.error(f"Error fetching Funding Rate: {e}")

    return 0.0


async def fetch_predicted_funding_rate(fetcher, symbol: str = "BTCUSDT") -> float:
    """Get the predicted next funding rate from Binance.

    Returns:
        Predicted funding rate
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/premiumIndex"
        params = {"symbol": to_binance_symbol(symbol)}

        data = await fetcher._get(url, params)

        if data:
            rate = float(data.get("interestRate", 0))
            return rate

    except Exception as e:
        logger.error(f"Error fetching predicted funding rate: {e}")

    return 0.0


async def fetch_bitget_funding_rate(fetcher, symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """Fetch current funding rate from Bitget.

    Comparing Binance vs Bitget funding rates reveals cross-exchange divergence.

    Returns:
        Dict with funding_rate, symbol
    """
    try:
        url = f"{BITGET_URL}/mix/market/current-fund-rate"
        params = {"symbol": symbol, "productType": "USDT-FUTURES"}

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.bitget_breaker.call(_fetch)

        if data and data.get("code") == "00000" and "data" in data:
            items = data["data"]
            if items and len(items) > 0:
                rate = float(items[0].get("fundingRate", 0))
                logger.info(f"Bitget Funding Rate ({symbol}): {rate:.6f}")
                return {"funding_rate": rate, "symbol": symbol}

    except CircuitBreakerError as e:
        logger.warning(f"Bitget API circuit open: {e}")
    except Exception as e:
        logger.error(f"Error fetching Bitget funding rate: {e}")

    return {"funding_rate": 0.0, "symbol": symbol}


async def fetch_bybit_futures(fetcher, symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """Fetch Bybit futures data: OI, funding rate, volume via Bybit V5 public API.

    Returns:
        Dict with open_interest, funding_rate, volume_24h, next_funding_time, price
    """
    try:
        async def _fetch_ticker():
            url = f"{BYBIT_URL}/v5/market/tickers"
            return await fetcher._get_with_retry(url, {"category": "linear", "symbol": symbol})

        async def _fetch_funding():
            url = f"{BYBIT_URL}/v5/market/funding/history"
            return await fetcher._get_with_retry(url, {"category": "linear", "symbol": symbol, "limit": "1"})

        ticker_data, funding_data = await asyncio.gather(
            _breakers.bybit_breaker.call(_fetch_ticker),
            _breakers.bybit_breaker.call(_fetch_funding),
            return_exceptions=True,
        )

        result = {
            "open_interest": 0.0,
            "funding_rate": 0.0,
            "volume_24h": 0.0,
            "next_funding_time": "",
            "price": 0.0,
        }

        if not isinstance(ticker_data, Exception) and ticker_data:
            tickers = ticker_data.get("result", {}).get("list", [])
            if tickers:
                t = tickers[0]
                result["open_interest"] = float(t.get("openInterest", 0))
                result["volume_24h"] = float(t.get("volume24h", 0))
                result["price"] = float(t.get("lastPrice", 0))
                result["next_funding_time"] = t.get("nextFundingTime", "")

        if not isinstance(funding_data, Exception) and funding_data:
            funding_list = funding_data.get("result", {}).get("list", [])
            if funding_list:
                result["funding_rate"] = float(funding_list[0].get("fundingRate", 0))

        logger.info(
            f"Bybit Futures ({symbol}): OI={result['open_interest']:.0f}, "
            f"FR={result['funding_rate']:.6f}, Vol24h={result['volume_24h']:.0f}"
        )
        return result

    except CircuitBreakerError as e:
        logger.warning(f"Bybit API circuit open: {e}")
    except Exception as e:
        logger.error(f"Error fetching Bybit futures data: {e}")

    return {"open_interest": 0.0, "funding_rate": 0.0, "volume_24h": 0.0, "next_funding_time": "", "price": 0.0}
