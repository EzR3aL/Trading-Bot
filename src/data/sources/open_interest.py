"""Open interest, liquidation, and order book data (Binance Futures)."""

from typing import Dict, Any, List, Optional

from src.utils.logger import get_logger
from src.utils.circuit_breaker import CircuitBreakerError
from src.data.sources import breakers as _breakers

from .base import to_binance_symbol

logger = get_logger(__name__)

BINANCE_FUTURES_URL = "https://fapi.binance.com"


async def fetch_open_interest(fetcher, symbol: str = "BTCUSDT") -> float:
    """Fetch open interest from Binance Futures.

    Returns:
        Open interest in base currency
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/openInterest"
        params = {"symbol": to_binance_symbol(symbol)}

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.binance_breaker.call(_fetch)

        if data:
            oi = float(data.get("openInterest", 0))
            logger.info(f"Open Interest ({symbol}): {oi:.2f}")
            return oi

    except CircuitBreakerError as e:
        logger.warning(f"Binance API circuit open for open interest: {e}")
    except Exception as e:
        logger.error(f"Error fetching Open Interest: {e}")

    return 0.0


async def fetch_open_interest_history(
    fetcher, symbol: str = "BTCUSDT", period: str = "1h", limit: int = 24
) -> list:
    """Fetch open interest history from Binance.

    Returns:
        List of historical open interest data
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/futures/data/openInterestHist"
        params = {
            "symbol": to_binance_symbol(symbol),
            "period": period,
            "limit": limit,
        }

        async def _fetch():
            return await fetcher._get(url, params)

        data = await _breakers.binance_breaker.call(_fetch)
        return data if data else []

    except CircuitBreakerError:
        logger.warning("Circuit breaker open for Binance OI history")
        return []
    except Exception as e:
        logger.error(f"Error fetching OI history: {e}")
        return []


async def fetch_recent_liquidations(fetcher, symbol: str = "BTCUSDT", limit: int = 100) -> list:
    """Fetch recent forced liquidations from Binance.

    Note: This endpoint may have restrictions or require API key.

    Returns:
        List of recent liquidations
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/forceOrders"
        params = {
            "symbol": to_binance_symbol(symbol),
            "limit": limit,
        }

        async def _fetch():
            return await fetcher._get(url, params)

        data = await _breakers.binance_breaker.call(_fetch)
        return data if data else []

    except CircuitBreakerError:
        logger.warning("Circuit breaker open for Binance liquidations")
        return []
    except Exception as e:
        logger.error(f"Error fetching liquidations: {e}")
        return []


async def fetch_order_book_depth(fetcher, symbol: str = "BTCUSDT", limit: int = 20) -> dict:
    """Fetch order book depth from Binance Futures.

    Returns:
        Dict with midPrice, spreadBps, imbalanceTop10, interpretation
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/depth"
        params = {"symbol": to_binance_symbol(symbol), "limit": limit}

        async def _fetch():
            return await fetcher._get(url, params)

        data = await _breakers.binance_breaker.call(_fetch)
        if not data or "bids" not in data or "asks" not in data:
            return {}

        bids = data["bids"][:10]
        asks = data["asks"][:10]
        if not bids or not asks:
            return {}

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid_price = (best_bid + best_ask) / 2
        spread_bps = ((best_ask - best_bid) / mid_price) * 10000 if mid_price > 0 else 0

        sum_bids = sum(float(b[1]) for b in bids)
        sum_asks = sum(float(a[1]) for a in asks)
        total = sum_bids + sum_asks
        imbalance = (sum_bids - sum_asks) / total if total > 0 else 0

        if abs(imbalance) < 0.1:
            interpretation = f"Balanced order book ({abs(imbalance)*100:.1f}% imbalance). No clear directional bias."
        elif imbalance > 0.3:
            interpretation = f"Strong bid-side imbalance ({imbalance*100:.1f}%). Buyers dominating — bullish pressure."
        elif imbalance > 0.1:
            interpretation = f"Moderate bid-side imbalance ({imbalance*100:.1f}%). Slight buy pressure."
        elif imbalance < -0.3:
            interpretation = f"Strong ask-side imbalance ({abs(imbalance)*100:.1f}%). Sellers dominating — bearish pressure."
        else:
            interpretation = f"Moderate ask-side imbalance ({abs(imbalance)*100:.1f}%). Slight sell pressure."

        return {
            "midPrice": round(mid_price, 2),
            "spreadBps": round(spread_bps, 4),
            "imbalanceTop10": round(imbalance, 4),
            "interpretation": interpretation,
        }

    except CircuitBreakerError:
        logger.warning("Circuit breaker open for Binance order book")
        return {}
    except Exception as e:
        logger.error(f"Error fetching order book depth: {e}")
        return {}


async def calculate_oiwap(
    fetcher, symbol: str = "BTCUSDT", klines: Optional[List[List]] = None, period_hours: int = 24
) -> float:
    """Approximate OI-Weighted Average Price.

    Uses OI history changes as weights: positions opened/closed at a price
    contribute more to the weighted average.

    OIWAP = sum(typical_price * abs(OI_change)) / sum(abs(OI_change))

    Returns:
        OIWAP price, or 0.0 if unavailable.
    """
    try:
        if klines is None:
            # Use fetcher method to allow test mocking
            klines = await fetcher.get_binance_klines(symbol, "1h", period_hours)
        if not klines:
            return 0.0

        # Use fetcher method to allow test mocking
        oi_history = await fetcher.get_open_interest_history(symbol, "1h", period_hours)
        if not oi_history or len(oi_history) < 2:
            return 0.0

        oi_map = {}
        for entry in oi_history:
            ts = int(entry.get("timestamp", 0))
            oi = float(entry.get("sumOpenInterest", 0))
            oi_map[ts] = oi

        total_weighted = 0.0
        total_weight = 0.0

        for i in range(len(klines)):
            try:
                kline_ts = int(klines[i][0])
                high = float(klines[i][2])
                low = float(klines[i][3])
                close = float(klines[i][4])
                tp = (high + low + close) / 3

                oi_current = oi_map.get(kline_ts, 0)
                if i > 0:
                    prev_ts = int(klines[i - 1][0])
                    oi_prev = oi_map.get(prev_ts, oi_current)
                else:
                    oi_prev = oi_current

                oi_change = abs(oi_current - oi_prev)
                if oi_change > 0:
                    total_weighted += tp * oi_change
                    total_weight += oi_change
            except (IndexError, ValueError, TypeError):
                continue

        if total_weight == 0:
            return 0.0

        oiwap = total_weighted / total_weight
        logger.info(f"OIWAP ({symbol}): {oiwap:.2f}")
        return oiwap

    except Exception as e:
        logger.error(f"Error calculating OIWAP: {e}")
        return 0.0
