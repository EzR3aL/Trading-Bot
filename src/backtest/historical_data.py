"""
Historical Data Fetcher for Backtesting.

Fetches and caches historical market data from various APIs:
- Fear & Greed Index (Alternative.me)
- Long/Short Ratio (Binance Futures)
- Funding Rates (Binance Futures + Bitget)
- Price Data / OHLCV (Binance Futures, CoinGecko fallback)
- Open Interest (Binance Futures)
- Taker Buy/Sell Volume (Binance Futures)
- Top Trader Positions (Binance Futures)
- Stablecoin Flows (DefiLlama)
- BTC Dominance & Total Market Cap (CoinGecko)
- Bitcoin Hashrate (Blockchain.info)
- DXY Index & Fed Funds Rate (FRED, optional API key)
- Historical Volatility (calculated from price data)
"""

import asyncio
import dataclasses
import json
import math
import os
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

    # Prices (close = btc_price/eth_price; open for next-candle entry)
    btc_price: float
    eth_price: float
    btc_open: float
    eth_open: float
    btc_high: float
    btc_low: float
    eth_high: float
    eth_low: float

    # 24h Changes
    btc_24h_change: float
    eth_24h_change: float

    # --- Extended fields (defaults for backward compatibility) ---

    # Open Interest (Binance Futures)
    open_interest_btc: float = 0.0
    open_interest_change_24h: float = 0.0

    # Taker Buy/Sell Volume Ratio (Binance Futures)
    taker_buy_sell_ratio: float = 1.0

    # Top Trader Long/Short Ratio (Binance Futures)
    top_trader_long_short_ratio: float = 1.0

    # Bitget Funding Rate (cross-exchange comparison)
    funding_rate_bitget: float = 0.0

    # Stablecoin Flows (DefiLlama)
    stablecoin_flow_7d: float = 0.0
    usdt_market_cap: float = 0.0

    # Global Market Data (CoinGecko)
    btc_dominance: float = 0.0
    total_crypto_market_cap: float = 0.0

    # Macro Indicators (FRED, optional)
    dxy_index: float = 0.0
    fed_funds_rate: float = 0.0

    # Bitcoin Network (Blockchain.info)
    btc_hashrate: float = 0.0

    # Calculated Metrics
    historical_volatility: float = 0.0
    btc_volume: float = 0.0
    eth_volume: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistoricalDataPoint":
        """Create from dictionary (handles missing fields gracefully)."""
        data = dict(data)
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        try:
            return cls(**filtered)
        except TypeError as e:
            raise ValueError(f"Incomplete historical data point (missing required fields): {e}") from e


