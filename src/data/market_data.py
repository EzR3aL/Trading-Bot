"""
Market Data Fetcher for Trading Strategies.

Facade module that aggregates all data sources. The MarketDataFetcher class
interface is preserved for backward compatibility — all internal logic has
been extracted into focused modules under src/data/sources/.

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
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List

import aiohttp

from src.exceptions import DataSourceError
from src.utils.logger import get_logger
from src.utils.circuit_breaker import (
    CircuitBreakerError,
    with_retry,
)

# Import source modules
from src.data.sources.fear_greed import fetch_fear_greed
from src.data.sources.long_short_ratios import (
    fetch_long_short_ratio,
    fetch_top_trader_long_short_ratio,
)
from src.data.sources.funding_rates import (
    fetch_funding_rate_binance,
    fetch_predicted_funding_rate,
    fetch_bitget_funding_rate,
    fetch_bybit_futures,
)
from src.data.sources.klines import (
    fetch_binance_klines,
    fetch_price_volatility,
    fetch_trend_direction,
    fetch_cme_gap,
    fetch_cvd,
    calculate_vwap as _calculate_vwap,
    calculate_atr as _calculate_atr,
    calculate_supertrend as _calculate_supertrend,
    calculate_ema as _calculate_ema,
    calculate_adx as _calculate_adx,
    calculate_macd as _calculate_macd,
    calculate_rsi as _calculate_rsi,
    detect_rsi_divergence as _detect_rsi_divergence,
)
from src.data.sources.open_interest import (
    fetch_open_interest,
    fetch_open_interest_history,
    fetch_recent_liquidations,
    fetch_order_book_depth,
    calculate_oiwap as _calculate_oiwap,
)
from src.data.sources.options_data import (
    fetch_options_oi_deribit,
    fetch_max_pain,
    fetch_put_call_ratio,
    fetch_deribit_options_extended,
    fetch_deribit_dvol,
    _empty_options_extended,
)
from src.data.sources.spot_volume import (
    get_spot_volume_analysis as _get_spot_volume_analysis,
    fetch_coinbase_premium,
)
from src.data.sources.macro_data import (
    fetch_fred_series,
    fetch_coingecko_market,
    fetch_stablecoin_flows,
    fetch_btc_hashrate,
)
from src.data.sources.social_sentiment import fetch_news_sentiment
from src.data.sources.base import to_binance_symbol

logger = get_logger(__name__)

# Regex to strip quote suffixes for symbol normalization (kept for backward compat)
_QUOTE_SUFFIXES_RE = re.compile(r"[-_/]?(USDT|USDC|USD|PERP|BUSD)$", re.IGNORECASE)


def _to_binance_symbol(symbol: str) -> str:
    """Normalize any exchange symbol format to Binance Futures format (e.g. BTCUSDT).

    Handles: "BTC" -> "BTCUSDT", "BTC-USDT" -> "BTCUSDT",
             "BTCUSDT" -> "BTCUSDT" (no-op).
    """
    return to_binance_symbol(symbol)


class DataFetchError(DataSourceError):
    """Raised when market data cannot be fetched from any source."""
    pass


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

    This class acts as a facade, delegating to focused source modules
    in src/data/sources/ while preserving the original interface.

    Sources:
    - Alternative.me: Fear & Greed Index
    - Binance Futures API: Long/Short Ratio, Funding Rates, Open Interest
    - Bitget API: Additional funding rate data
    """

    # API Endpoints (kept for backward compatibility)
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
    COINBASE_URL = "https://api.exchange.coinbase.com"
    BINANCE_SPOT_URL = "https://api.binance.com"
    BYBIT_URL = "https://api.bybit.com"

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

    async def _get(self, url: str, params: Optional[Dict] = None, timeout: int = 10) -> Dict[str, Any]:
        """Make a GET request with retry logic."""
        await self._ensure_session()
        try:
            async with self._session.get(url, params=params, timeout=timeout) as response:
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
    async def _get_with_retry(self, url: str, params: Optional[Dict] = None, timeout: int = 10) -> Dict[str, Any]:
        """Make a GET request with automatic retry on failure."""
        return await self._get(url, params, timeout=timeout)

    # ==================== Fear & Greed Index ====================

    async def get_fear_greed_index(self) -> Tuple[int, str]:
        """Fetch the current Fear & Greed Index from Alternative.me."""
        return await fetch_fear_greed(self)

    # ==================== Long/Short Ratio ====================

    async def get_long_short_ratio(self, symbol: str = "BTCUSDT") -> float:
        """Fetch the Global Long/Short Account Ratio from Binance Futures."""
        return await fetch_long_short_ratio(self, symbol)

    async def get_top_trader_long_short_ratio(self, symbol: str = "BTCUSDT") -> float:
        """Fetch the Top Trader Long/Short Ratio (Positions) from Binance."""
        return await fetch_top_trader_long_short_ratio(self, symbol)

    # ==================== Funding Rates ====================

    async def get_funding_rate_binance(self, symbol: str = "BTCUSDT") -> float:
        """Fetch the current funding rate from Binance Futures."""
        return await fetch_funding_rate_binance(self, symbol)

    async def get_predicted_funding_rate(self, symbol: str = "BTCUSDT") -> float:
        """Get the predicted next funding rate from Binance."""
        return await fetch_predicted_funding_rate(self, symbol)

    # ==================== Price & Ticker Data ====================

    async def get_24h_ticker(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """Fetch 24-hour ticker data from Binance Futures."""
        # Ticker stays in the facade since it's a simple Binance call
        # used directly by fetch_all_metrics
        try:
            url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/ticker/24hr"
            params = {"symbol": _to_binance_symbol(symbol)}

            async def _fetch():
                return await self._get_with_retry(url, params)

            from src.data.sources import breakers as _breakers
            data = await _breakers.binance_breaker.call(_fetch)

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
        """Fetch open interest from Binance Futures."""
        return await fetch_open_interest(self, symbol)

    async def get_open_interest_history(
        self, symbol: str = "BTCUSDT", period: str = "1h", limit: int = 24
    ) -> list:
        """Fetch open interest history from Binance."""
        return await fetch_open_interest_history(self, symbol, period, limit)

    # ==================== Liquidation Data ====================

    async def get_recent_liquidations(self, symbol: str = "BTCUSDT", limit: int = 100) -> list:
        """Fetch recent forced liquidations from Binance."""
        return await fetch_recent_liquidations(self, symbol, limit)

    async def get_order_book_depth(self, symbol: str = "BTCUSDT", limit: int = 20) -> dict:
        """Fetch order book depth from Binance Futures."""
        return await fetch_order_book_depth(self, symbol, limit)

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
        """Calculate price volatility based on recent candles."""
        return await fetch_price_volatility(self, symbol, period)

    async def get_trend_direction(self, symbol: str = "BTCUSDT") -> str:
        """Determine short-term trend direction using simple moving averages."""
        return await fetch_trend_direction(self, symbol)

    # ==================== News Sentiment (GDELT) ====================

    async def get_news_sentiment(
        self, query: str = "bitcoin", lookback_hours: int = 12, max_records: int = 10
    ) -> Dict[str, Any]:
        """Fetch news sentiment from GDELT Project API."""
        return await fetch_news_sentiment(self, query, lookback_hours, max_records)

    # ==================== Kline / Candlestick Data ====================

    async def get_binance_klines(
        self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 24
    ) -> List[List]:
        """Fetch kline/candlestick data from Binance Futures."""
        return await fetch_binance_klines(self, symbol, interval, limit)

    # ==================== VWAP Calculation ====================

    @staticmethod
    def calculate_vwap(klines: List[List]) -> float:
        """Calculate Volume-Weighted Average Price from kline data."""
        return _calculate_vwap(klines)

    # ==================== ATR (Average True Range) ====================

    @staticmethod
    def calculate_atr(klines: List[List], period: int = 14) -> List[float]:
        """Calculate Average True Range using Wilder's smoothing."""
        return _calculate_atr(klines, period)

    # ==================== Supertrend Indicator ====================

    @staticmethod
    def calculate_supertrend(
        klines: List[List], atr_period: int = 10, multiplier: float = 3.0
    ) -> Dict[str, Any]:
        """Calculate Supertrend indicator from kline data."""
        return _calculate_supertrend(klines, atr_period, multiplier)

    # ==================== Spot Volume Analysis ====================

    @staticmethod
    def get_spot_volume_analysis(klines: List[List]) -> Dict[str, Any]:
        """Analyze buy/sell volume split from kline data."""
        return _get_spot_volume_analysis(klines)

    # ==================== OIWAP Calculation ====================

    async def calculate_oiwap(
        self, symbol: str = "BTCUSDT", klines: Optional[List[List]] = None, period_hours: int = 24
    ) -> float:
        """Approximate OI-Weighted Average Price."""
        return await _calculate_oiwap(self, symbol, klines, period_hours)

    # ==================== Deribit Options Data ====================

    async def get_options_oi_deribit(self, currency: str = "BTC") -> Dict[str, Any]:
        """Fetch total options open interest from Deribit."""
        return await fetch_options_oi_deribit(self, currency)

    async def get_max_pain(self, currency: str = "BTC") -> Dict[str, Any]:
        """Calculate the max pain price from Deribit options data."""
        return await fetch_max_pain(self, currency)

    async def get_put_call_ratio(self, currency: str = "BTC") -> Dict[str, Any]:
        """Calculate put/call ratio from Deribit options open interest."""
        return await fetch_put_call_ratio(self, currency)

    # ==================== CoinGecko Market Data ====================

    async def get_coingecko_market(self) -> Dict[str, Any]:
        """Fetch global crypto market data from CoinGecko."""
        return await fetch_coingecko_market(self)

    # ==================== Stablecoin Flows (DefiLlama) ====================

    async def get_stablecoin_flows(self) -> Dict[str, Any]:
        """Fetch stablecoin market cap data from DefiLlama."""
        return await fetch_stablecoin_flows(self)

    # ==================== BTC Hashrate (Blockchain.info) ====================

    async def get_btc_hashrate(self) -> Dict[str, Any]:
        """Fetch Bitcoin network hashrate from Blockchain.info."""
        return await fetch_btc_hashrate(self)

    # ==================== Bitget Funding Rate ====================

    async def get_bitget_funding_rate(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """Fetch current funding rate from Bitget."""
        return await fetch_bitget_funding_rate(self, symbol)

    # ==================== FRED Macro Data ====================

    async def get_fred_series(self, series_id: str) -> Dict[str, Any]:
        """Fetch latest value of a FRED economic data series."""
        return await fetch_fred_series(self, series_id)

    # ==================== CME Gap Detection ====================

    async def get_cme_gap(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """Detect CME gap by comparing Friday 21:00 UTC close with current price."""
        return await fetch_cme_gap(self, symbol)

    # ==================== Cumulative Volume Delta (CVD) ====================

    async def get_cvd(self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 24) -> Dict[str, Any]:
        """Calculate Cumulative Volume Delta from Binance klines."""
        return await fetch_cvd(self, symbol, interval, limit)

    # ==================== Coinbase Premium ====================

    async def get_coinbase_premium(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """Calculate Coinbase Premium: price diff between Coinbase and Binance spot."""
        return await fetch_coinbase_premium(self, symbol)

    # ==================== Bybit Futures Data ====================

    async def get_bybit_futures(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """Fetch Bybit futures data: OI, funding rate, volume."""
        return await fetch_bybit_futures(self, symbol)

    # ==================== Deribit Options Extended ====================

    async def get_deribit_options_extended(self, currency: str = "BTC") -> Dict[str, Any]:
        """Full options data from Deribit: IV per tenor, Skew, Put/Call Ratio."""
        return await fetch_deribit_options_extended(self, currency)

    @staticmethod
    def _empty_options_extended(currency: str) -> Dict[str, Any]:
        return _empty_options_extended(currency)

    # ==================== Deribit DVOL (Volatility Index) ====================

    async def get_deribit_dvol(self, currency: str = "BTC") -> Dict[str, Any]:
        """Fetch Deribit Volatility Index (DVOL)."""
        return await fetch_deribit_dvol(self, currency)

    # ==================== EMA Calculation ====================

    @staticmethod
    def calculate_ema(values: List[float], period: int) -> List[float]:
        """Calculate Exponential Moving Average."""
        return _calculate_ema(values, period)

    # ==================== ADX Calculation ====================

    @staticmethod
    def calculate_adx(klines: List[List], period: int = 14) -> Dict[str, Any]:
        """Calculate Average Directional Index (ADX) using Wilder's method."""
        return _calculate_adx(klines, period)

    # ==================== MACD Calculation ====================

    @staticmethod
    def calculate_macd(
        klines: List[List], fast: int = 12, slow: int = 26, signal_period: int = 9
    ) -> Dict[str, Any]:
        """Calculate MACD (Moving Average Convergence Divergence)."""
        return _calculate_macd(klines, fast, slow, signal_period)

    # ==================== RSI Calculation ====================

    @staticmethod
    def calculate_rsi(klines: List[List], period: int = 14) -> List[float]:
        """Calculate Relative Strength Index (RSI) using Wilder's smoothing."""
        return _calculate_rsi(klines, period)

    # ==================== RSI Divergence Detection ====================

    @staticmethod
    def detect_rsi_divergence(
        klines: List[List], rsi_period: int = 14, lookback: int = 20
    ) -> Dict[str, Any]:
        """Detect bullish and bearish RSI divergence."""
        return _detect_rsi_divergence(klines, rsi_period, lookback)

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
        # Technical indicators need klines -- track if we need them
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
            elif src_id == "order_book":
                dispatch[src_id] = self.get_order_book_depth(symbol)
            elif src_id == "bitget_funding":
                dispatch[src_id] = self.get_bitget_funding_rate(symbol)
            elif src_id == "macro_dxy":
                dispatch[src_id] = self.get_fred_series("DTWEXBGS")
            elif src_id == "fed_funds_rate":
                dispatch[src_id] = self.get_fred_series("DFF")
            elif src_id == "cvd":
                dispatch[src_id] = self.get_cvd(symbol)
            elif src_id == "coinbase_premium":
                dispatch[src_id] = self.get_coinbase_premium(symbol)
            elif src_id == "bybit_futures":
                dispatch[src_id] = self.get_bybit_futures(symbol)
            elif src_id == "deribit_options_extended":
                currency = symbol.replace("USDT", "").replace("USD", "")
                dispatch[src_id] = self.get_deribit_options_extended(currency)
            elif src_id == "deribit_dvol":
                currency = symbol.replace("USDT", "").replace("USD", "")
                dispatch[src_id] = self.get_deribit_dvol(currency)
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
