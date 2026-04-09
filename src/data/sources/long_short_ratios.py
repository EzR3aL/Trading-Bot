"""Long/Short ratio data (Binance Futures)."""

from src.utils.logger import get_logger
from src.utils.circuit_breaker import CircuitBreakerError
from src.data.sources import breakers as _breakers

from .base import to_binance_symbol

logger = get_logger(__name__)

BINANCE_FUTURES_URL = "https://fapi.binance.com"


async def fetch_long_short_ratio(fetcher, symbol: str = "BTCUSDT") -> float:
    """Fetch the Global Long/Short Account Ratio from Binance Futures.

    Ratio > 1: More accounts are long
    Ratio < 1: More accounts are short

    Returns:
        Long/Short ratio as float
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/futures/data/globalLongShortAccountRatio"
        params = {
            "symbol": to_binance_symbol(symbol),
            "period": "1h",
            "limit": 1,
        }

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.binance_breaker.call(_fetch)

        if data and len(data) > 0:
            ratio = float(data[0].get("longShortRatio", 1.0))
            logger.info(f"Long/Short Ratio ({symbol}): {ratio:.4f}")
            return ratio

    except CircuitBreakerError as e:
        logger.warning(f"Binance API circuit open for L/S ratio: {e}")
    except Exception as e:
        logger.error(f"Error fetching Long/Short Ratio: {e}")

    return 1.0


async def fetch_top_trader_long_short_ratio(fetcher, symbol: str = "BTCUSDT") -> float:
    """Fetch the Top Trader Long/Short Ratio (Positions) from Binance.

    Shows the ratio among top traders (whales).

    Returns:
        Long/Short ratio as float
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/futures/data/topLongShortPositionRatio"
        params = {
            "symbol": to_binance_symbol(symbol),
            "period": "1h",
            "limit": 1,
        }

        async def _fetch():
            return await fetcher._get(url, params)

        data = await _breakers.binance_breaker.call(_fetch)

        if data and len(data) > 0:
            ratio = float(data[0].get("longShortRatio", 1.0))
            logger.info(f"Top Trader Long/Short Ratio ({symbol}): {ratio:.4f}")
            return ratio

    except CircuitBreakerError:
        logger.warning("Circuit breaker open for Binance top trader L/S ratio")
    except Exception as e:
        logger.error(f"Error fetching Top Trader Long/Short Ratio: {e}")

    return 1.0
