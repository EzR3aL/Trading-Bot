"""
Backtest Market Data Fetcher — Injects historical data into live strategy code.

Instead of calling Binance/CoinGecko APIs, this fetcher returns pre-loaded
historical data in the exact same format the live strategies expect.

Usage:
    mock_fetcher = BacktestMarketDataFetcher()
    mock_fetcher.set_state(current_hdp, history_slice, "BTC")
    strategy = EdgeIndicatorStrategy(params=params, data_fetcher=mock_fetcher)
    signal = await strategy.generate_signal("BTCUSDT")
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional

from src.backtest.historical_data import HistoricalDataPoint
from src.data.market_data import MarketDataFetcher, MarketMetrics
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Interval durations in milliseconds for close_time calculation
_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000,
    "1d": 86_400_000,
}


class BacktestMarketDataFetcher(MarketDataFetcher):
    """
    Drop-in replacement for MarketDataFetcher that serves historical data.

    Inherits all static indicator methods (calculate_ema, calculate_rsi,
    calculate_adx, etc.) and overrides only the async data-fetching methods
    to return data from HistoricalDataPoint objects.
    """

    def __init__(self):
        # Skip parent __init__ to avoid creating an aiohttp session
        self._session = None
        self._current: Optional[HistoricalDataPoint] = None
        self._history: List[HistoricalDataPoint] = []
        self._symbol: str = "BTC"
        self._interval: str = "1h"

    def set_state(
        self,
        current: HistoricalDataPoint,
        history: List[HistoricalDataPoint],
        symbol: str,
        interval: str = "1h",
    ):
        """Set the current data point and history for the next generate_signal() call.

        Called by BacktestEngine before each strategy invocation.

        Args:
            current: The current candle's HistoricalDataPoint
            history: List of preceding HistoricalDataPoints (oldest first)
            symbol: Base symbol (e.g. "BTC", "ETH")
            interval: Candle interval for this backtest (e.g. "15m", "1h", "4h")
        """
        self._current = current
        self._history = history
        self._symbol = symbol
        self._interval = interval

    # ------------------------------------------------------------------ #
    #  Kline Conversion                                                    #
    # ------------------------------------------------------------------ #

    def _hdp_to_kline(self, hdp: HistoricalDataPoint, interval: str = "1h") -> List:
        """Convert a HistoricalDataPoint to a Binance kline array.

        Format: [open_time, open, high, low, close, volume, close_time,
                 quote_vol, num_trades, taker_buy_base_vol,
                 taker_buy_quote_vol, ignore]
        """
        if self._symbol == "ETH":
            o, h, liq, c = hdp.eth_open, hdp.eth_high, hdp.eth_low, hdp.eth_price
            vol = hdp.eth_volume
        else:
            o, h, liq, c = hdp.btc_open, hdp.btc_high, hdp.btc_low, hdp.btc_price
            vol = hdp.btc_volume

        ts = int(hdp.timestamp.timestamp() * 1000)
        interval_ms = _INTERVAL_MS.get(interval, 3_600_000)
        quote_vol = vol * c if c > 0 else 0.0
        # Approximate taker buy volume as ratio-weighted
        taker_ratio = hdp.taker_buy_sell_ratio
        taker_buy_vol = vol * (taker_ratio / (1 + taker_ratio)) if taker_ratio > 0 else vol * 0.5
        taker_buy_quote = taker_buy_vol * c if c > 0 else 0.0

        return [
            ts,                        # open_time
            str(o),                    # open
            str(h),                    # high
            str(liq),                  # low
            str(c),                    # close
            str(vol),                  # volume
            ts + interval_ms - 1,      # close_time
            str(quote_vol),            # quote_asset_volume
            100,                       # number_of_trades (placeholder)
            str(taker_buy_vol),        # taker_buy_base_asset_volume
            str(taker_buy_quote),      # taker_buy_quote_asset_volume
            "0",                       # ignore
        ]

    # ------------------------------------------------------------------ #
    #  Overridden async data methods                                       #
    # ------------------------------------------------------------------ #

    async def _ensure_session(self):
        """No-op: no HTTP session needed for backtest.

        This override prevents strategies from silently creating a live
        MarketDataFetcher session when they call _ensure_fetcher().
        """
        pass

    async def close(self):
        """No-op: nothing to clean up."""
        pass

    async def get_binance_klines(
        self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 24
    ) -> List[List]:
        """Return historical data as Binance-format kline arrays."""
        # Use history + current, take the last `limit` points
        all_points = list(self._history)
        if self._current and (not all_points or all_points[-1] is not self._current):
            all_points.append(self._current)

        # Take last N points
        points = all_points[-limit:] if len(all_points) > limit else all_points

        if len(points) < limit:
            logger.debug(
                f"BacktestMarketDataFetcher: {len(points)} candles available, "
                f"{limit} requested for {interval}. Indicators may be in warm-up."
            )

        klines = [self._hdp_to_kline(hdp, interval) for hdp in points]
        return klines

    def _calculate_24h_change(self) -> tuple:
        """Calculate actual 24h price change from history instead of per-candle change.

        For intraday timeframes (15m, 1h, 4h), the HDP's btc_24h_change is actually
        the per-candle change, not the real 24h change. This method looks back ~24h
        in history to compute the actual change, making results timeframe-dependent.
        """
        hdp = self._current
        btc_change = hdp.btc_24h_change
        eth_change = hdp.eth_24h_change

        if not self._history:
            return btc_change, eth_change

        target_time = hdp.timestamp - timedelta(hours=24)
        # Find the HDP closest to 24h ago
        best = None
        best_delta = float("inf")
        for h in self._history:
            delta = abs((h.timestamp - target_time).total_seconds())
            if delta < best_delta:
                best_delta = delta
                best = h

        # Only use if within 4h of target (covers 4h candle gaps)
        if best and best_delta < 14400:
            if best.btc_price > 0:
                btc_change = (hdp.btc_price - best.btc_price) / best.btc_price * 100
            if best.eth_price > 0:
                eth_change = (hdp.eth_price - best.eth_price) / best.eth_price * 100

        return round(btc_change, 4), round(eth_change, 4)

    async def fetch_all_metrics(self, require_reliable: bool = True) -> MarketMetrics:
        """Build MarketMetrics from the current HistoricalDataPoint."""
        hdp = self._current
        if hdp is None:
            raise ValueError("BacktestMarketDataFetcher: no current data point set")

        # Classify fear & greed
        fgi = hdp.fear_greed_index
        if fgi <= 20:
            classification = "Extreme Fear"
        elif fgi <= 40:
            classification = "Fear"
        elif fgi <= 60:
            classification = "Neutral"
        elif fgi <= 80:
            classification = "Greed"
        else:
            classification = "Extreme Greed"

        # Use actual 24h change (not per-candle change)
        btc_24h_change, eth_24h_change = self._calculate_24h_change()

        return MarketMetrics(
            fear_greed_index=fgi,
            fear_greed_classification=classification,
            long_short_ratio=hdp.long_short_ratio,
            funding_rate_btc=hdp.funding_rate_btc,
            funding_rate_eth=hdp.funding_rate_eth,
            btc_24h_change_percent=btc_24h_change,
            eth_24h_change_percent=eth_24h_change,
            btc_price=hdp.btc_price,
            eth_price=hdp.eth_price,
            btc_open_interest=hdp.open_interest_btc,
            eth_open_interest=0.0,
            timestamp=hdp.timestamp,
        )

    async def get_news_sentiment(
        self,
        query: str = "bitcoin OR cryptocurrency OR crypto",
        lookback_hours: int = 24,
        max_records: int = 25,
    ) -> Dict[str, Any]:
        """No news data in historical backtest — return neutral stub."""
        return {"average_tone": 0.0, "article_count": 0}

    async def calculate_oiwap(
        self, symbol: str, klines: Optional[List[List]] = None, period_hours: int = 24
    ) -> float:
        """No granular OI data available in backtest — return 0."""
        return 0.0

    async def get_funding_rate_binance(self, symbol: str = "BTCUSDT") -> float:
        """Return funding rate from current HistoricalDataPoint."""
        if self._current is None:
            return 0.0
        if "ETH" in symbol.upper():
            return self._current.funding_rate_eth
        return self._current.funding_rate_btc

    async def get_predicted_funding_rate(self, symbol: str = "BTCUSDT") -> float:
        """Use current funding rate as prediction (best available approximation)."""
        return await self.get_funding_rate_binance(symbol)

    async def get_24h_ticker(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """Build 24h ticker from HistoricalDataPoint with actual 24h change."""
        if self._current is None:
            return {"symbol": symbol, "price": 0, "price_change_percent": 0,
                    "high_24h": 0, "low_24h": 0, "volume_24h": 0, "quote_volume_24h": 0}

        hdp = self._current
        btc_24h_change, eth_24h_change = self._calculate_24h_change()

        if "ETH" in symbol.upper():
            return {
                "symbol": symbol,
                "price": hdp.eth_price,
                "price_change_percent": eth_24h_change,
                "high_24h": hdp.eth_high,
                "low_24h": hdp.eth_low,
                "volume_24h": hdp.eth_volume,
                "quote_volume_24h": hdp.eth_volume * hdp.eth_price,
            }
        return {
            "symbol": symbol,
            "price": hdp.btc_price,
            "price_change_percent": btc_24h_change,
            "high_24h": hdp.btc_high,
            "low_24h": hdp.btc_low,
            "volume_24h": hdp.btc_volume,
            "quote_volume_24h": hdp.btc_volume * hdp.btc_price,
        }

    async def get_open_interest(self, symbol: str = "BTCUSDT") -> float:
        """Return open interest from current HistoricalDataPoint."""
        if self._current is None:
            return 0.0
        if "ETH" in symbol.upper():
            return 0.0  # No ETH OI in historical data
        return self._current.open_interest_btc

    async def get_top_trader_long_short_ratio(self, symbol: str = "BTCUSDT") -> float:
        """Return top trader L/S ratio from current HistoricalDataPoint."""
        if self._current is None:
            return 1.0
        return self._current.top_trader_long_short_ratio

    async def get_long_short_ratio(self, symbol: str = "BTCUSDT") -> float:
        """Return long/short ratio from current HistoricalDataPoint."""
        if self._current is None:
            return 1.0
        return self._current.long_short_ratio

    async def get_fear_greed_index(self):
        """Return fear & greed from current HistoricalDataPoint."""
        if self._current is None:
            return (50, "Neutral")
        fgi = self._current.fear_greed_index
        classification = self._current.fear_greed_classification
        return (fgi, classification)

    async def get_open_interest_history(
        self, symbol: str = "BTCUSDT", period: str = "1h", limit: int = 24
    ) -> list:
        """No granular OI history in backtest."""
        return []

    async def get_price_volatility(self, symbol: str = "BTCUSDT", period: int = 24) -> float:
        """Return historical volatility from current HistoricalDataPoint."""
        if self._current is None:
            return 0.0
        return self._current.historical_volatility

    async def get_recent_liquidations(self, symbol: str = "BTCUSDT", limit: int = 100) -> list:
        """No liquidation data in backtest."""
        return []

    async def get_order_book_depth(self, symbol: str = "BTCUSDT", limit: int = 20) -> dict:
        """No order book data in backtest — return empty."""
        return {"bids": [], "asks": []}

    async def get_trend_direction(self, symbol: str = "BTCUSDT") -> str:
        """Derive trend from 24h price change."""
        if self._current is None:
            return "neutral"
        change = self._current.btc_24h_change if "BTC" in symbol.upper() or "ETH" not in symbol.upper() else self._current.eth_24h_change
        if change > 1.0:
            return "uptrend"
        elif change < -1.0:
            return "downtrend"
        return "neutral"
