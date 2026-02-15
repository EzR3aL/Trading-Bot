"""
Data Source Registry.

Static catalog of all available market data sources with metadata.
Used by the frontend (Bot Builder cards) and backend (selective fetching).
"""

from dataclasses import dataclass, asdict
from typing import Dict, List


@dataclass(frozen=True)
class DataSourceDef:
    """Definition of a single data source."""

    id: str
    name: str
    description: str
    category: str  # sentiment | futures | options | spot | technical | tradfi
    provider: str  # Alternative.me | Binance | Deribit | CoinGecko | GDELT | Calculated
    free: bool
    default: bool  # pre-selected for new bots

    def to_dict(self) -> dict:
        return asdict(self)


# ── All available data sources (free only) ──────────────────────────────────

DATA_SOURCES: List[DataSourceDef] = [
    # ── Sentiment & News ──
    DataSourceDef(
        id="fear_greed",
        name="Fear & Greed Index",
        description="Market sentiment score 0-100 (Extreme Fear → Extreme Greed)",
        category="sentiment",
        provider="Alternative.me",
        free=True,
        default=True,
    ),
    DataSourceDef(
        id="news_sentiment",
        name="News Sentiment (GDELT)",
        description="Aggregated news tone from global media coverage",
        category="sentiment",
        provider="GDELT",
        free=True,
        default=False,
    ),
    # ── Futures Data ──
    DataSourceDef(
        id="long_short_ratio",
        name="Long/Short Ratio",
        description="Global account long/short position ratio",
        category="futures",
        provider="Binance",
        free=True,
        default=True,
    ),
    DataSourceDef(
        id="top_trader_ls_ratio",
        name="Top Trader L/S Ratio",
        description="Long/short ratio among top traders (whales)",
        category="futures",
        provider="Binance",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="funding_rate",
        name="Funding Rate",
        description="Current perpetual funding rate (positive = longs pay shorts)",
        category="futures",
        provider="Binance",
        free=True,
        default=True,
    ),
    DataSourceDef(
        id="predicted_funding",
        name="Predicted Funding Rate",
        description="Estimated next funding rate based on current premium",
        category="futures",
        provider="Binance",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="open_interest",
        name="Open Interest",
        description="Total outstanding perpetual contracts",
        category="futures",
        provider="Binance",
        free=True,
        default=True,
    ),
    DataSourceDef(
        id="oi_history",
        name="OI History (24h)",
        description="Open interest change over the last 24 hours",
        category="futures",
        provider="Binance",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="liquidations",
        name="Recent Liquidations",
        description="Forced liquidation orders in the last hour",
        category="futures",
        provider="Binance",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="order_book",
        name="Order Book Depth",
        description="Bid/ask imbalance and spread from Binance Futures order book",
        category="futures",
        provider="Binance",
        free=True,
        default=False,
    ),
    # ── Options Data ──
    DataSourceDef(
        id="options_oi",
        name="Options Open Interest",
        description="Total open interest across BTC options (calls + puts)",
        category="options",
        provider="Deribit",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="max_pain",
        name="Max Pain Price",
        description="Strike price where most options expire worthless",
        category="options",
        provider="Deribit",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="put_call_ratio",
        name="Put/Call Ratio",
        description="Ratio of put to call open interest (>1 = bearish sentiment)",
        category="options",
        provider="Deribit",
        free=True,
        default=False,
    ),
    # ── Spot Market ──
    DataSourceDef(
        id="spot_price",
        name="24h Ticker / Price",
        description="Current price, 24h change, high/low, volume",
        category="spot",
        provider="Binance",
        free=True,
        default=True,
    ),
    DataSourceDef(
        id="spot_volume",
        name="Volume Analysis (Buy/Sell)",
        description="Taker buy vs sell volume ratio from kline data",
        category="spot",
        provider="Binance",
        free=True,
        default=True,
    ),
    DataSourceDef(
        id="coingecko_market",
        name="Market Cap & Dominance",
        description="Total crypto market cap, BTC dominance, active coins",
        category="spot",
        provider="CoinGecko",
        free=True,
        default=False,
    ),
    # ── Technical Indicators ──
    DataSourceDef(
        id="vwap",
        name="VWAP (24h)",
        description="Volume-Weighted Average Price over 24 hours",
        category="technical",
        provider="Calculated",
        free=True,
        default=True,
    ),
    DataSourceDef(
        id="supertrend",
        name="Supertrend",
        description="ATR-based trend indicator (bullish/bearish direction)",
        category="technical",
        provider="Calculated",
        free=True,
        default=True,
    ),
    DataSourceDef(
        id="oiwap",
        name="OI-Weighted Avg Price",
        description="Price weighted by open interest changes",
        category="technical",
        provider="Calculated",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="volatility",
        name="Price Volatility",
        description="Average true range as percentage over 24h candles",
        category="technical",
        provider="Binance",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="trend_sma",
        name="Trend (SMA 8/21)",
        description="Short-term trend via 8 and 21 period moving averages",
        category="technical",
        provider="Binance",
        free=True,
        default=False,
    ),
    # ── On-Chain Data ──
    DataSourceDef(
        id="stablecoin_flows",
        name="Stablecoin Flows",
        description="7-day USDT market cap change – inflows signal new capital entering crypto",
        category="spot",
        provider="DefiLlama",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="btc_hashrate",
        name="BTC Hashrate",
        description="Bitcoin network hashrate – rising hashrate signals miner confidence",
        category="spot",
        provider="Blockchain.info",
        free=True,
        default=False,
    ),
    # ── Cross-Exchange ──
    DataSourceDef(
        id="bitget_funding",
        name="Bitget Funding Rate",
        description="Bitget perpetual funding rate – compare with Binance for divergence signals",
        category="futures",
        provider="Bitget",
        free=True,
        default=False,
    ),
    # ── TradFi / CME ──
    DataSourceDef(
        id="cme_gap",
        name="CME Gap Detection",
        description="Detects price gaps between CME Friday close and current price",
        category="tradfi",
        provider="Binance",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="macro_dxy",
        name="US Dollar Index (DXY)",
        description="Dollar strength index – strong USD is typically bearish for crypto",
        category="tradfi",
        provider="FRED",
        free=True,
        default=False,
    ),
    DataSourceDef(
        id="fed_funds_rate",
        name="Fed Funds Rate",
        description="US Federal Reserve interest rate – rate cuts are bullish for risk assets",
        category="tradfi",
        provider="FRED",
        free=True,
        default=False,
    ),
]

