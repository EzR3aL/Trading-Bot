"""Spot trading volume analysis and Coinbase premium."""

import asyncio
from typing import Dict, Any, List

from src.utils.logger import get_logger
from src.utils.circuit_breaker import CircuitBreakerError
from src.data.sources import breakers as _breakers

logger = get_logger(__name__)

COINBASE_URL = "https://api.exchange.coinbase.com"
BINANCE_SPOT_URL = "https://api.binance.com"


def get_spot_volume_analysis(klines: List[List]) -> Dict[str, Any]:
    """Analyze buy/sell volume split from kline data.

    kline[5] = total volume, kline[9] = taker buy base volume.
    buy_ratio > 0.55 = accumulation, < 0.45 = distribution.

    Returns:
        {"buy_ratio": float, "sell_ratio": float, "total_volume": float,
         "buy_volume": float, "sell_volume": float}
    """
    total_volume = 0.0
    buy_volume = 0.0

    for k in klines:
        try:
            vol = float(k[5])
            buy_vol = float(k[9])
            total_volume += vol
            buy_volume += buy_vol
        except (IndexError, ValueError, TypeError):
            continue

    if total_volume == 0:
        return {
            "buy_ratio": 0.5,
            "sell_ratio": 0.5,
            "total_volume": 0.0,
            "buy_volume": 0.0,
            "sell_volume": 0.0,
        }

    sell_volume = total_volume - buy_volume
    buy_ratio = buy_volume / total_volume
    return {
        "buy_ratio": buy_ratio,
        "sell_ratio": 1.0 - buy_ratio,
        "total_volume": total_volume,
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
    }


async def fetch_coinbase_premium(fetcher, symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """Calculate Coinbase Premium: price diff between Coinbase and Binance spot.

    Positive premium = US institutional buying pressure.
    Negative premium = selling pressure or arbitrage flow.

    Returns:
        Dict with premium_pct, coinbase_price, binance_price, signal
    """
    try:
        base = symbol.replace("USDT", "").replace("USD", "")
        cb_product = f"{base}-USD"
        binance_symbol = f"{base}USDT"

        async def _fetch_coinbase():
            url = f"{COINBASE_URL}/products/{cb_product}/ticker"
            return await fetcher._get_with_retry(url, timeout=8)

        async def _fetch_binance():
            url = f"{BINANCE_SPOT_URL}/api/v3/ticker/price"
            return await fetcher._get_with_retry(url, {"symbol": binance_symbol}, timeout=8)

        cb_data, bn_data = await asyncio.gather(
            _breakers.coinbase_breaker.call(_fetch_coinbase),
            _breakers.binance_breaker.call(_fetch_binance),
            return_exceptions=True,
        )

        if isinstance(cb_data, Exception) or isinstance(bn_data, Exception):
            raise ValueError(f"Fetch failed: cb={cb_data}, bn={bn_data}")

        cb_price = float(cb_data.get("price", 0))
        bn_price = float(bn_data.get("price", 0))

        if cb_price <= 0 or bn_price <= 0:
            return {"premium_pct": 0.0, "coinbase_price": 0.0, "binance_price": 0.0, "signal": "neutral"}

        premium_pct = ((cb_price - bn_price) / bn_price) * 100

        if premium_pct > 0.05:
            signal = "bullish"
        elif premium_pct < -0.05:
            signal = "bearish"
        else:
            signal = "neutral"

        logger.info(f"Coinbase Premium ({base}): {premium_pct:.4f}% (CB=${cb_price:,.2f}, BN=${bn_price:,.2f})")
        return {
            "premium_pct": round(premium_pct, 4),
            "coinbase_price": cb_price,
            "binance_price": bn_price,
            "signal": signal,
        }

    except CircuitBreakerError as e:
        logger.warning(f"Coinbase/Binance API circuit open: {e}")
    except Exception as e:
        logger.error(f"Error fetching Coinbase premium: {e}")

    return {"premium_pct": 0.0, "coinbase_price": 0.0, "binance_price": 0.0, "signal": "neutral"}