class HistoricalDataFetcher:
    """
    Fetches historical market data for backtesting.

    Data is cached locally to avoid repeated API calls.
    """

    FEAR_GREED_URL = "https://api.alternative.me/fng/"
    BINANCE_FUTURES_URL = "https://fapi.binance.com"
    COINGECKO_URL = "https://api.coingecko.com/api/v3"
    BITGET_URL = "https://api.bitget.com/api/v2"
    DEFILLAMA_STABLECOINS_URL = "https://stablecoins.llama.fi"
    BLOCKCHAIN_INFO_URL = "https://api.blockchain.info"
    FRED_URL = "https://api.stlouisfed.org/fred"

    COINGECKO_IDS = {
        "BTC": "bitcoin",
        "ETH": "ethereum"
    }

    def __init__(self, cache_dir: str = "data/backtest/cache"):
        """Initialize the historical data fetcher."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session: Optional[aiohttp.ClientSession] = None
        self._data_sources: List[str] = []
        self._start_ms: Optional[int] = None
        self._end_ms: Optional[int] = None

    async def _ensure_session(self):
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def set_date_range(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None):
        """Set explicit date range for all fetches. None = use default (now - days)."""
        self._start_ms = int(start_date.timestamp() * 1000) if start_date else None
        self._end_ms = int(end_date.timestamp() * 1000) if end_date else None

    def _get_time_range_ms(self, days: int) -> tuple:
        """Get (start_ms, end_ms) respecting optional date range."""
        end_ms = self._end_ms or int(datetime.now().timestamp() * 1000)
        start_ms = self._start_ms or int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
        return start_ms, end_ms

    def _cache_suffix(self) -> str:
        """Cache key suffix for date-range-specific caching."""
        if self._start_ms and self._end_ms:
            s = datetime.fromtimestamp(self._start_ms / 1000).strftime("%Y%m%d")
            e = datetime.fromtimestamp(self._end_ms / 1000).strftime("%Y%m%d")
            return f"_{s}_{e}"
        return ""

    async def _get(self, url: str, params: Optional[Dict] = None) -> Any:
        """Make a GET request with error handling."""
        await self._ensure_session()
        try:
            async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
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

    # ------------------------------------------------------------------ #
    #  EXISTING DATA SOURCES                                              #
    # ------------------------------------------------------------------ #

    async def fetch_fear_greed_history(self, days: int = 180) -> List[Dict]:
        """Fetch Fear & Greed Index history from Alternative.me."""
        # F&G API only supports "most recent N" — extend limit to cover historical period
        if self._start_ms:
            days_from_now = int((datetime.now().timestamp() * 1000 - self._start_ms) / (86400 * 1000)) + 1
            days = max(days, days_from_now)
        cache_name = f"fear_greed_{days}d{self._cache_suffix()}"
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
        """Fetch funding rate history from Binance Futures."""
        cache_name = f"funding_{symbol}_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching funding rate history for {symbol} ({days} days)...")

        url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/fundingRate"

        start_time, end_time = self._get_time_range_ms(days)

        # Forward pagination from start_time to end_time
        all_data = []
        current_start = start_time

        for _ in range(50):  # Funding = 3x/day → 180d = 540 entries, 1 page enough
            params = {
                "symbol": symbol,
                "startTime": current_start,
                "limit": 1000,
            }

            data = await self._get(url, params)

            if not data or len(data) == 0:
                break

            all_data.extend(data)

            if len(data) < 1000:
                break  # Last page

            # Next page starts after the last item
            current_start = int(data[-1]["fundingTime"]) + 1
            if current_start >= end_time:
                break
            await asyncio.sleep(0.2)

        result = []
        for item in all_data:
            ts = int(item["fundingTime"]) // 1000
            result.append({
                "timestamp": ts,
                "rate": float(item["fundingRate"])
            })

        result.sort(key=lambda x: x["timestamp"])
        self._save_cache(cache_name, result)
        logger.info(f"Funding {symbol}: Got {len(result)} data points")
        return result

    async def fetch_klines_history(
        self, symbol: str = "BTCUSDT", interval: str = "1d", days: int = 180
    ) -> List[Dict]:
        """Fetch OHLCV candlestick data from Binance Futures with pagination."""
        cache_name = f"klines_{symbol}_{interval}_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching {interval} price history for {symbol} ({days} days)...")

        url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/klines"

        start_ms, end_ms = self._get_time_range_ms(days)

        all_candles = []
        seen_ts = set()
        current_start = start_ms

        while current_start < end_ms:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": current_start,
                "endTime": end_ms,
                "limit": 1500
            }

            data = await self._get(url, params)

            if not data:
                break

            for candle in data:
                ts = int(candle[0]) // 1000
                if ts not in seen_ts:
                    seen_ts.add(ts)
                    all_candles.append({
                        "timestamp": ts,
                        "open": float(candle[1]),
                        "high": float(candle[2]),
                        "low": float(candle[3]),
                        "close": float(candle[4]),
                        "volume": float(candle[5])
                    })

            if len(data) < 1500:
                break

            # Next page starts after the last candle
            current_start = int(data[-1][0]) + 1
            await asyncio.sleep(0.2)

        if all_candles:
            self._save_cache(cache_name, all_candles)
            logger.info(f"Fetched {len(all_candles)} {interval} candles for {symbol}")

        return all_candles

    async def fetch_coingecko_history(
        self, coin_id: str = "bitcoin", days: int = 180
    ) -> List[Dict]:
        """Fetch OHLCV data from CoinGecko as fallback."""
        # Extend days to cover historical period when date range is set
        if self._start_ms:
            days_from_now = int((datetime.now().timestamp() * 1000 - self._start_ms) / (86400 * 1000)) + 1
            days = max(days, days_from_now)
        cache_name = f"coingecko_{coin_id}_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching CoinGecko price history for {coin_id} ({days} days)...")

        url = f"{self.COINGECKO_URL}/coins/{coin_id}/market_chart"
        params = {
            "vs_currency": "usd",
            "days": str(days),
            "interval": "daily"
        }

        data = await self._get(url, params)

        if not data or "prices" not in data:
            logger.warning(f"CoinGecko returned no data for {coin_id}")
            return []

        prices = data.get("prices", [])

        result = []
        for price_data in prices:
            ts = int(price_data[0]) // 1000
            price = float(price_data[1])

            result.append({
                "timestamp": ts,
                "open": price * 0.99,
                "high": price * 1.02,
                "low": price * 0.98,
                "close": price,
                "volume": 0
            })

        self._save_cache(cache_name, result)
        logger.info(f"CoinGecko: Got {len(result)} data points for {coin_id}")
        return result

    async def fetch_klines_with_fallback(
        self, symbol: str = "BTCUSDT", days: int = 180, interval: str = "1d"
    ) -> List[Dict]:
        """Fetch price data with fallback to CoinGecko."""
        data = await self.fetch_klines_history(symbol, interval, days)
        if data:
            logger.info(f"Got {len(data)} {interval} candles from Binance for {symbol}")
            return data

        # CoinGecko fallback only available for daily data
        if interval == "1d":
            coin_id = "bitcoin" if "BTC" in symbol else "ethereum"
            data = await self.fetch_coingecko_history(coin_id, days)
            if data:
                logger.info(f"Got {len(data)} candles from CoinGecko for {coin_id}")
                return data

        logger.warning(f"All price sources failed for {symbol} ({interval})")
        return []

    async def fetch_long_short_history(
        self, symbol: str = "BTCUSDT", days: int = 180
    ) -> List[Dict]:
        """Fetch Long/Short ratio history from Binance Futures."""
        cache_name = f"long_short_{symbol}_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching Long/Short ratio history for {symbol} ({days} days)...")

        url = f"{self.BINANCE_FUTURES_URL}/futures/data/globalLongShortAccountRatio"

        all_data = []
        start_time, end_time = self._get_time_range_ms(days)

        current_end = end_time

        for _ in range(500):
            if current_end <= start_time:
                break
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
            new_end = int(data[-1]["timestamp"]) - 1
            if new_end >= current_end:
                break
            current_end = new_end
            await asyncio.sleep(0.2)

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

    # ------------------------------------------------------------------ #
    #  NEW DATA SOURCES                                                   #
    # ------------------------------------------------------------------ #

    async def fetch_open_interest_history(
        self, symbol: str = "BTCUSDT", days: int = 180
    ) -> List[Dict]:
        """Fetch Open Interest history from Binance Futures."""
        cache_name = f"open_interest_{symbol}_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching Open Interest history for {symbol} ({days} days)...")

        url = f"{self.BINANCE_FUTURES_URL}/futures/data/openInterestHist"

        all_data = []
        start_time, end_time = self._get_time_range_ms(days)
        current_end = end_time

        for _ in range(500):
            if current_end <= start_time:
                break
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
            oldest_ts = min(int(d["timestamp"]) for d in data)
            new_end = oldest_ts - 1
            if new_end >= current_end:
                break
            current_end = new_end
            await asyncio.sleep(0.2)

        all_data.sort(key=lambda x: x["timestamp"])

        result = []
        seen = set()
        for item in all_data:
            ts = int(item["timestamp"]) // 1000
            if ts >= start_time // 1000 and ts not in seen:
                seen.add(ts)
                result.append({
                    "timestamp": ts,
                    "oi_value": float(item.get("sumOpenInterestValue", 0)),
                    "oi_quantity": float(item.get("sumOpenInterest", 0)),
                })

        self._save_cache(cache_name, result)
        logger.info(f"Open Interest: Got {len(result)} data points")
        return result

    async def fetch_taker_buy_sell_history(
        self, symbol: str = "BTCUSDT", days: int = 180
    ) -> List[Dict]:
        """Fetch Taker Buy/Sell Volume Ratio from Binance Futures."""
        cache_name = f"taker_bs_{symbol}_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching Taker Buy/Sell ratio for {symbol} ({days} days)...")

        url = f"{self.BINANCE_FUTURES_URL}/futures/data/takerlongshortRatio"

        all_data = []
        start_time, end_time = self._get_time_range_ms(days)
        current_end = end_time

        for _ in range(500):
            if current_end <= start_time:
                break
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
            oldest_ts = min(int(d["timestamp"]) for d in data)
            new_end = oldest_ts - 1
            if new_end >= current_end:
                break
            current_end = new_end
            await asyncio.sleep(0.2)

        all_data.sort(key=lambda x: x["timestamp"])

        result = []
        seen = set()
        for item in all_data:
            ts = int(item["timestamp"]) // 1000
            if ts >= start_time // 1000 and ts not in seen:
                seen.add(ts)
                result.append({
                    "timestamp": ts,
                    "ratio": float(item.get("buySellRatio", 1.0)),
                    "buy_vol": float(item.get("buyVol", 0)),
                    "sell_vol": float(item.get("sellVol", 0)),
                })

        self._save_cache(cache_name, result)
        logger.info(f"Taker Buy/Sell: Got {len(result)} data points")
        return result

    async def fetch_top_trader_ls_history(
        self, symbol: str = "BTCUSDT", days: int = 180
    ) -> List[Dict]:
        """Fetch Top Trader Long/Short Ratio (Accounts) from Binance Futures."""
        cache_name = f"top_trader_ls_{symbol}_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching Top Trader L/S ratio for {symbol} ({days} days)...")

        url = f"{self.BINANCE_FUTURES_URL}/futures/data/topLongShortAccountRatio"

        all_data = []
        start_time, end_time = self._get_time_range_ms(days)
        current_end = end_time

        for _ in range(500):
            if current_end <= start_time:
                break
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
            oldest_ts = min(int(d["timestamp"]) for d in data)
            new_end = oldest_ts - 1
            if new_end >= current_end:
                break
            current_end = new_end
            await asyncio.sleep(0.2)

        all_data.sort(key=lambda x: x["timestamp"])

        result = []
        seen = set()
        for item in all_data:
            ts = int(item["timestamp"]) // 1000
            if ts >= start_time // 1000 and ts not in seen:
                seen.add(ts)
                result.append({
                    "timestamp": ts,
                    "ratio": float(item.get("longShortRatio", 1.0)),
                })

        self._save_cache(cache_name, result)
        logger.info(f"Top Trader L/S: Got {len(result)} data points")
        return result

    async def fetch_bitget_funding_history(
        self, symbol: str = "BTCUSDT", days: int = 180
    ) -> List[Dict]:
        """Fetch funding rate history from Bitget for cross-exchange comparison."""
        cache_name = f"bitget_funding_{symbol}_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching Bitget funding rate history for {symbol} ({days} days)...")

        url = f"{self.BITGET_URL}/mix/market/history-fund-rate"

        all_data = []
        page_no = 1
        max_pages = 20

        while page_no <= max_pages:
            params = {
                "symbol": symbol,
                "productType": "USDT-FUTURES",
                "pageSize": "100",
                "pageNo": str(page_no),
            }

            data = await self._get(url, params)

            if not data or data.get("code") != "00000":
                break

            items = data.get("data", [])
            if not items:
                break

            all_data.extend(items)
            page_no += 1
            await asyncio.sleep(0.3)

        cutoff_ts = self._start_ms or int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        result = []
        for item in all_data:
            settle_time = int(item.get("settleTime", 0))
            if settle_time >= cutoff_ts:
                result.append({
                    "timestamp": settle_time // 1000,
                    "rate": float(item.get("fundingRate", 0)),
                })

        result.sort(key=lambda x: x["timestamp"])
        self._save_cache(cache_name, result)
        logger.info(f"Bitget Funding: Got {len(result)} data points")
        return result

    async def fetch_stablecoin_history(self, days: int = 180) -> List[Dict]:
        """Fetch USDT stablecoin market cap history from DefiLlama."""
        cache_name = f"stablecoin_usdt_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching stablecoin (USDT) history ({days} days)...")

        # DefiLlama: stablecoin id 1 = USDT
        url = f"{self.DEFILLAMA_STABLECOINS_URL}/stablecoincharts/all"
        params = {"stablecoin": "1"}

        data = await self._get(url, params)

        if not data or not isinstance(data, list):
            logger.warning("DefiLlama stablecoin API returned no data")
            return []

        cutoff_ts = (self._start_ms // 1000) if self._start_ms else int((datetime.now() - timedelta(days=days)).timestamp())

        result = []
        for item in data:
            ts = int(item.get("date", 0))
            if ts >= cutoff_ts:
                circulating = item.get("totalCirculatingUSD", {})
                mcap = circulating.get("peggedUSD", 0) if isinstance(circulating, dict) else 0
                result.append({
                    "timestamp": ts,
                    "usdt_mcap": float(mcap),
                })

        self._save_cache(cache_name, result)
        logger.info(f"DefiLlama Stablecoins: Got {len(result)} data points")
        return result

    async def fetch_global_market_data(self) -> Dict:
        """Fetch current global crypto market data from CoinGecko."""
        cache_name = "coingecko_global"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info("Fetching CoinGecko global market data...")

        url = f"{self.COINGECKO_URL}/global"
        data = await self._get(url)

        if not data or "data" not in data:
            logger.warning("CoinGecko global API returned no data")
            return {}

        global_data = data["data"]
        result = {
            "btc_dominance": float(global_data.get("market_cap_percentage", {}).get("btc", 0)),
            "total_market_cap_usd": float(global_data.get("total_market_cap", {}).get("usd", 0)),
            "total_volume_usd": float(global_data.get("total_volume", {}).get("usd", 0)),
        }

        self._save_cache(cache_name, result)
        logger.info(f"CoinGecko Global: BTC dominance={result['btc_dominance']:.1f}%")
        return result

    async def fetch_btc_hashrate_history(self, days: int = 180) -> List[Dict]:
        """Fetch Bitcoin hashrate history from Blockchain.info."""
        # Extend timespan to cover historical period
        if self._start_ms:
            days_from_now = int((datetime.now().timestamp() * 1000 - self._start_ms) / (86400 * 1000)) + 1
            days = max(days, days_from_now)
        cache_name = f"btc_hashrate_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching BTC hashrate history ({days} days)...")

        url = f"{self.BLOCKCHAIN_INFO_URL}/charts/hash-rate"
        params = {
            "timespan": f"{days}days",
            "format": "json",
            "rollingAverage": "1days",
        }

        data = await self._get(url, params)

        if not data or "values" not in data:
            logger.warning("Blockchain.info hashrate API returned no data")
            return []

        result = []
        for item in data["values"]:
            result.append({
                "timestamp": int(item["x"]),
                "hashrate": float(item["y"]),
            })

        self._save_cache(cache_name, result)
        logger.info(f"Blockchain.info Hashrate: Got {len(result)} data points")
        return result

    async def fetch_fred_series(
        self, series_id: str, days: int = 180
    ) -> List[Dict]:
        """Fetch economic data from FRED (requires FRED_API_KEY env var)."""
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            logger.info(f"FRED_API_KEY not set, skipping {series_id}")
            return []

        cache_name = f"fred_{series_id}_{days}d{self._cache_suffix()}"
        cached = self._load_cache(cache_name)
        if cached:
            return cached

        logger.info(f"Fetching FRED series {series_id} ({days} days)...")

        if self._start_ms:
            start_date = datetime.fromtimestamp(self._start_ms / 1000).strftime("%Y-%m-%d")
        else:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        url = f"{self.FRED_URL}/series/observations"
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start_date,
        }

        data = await self._get(url, params)

        if not data or "observations" not in data:
            logger.warning(f"FRED returned no data for {series_id}")
            return []

        result = []
        for obs in data["observations"]:
            try:
                val = float(obs["value"])
                date = datetime.strptime(obs["date"], "%Y-%m-%d")
                result.append({
                    "timestamp": int(date.timestamp()),
                    "value": val,
                    "date": obs["date"],
                })
            except (ValueError, KeyError):
                continue

        self._save_cache(cache_name, result)
        logger.info(f"FRED {series_id}: Got {len(result)} data points")
        return result

    # ------------------------------------------------------------------ #
    #  CALCULATED METRICS                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def calculate_volatility(
        klines: List[Dict], window: int = 20
    ) -> Dict[str, float]:
        """
        Calculate rolling historical volatility from kline data.

        Returns dict of date_key -> annualized volatility.
        """
        if len(klines) < window + 1:
            return {}

        daily_returns = []
        for i in range(1, len(klines)):
            prev_close = klines[i - 1]["close"]
            curr_close = klines[i]["close"]
            if prev_close > 0:
                ret = math.log(curr_close / prev_close)
                daily_returns.append((klines[i]["timestamp"], ret))

        volatility_by_date = {}
        for i in range(window, len(daily_returns)):
            window_returns = [r[1] for r in daily_returns[i - window:i]]
            mean = sum(window_returns) / len(window_returns)
            variance = sum((r - mean) ** 2 for r in window_returns) / (len(window_returns) - 1)
            std = math.sqrt(variance) if variance > 0 else 0
            annualized_vol = std * math.sqrt(365) * 100

            ts = daily_returns[i][0]
            date_key = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            volatility_by_date[date_key] = round(annualized_vol, 2)

        return volatility_by_date

    # ------------------------------------------------------------------ #
    #  COMBINED DATA FETCH                                                #
    # ------------------------------------------------------------------ #

    async def fetch_all_historical_data(
        self,
        days: int = 180,
        interval: str = "1d",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[HistoricalDataPoint]:
        """
        Fetch all historical data and combine into data points.

        Args:
            days: Number of days of history to fetch (used when start_date/end_date not set)
            interval: Candle interval (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            start_date: Explicit start date (overrides days-from-now)
            end_date: Explicit end date (overrides "now" as end)

        Returns:
            List of combined historical data points with all available fields
        """
        # Set date range on instance so all sub-fetchers use it
        if start_date and end_date:
            self.set_date_range(start_date, end_date)
            days = (end_date - start_date).days
            logger.info(
                f"Fetching historical data for {start_date.strftime('%Y-%m-%d')} to "
                f"{end_date.strftime('%Y-%m-%d')} ({days} days), interval={interval}..."
            )
        else:
            logger.info(f"Fetching all historical data for {days} days, interval={interval}...")

        self._data_sources = []

        # Phase 1: Core data (Binance + Alternative.me)
        # Klines use the requested interval; all other sources remain daily
        core_results = await asyncio.gather(
            self.fetch_fear_greed_history(days),
            self.fetch_funding_rate_history("BTCUSDT", days),
            self.fetch_funding_rate_history("ETHUSDT", days),
            self.fetch_klines_with_fallback("BTCUSDT", days, interval),
            self.fetch_klines_with_fallback("ETHUSDT", days, interval),
            self.fetch_long_short_history("BTCUSDT", days),
            return_exceptions=True
        )

        fear_greed = core_results[0] if not isinstance(core_results[0], Exception) else []
        funding_btc = core_results[1] if not isinstance(core_results[1], Exception) else []
        funding_eth = core_results[2] if not isinstance(core_results[2], Exception) else []
        klines_btc = core_results[3] if not isinstance(core_results[3], Exception) else []
        klines_eth = core_results[4] if not isinstance(core_results[4], Exception) else []
        long_short = core_results[5] if not isinstance(core_results[5], Exception) else []

        # Phase 2: Extended data (new sources, parallel)
        ext_results = await asyncio.gather(
            self.fetch_open_interest_history("BTCUSDT", days),
            self.fetch_taker_buy_sell_history("BTCUSDT", days),
            self.fetch_top_trader_ls_history("BTCUSDT", days),
            self.fetch_bitget_funding_history("BTCUSDT", days),
            self.fetch_stablecoin_history(days),
            self.fetch_global_market_data(),
            self.fetch_btc_hashrate_history(days),
            self.fetch_fred_series("DTWEXBGS", days),   # DXY
            self.fetch_fred_series("DFF", days),         # Fed Funds Rate
            return_exceptions=True
        )

        open_interest = ext_results[0] if not isinstance(ext_results[0], Exception) else []
        taker_bs = ext_results[1] if not isinstance(ext_results[1], Exception) else []
        top_trader_ls = ext_results[2] if not isinstance(ext_results[2], Exception) else []
        bitget_funding = ext_results[3] if not isinstance(ext_results[3], Exception) else []
        stablecoin_data = ext_results[4] if not isinstance(ext_results[4], Exception) else []
        global_market = ext_results[5] if not isinstance(ext_results[5], Exception) else {}
        btc_hashrate = ext_results[6] if not isinstance(ext_results[6], Exception) else []
        fred_dxy = ext_results[7] if not isinstance(ext_results[7], Exception) else []
        fred_ffr = ext_results[8] if not isinstance(ext_results[8], Exception) else []

        # Track which data sources returned data
        if klines_btc:
            self._data_sources.append("Binance Futures (OHLCV)")
        if fear_greed:
            self._data_sources.append("Alternative.me (Fear & Greed)")
        if long_short:
            self._data_sources.append("Binance (L/S Ratio)")
        if funding_btc:
            self._data_sources.append("Binance (Funding Rates)")
        if open_interest:
            self._data_sources.append("Binance (Open Interest)")
        if taker_bs:
            self._data_sources.append("Binance (Taker Buy/Sell)")
        if top_trader_ls:
            self._data_sources.append("Binance (Top Trader L/S)")
        if bitget_funding:
            self._data_sources.append("Bitget (Funding Rates)")
        if stablecoin_data:
            self._data_sources.append("DefiLlama (Stablecoin Flows)")
        if global_market:
            self._data_sources.append("CoinGecko (Global Market)")
        if btc_hashrate:
            self._data_sources.append("Blockchain.info (Hashrate)")
        if fred_dxy:
            self._data_sources.append("FRED (DXY Index)")
        if fred_ffr:
            self._data_sources.append("FRED (Fed Funds Rate)")

        logger.info(f"Active data sources: {len(self._data_sources)}")
        for src in self._data_sources:
            logger.info(f"  - {src}")

        logger.info(
            f"Data counts - FG:{len(fear_greed)} Funding:{len(funding_btc)} "
            f"Klines:{len(klines_btc)} L/S:{len(long_short)} OI:{len(open_interest)} "
            f"Taker:{len(taker_bs)} TopTrader:{len(top_trader_ls)} "
            f"Bitget:{len(bitget_funding)} Stable:{len(stablecoin_data)} "
            f"Hash:{len(btc_hashrate)} DXY:{len(fred_dxy)} FFR:{len(fred_ffr)}"
        )

        # Calculate volatility from daily klines (not intraday)
        if interval != "1d" and klines_btc:
            # Fetch separate daily klines for volatility calculation
            daily_klines_btc = await self.fetch_klines_history("BTCUSDT", "1d", days)
            volatility_map = self.calculate_volatility(daily_klines_btc) if daily_klines_btc else {}
        else:
            volatility_map = self.calculate_volatility(klines_btc) if klines_btc else {}

        # Build lookup dictionaries by date
        def to_date_key(ts: int) -> str:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

        fg_by_date = {to_date_key(item["timestamp"]): item for item in fear_greed}

        # Aggregate funding rates by date (average of daily payments)
        funding_btc_by_date: Dict[str, List[float]] = {}
        for item in funding_btc:
            dk = to_date_key(item["timestamp"])
            funding_btc_by_date.setdefault(dk, []).append(item["rate"])

        funding_eth_by_date: Dict[str, List[float]] = {}
        for item in funding_eth:
            dk = to_date_key(item["timestamp"])
            funding_eth_by_date.setdefault(dk, []).append(item["rate"])

        # ETH klines: exact timestamp match for intraday, date fallback for CoinGecko
        klines_eth_by_ts = {item["timestamp"]: item for item in klines_eth}
        klines_eth_by_date = {to_date_key(item["timestamp"]): item for item in klines_eth}
        ls_by_date = {to_date_key(item["timestamp"]): item for item in long_short}

        # New source lookups
        oi_by_date = {to_date_key(item["timestamp"]): item for item in open_interest}
        taker_by_date = {to_date_key(item["timestamp"]): item for item in taker_bs}
        top_ls_by_date = {to_date_key(item["timestamp"]): item for item in top_trader_ls}

        # Aggregate Bitget funding by date
        bitget_funding_by_date: Dict[str, List[float]] = {}
        for item in bitget_funding:
            dk = to_date_key(item["timestamp"])
            bitget_funding_by_date.setdefault(dk, []).append(item["rate"])

        stable_by_date = {to_date_key(item["timestamp"]): item for item in stablecoin_data}
        hashrate_by_date = {to_date_key(item["timestamp"]): item for item in btc_hashrate}

        # FRED data uses date strings directly
        dxy_by_date = {}
        for item in fred_dxy:
            dk = item.get("date", to_date_key(item["timestamp"]))
            dxy_by_date[dk] = item["value"]

        ffr_by_date = {}
        for item in fred_ffr:
            dk = item.get("date", to_date_key(item["timestamp"]))
            ffr_by_date[dk] = item["value"]

        # Compute stablecoin 7-day flows
        stable_sorted = sorted(stablecoin_data, key=lambda x: x["timestamp"])
        stable_flow_by_date = {}
        for i, item in enumerate(stable_sorted):
            dk = to_date_key(item["timestamp"])
            if i >= 7:
                flow = item["usdt_mcap"] - stable_sorted[i - 7]["usdt_mcap"]
                stable_flow_by_date[dk] = flow
            else:
                stable_flow_by_date[dk] = 0.0

        # Compute OI 24h change
        oi_sorted = sorted(open_interest, key=lambda x: x["timestamp"])
        oi_change_by_date = {}
        for i, item in enumerate(oi_sorted):
            dk = to_date_key(item["timestamp"])
            if i >= 1:
                prev_oi = oi_sorted[i - 1]["oi_value"]
                curr_oi = item["oi_value"]
                change_pct = ((curr_oi - prev_oi) / prev_oi * 100) if prev_oi > 0 else 0
                oi_change_by_date[dk] = change_pct
            else:
                oi_change_by_date[dk] = 0.0

        # Global market data (current snapshot applied to all dates)
        current_btc_dom = global_market.get("btc_dominance", 0) if isinstance(global_market, dict) else 0
        current_total_mcap = global_market.get("total_market_cap_usd", 0) if isinstance(global_market, dict) else 0

        # FRED data: forward-fill (use last known value for missing dates)
        last_dxy = 0.0
        last_ffr = 0.0

        # Combine into data points
        data_points = []

        for kline in klines_btc:
            ts = kline["timestamp"]
            date_key = to_date_key(ts)
            timestamp = datetime.fromtimestamp(ts)

            # Core data — daily sources use date_key (forward-fill for intraday)
            fg = fg_by_date.get(date_key, {"value": 50, "classification": "Neutral"})
            btc_funding_rates = funding_btc_by_date.get(date_key, [0])
            eth_funding_rates = funding_eth_by_date.get(date_key, [0])
            # ETH klines: exact timestamp match first, date fallback for CoinGecko
            eth_default = {"close": 0, "high": 0, "low": 0, "open": 0}
            eth_kline = klines_eth_by_ts.get(ts) or klines_eth_by_date.get(date_key, eth_default)
            ls = ls_by_date.get(date_key, {"ratio": 1.0})

            btc_change = ((kline["close"] - kline["open"]) / kline["open"] * 100) if kline["open"] > 0 else 0
            eth_change = ((eth_kline.get("close", 0) - eth_kline.get("open", 0)) / eth_kline.get("open", 1) * 100) if eth_kline.get("open", 0) > 0 else 0

            # Open Interest
            oi = oi_by_date.get(date_key, {"oi_value": 0})
            oi_change = oi_change_by_date.get(date_key, 0.0)

            # Taker Buy/Sell
            taker = taker_by_date.get(date_key, {"ratio": 1.0})

            # Top Trader L/S
            top_ls = top_ls_by_date.get(date_key, {"ratio": 1.0})

            # Bitget Funding
            bitget_rates = bitget_funding_by_date.get(date_key, [0])

            # Stablecoin
            stable = stable_by_date.get(date_key, {"usdt_mcap": 0})
            stable_flow = stable_flow_by_date.get(date_key, 0.0)

            # Hashrate
            hr = hashrate_by_date.get(date_key, {"hashrate": 0})

            # FRED (forward-fill)
            if date_key in dxy_by_date:
                last_dxy = dxy_by_date[date_key]
            if date_key in ffr_by_date:
                last_ffr = ffr_by_date[date_key]

            # Volatility
            vol = volatility_map.get(date_key, 0.0)

            data_point = HistoricalDataPoint(
                timestamp=timestamp,
                date_str=date_key,
                fear_greed_index=fg.get("value", 50),
                fear_greed_classification=fg.get("classification", "Neutral"),
                long_short_ratio=ls.get("ratio", 1.0),
                funding_rate_btc=sum(btc_funding_rates) / len(btc_funding_rates) if btc_funding_rates else 0,
                funding_rate_eth=sum(eth_funding_rates) / len(eth_funding_rates) if eth_funding_rates else 0,
                btc_price=kline["close"],
                eth_price=eth_kline.get("close", 0),
                btc_open=kline.get("open", kline["close"]),
                eth_open=eth_kline.get("open", eth_kline.get("close", 0)),
                btc_high=kline["high"],
                btc_low=kline["low"],
                eth_high=eth_kline.get("high", 0),
                eth_low=eth_kline.get("low", 0),
                btc_24h_change=btc_change,
                eth_24h_change=eth_change,
                # New fields
                open_interest_btc=oi.get("oi_value", 0),
                open_interest_change_24h=oi_change,
                taker_buy_sell_ratio=taker.get("ratio", 1.0),
                top_trader_long_short_ratio=top_ls.get("ratio", 1.0),
                funding_rate_bitget=sum(bitget_rates) / len(bitget_rates) if bitget_rates else 0,
                stablecoin_flow_7d=stable_flow,
                usdt_market_cap=stable.get("usdt_mcap", 0),
                btc_dominance=current_btc_dom,
                total_crypto_market_cap=current_total_mcap,
                dxy_index=last_dxy,
                fed_funds_rate=last_ffr,
                btc_hashrate=hr.get("hashrate", 0),
                historical_volatility=vol,
                btc_volume=kline.get("volume", 0),
                eth_volume=eth_kline.get("volume", 0),
            )

            data_points.append(data_point)

        data_points.sort(key=lambda x: x.timestamp)

        logger.info(f"Combined {len(data_points)} historical data points from {len(self._data_sources)} sources")

        return data_points

    @property
    def data_sources(self) -> List[str]:
        """Return list of data sources used in the last fetch."""
        return self._data_sources

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
