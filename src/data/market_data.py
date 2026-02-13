"""
Market Data Fetcher for Trading Strategies.

Fetches:
- Fear & Greed Index (Alternative.me)
- Long/Short Ratio (Binance Futures)
- Funding Rates (Binance & Bitget)
- 24h Ticker Data (Price trends)
- Open Interest (Derivatives data)
- News Sentiment (GDELT Project)
- Kline/Candlestick Data (Binance Futures)
- VWAP, Supertrend, Spot Volume Analysis (calculated from klines)
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List

import aiohttp

from src.utils.logger import get_logger
from src.utils.circuit_breaker import (
    circuit_registry,
    CircuitBreakerError,
    with_retry,
)

logger = get_logger(__name__)

# Circuit breakers for external APIs
_binance_breaker = circuit_registry.get("binance_api", fail_threshold=5, reset_timeout=60)
_alternative_me_breaker = circuit_registry.get("alternative_me_api", fail_threshold=3, reset_timeout=120)
_gdelt_breaker = circuit_registry.get("gdelt_api", fail_threshold=3, reset_timeout=120)
_deribit_breaker = circuit_registry.get("deribit_api", fail_threshold=3, reset_timeout=120)
_coingecko_breaker = circuit_registry.get("coingecko_api", fail_threshold=3, reset_timeout=120)
_defillama_breaker = circuit_registry.get("defillama_api", fail_threshold=3, reset_timeout=120)
_blockchain_breaker = circuit_registry.get("blockchain_api", fail_threshold=3, reset_timeout=120)
_bitget_breaker = circuit_registry.get("bitget_api", fail_threshold=3, reset_timeout=120)
_fred_breaker = circuit_registry.get("fred_api", fail_threshold=3, reset_timeout=300)


class DataFetchError(Exception):
    """Raised when market data cannot be fetched from any source."""

    def __init__(self, source: str, message: str, original_error: Optional[Exception] = None):
        self.source = source
        self.message = message
        self.original_error = original_error
        super().__init__(f"[{source}] {message}")


class DataQuality:
    """Tracks the quality/reliability of fetched market data."""

    def __init__(self):
        self.failed_sources: List[str] = []
        self.successful_sources: List[str] = []
        self.warnings: List[str] = []
        self.fetch_timestamps: Dict[str, float] = {}

    def mark_success(self, source: str):
        """Mark a data source as successfully fetched."""
        self.successful_sources.append(source)
        self.fetch_timestamps[source] = time.time()

    def mark_failure(self, source: str, reason: str):
        """Mark a data source as failed."""
        self.failed_sources.append(source)
        self.warnings.append(f"{source}: {reason}")

    @property
    def is_reliable(self) -> bool:
        """Check if enough data sources succeeded for reliable trading."""
        critical_sources = {"fear_greed", "long_short_ratio", "ticker_btc"}
        return all(s in self.successful_sources for s in critical_sources)

    @property
    def success_rate(self) -> float:
        """Calculate the percentage of successful data fetches."""
        total = len(self.failed_sources) + len(self.successful_sources)
        if total == 0:
            return 0.0
        return len(self.successful_sources) / total * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_reliable": self.is_reliable,
            "success_rate": self.success_rate,
            "failed_sources": self.failed_sources,
            "warnings": self.warnings,
        }


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

    # Data Quality tracking
    data_quality: Optional[DataQuality] = field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        result = {
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
        if self.data_quality:
            result["data_quality"] = self.data_quality.to_dict()
        return result

    @property
    def is_reliable(self) -> bool:
        """Check if the market data is reliable enough for trading."""
        if self.data_quality is None:
            return True  # Assume reliable if no quality tracking
        return self.data_quality.is_reliable


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
    GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
    DERIBIT_URL = "https://www.deribit.com/api/v2"
    COINGECKO_URL = "https://api.coingecko.com/api/v3"
    DEFILLAMA_URL = "https://stablecoins.llama.fi"
    BLOCKCHAIN_URL = "https://api.blockchain.info"
    BITGET_URL = "https://api.bitget.com/api/v2"
    FRED_URL = "https://api.stlouisfed.org/fred"

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
        """Make a GET request with retry logic."""
        await self._ensure_session()
        try:
            async with self._session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    # Rate limited - raise to trigger retry
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
            raise  # Re-raise for circuit breaker
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {url}")
            raise  # Re-raise for circuit breaker
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return {}

    @with_retry(max_attempts=3, min_wait=1.0, max_wait=5.0, retry_on=(aiohttp.ClientError, asyncio.TimeoutError))
    async def _get_with_retry(self, url: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GET request with automatic retry on failure."""
        return await self._get(url, params)

    # ==================== Fear & Greed Index ====================

    async def get_fear_greed_index(self) -> Tuple[int, str]:
        """
        Fetch the current Fear & Greed Index from Alternative.me.

        Returns:
            Tuple of (index value 0-100, classification string)
        """
        try:
            # Use circuit breaker for Alternative.me API
            async def _fetch():
                return await self._get_with_retry(self.FEAR_GREED_URL, {"limit": "1"})

            data = await _alternative_me_breaker.call(_fetch)

            if data and "data" in data and len(data["data"]) > 0:
                fng_data = data["data"][0]
                value = int(fng_data.get("value", 50))
                classification = fng_data.get("value_classification", "Neutral")

                logger.info(f"Fear & Greed Index: {value} ({classification})")
                return value, classification

        except CircuitBreakerError as e:
            logger.warning(f"Fear & Greed API circuit open: {e}")
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

            async def _fetch():
                return await self._get_with_retry(url, params)

            data = await _binance_breaker.call(_fetch)

            if data and len(data) > 0:
                ratio = float(data[0].get("longShortRatio", 1.0))
                logger.info(f"Long/Short Ratio ({symbol}): {ratio:.4f}")
                return ratio

        except CircuitBreakerError as e:
            logger.warning(f"Binance API circuit open for L/S ratio: {e}")
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

            async def _fetch():
                return await self._get(url, params)

            data = await _binance_breaker.call(_fetch)

            if data and len(data) > 0:
                ratio = float(data[0].get("longShortRatio", 1.0))
                logger.info(f"Top Trader Long/Short Ratio ({symbol}): {ratio:.4f}")
                return ratio

        except CircuitBreakerError:
            logger.warning("Circuit breaker open for Binance top trader L/S ratio")
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

            async def _fetch():
                return await self._get_with_retry(url, params)

            data = await _binance_breaker.call(_fetch)

            if data:
                rate = float(data.get("lastFundingRate", 0))
                logger.info(f"Funding Rate ({symbol}): {rate:.6f} ({rate*100:.4f}%)")
                return rate

        except CircuitBreakerError as e:
            logger.warning(f"Binance API circuit open for funding rate: {e}")
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

            async def _fetch():
                return await self._get_with_retry(url, params)

            data = await _binance_breaker.call(_fetch)

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

        except CircuitBreakerError as e:
            logger.warning(f"Binance API circuit open for 24h ticker: {e}")
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

            async def _fetch():
                return await self._get_with_retry(url, params)

            data = await _binance_breaker.call(_fetch)

            if data:
                oi = float(data.get("openInterest", 0))
                logger.info(f"Open Interest ({symbol}): {oi:.2f}")
                return oi

        except CircuitBreakerError as e:
            logger.warning(f"Binance API circuit open for open interest: {e}")
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

            async def _fetch():
                return await self._get(url, params)

            data = await _binance_breaker.call(_fetch)
            return data if data else []

        except CircuitBreakerError:
            logger.warning("Circuit breaker open for Binance OI history")
            return []
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

            async def _fetch():
                return await self._get(url, params)

            data = await _binance_breaker.call(_fetch)
            return data if data else []

        except CircuitBreakerError:
            logger.warning("Circuit breaker open for Binance liquidations")
            return []
        except Exception as e:
            logger.error(f"Error fetching liquidations: {e}")
            return []

    # ==================== Aggregate Fetching ====================

    async def fetch_all_metrics(self, require_reliable: bool = True) -> MarketMetrics:
        """
        Fetch all market metrics in parallel for strategy analysis.

        Args:
            require_reliable: If True, raises DataFetchError when critical data is missing

        Returns:
            MarketMetrics dataclass with all relevant data

        Raises:
            DataFetchError: If require_reliable=True and critical data sources fail
        """
        logger.info("Fetching all market metrics...")

        # Track data quality
        quality = DataQuality()

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

        # Unpack results with proper error tracking
        # Fear & Greed Index
        if isinstance(results[0], Exception):
            quality.mark_failure("fear_greed", str(results[0]))
            fear_greed = (50, "Unknown")
        elif results[0] is None or results[0][0] is None:
            quality.mark_failure("fear_greed", "No data returned")
            fear_greed = (50, "Unknown")
        else:
            quality.mark_success("fear_greed")
            fear_greed = results[0]

        # Long/Short Ratio
        if isinstance(results[1], Exception):
            quality.mark_failure("long_short_ratio", str(results[1]))
            long_short = 1.0
        elif results[1] is None:
            quality.mark_failure("long_short_ratio", "No data returned")
            long_short = 1.0
        else:
            quality.mark_success("long_short_ratio")
            long_short = results[1]

        # Funding Rate BTC
        if isinstance(results[2], Exception):
            quality.mark_failure("funding_btc", str(results[2]))
            funding_btc = 0.0
        elif results[2] is None:
            quality.mark_failure("funding_btc", "No data returned")
            funding_btc = 0.0
        else:
            quality.mark_success("funding_btc")
            funding_btc = results[2]

        # Funding Rate ETH
        if isinstance(results[3], Exception):
            quality.mark_failure("funding_eth", str(results[3]))
            funding_eth = 0.0
        elif results[3] is None:
            quality.mark_failure("funding_eth", "No data returned")
            funding_eth = 0.0
        else:
            quality.mark_success("funding_eth")
            funding_eth = results[3]

        # Ticker BTC
        if isinstance(results[4], Exception):
            quality.mark_failure("ticker_btc", str(results[4]))
            ticker_btc = {"price": 0, "price_change_percent": 0}
        elif results[4] is None or results[4].get("price", 0) == 0:
            quality.mark_failure("ticker_btc", "No price data")
            ticker_btc = {"price": 0, "price_change_percent": 0}
        else:
            quality.mark_success("ticker_btc")
            ticker_btc = results[4]

        # Ticker ETH
        if isinstance(results[5], Exception):
            quality.mark_failure("ticker_eth", str(results[5]))
            ticker_eth = {"price": 0, "price_change_percent": 0}
        elif results[5] is None or results[5].get("price", 0) == 0:
            quality.mark_failure("ticker_eth", "No price data")
            ticker_eth = {"price": 0, "price_change_percent": 0}
        else:
            quality.mark_success("ticker_eth")
            ticker_eth = results[5]

        # Open Interest BTC
        if isinstance(results[6], Exception):
            quality.mark_failure("oi_btc", str(results[6]))
            oi_btc = 0.0
        else:
            quality.mark_success("oi_btc")
            oi_btc = results[6] if results[6] is not None else 0.0

        # Open Interest ETH
        if isinstance(results[7], Exception):
            quality.mark_failure("oi_eth", str(results[7]))
            oi_eth = 0.0
        else:
            quality.mark_success("oi_eth")
            oi_eth = results[7] if results[7] is not None else 0.0

        # Check if data is reliable enough for trading
        if require_reliable and not quality.is_reliable:
            error_msg = f"Critical data sources failed: {', '.join(quality.failed_sources)}"
            logger.error(f"Data fetch failed - {error_msg}")
            raise DataFetchError(
                source="fetch_all_metrics",
                message=error_msg
            )

        # Log warnings if any sources failed
        if quality.failed_sources:
            logger.warning(
                f"Some data sources failed ({len(quality.failed_sources)}/{len(quality.failed_sources) + len(quality.successful_sources)}): "
                f"{', '.join(quality.warnings)}"
            )

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
            data_quality=quality,
        )

        logger.info(
            f"Market Metrics Collected (Quality: {quality.success_rate:.0f}% reliable): "
            f"{metrics.to_dict()}"
        )
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

    # ==================== News Sentiment (GDELT) ====================

    async def get_news_sentiment(
        self, query: str = "bitcoin", lookback_hours: int = 24, max_records: int = 250
    ) -> Dict[str, Any]:
        """
        Fetch news sentiment from GDELT Project API.

        Returns:
            Dict with average_tone (-10 to +10), article_count
        """
        from datetime import timedelta

        try:
            now = datetime.utcnow()
            start = now - timedelta(hours=lookback_hours)

            params = {
                "query": f'"{query}"',
                "startdatetime": start.strftime("%Y%m%d%H%M%S"),
                "enddatetime": now.strftime("%Y%m%d%H%M%S"),
                "format": "json",
                "mode": "tonechart",
                "maxrecords": str(max_records),
            }

            async def _fetch():
                return await self._get_with_retry(self.GDELT_API_URL, params)

            data = await _gdelt_breaker.call(_fetch)

            if data and "tonechart" in data:
                tones = data["tonechart"]
                if tones:
                    tone_values = [float(t.get("tone", 0)) for t in tones if "tone" in t]
                    if tone_values:
                        avg_tone = sum(tone_values) / len(tone_values)
                        logger.info(f"News Sentiment ({query}): tone={avg_tone:.2f}, articles={len(tone_values)}")
                        return {"average_tone": avg_tone, "article_count": len(tone_values)}

        except CircuitBreakerError as e:
            logger.warning(f"GDELT API circuit open: {e}")
        except Exception as e:
            logger.error(f"Error fetching news sentiment: {e}")

        return {"average_tone": 0.0, "article_count": 0}

    # ==================== Kline / Candlestick Data ====================

    async def get_binance_klines(
        self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 24
    ) -> List[List]:
        """
        Fetch kline/candlestick data from Binance Futures.

        Each kline: [open_time, open, high, low, close, volume, close_time,
                     quote_volume, num_trades, taker_buy_base_vol,
                     taker_buy_quote_vol, ignore]

        Returns:
            List of kline arrays, or empty list on failure.
        """
        try:
            url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/klines"
            params = {"symbol": symbol, "interval": interval, "limit": limit}

            async def _fetch():
                return await self._get_with_retry(url, params)

            data = await _binance_breaker.call(_fetch)
            if data and isinstance(data, list):
                logger.info(f"Klines ({symbol}, {interval}): fetched {len(data)} candles")
                return data

        except CircuitBreakerError as e:
            logger.warning(f"Binance API circuit open for klines: {e}")
        except Exception as e:
            logger.error(f"Error fetching klines: {e}")

        return []

    # ==================== VWAP Calculation ====================

    @staticmethod
    def calculate_vwap(klines: List[List]) -> float:
        """
        Calculate Volume-Weighted Average Price from kline data.

        VWAP = sum(typical_price * volume) / sum(volume)
        typical_price = (high + low + close) / 3

        Returns:
            VWAP price, or 0.0 if no data.
        """
        if not klines:
            return 0.0

        total_tp_vol = 0.0
        total_vol = 0.0

        for k in klines:
            try:
                high = float(k[2])
                low = float(k[3])
                close = float(k[4])
                volume = float(k[5])
                typical_price = (high + low + close) / 3
                total_tp_vol += typical_price * volume
                total_vol += volume
            except (IndexError, ValueError, TypeError):
                continue

        if total_vol == 0:
            return 0.0

        return total_tp_vol / total_vol

    # ==================== Supertrend Indicator ====================

    @staticmethod
    def calculate_supertrend(
        klines: List[List], atr_period: int = 10, multiplier: float = 3.0
    ) -> Dict[str, Any]:
        """
        Calculate Supertrend indicator from kline data.

        Uses ATR (Average True Range) for dynamic support/resistance.
        Green = uptrend (price above lower band), Red = downtrend.

        Returns:
            {"direction": "bullish"|"bearish", "value": float, "atr": float}
        """
        if not klines or len(klines) < atr_period + 1:
            return {"direction": "neutral", "value": 0.0, "atr": 0.0}

        highs = []
        lows = []
        closes = []
        for k in klines:
            try:
                highs.append(float(k[2]))
                lows.append(float(k[3]))
                closes.append(float(k[4]))
            except (IndexError, ValueError, TypeError):
                continue

        if len(closes) < atr_period + 1:
            return {"direction": "neutral", "value": 0.0, "atr": 0.0}

        # Calculate True Range
        true_ranges = [highs[0] - lows[0]]
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)

        # Calculate ATR using simple moving average
        atr_values = []
        for i in range(len(true_ranges)):
            if i < atr_period - 1:
                atr_values.append(0.0)
            elif i == atr_period - 1:
                atr_values.append(sum(true_ranges[:atr_period]) / atr_period)
            else:
                atr_values.append(
                    (atr_values[-1] * (atr_period - 1) + true_ranges[i]) / atr_period
                )

        # Calculate Supertrend
        supertrend = [0.0] * len(closes)
        direction = [1] * len(closes)  # 1 = bullish, -1 = bearish

        for i in range(atr_period, len(closes)):
            hl2 = (highs[i] + lows[i]) / 2
            upper_band = hl2 + multiplier * atr_values[i]
            lower_band = hl2 - multiplier * atr_values[i]

            if i == atr_period:
                supertrend[i] = upper_band if closes[i] <= upper_band else lower_band
                direction[i] = -1 if closes[i] <= upper_band else 1
            else:
                prev_st = supertrend[i - 1]
                prev_dir = direction[i - 1]

                if prev_dir == 1:  # was bullish
                    lower_band = max(lower_band, prev_st)
                    if closes[i] >= lower_band:
                        supertrend[i] = lower_band
                        direction[i] = 1
                    else:
                        supertrend[i] = upper_band
                        direction[i] = -1
                else:  # was bearish
                    upper_band = min(upper_band, prev_st)
                    if closes[i] <= upper_band:
                        supertrend[i] = upper_band
                        direction[i] = -1
                    else:
                        supertrend[i] = lower_band
                        direction[i] = 1

        current_dir = "bullish" if direction[-1] == 1 else "bearish"
        return {
            "direction": current_dir,
            "value": supertrend[-1],
            "atr": atr_values[-1],
        }

    # ==================== Spot Volume Analysis ====================

    @staticmethod
    def get_spot_volume_analysis(klines: List[List]) -> Dict[str, Any]:
        """
        Analyze buy/sell volume split from kline data.

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

    # ==================== OIWAP Calculation ====================

    async def calculate_oiwap(
        self, symbol: str = "BTCUSDT", klines: Optional[List[List]] = None, period_hours: int = 24
    ) -> float:
        """
        Approximate OI-Weighted Average Price.

        Uses OI history changes as weights: positions opened/closed at a price
        contribute more to the weighted average.

        OIWAP = sum(typical_price * abs(OI_change)) / sum(abs(OI_change))

        Returns:
            OIWAP price, or 0.0 if unavailable.
        """
        try:
            if klines is None:
                klines = await self.get_binance_klines(symbol, "1h", period_hours)
            if not klines:
                return 0.0

            oi_history = await self.get_open_interest_history(symbol, "1h", period_hours)
            if not oi_history or len(oi_history) < 2:
                return 0.0

            # Build timestamp -> OI map
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

                    # Find matching or closest OI entry
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

    # ==================== Deribit Options Data ====================

    async def get_options_oi_deribit(self, currency: str = "BTC") -> Dict[str, Any]:
        """
        Fetch total options open interest from Deribit (public, no auth).

        Returns:
            Dict with total_oi, num_instruments
        """
        try:
            url = f"{self.DERIBIT_URL}/public/get_book_summary_by_currency"
            params = {"currency": currency, "kind": "option"}

            async def _fetch():
                return await self._get_with_retry(url, params)

            data = await _deribit_breaker.call(_fetch)

            if data and "result" in data:
                instruments = data["result"]
                total_oi = sum(float(i.get("open_interest", 0)) for i in instruments)
                logger.info(f"Deribit Options OI ({currency}): {total_oi:.2f} across {len(instruments)} instruments")
                return {
                    "total_oi": total_oi,
                    "num_instruments": len(instruments),
                    "currency": currency,
                }

        except CircuitBreakerError as e:
            logger.warning(f"Deribit API circuit open: {e}")
        except Exception as e:
            logger.error(f"Error fetching Deribit options OI: {e}")

        return {"total_oi": 0.0, "num_instruments": 0, "currency": currency}

    async def get_max_pain(self, currency: str = "BTC") -> Dict[str, Any]:
        """
        Calculate the max pain price from Deribit options data.

        Max pain = strike price where the most options expire worthless.

        Returns:
            Dict with max_pain_price, nearest_expiry
        """
        try:
            # Get active option instruments
            url = f"{self.DERIBIT_URL}/public/get_instruments"
            params = {"currency": currency, "kind": "option", "expired": "false"}

            async def _fetch():
                return await self._get_with_retry(url, params)

            data = await _deribit_breaker.call(_fetch)

            if not data or "result" not in data:
                return {"max_pain_price": 0.0, "nearest_expiry": ""}

            instruments = data["result"]
            if not instruments:
                return {"max_pain_price": 0.0, "nearest_expiry": ""}

            # Find nearest expiry
            now_ms = datetime.now().timestamp() * 1000
            expiries = sorted(set(
                i["expiration_timestamp"] for i in instruments
                if i["expiration_timestamp"] > now_ms
            ))
            if not expiries:
                return {"max_pain_price": 0.0, "nearest_expiry": ""}

            nearest_exp = expiries[0]
            nearest_instruments = [
                i for i in instruments
                if i["expiration_timestamp"] == nearest_exp
            ]

            # Group by strike
            strikes: Dict[float, Dict[str, float]] = {}
            for inst in nearest_instruments:
                strike = float(inst["strike"])
                if strike not in strikes:
                    strikes[strike] = {"call_oi": 0.0, "put_oi": 0.0}
                oi = float(inst.get("open_interest", 0) or 0)
                if inst["option_type"] == "call":
                    strikes[strike]["call_oi"] += oi
                else:
                    strikes[strike]["put_oi"] += oi

            # Calculate pain at each strike
            if not strikes:
                return {"max_pain_price": 0.0, "nearest_expiry": ""}

            strike_list = sorted(strikes.keys())
            min_pain = float("inf")
            max_pain_strike = 0.0

            for test_price in strike_list:
                total_pain = 0.0
                for strike, oi_data in strikes.items():
                    # Call holders lose when price < strike
                    if test_price > strike:
                        total_pain += (test_price - strike) * oi_data["call_oi"]
                    # Put holders lose when price > strike
                    if test_price < strike:
                        total_pain += (strike - test_price) * oi_data["put_oi"]
                if total_pain < min_pain:
                    min_pain = total_pain
                    max_pain_strike = test_price

            expiry_dt = datetime.fromtimestamp(nearest_exp / 1000)
            logger.info(f"Max Pain ({currency}): ${max_pain_strike:,.0f} (expiry {expiry_dt.date()})")
            return {
                "max_pain_price": max_pain_strike,
                "nearest_expiry": expiry_dt.isoformat(),
            }

        except CircuitBreakerError as e:
            logger.warning(f"Deribit API circuit open for max pain: {e}")
        except Exception as e:
            logger.error(f"Error calculating max pain: {e}")

        return {"max_pain_price": 0.0, "nearest_expiry": ""}

    async def get_put_call_ratio(self, currency: str = "BTC") -> Dict[str, Any]:
        """
        Calculate put/call ratio from Deribit options open interest.

        Ratio > 1 = more puts (bearish), < 1 = more calls (bullish).

        Returns:
            Dict with ratio, total_puts, total_calls
        """
        try:
            url = f"{self.DERIBIT_URL}/public/get_book_summary_by_currency"
            params = {"currency": currency, "kind": "option"}

            async def _fetch():
                return await self._get_with_retry(url, params)

            data = await _deribit_breaker.call(_fetch)

            if data and "result" in data:
                instruments = data["result"]
                total_puts = 0.0
                total_calls = 0.0
                for inst in instruments:
                    name = inst.get("instrument_name", "")
                    oi = float(inst.get("open_interest", 0) or 0)
                    if "-P" in name:
                        total_puts += oi
                    elif "-C" in name:
                        total_calls += oi

                ratio = total_puts / total_calls if total_calls > 0 else 0.0
                logger.info(f"Put/Call Ratio ({currency}): {ratio:.3f} (puts={total_puts:.0f}, calls={total_calls:.0f})")
                return {
                    "ratio": ratio,
                    "total_puts": total_puts,
                    "total_calls": total_calls,
                }

        except CircuitBreakerError as e:
            logger.warning(f"Deribit API circuit open for P/C ratio: {e}")
        except Exception as e:
            logger.error(f"Error fetching put/call ratio: {e}")

        return {"ratio": 0.0, "total_puts": 0.0, "total_calls": 0.0}

    # ==================== CoinGecko Market Data ====================

    async def get_coingecko_market(self) -> Dict[str, Any]:
        """
        Fetch global crypto market data from CoinGecko (free tier).

        Returns:
            Dict with total_market_cap, btc_dominance, active_cryptocurrencies
        """
        try:
            url = f"{self.COINGECKO_URL}/global"

            async def _fetch():
                return await self._get_with_retry(url)

            data = await _coingecko_breaker.call(_fetch)

            if data and "data" in data:
                d = data["data"]
                market_cap = d.get("total_market_cap", {}).get("usd", 0)
                btc_dom = d.get("market_cap_percentage", {}).get("btc", 0)
                active = d.get("active_cryptocurrencies", 0)
                logger.info(f"CoinGecko Global: MCap=${market_cap/1e9:.1f}B, BTC Dom={btc_dom:.1f}%")
                return {
                    "total_market_cap_usd": market_cap,
                    "btc_dominance_pct": btc_dom,
                    "active_cryptocurrencies": active,
                    "market_cap_change_24h_pct": d.get("market_cap_change_percentage_24h_usd", 0),
                }

        except CircuitBreakerError as e:
            logger.warning(f"CoinGecko API circuit open: {e}")
        except Exception as e:
            logger.error(f"Error fetching CoinGecko market data: {e}")

        return {
            "total_market_cap_usd": 0,
            "btc_dominance_pct": 0,
            "active_cryptocurrencies": 0,
            "market_cap_change_24h_pct": 0,
        }

    # ==================== Stablecoin Flows (DefiLlama) ====================

    async def get_stablecoin_flows(self) -> Dict[str, Any]:
        """
        Fetch stablecoin market cap data from DefiLlama.

        Rising USDT market cap = new capital entering crypto (bullish).

        Returns:
            Dict with usdt_market_cap, change_7d, change_7d_pct
        """
        try:
            url = f"{self.DEFILLAMA_URL}/stablecoins?includePrices=false"

            async def _fetch():
                return await self._get_with_retry(url)

            data = await _defillama_breaker.call(_fetch)

            if data and "peggedAssets" in data:
                for asset in data["peggedAssets"]:
                    if asset.get("symbol", "").upper() == "USDT":
                        chains = asset.get("chainCirculating", {})
                        total_mcap = sum(
                            c.get("current", {}).get("peggedUSD", 0)
                            for c in chains.values()
                        )
                        if total_mcap == 0:
                            total_mcap = asset.get("circulating", {}).get("peggedUSD", 0)

                        logger.info(f"Stablecoin USDT MCap: ${total_mcap / 1e9:.1f}B")
                        return {
                            "usdt_market_cap": total_mcap,
                            "symbol": "USDT",
                        }

        except CircuitBreakerError as e:
            logger.warning(f"DefiLlama API circuit open: {e}")
        except Exception as e:
            logger.error(f"Error fetching stablecoin flows: {e}")

        return {"usdt_market_cap": 0, "symbol": "USDT"}

    # ==================== BTC Hashrate (Blockchain.info) ====================

    async def get_btc_hashrate(self) -> Dict[str, Any]:
        """
        Fetch Bitcoin network hashrate from Blockchain.info.

        Rising hashrate = miner confidence, network security.

        Returns:
            Dict with hashrate (TH/s), difficulty
        """
        try:
            url = f"{self.BLOCKCHAIN_URL}/stats"

            async def _fetch():
                return await self._get_with_retry(url)

            data = await _blockchain_breaker.call(_fetch)

            if data:
                hashrate = data.get("hash_rate", 0)  # TH/s
                difficulty = data.get("difficulty", 0)
                logger.info(f"BTC Hashrate: {hashrate / 1e6:.1f} EH/s")
                return {
                    "hashrate_ths": hashrate,
                    "difficulty": difficulty,
                }

        except CircuitBreakerError as e:
            logger.warning(f"Blockchain.info API circuit open: {e}")
        except Exception as e:
            logger.error(f"Error fetching BTC hashrate: {e}")

        return {"hashrate_ths": 0, "difficulty": 0}

    # ==================== Bitget Funding Rate ====================

    async def get_bitget_funding_rate(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """
        Fetch current funding rate from Bitget.

        Comparing Binance vs Bitget funding rates reveals cross-exchange divergence.

        Returns:
            Dict with funding_rate, funding_time
        """
        try:
            url = f"{self.BITGET_URL}/mix/market/current-fund-rate"
            params = {"symbol": symbol, "productType": "USDT-FUTURES"}

            async def _fetch():
                return await self._get_with_retry(url, params)

            data = await _bitget_breaker.call(_fetch)

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

    # ==================== FRED Macro Data ====================

    async def get_fred_series(self, series_id: str) -> Dict[str, Any]:
        """
        Fetch latest value of a FRED economic data series.

        Used for DXY (US Dollar Index) and Fed Funds Rate.

        Args:
            series_id: FRED series ID (e.g. 'DTWEXBGS' for DXY, 'DFF' for Fed Funds)

        Returns:
            Dict with value, date, series_id
        """
        import os

        api_key = os.environ.get("FRED_API_KEY", "")
        if not api_key:
            return {"value": 0.0, "date": "", "series_id": series_id}

        try:
            url = f"{self.FRED_URL}/series/observations"
            params = {
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "1",
            }

            async def _fetch():
                return await self._get_with_retry(url, params)

            data = await _fred_breaker.call(_fetch)

            if data and "observations" in data and data["observations"]:
                obs = data["observations"][0]
                value_str = obs.get("value", ".")
                value = float(value_str) if value_str != "." else 0.0
                date = obs.get("date", "")
                logger.info(f"FRED {series_id}: {value} ({date})")
                return {"value": value, "date": date, "series_id": series_id}

        except CircuitBreakerError as e:
            logger.warning(f"FRED API circuit open: {e}")
        except Exception as e:
            logger.error(f"Error fetching FRED {series_id}: {e}")

        return {"value": 0.0, "date": "", "series_id": series_id}

    # ==================== CME Gap Detection ====================

    async def get_cme_gap(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """
        Detect CME gap by comparing Friday 21:00 UTC close with current price.

        CME BTC futures trade Mon-Fri. Weekend gaps often get filled.

        Returns:
            Dict with gap_pct, friday_close, current_price, gap_direction
        """
        try:
            # Fetch 7 days of 4h candles to find Friday close
            klines = await self.get_binance_klines(symbol, "4h", 42)
            if not klines:
                return {"gap_pct": 0.0, "friday_close": 0.0, "current_price": 0.0, "gap_direction": "none"}

            # Find the last Friday 20:00-00:00 UTC candle (CME close ~21:00 UTC)
            friday_close = 0.0
            for k in reversed(klines):
                ts = datetime.fromtimestamp(int(k[0]) / 1000)
                if ts.weekday() == 4 and ts.hour >= 20:  # Friday, after 20:00
                    friday_close = float(k[4])  # close price
                    break

            if friday_close == 0:
                return {"gap_pct": 0.0, "friday_close": 0.0, "current_price": 0.0, "gap_direction": "none"}

            current_price = float(klines[-1][4])
            gap_pct = ((current_price - friday_close) / friday_close) * 100
            direction = "up" if gap_pct > 0.5 else "down" if gap_pct < -0.5 else "none"

            logger.info(f"CME Gap ({symbol}): {gap_pct:.2f}% (Fri close=${friday_close:,.0f}, now=${current_price:,.0f})")
            return {
                "gap_pct": gap_pct,
                "friday_close": friday_close,
                "current_price": current_price,
                "gap_direction": direction,
            }

        except Exception as e:
            logger.error(f"Error detecting CME gap: {e}")

        return {"gap_pct": 0.0, "friday_close": 0.0, "current_price": 0.0, "gap_direction": "none"}

    # ==================== Selective Fetching ====================

    async def fetch_selected_metrics(
        self, sources: List[str], symbol: str = "BTCUSDT"
    ) -> Dict[str, Any]:
        """
        Fetch only the selected data sources in parallel.

        Args:
            sources: List of data source IDs (from data_source_registry)
            symbol: Trading pair for symbol-specific data

        Returns:
            Dict keyed by source ID with fetched data. Failed sources are omitted.
        """
        await self._ensure_session()

        # Map source IDs to coroutines
        dispatch: Dict[str, Any] = {}
        # Technical indicators need klines — track if we need them
        needs_klines = any(s in sources for s in ("vwap", "supertrend", "spot_volume", "oiwap"))

        for src_id in sources:
            if src_id == "fear_greed":
                dispatch[src_id] = self.get_fear_greed_index()
            elif src_id == "news_sentiment":
                dispatch[src_id] = self.get_news_sentiment()
            elif src_id == "long_short_ratio":
                dispatch[src_id] = self.get_long_short_ratio(symbol)
            elif src_id == "top_trader_ls_ratio":
                dispatch[src_id] = self.get_top_trader_long_short_ratio(symbol)
            elif src_id == "funding_rate":
                dispatch[src_id] = self.get_funding_rate_binance(symbol)
            elif src_id == "predicted_funding":
                dispatch[src_id] = self.get_predicted_funding_rate(symbol)
            elif src_id == "open_interest":
                dispatch[src_id] = self.get_open_interest(symbol)
            elif src_id == "oi_history":
                dispatch[src_id] = self.get_open_interest_history(symbol)
            elif src_id == "liquidations":
                dispatch[src_id] = self.get_recent_liquidations(symbol)
            elif src_id == "options_oi":
                currency = symbol.replace("USDT", "").replace("USD", "")
                dispatch[src_id] = self.get_options_oi_deribit(currency)
            elif src_id == "max_pain":
                currency = symbol.replace("USDT", "").replace("USD", "")
                dispatch[src_id] = self.get_max_pain(currency)
            elif src_id == "put_call_ratio":
                currency = symbol.replace("USDT", "").replace("USD", "")
                dispatch[src_id] = self.get_put_call_ratio(currency)
            elif src_id == "spot_price":
                dispatch[src_id] = self.get_24h_ticker(symbol)
            elif src_id == "coingecko_market":
                dispatch[src_id] = self.get_coingecko_market()
            elif src_id == "volatility":
                dispatch[src_id] = self.get_price_volatility(symbol)
            elif src_id == "trend_sma":
                dispatch[src_id] = self.get_trend_direction(symbol)
            elif src_id == "cme_gap":
                dispatch[src_id] = self.get_cme_gap(symbol)
            elif src_id == "stablecoin_flows":
                dispatch[src_id] = self.get_stablecoin_flows()
            elif src_id == "btc_hashrate":
                dispatch[src_id] = self.get_btc_hashrate()
            elif src_id == "bitget_funding":
                dispatch[src_id] = self.get_bitget_funding_rate(symbol)
            elif src_id == "macro_dxy":
                dispatch[src_id] = self.get_fred_series("DTWEXBGS")
            elif src_id == "fed_funds_rate":
                dispatch[src_id] = self.get_fred_series("DFF")
            # Technical indicators computed from klines are handled below

        # Fetch klines if needed for calculated indicators
        klines = []
        if needs_klines:
            try:
                klines = await self.get_binance_klines(symbol, "1h", 24)
            except Exception as e:
                logger.warning(f"Klines fetch failed for calculated indicators: {e}")

        # Run all dispatched fetches in parallel
        if dispatch:
            keys = list(dispatch.keys())
            coros = list(dispatch.values())
            raw_results = await asyncio.gather(*coros, return_exceptions=True)
        else:
            keys = []
            raw_results = []

        # Build result dict, skipping failures
        result: Dict[str, Any] = {}
        for key, val in zip(keys, raw_results):
            if isinstance(val, Exception):
                logger.warning(f"Data source '{key}' failed: {val}")
            else:
                result[key] = val

        # Compute kline-based indicators
        if klines:
            if "vwap" in sources:
                result["vwap"] = self.calculate_vwap(klines)
            if "supertrend" in sources:
                result["supertrend"] = self.calculate_supertrend(klines)
            if "spot_volume" in sources:
                result["spot_volume"] = self.get_spot_volume_analysis(klines)
            if "oiwap" in sources:
                try:
                    result["oiwap"] = await self.calculate_oiwap(symbol, klines=klines)
                except Exception as e:
                    logger.warning(f"OIWAP calculation failed: {e}")

        logger.info(
            f"Selective fetch: {len(result)}/{len(sources)} sources succeeded "
            f"[{', '.join(result.keys())}]"
        )
        return result
