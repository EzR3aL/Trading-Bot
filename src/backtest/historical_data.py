"""
Historical Data Fetcher for Backtesting.

Fetches and caches historical market data from various APIs:
- Fear & Greed Index (Alternative.me)
- Long/Short Ratio (Binance Futures)
- Funding Rates (Binance Futures)
- Price Data (Binance)
"""

import asyncio
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

import aiohttp

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class HistoricalDataPoint:
    """Single data point for backtesting."""
    timestamp: datetime
    date_str: str

    # Fear & Greed
    fear_greed_index: int
    fear_greed_classification: str

    # Long/Short Ratio
    long_short_ratio: float

    # Funding Rates
    funding_rate_btc: float
    funding_rate_eth: float

    # Prices
    btc_price: float
    eth_price: float
    btc_high: float
    btc_low: float
    eth_high: float
    eth_low: float

    # 24h Changes
    btc_24h_change: float
    eth_24h_change: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistoricalDataPoint":
        """Create from dictionary."""
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


class HistoricalDataFetcher:
    """
    Fetches historical market data for backtesting.

    Data is cached locally to avoid repeated API calls.
    """

    FEAR_GREED_URL = "https://api.alternative.me/fng/"
    BINANCE_FUTURES_URL = "https://fapi.binance.com"

    def __init__(self, cache_dir: str = "data/backtest/cache"):
        """Initialize the historical data fetcher."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self):
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, url: str, params: Optional[Dict] = None) -> Any:
        """Make a GET request with error handling."""
        await self._ensure_session()
        try:
            async with self._session.get(url, params=params, timeout=30) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.warning(f"HTTP {response.status} from {url}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def _get_cache_file(self, name: str) -> Path:
        """Get cache file path."""
        return self.cache_dir / f"{name}.json"

    def _load_cache(self, name: str) -> Optional[Any]:
        """Load data from cache."""
        cache_file = self._get_cache_file(name)
        if cache_file.exists():
            try:
                with open(cache_file, "r") as f:
                    data = json.load(f)
                    # Check if cache is fresh (less than 24 hours old)
                    if "cached_at" in data:
                        cached_at = datetime.fromisoformat(data["cached_at"])
                        if datetime.now() - cached_at < timedelta(hours=24):
                            logger.info(f"Using cached data: {name}")
                            return data.get("data")
            except Exception as e:
                logger.warning(f"Error loading cache {name}: {e}")
        return None

    def _save_cache(self, name: str, data: Any):
        """Save data to cache."""
        cache_file = self._get_cache_file(name)
        try:
            with open(cache_file, "w") as f:
                json.dump({
                    "cached_at": datetime.now().isoformat(),
                    "data": data
                }, f, indent=2)
            logger.info(f"Cached data: {name}")
        except Exception as e:
            logger.warning(f"Error saving cache {name}: {e}")

    async def fetch_fear_greed_history(self, days: int = 180) -> List[Dict]:
        """
        Fetch Fear & Greed Index history.

        Args:
            days: Number of days to fetch

        Returns:
            List of Fear & Greed data points
        """
        cache_name = f"fear_greed_{days}d"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching Fear & Greed history ({days} days)...")

        data = await self._get(self.FEAR_GREED_URL, {"limit": str(days)})

        if data and "data" in data:
            result = []
            for item in data["data"]:
                result.append({
                    "timestamp": int(item["timestamp"]),
                    "value": int(item["value"]),
                    "classification": item["value_classification"]
                })
            self._save_cache(cache_name, result)
            return result

        return []

    async def fetch_funding_rate_history(
        self, symbol: str = "BTCUSDT", days: int = 180
    ) -> List[Dict]:
        """
        Fetch funding rate history from Binance.

        Args:
            symbol: Trading pair
            days: Number of days to fetch

        Returns:
            List of funding rate data points
        """
        cache_name = f"funding_{symbol}_{days}d"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching funding rate history for {symbol} ({days} days)...")

        # Binance returns max 1000 records, funding is every 8 hours
        # 180 days = 180 * 3 = 540 funding payments
        url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/fundingRate"

        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        all_data = []
        current_end = end_time

        while current_end > start_time:
            params = {
                "symbol": symbol,
                "endTime": current_end,
                "limit": 1000
            }

            data = await self._get(url, params)

            if not data or len(data) == 0:
                break

            all_data.extend(data)

            # Move to earlier time
            current_end = int(data[-1]["fundingTime"]) - 1

            # Rate limiting
            await asyncio.sleep(0.2)

        # Sort by time
        all_data.sort(key=lambda x: x["fundingTime"])

        result = []
        for item in all_data:
            ts = int(item["fundingTime"]) // 1000
            if ts >= start_time // 1000:
                result.append({
                    "timestamp": ts,
                    "rate": float(item["fundingRate"])
                })

        self._save_cache(cache_name, result)
        return result

    async def fetch_klines_history(
        self, symbol: str = "BTCUSDT", interval: str = "1d", days: int = 180
    ) -> List[Dict]:
        """
        Fetch OHLCV candlestick data from Binance.

        Args:
            symbol: Trading pair
            interval: Candle interval (1d recommended for backtest)
            days: Number of days to fetch

        Returns:
            List of OHLCV data points
        """
        cache_name = f"klines_{symbol}_{interval}_{days}d"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching price history for {symbol} ({days} days)...")

        url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/klines"

        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_time,
            "endTime": end_time,
            "limit": 1000
        }

        data = await self._get(url, params)

        if not data:
            return []

        result = []
        for candle in data:
            result.append({
                "timestamp": int(candle[0]) // 1000,
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5])
            })

        self._save_cache(cache_name, result)
        return result

    async def fetch_long_short_history(
        self, symbol: str = "BTCUSDT", days: int = 180
    ) -> List[Dict]:
        """
        Fetch Long/Short ratio history from Binance.

        Args:
            symbol: Trading pair
            days: Number of days to fetch

        Returns:
            List of L/S ratio data points
        """
        cache_name = f"long_short_{symbol}_{days}d"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching Long/Short ratio history for {symbol} ({days} days)...")

        url = f"{self.BINANCE_FUTURES_URL}/futures/data/globalLongShortAccountRatio"

        all_data = []
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        current_end = end_time

        while current_end > start_time:
            params = {
                "symbol": symbol,
                "period": "1d",
                "endTime": current_end,
                "limit": 500
            }

            data = await self._get(url, params)

            if not data or len(data) == 0:
                break

            all_data.extend(data)

            # Move to earlier time
            current_end = int(data[-1]["timestamp"]) - 1

            await asyncio.sleep(0.2)

        # Sort and deduplicate
        all_data.sort(key=lambda x: x["timestamp"])

        result = []
        seen_timestamps = set()
        for item in all_data:
            ts = int(item["timestamp"]) // 1000
            if ts >= start_time // 1000 and ts not in seen_timestamps:
                seen_timestamps.add(ts)
                result.append({
                    "timestamp": ts,
                    "ratio": float(item["longShortRatio"])
                })

        self._save_cache(cache_name, result)
        return result

    async def fetch_all_historical_data(self, days: int = 180) -> List[HistoricalDataPoint]:
        """
        Fetch all historical data and combine into data points.

        Args:
            days: Number of days to fetch

        Returns:
            List of combined historical data points
        """
        logger.info(f"Fetching all historical data for {days} days...")

        # Fetch all data in parallel
        results = await asyncio.gather(
            self.fetch_fear_greed_history(days),
            self.fetch_funding_rate_history("BTCUSDT", days),
            self.fetch_funding_rate_history("ETHUSDT", days),
            self.fetch_klines_history("BTCUSDT", "1d", days),
            self.fetch_klines_history("ETHUSDT", "1d", days),
            self.fetch_long_short_history("BTCUSDT", days),
            return_exceptions=True
        )

        fear_greed = results[0] if not isinstance(results[0], Exception) else []
        funding_btc = results[1] if not isinstance(results[1], Exception) else []
        funding_eth = results[2] if not isinstance(results[2], Exception) else []
        klines_btc = results[3] if not isinstance(results[3], Exception) else []
        klines_eth = results[4] if not isinstance(results[4], Exception) else []
        long_short = results[5] if not isinstance(results[5], Exception) else []

        logger.info(f"Data fetched - FG: {len(fear_greed)}, Funding BTC: {len(funding_btc)}, "
                   f"Klines BTC: {len(klines_btc)}, L/S: {len(long_short)}")

        # Create lookup dictionaries by date
        def to_date_key(ts: int) -> str:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

        fg_by_date = {to_date_key(item["timestamp"]): item for item in fear_greed}

        # Aggregate funding rates by date (average of 3 daily payments)
        funding_btc_by_date = {}
        for item in funding_btc:
            date_key = to_date_key(item["timestamp"])
            if date_key not in funding_btc_by_date:
                funding_btc_by_date[date_key] = []
            funding_btc_by_date[date_key].append(item["rate"])

        funding_eth_by_date = {}
        for item in funding_eth:
            date_key = to_date_key(item["timestamp"])
            if date_key not in funding_eth_by_date:
                funding_eth_by_date[date_key] = []
            funding_eth_by_date[date_key].append(item["rate"])

        klines_btc_by_date = {to_date_key(item["timestamp"]): item for item in klines_btc}
        klines_eth_by_date = {to_date_key(item["timestamp"]): item for item in klines_eth}
        ls_by_date = {to_date_key(item["timestamp"]): item for item in long_short}

        # Combine into data points
        data_points = []

        # Use BTC klines as the base timeline
        for kline in klines_btc:
            date_key = to_date_key(kline["timestamp"])
            timestamp = datetime.fromtimestamp(kline["timestamp"])

            # Get Fear & Greed (default to 50 = neutral if missing)
            fg = fg_by_date.get(date_key, {"value": 50, "classification": "Neutral"})

            # Get funding rates (average if multiple, default to 0)
            btc_funding = funding_btc_by_date.get(date_key, [0])
            eth_funding = funding_eth_by_date.get(date_key, [0])

            # Get ETH klines
            eth_kline = klines_eth_by_date.get(date_key, {
                "close": 0, "high": 0, "low": 0
            })

            # Get L/S ratio (default to 1.0 = neutral)
            ls = ls_by_date.get(date_key, {"ratio": 1.0})

            # Calculate 24h changes
            btc_change = ((kline["close"] - kline["open"]) / kline["open"] * 100) if kline["open"] > 0 else 0
            eth_change = ((eth_kline.get("close", 0) - eth_kline.get("open", 0)) / eth_kline.get("open", 1) * 100) if eth_kline.get("open", 0) > 0 else 0

            data_point = HistoricalDataPoint(
                timestamp=timestamp,
                date_str=date_key,
                fear_greed_index=fg.get("value", 50),
                fear_greed_classification=fg.get("classification", "Neutral"),
                long_short_ratio=ls.get("ratio", 1.0),
                funding_rate_btc=sum(btc_funding) / len(btc_funding) if btc_funding else 0,
                funding_rate_eth=sum(eth_funding) / len(eth_funding) if eth_funding else 0,
                btc_price=kline["close"],
                eth_price=eth_kline.get("close", 0),
                btc_high=kline["high"],
                btc_low=kline["low"],
                eth_high=eth_kline.get("high", 0),
                eth_low=eth_kline.get("low", 0),
                btc_24h_change=btc_change,
                eth_24h_change=eth_change
            )

            data_points.append(data_point)

        # Sort by date
        data_points.sort(key=lambda x: x.timestamp)

        logger.info(f"Combined {len(data_points)} historical data points")

        return data_points

    def save_data_points(self, data_points: List[HistoricalDataPoint], filename: str = "historical_data.json"):
        """Save data points to file."""
        filepath = self.cache_dir.parent / filename
        with open(filepath, "w") as f:
            json.dump([dp.to_dict() for dp in data_points], f, indent=2)
        logger.info(f"Saved {len(data_points)} data points to {filepath}")

    def load_data_points(self, filename: str = "historical_data.json") -> List[HistoricalDataPoint]:
        """Load data points from file."""
        filepath = self.cache_dir.parent / filename
        if filepath.exists():
            with open(filepath, "r") as f:
                data = json.load(f)
                return [HistoricalDataPoint.from_dict(item) for item in data]
        return []