# Quick lookup by ID
DATA_SOURCE_MAP: Dict[str, DataSourceDef] = {ds.id: ds for ds in DATA_SOURCES}

# IDs of sources selected by default for new bots
DEFAULT_SOURCES: List[str] = [ds.id for ds in DATA_SOURCES if ds.default]

# All category names in display order
CATEGORIES = ["sentiment", "futures", "options", "spot", "technical", "tradfi"]

# Provider → health-check URL mapping (for connections tab)
PROVIDER_HEALTH_URLS: Dict[str, str] = {
    "Alternative.me": "https://api.alternative.me/fng/?limit=1",
    "Binance": "https://fapi.binance.com/fapi/v1/ping",
    "Deribit": "https://www.deribit.com/api/v2/public/test",
    "CoinGecko": "https://api.coingecko.com/api/v3/ping",
    "GDELT": "https://api.gdeltproject.org/api/v2/doc/doc?query=bitcoin&mode=tonechart&format=json&maxrecords=5",
    "DefiLlama": "https://stablecoins.llama.fi/stablecoins?includePrices=false",
    "Blockchain.info": "https://api.blockchain.info/stats",
    "Bitget": "https://api.bitget.com/api/v2/public/time",
    "FRED": "https://api.stlouisfed.org/fred/series?series_id=DFF&api_key=DEMO_KEY&file_type=json",
    # "Calculated" sources have no external dependency
}


def get_sources_by_category(category: str) -> List[DataSourceDef]:
    """Return all sources in a given category."""
    return [ds for ds in DATA_SOURCES if ds.category == category]


def get_unique_providers() -> List[str]:
    """Return unique external provider names (excluding 'Calculated')."""
    return sorted({ds.provider for ds in DATA_SOURCES if ds.provider != "Calculated"})
