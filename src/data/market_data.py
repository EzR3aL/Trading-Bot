"""
Market Data Fetcher for the Contrarian Liquidation Hunter Strategy.

Fetches:
- Fear & Greed Index (Alternative.me)
- Long/Short Ratio (Binance Futures)
- Funding Rates (Binance & Bitget)
- 24h Ticker Data (Price trends)
- Open Interest (Derivatives data)
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

import aiohttp

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MarketMetrics:
    """Container for all market metrics used in strategy decisions."""

    # Fear & Greed Index (0-100)
    fear_greed_index: int
    fear_greed_classification: str  # Extreme Fear, Fear, Neutral, Greed, Extreme Greed

    # Long/Short Ratio (from Binance)
    long_short_ratio: float  # > 1 means more longs, < 1 means more shorts

    # Funding Rates (as decimal, e.g., 0.0001 = 0.01%)
    funding_rate_btc: float
    funding_rate_eth: float

    # 24h Price Change
    btc_24h_change_percent: float
    eth_24h_change_percent: float

    # Current Prices
    btc_price: float
    eth_price: float

    # Open Interest
    btc_open_interest: float
    eth_open_interest: float

    # Timestamp
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            "fear_greed_index": self.fear_greed_index,
            "fear_greed_classification": self.fear_greed_classification,
            "long_short_ratio": self.long_short_ratio,
            "funding_rate_btc": self.funding_rate_btc,
            "funding_rate_eth": self.funding_rate_eth,
            "btc_24h_change_percent": self.btc_24h_change_percent,
            "eth_24h_change_percent": self.eth_24h_change_percent,
            "btc_price": self.btc_price,
            "eth_price": self.eth_price,
            "btc_open_interest": self.btc_open_interest,
            "eth_open_interest": self.eth_open_interest,
            "timestamp": self.timestamp.isoformat(),
        }


class MarketDataFetcher:
    """
    Fetches market data from various sources for strategy analysis.

    Sources:
    - Alternative.me: Fear & Greed Index
    - Binance Futures API: Long/Short Ratio, Funding Rates, Open Interest
    - Bitget API: Additional funding rate data
    """

    # API Endpoints
    FEAR_GREED_URL = "https://api.alternative.me/fng/"
    BINANCE_FUTURES_URL = "https://fapi.binance.com"
    COINGLASS_URL = "https://open-api.coinglass.com/public/v2"

    def __init__(self):
        """Initialize the market data fetcher."""
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _ensure_session(self):
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, url: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GET request."""
        await self._ensure_session()
        try:
            async with self._session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"HTTP {response.status} from {url}")
                    return {}
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return {}

    # ==================== Fear & Greed Index ====================

    async def get_fear_greed_index(self) -> Tuple[int, str]:
        """
        Fetch the current Fear & Greed Index from Alternative.me.

        Returns:
            Tuple of (index value 0-100, classification string)
        """
        try:
            data = await self._get(self.FEAR_GREED_URL, {"limit": "1"})

            if data and "data" in data and len(data["data"]) > 0:
                fng_data = data["data"][0]
                value = int(fng_data.get("value", 50))
                classification = fng_data.get("value_classification", "Neutral")

                logger.info(f"Fear & Greed Index: {value} ({classification})")
                return value, classification

        except Exception as e:
            logger.error(f"Error fetching Fear & Greed Index: {e}")

        # Return neutral on error
        return 50, "Neutral"

    # ==================== Long/Short Ratio ====================

    async def get_long_short_ratio(self, symbol: str = "BTCUSDT") -> float:
        """
        Fetch the Global Long/Short Account Ratio from Binance Futures.

        This shows the ratio of long positions to short positions among all accounts.
        Ratio > 1: More accounts are long
        Ratio < 1: More accounts are short

        Args:
            symbol: Trading pair (default: BTCUSDT)

        Returns:
            Long/Short ratio as float
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/futures/data/globalLongShortAccountRatio"
            params = {
                "symbol": symbol,
                "period": "1h",  # 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d
                "limit": 1,
            }

            data = await self._get(url, params)

            if data and len(data) > 0:
                ratio = float(data[0].get("longShortRatio", 1.0))
                logger.info(f"Long/Short Ratio ({symbol}): {ratio:.4f}")
                return ratio

        except Exception as e:
            logger.error(f"Error fetching Long/Short Ratio: {e}")

        # Return neutral on error
        return 1.0

    async def get_top_trader_long_short_ratio(self, symbol: str = "BTCUSDT") -> float:
        """
        Fetch the Top Trader Long/Short Ratio (Positions) from Binance.

        This shows the ratio among top traders (whales).

        Args:
            symbol: Trading pair (default: BTCUSDT)

        Returns:
            Long/Short ratio as float
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/futures/data/topLongShortPositionRatio"
            params = {
                "symbol": symbol,
                "period": "1h",
                "limit": 1,
            }

            data = await self._get(url, params)

            if data and len(data) > 0:
                ratio = float(data[0].get("longShortRatio", 1.0))
                logger.info(f"Top Trader Long/Short Ratio ({symbol}): {ratio:.4f}")
                return ratio

        except Exception as e:
            logger.error(f"Error fetching Top Trader Long/Short Ratio: {e}")

        return 1.0

    # ==================== Funding Rates ====================

    async def get_funding_rate_binance(self, symbol: str = "BTCUSDT") -> float:
        """
        Fetch the current funding rate from Binance Futures.

        Positive rate: Longs pay shorts (bullish sentiment)
        Negative rate: Shorts pay longs (bearish sentiment)

        Args:
            symbol: Trading pair (default: BTCUSDT)

        Returns:
            Funding rate as decimal (e.g., 0.0001 = 0.01%)
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/premiumIndex"
            params = {"symbol": symbol}

            data = await self._get(url, params)

            if data:
                rate = float(data.get("lastFundingRate", 0))
                logger.info(f"Funding Rate ({symbol}): {rate:.6f} ({rate*100:.4f}%)")
                return rate

        except Exception as e:
            logger.error(f"Error fetching Funding Rate: {e}")

        return 0.0

    async def get_predicted_funding_rate(self, symbol: str = "BTCUSDT") -> float:
        """
        Get the predicted next funding rate from Binance.

        Args:
            symbol: Trading pair

        Returns:
            Predicted funding rate
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/premiumIndex"
            params = {"symbol": symbol}

            data = await self._get(url, params)

            if data:
                # Binance provides predicted rate in interestRate field
                rate = float(data.get("interestRate", 0))
                return rate

        except Exception as e:
            logger.error(f"Error fetching predicted funding rate: {e}")

        return 0.0

    # ==================== Price & Ticker Data ====================

    async def get_24h_ticker(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """
        Fetch 24-hour ticker data from Binance Futures.

        Args:
            symbol: Trading pair (default: BTCUSDT)

        Returns:
            Dict with price, change percent, volume, etc.
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/ticker/24hr"
            params = {"symbol": symbol}

            data = await self._get(url, params)

            if data:
                result = {
                    "symbol": symbol,
                    "price": float(data.get("lastPrice", 0)),
                    "price_change_percent": float(data.get("priceChangePercent", 0)),
                    "high_24h": float(data.get("highPrice", 0)),
                    "low_24h": float(data.get("lowPrice", 0)),
                    "volume_24h": float(data.get("volume", 0)),
                    "quote_volume_24h": float(data.get("quoteVolume", 0)),
                }
                logger.info(f"24h Ticker ({symbol}): Price={result['price']}, Change={result['price_change_percent']:.2f}%")
                return result

        except Exception as e:
            logger.error(f"Error fetching 24h Ticker: {e}")

        return {
            "symbol": symbol,
            "price": 0,
            "price_change_percent": 0,
            "high_24h": 0,
            "low_24h": 0,
            "volume_24h": 0,
            "quote_volume_24h": 0,
        }

    # ==================== Open Interest ====================

    async def get_open_interest(self, symbol: str = "BTCUSDT") -> float:
        """
        Fetch open interest from Binance Futures.

        Args:
            symbol: Trading pair (default: BTCUSDT)

        Returns:
            Open interest in base currency
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/openInterest"
            params = {"symbol": symbol}

            data = await self._get(url, params)

            if data:
                oi = float(data.get("openInterest", 0))
                logger.info(f"Open Interest ({symbol}): {oi:.2f}")
                return oi

        except Exception as e:
            logger.error(f"Error fetching Open Interest: {e}")

        return 0.0

    async def get_open_interest_history(
        self, symbol: str = "BTCUSDT", period: str = "1h", limit: int = 24
    ) -> list:
        """
        Fetch open interest history from Binance.

        Args:
            symbol: Trading pair
            period: Time period (5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d)
            limit: Number of data points

        Returns:
            List of historical open interest data
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/futures/data/openInterestHist"
            params = {
                "symbol": symbol,
                "period": period,
                "limit": limit,
            }

            data = await self._get(url, params)
            return data if data else []

        except Exception as e:
            logger.error(f"Error fetching OI history: {e}")
            return []

    # ==================== Liquidation Data ====================

    async def get_recent_liquidations(self, symbol: str = "BTCUSDT", limit: int = 100) -> list:
        """
        Fetch recent forced liquidations from Binance.

        Note: This endpoint may have restrictions or require API key.

        Args:
            symbol: Trading pair
            limit: Number of records

        Returns:
            List of recent liquidations
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/forceOrders"
            params = {
                "symbol": symbol,
                "limit": limit,
            }

            data = await self._get(url, params)
            return data if data else []

        except Exception as e:
            logger.error(f"Error fetching liquidations: {e}")
            return []

    # ==================== Aggregate Fetching ====================

    async def fetch_all_metrics(self) -> MarketMetrics:
        """
        Fetch all market metrics in parallel for strategy analysis.

        Returns:
            MarketMetrics dataclass with all relevant data
        """
        logger.info("Fetching all market metrics...")

        # Fetch all data in parallel
        results = await asyncio.gather(
            self.get_fear_greed_index(),
            self.get_long_short_ratio("BTCUSDT"),
            self.get_funding_rate_binance("BTCUSDT"),
            self.get_funding_rate_binance("ETHUSDT"),
            self.get_24h_ticker("BTCUSDT"),
            self.get_24h_ticker("ETHUSDT"),
            self.get_open_interest("BTCUSDT"),
            self.get_open_interest("ETHUSDT"),
            return_exceptions=True,
        )

        # Unpack results with error handling
        fear_greed = results[0] if not isinstance(results[0], Exception) else (50, "Neutral")
        long_short = results[1] if not isinstance(results[1], Exception) else 1.0
        funding_btc = results[2] if not isinstance(results[2], Exception) else 0.0
        funding_eth = results[3] if not isinstance(results[3], Exception) else 0.0
        ticker_btc = results[4] if not isinstance(results[4], Exception) else {"price": 0, "price_change_percent": 0}
        ticker_eth = results[5] if not isinstance(results[5], Exception) else {"price": 0, "price_change_percent": 0}
        oi_btc = results[6] if not isinstance(results[6], Exception) else 0.0
        oi_eth = results[7] if not isinstance(results[7], Exception) else 0.0

        metrics = MarketMetrics(
            fear_greed_index=fear_greed[0],
            fear_greed_classification=fear_greed[1],
            long_short_ratio=long_short,
            funding_rate_btc=funding_btc,
            funding_rate_eth=funding_eth,
            btc_24h_change_percent=ticker_btc.get("price_change_percent", 0),
            eth_24h_change_percent=ticker_eth.get("price_change_percent", 0),
            btc_price=ticker_btc.get("price", 0),
            eth_price=ticker_eth.get("price", 0),
            btc_open_interest=oi_btc,
            eth_open_interest=oi_eth,
            timestamp=datetime.now(),
        )

        logger.info(f"Market Metrics Collected: {metrics.to_dict()}")
        return metrics

    # ==================== Technical Analysis Helpers ====================

    async def get_price_volatility(self, symbol: str = "BTCUSDT", period: int = 24) -> float:
        """
        Calculate price volatility based on recent candles.

        Args:
            symbol: Trading pair
            period: Number of hours to analyze

        Returns:
            Volatility as percentage
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/klines"
            params = {
                "symbol": symbol,
                "interval": "1h",
                "limit": period,
            }

            data = await self._get(url, params)

            if data:
                # Extract high and low prices
                highs = [float(candle[2]) for candle in data]
                lows = [float(candle[3]) for candle in data]

                # Calculate average true range as percentage
                ranges = [(h - l) / l * 100 for h, l in zip(highs, lows)]
                avg_volatility = sum(ranges) / len(ranges)

                logger.info(f"24h Volatility ({symbol}): {avg_volatility:.2f}%")
                return avg_volatility

        except Exception as e:
            logger.error(f"Error calculating volatility: {e}")

        return 3.0  # Default 3% volatility

    async def get_trend_direction(self, symbol: str = "BTCUSDT") -> str:
        """
        Determine short-term trend direction using simple moving averages.

        Args:
            symbol: Trading pair

        Returns:
            'bullish', 'bearish', or 'neutral'
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/klines"
            params = {
                "symbol": symbol,
                "interval": "1h",
                "limit": 24,
            }

            data = await self._get(url, params)

            if data and len(data) >= 24:
                # Calculate simple moving averages
                closes = [float(candle[4]) for candle in data]

                sma_8 = sum(closes[-8:]) / 8
                sma_21 = sum(closes[-21:]) / 21

                current_price = closes[-1]

                # Determine trend
                if current_price > sma_8 > sma_21:
                    trend = "bullish"
                elif current_price < sma_8 < sma_21:
                    trend = "bearish"
                else:
                    trend = "neutral"

                logger.info(f"Trend ({symbol}): {trend} (Price: {current_price:.2f}, SMA8: {sma_8:.2f}, SMA21: {sma_21:.2f})")
                return trend

        except Exception as e:
            logger.error(f"Error determining trend: {e}")

        return "neutral"
