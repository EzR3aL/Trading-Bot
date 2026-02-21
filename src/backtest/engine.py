"""
Backtest Engine for the Contrarian Liquidation Hunter Strategy.

Simulates trading over historical data and calculates performance metrics.
Uses multi-source data analysis for signal generation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, List, Optional, Dict, Tuple

from src.backtest.historical_data import HistoricalDataPoint
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.backtest.report import BacktestResult

logger = get_logger(__name__)


# ------------------------------------------------------------------ #
#  Technical Indicator Helpers (pure math, no external deps)         #
# ------------------------------------------------------------------ #

def _ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    if len(values) < period or period < 1:
        return values[:]
    k = 2.0 / (period + 1)
    result = [0.0] * len(values)
    result[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def _rsi(closes: List[float], period: int = 14) -> List[float]:
    """Relative Strength Index from close prices."""
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    result = [50.0] * len(closes)
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    if len(gains) < period:
        return result
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))
    return result


def _macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, float]:
    """MACD line, signal, histogram (returns latest values)."""
    if len(closes) < slow + signal:
        return {"macd": 0, "signal": 0, "histogram": 0, "histogram_series": []}
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    valid_macd = [m for i, m in enumerate(macd_line) if i >= slow - 1 and m != 0]
    if len(valid_macd) < signal:
        return {"macd": macd_line[-1], "signal": 0, "histogram": macd_line[-1], "histogram_series": []}
    sig = _ema(valid_macd, signal)
    hist_series = [valid_macd[i] - sig[i] for i in range(len(valid_macd))]
    return {
        "macd": valid_macd[-1] if valid_macd else 0,
        "signal": sig[-1] if sig else 0,
        "histogram": hist_series[-1] if hist_series else 0,
        "histogram_series": hist_series,
    }


def _adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Average Directional Index."""
    if len(closes) < period + 1:
        return 0.0
    plus_dm_list = []
    minus_dm_list = []
    tr_list = []
    for i in range(1, len(closes)):
        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]
        plus_dm_list.append(max(high_diff, 0) if high_diff > low_diff else 0)
        minus_dm_list.append(max(low_diff, 0) if low_diff > high_diff else 0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
    if len(tr_list) < period:
        return 0.0
    atr = sum(tr_list[:period]) / period
    plus_dm = sum(plus_dm_list[:period]) / period
    minus_dm = sum(minus_dm_list[:period]) / period
    dx_list = []
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        plus_dm = (plus_dm * (period - 1) + plus_dm_list[i]) / period
        minus_dm = (minus_dm * (period - 1) + minus_dm_list[i]) / period
        if atr == 0:
            continue
        plus_di = 100 * plus_dm / atr
        minus_di = 100 * minus_dm / atr
        di_sum = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0
        dx_list.append(dx)
    if not dx_list:
        return 0.0
    if len(dx_list) < period:
        return sum(dx_list) / len(dx_list)
    adx_val = sum(dx_list[:period]) / period
    for i in range(period, len(dx_list)):
        adx_val = (adx_val * (period - 1) + dx_list[i]) / period
    return adx_val


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Average True Range (latest value)."""
    if len(closes) < 2:
        return 0.0
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
    if len(tr_list) < period:
        return sum(tr_list) / len(tr_list) if tr_list else 0
    atr_val = sum(tr_list[:period]) / period
    for i in range(period, len(tr_list)):
        atr_val = (atr_val * (period - 1) + tr_list[i]) / period
    return atr_val


def _stdev(values: List[float], window: int) -> float:
    """Standard deviation of last `window` values."""
    if len(values) < 2:
        return 1e-10
    subset = values[-window:]
    mean = sum(subset) / len(subset)
    var = sum((v - mean) ** 2 for v in subset) / len(subset)
    return max(math.sqrt(var), 1e-10)


def _tanh(x: float) -> float:
    return math.tanh(x)


def _supertrend_direction(
    highs: List[float], lows: List[float], closes: List[float],
    atr_period: int = 10, multiplier: float = 3.0,
) -> str:
    """Calculate Supertrend trend direction: 'bullish', 'bearish', or 'neutral'."""
    n = len(closes)
    if n < atr_period + 2:
        return "neutral"

    # True Range series (index 0 corresponds to closes[1])
    tr_list = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)

    if len(tr_list) < atr_period:
        return "neutral"

    # ATR series (Wilder smoothing)
    atr_vals = [0.0] * len(tr_list)
    atr_vals[atr_period - 1] = sum(tr_list[:atr_period]) / atr_period
    for i in range(atr_period, len(tr_list)):
        atr_vals[i] = (atr_vals[i - 1] * (atr_period - 1) + tr_list[i]) / atr_period

    # Walk through price series computing Supertrend bands and direction
    trend = 1  # 1 = bullish, -1 = bearish
    prev_upper = 0.0
    prev_lower = 0.0

    for i in range(atr_period, len(tr_list)):
        close_idx = i + 1  # Corresponding close index
        if close_idx >= len(closes):
            break
        mid = (highs[close_idx] + lows[close_idx]) / 2
        atr = atr_vals[i]

        basic_upper = mid + multiplier * atr
        basic_lower = mid - multiplier * atr

        if i == atr_period:
            final_upper = basic_upper
            final_lower = basic_lower
        else:
            # Upper band can only decrease unless price broke above
            final_upper = basic_upper if (basic_upper < prev_upper or closes[close_idx - 1] > prev_upper) else prev_upper
            # Lower band can only increase unless price broke below
            final_lower = basic_lower if (basic_lower > prev_lower or closes[close_idx - 1] < prev_lower) else prev_lower

        # Trend flips
        if trend == 1 and closes[close_idx] < final_lower:
            trend = -1
        elif trend == -1 and closes[close_idx] > final_upper:
            trend = 1

        prev_upper = final_upper
        prev_lower = final_lower

    return "bullish" if trend == 1 else "bearish"


def _detect_rsi_divergence(
    closes: List[float], rsi_values: List[float], lookback: int = 20,
) -> Dict[str, bool]:
    """Detect bullish/bearish RSI divergence over a lookback window."""
    result = {"bullish_divergence": False, "bearish_divergence": False}

    if len(closes) < lookback + 2 or len(rsi_values) < lookback + 2:
        return result

    recent_closes = closes[-lookback:]
    recent_rsi = rsi_values[-lookback:]
    half = lookback // 2

    first_half_c = recent_closes[:half]
    second_half_c = recent_closes[half:]
    first_half_r = recent_rsi[:half]
    second_half_r = recent_rsi[half:]

    if not first_half_c or not second_half_c:
        return result

    # Bullish divergence: price lower low, RSI higher low
    first_low_idx = first_half_c.index(min(first_half_c))
    second_low_idx = second_half_c.index(min(second_half_c))
    if min(second_half_c) < min(first_half_c) and second_half_r[second_low_idx] > first_half_r[first_low_idx]:
        result["bullish_divergence"] = True

    # Bearish divergence: price higher high, RSI lower high
    first_high_idx = first_half_c.index(max(first_half_c))
    second_high_idx = second_half_c.index(max(second_half_c))
    if max(second_half_c) > max(first_half_c) and second_half_r[second_high_idx] < first_half_r[first_high_idx]:
        result["bearish_divergence"] = True

    return result


class TradeResult(Enum):
    """Trade outcome."""
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TIME_EXIT = "time_exit"
    OPEN = "open"


class TradeDirection(Enum):
    """Trade direction."""
    LONG = "long"
    SHORT = "short"


@dataclass
class BacktestTrade:
    """Single trade in the backtest."""
    id: int
    symbol: str
    direction: TradeDirection
    entry_date: str
    entry_price: float
    position_size: float
    position_value: float
    leverage: int
    confidence: int
    reason: str

    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    result: TradeResult = TradeResult.OPEN
    pnl: float = 0.0
    pnl_percent: float = 0.0
    fees: float = 0.0
    funding_paid: float = 0.0
    net_pnl: float = 0.0

    take_profit_price: float = 0.0
    stop_loss_price: float = 0.0

    # ExecutionSimulator fields (populated in unified mode)
    entry_timestamp: Optional[datetime] = None
    entry_candle_range: float = 0.0  # (high-low)/close of entry candle

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "position_size": self.position_size,
            "position_value": self.position_value,
            "leverage": self.leverage,
            "confidence": self.confidence,
            "reason": self.reason,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "result": self.result.value,
            "pnl": self.pnl,
            "pnl_percent": self.pnl_percent,
            "fees": self.fees,
            "funding_paid": self.funding_paid,
            "net_pnl": self.net_pnl,
            "take_profit_price": self.take_profit_price,
            "stop_loss_price": self.stop_loss_price,
        }


@dataclass
class DailyBacktestStats:
    """Daily statistics during backtest."""
    date: str
    starting_balance: float
    ending_balance: float
    trades_opened: int
    trades_closed: int
    daily_pnl: float
    daily_fees: float
    daily_funding: float
    daily_return_percent: float
    cumulative_return_percent: float


@dataclass
class BacktestConfig:
    """Backtest configuration."""
    starting_capital: float = 10000.0
    leverage: int = 3
    take_profit_percent: float = 3.5
    stop_loss_percent: float = 2.0
    max_trades_per_day: int = 3
    daily_loss_limit_percent: float = 5.0
    position_size_percent: float = 10.0
    trading_fee_percent: float = 0.04
    slippage_percent: float = 0.03  # 0.03% per trade (entry + exit)

    # Strategy type (determines signal generation logic)
    strategy_type: str = "liquidation_hunter"

    # Strategy thresholds
    fear_greed_extreme_fear: int = 25
    fear_greed_extreme_greed: int = 75
    long_short_crowded_longs: float = 2.0
    long_short_crowded_shorts: float = 0.5
    funding_rate_high: float = 0.0005
    funding_rate_low: float = -0.0002
    high_confidence_min: int = 85
    low_confidence_min: int = 55

    # Profit Lock-In settings
    enable_profit_lock: bool = True
    profit_lock_percent: float = 75.0
    min_profit_floor: float = 0.5


class BacktestEngine:
    """
    Backtest engine that simulates the trading strategy.

    Uses multi-source data analysis including Open Interest, Taker Volume,
    Top Trader positioning, stablecoin flows, hashrate, and volatility
    for improved signal generation.
    """

    def __init__(self, config: Optional[BacktestConfig] = None, strategy_type: str = "liquidation_hunter", symbol: str = "BTC"):
        self.config = config or BacktestConfig()
        self.strategy_type = strategy_type
        self.symbol = symbol
        self._signal_metadata: Dict[str, Any] = {}
        self.execution_simulator = None  # Set by strategy_adapter for unified mode
        self.reset()

    def reset(self):
        """Reset the backtest state."""
        self.capital = self.config.starting_capital
        self.trades: List[BacktestTrade] = []
        self.daily_stats: List[DailyBacktestStats] = []
        self.open_positions: Dict[str, BacktestTrade] = {}
        self.trade_counter = 0
        self.daily_trades_count = 0
        self.daily_pnl = 0.0
        self.daily_closed_count = 0
        self.daily_fees = 0.0
        self.daily_funding = 0.0
        self.current_date = ""
        self._signal_metadata = {}

    def _get_min_confidence(self) -> int:
        """Per-strategy minimum confidence, matching live defaults."""
        if self.strategy_type in ("edge_indicator", "claude_edge_indicator", "sentiment_surfer"):
            return 40
        if self.strategy_type == "liquidation_hunter":
            return 60
        return self.config.low_confidence_min

    def _build_score_series_backtest(self, closes: List[float]) -> List[float]:
        """Build the full momentum score series for EMA smoothing (matches live)."""
        macd_slow = 26
        macd_signal = 9

        if len(closes) < macd_slow + macd_signal + 10:
            return []

        # Full MACD histogram series
        ema_f_macd = _ema(closes, 12)
        ema_s_macd = _ema(closes, 26)
        macd_line = [ema_f_macd[i] - ema_s_macd[i] for i in range(len(closes))]
        valid_macd = [m for i, m in enumerate(macd_line) if i >= 25 and m != 0]
        if len(valid_macd) < macd_signal:
            return []
        sig_line = _ema(valid_macd, macd_signal)
        hist_series = [valid_macd[i] - sig_line[i] for i in range(len(valid_macd))]

        # Full RSI smoothed series
        rsi_vals = _rsi(closes, 14)
        rsi_smoothed = _ema(rsi_vals, 5)

        # Full EMA 8/21 series
        ema_f = _ema(closes, 8)
        ema_s = _ema(closes, 21)

        min_len = min(len(hist_series), len(rsi_smoothed) - 1, len(ema_f), len(ema_s))
        if min_len <= 1:
            return []

        scores = []
        for i in range(1, min_len):
            hist_val = hist_series[i] if i < len(hist_series) else 0.0
            hist_window = hist_series[max(0, i - 99):i + 1]
            sd = _stdev(hist_window, min(100, len(hist_window)))
            m_norm = _tanh(hist_val / sd) if sd > 1e-10 else 0

            rsi_idx = len(rsi_smoothed) - min_len + i
            rsi_prev_idx = rsi_idx - 1
            if rsi_idx < len(rsi_smoothed) and rsi_prev_idx >= 0:
                drift = rsi_smoothed[rsi_idx] - rsi_smoothed[rsi_prev_idx]
            else:
                drift = 0.0
            r_norm = _tanh(drift / 2.0)

            ema_f_idx = len(ema_f) - min_len + i
            ema_s_idx = len(ema_s) - min_len + i
            if ema_f_idx < len(ema_f) and ema_s_idx < len(ema_s):
                t_bonus = 0.6 if ema_f[ema_f_idx] > ema_s[ema_s_idx] else -0.6
            else:
                t_bonus = 0.0

            raw = m_norm + r_norm + t_bonus
            scores.append(max(-1.0, min(1.0, raw)))

        return scores

    # ------------------------------------------------------------------ #
    #  SIGNAL ANALYSIS COMPONENTS                                        #
    # ------------------------------------------------------------------ #

    def _analyze_leverage(self, long_short_ratio: float) -> Tuple[Optional[TradeDirection], int, str]:
        """Analyze leverage position based on Long/Short Ratio."""
        crowded_longs = self.config.long_short_crowded_longs
        crowded_shorts = self.config.long_short_crowded_shorts

        if long_short_ratio > crowded_longs:
            excess = (long_short_ratio - crowded_longs) / crowded_longs * 100
            confidence_boost = min(int(excess * 2), 30)
            reason = f"Crowded Longs (L/S={long_short_ratio:.2f})"
            return TradeDirection.SHORT, confidence_boost, reason

        elif long_short_ratio < crowded_shorts:
            excess = (crowded_shorts - long_short_ratio) / crowded_shorts * 100
            confidence_boost = min(int(excess * 2), 30)
            reason = f"Crowded Shorts (L/S={long_short_ratio:.2f})"
            return TradeDirection.LONG, confidence_boost, reason

        return None, 0, f"L/S Neutral ({long_short_ratio:.2f})"

    def _analyze_sentiment(self, fear_greed: int) -> Tuple[Optional[TradeDirection], int, str]:
        """Analyze Fear & Greed sentiment."""
        extreme_fear = self.config.fear_greed_extreme_fear
        extreme_greed = self.config.fear_greed_extreme_greed

        if fear_greed > extreme_greed:
            excess = fear_greed - extreme_greed
            confidence_boost = min(excess, 20)
            reason = f"Extreme Greed (FGI={fear_greed})"
            return TradeDirection.SHORT, confidence_boost, reason

        elif fear_greed < extreme_fear:
            excess = extreme_fear - fear_greed
            confidence_boost = min(excess, 20)
            reason = f"Extreme Fear (FGI={fear_greed})"
            return TradeDirection.LONG, confidence_boost, reason

        return None, 0, f"Sentiment Neutral (FGI={fear_greed})"

    def _analyze_funding_rate(
        self, funding_rate: float, base_direction: Optional[TradeDirection]
    ) -> Tuple[int, str]:
        """Analyze funding rate and adjust confidence."""
        high_threshold = self.config.funding_rate_high
        low_threshold = self.config.funding_rate_low

        if funding_rate > high_threshold:
            adjustment = 20 if base_direction == TradeDirection.SHORT else -10
            return adjustment, f"High Funding ({funding_rate*100:.4f}%)"

        elif funding_rate < low_threshold:
            adjustment = 20 if base_direction == TradeDirection.LONG else -10
            return adjustment, f"Negative Funding ({funding_rate*100:.4f}%)"

        return 0, f"Funding Neutral ({funding_rate*100:.4f}%)"

    def _analyze_open_interest(
        self, data: HistoricalDataPoint, base_direction: Optional[TradeDirection]
    ) -> Tuple[int, str]:
        """
        Analyze Open Interest changes.

        Rising OI + price up = strong trend (confirms longs)
        Rising OI + price down = strong selling pressure (confirms shorts)
        Falling OI = positions closing (reduces confidence)
        """
        oi_change = data.open_interest_change_24h
        price_change = data.btc_24h_change

        if abs(oi_change) < 1.0:
            return 0, f"OI Flat ({oi_change:+.1f}%)"

        if oi_change > 3.0 and price_change > 0:
            # Rising OI + rising price = strong longs building
            adj = 10 if base_direction == TradeDirection.SHORT else 5
            return adj, f"OI Rising+Price Up ({oi_change:+.1f}%, crowded longs)"

        if oi_change > 3.0 and price_change < 0:
            # Rising OI + falling price = aggressive shorts opening
            adj = 10 if base_direction == TradeDirection.LONG else 5
            return adj, f"OI Rising+Price Down ({oi_change:+.1f}%, crowded shorts)"

        if oi_change < -3.0:
            # Falling OI = liquidations/position closing, reduces directional confidence
            return -5, f"OI Falling ({oi_change:+.1f}%, deleveraging)"

        return 0, f"OI Moderate ({oi_change:+.1f}%)"

    def _analyze_taker_volume(
        self, data: HistoricalDataPoint, base_direction: Optional[TradeDirection]
    ) -> Tuple[int, str]:
        """
        Analyze Taker Buy/Sell Volume Ratio.

        > 1.0 = more aggressive buying (takers buying)
        < 1.0 = more aggressive selling (takers selling)
        Extreme readings suggest contrarian opportunity.
        """
        ratio = data.taker_buy_sell_ratio

        if ratio > 1.3:
            # Heavy buying pressure - contrarian short signal
            adj = 8 if base_direction == TradeDirection.SHORT else -5
            return adj, f"Taker Heavy Buy ({ratio:.2f})"

        if ratio < 0.7:
            # Heavy selling pressure - contrarian long signal
            adj = 8 if base_direction == TradeDirection.LONG else -5
            return adj, f"Taker Heavy Sell ({ratio:.2f})"

        if ratio > 1.1:
            adj = 3 if base_direction == TradeDirection.SHORT else 0
            return adj, f"Taker Mild Buy ({ratio:.2f})"

        if ratio < 0.9:
            adj = 3 if base_direction == TradeDirection.LONG else 0
            return adj, f"Taker Mild Sell ({ratio:.2f})"

        return 0, f"Taker Balanced ({ratio:.2f})"

    def _analyze_top_traders(
        self, data: HistoricalDataPoint, base_direction: Optional[TradeDirection]
    ) -> Tuple[int, str]:
        """
        Analyze Top Trader Long/Short Ratio.

        Top traders often have better insight, so their positioning is
        confirmation rather than contrarian.
        """
        ratio = data.top_trader_long_short_ratio

        if ratio > 1.5:
            # Top traders heavily long -> confirms long or warns against short
            adj = 5 if base_direction == TradeDirection.LONG else -5
            return adj, f"TopTraders Long ({ratio:.2f})"

        if ratio < 0.7:
            # Top traders heavily short -> confirms short or warns against long
            adj = 5 if base_direction == TradeDirection.SHORT else -5
            return adj, f"TopTraders Short ({ratio:.2f})"

        return 0, f"TopTraders Neutral ({ratio:.2f})"

    def _analyze_funding_divergence(
        self, data: HistoricalDataPoint, base_direction: Optional[TradeDirection]
    ) -> Tuple[int, str]:
        """
        Cross-exchange funding rate comparison (Binance vs Bitget).

        Large divergence suggests arbitrage pressure or localized sentiment.
        """
        binance_rate = data.funding_rate_btc
        bitget_rate = data.funding_rate_bitget

        if bitget_rate == 0 and binance_rate == 0:
            return 0, "Funding Divergence N/A"

        diff = abs(binance_rate - bitget_rate)

        if diff > 0.0005:
            # Large divergence - signals market stress
            return 5, f"Funding Divergence ({diff*100:.4f}%)"

        return 0, f"Funding Aligned ({diff*100:.4f}%)"

    def _analyze_stablecoin_flows(
        self, data: HistoricalDataPoint, base_direction: Optional[TradeDirection]
    ) -> Tuple[int, str]:
        """
        Analyze stablecoin (USDT) 7-day net flows.

        Positive flows = money entering crypto ecosystem (bullish)
        Negative flows = money leaving (bearish)
        """
        flow = data.stablecoin_flow_7d

        if abs(flow) < 500_000_000:
            return 0, "Stablecoin Flows Neutral"

        if flow > 2_000_000_000:
            adj = 5 if base_direction == TradeDirection.LONG else -3
            return adj, f"Stablecoin Inflow (${flow/1e9:.1f}B)"

        if flow > 500_000_000:
            adj = 3 if base_direction == TradeDirection.LONG else 0
            return adj, f"Stablecoin Mild Inflow (${flow/1e9:.1f}B)"

        if flow < -2_000_000_000:
            adj = 5 if base_direction == TradeDirection.SHORT else -3
            return adj, f"Stablecoin Outflow (${flow/1e9:.1f}B)"

        if flow < -500_000_000:
            adj = 3 if base_direction == TradeDirection.SHORT else 0
            return adj, f"Stablecoin Mild Outflow (${flow/1e9:.1f}B)"

        return 0, f"Stablecoin Flow (${flow/1e9:.1f}B)"

    def _analyze_volatility(
        self, data: HistoricalDataPoint
    ) -> Tuple[int, str]:
        """
        Analyze historical volatility for position sizing adjustment.

        High volatility -> reduce confidence (tighter risk management)
        Low volatility -> slightly increase confidence
        """
        vol = data.historical_volatility

        if vol > 100:
            return -10, f"Extreme Volatility ({vol:.0f}%)"

        if vol > 70:
            return -5, f"High Volatility ({vol:.0f}%)"

        if vol < 30:
            return 3, f"Low Volatility ({vol:.0f}%)"

        return 0, f"Normal Volatility ({vol:.0f}%)"

    def _analyze_macro(
        self, data: HistoricalDataPoint, base_direction: Optional[TradeDirection]
    ) -> Tuple[int, str]:
        """
        Analyze macro indicators (DXY, Fed Funds Rate).

        Strong USD (high DXY) is typically bearish for crypto.
        High interest rates are bearish for risk assets.
        """
        dxy = data.dxy_index

        if dxy == 0:
            return 0, "Macro N/A"

        if dxy > 107:
            adj = 3 if base_direction == TradeDirection.SHORT else -3
            return adj, f"Strong USD (DXY={dxy:.1f})"

        if dxy < 100:
            adj = 3 if base_direction == TradeDirection.LONG else -3
            return adj, f"Weak USD (DXY={dxy:.1f})"

        return 0, f"USD Neutral (DXY={dxy:.1f})"

    # ------------------------------------------------------------------ #
    #  STRATEGY-SPECIFIC SIGNAL GENERATORS                                #
    # ------------------------------------------------------------------ #

    def _signal_sentiment_surfer(
        self, data: HistoricalDataPoint, symbol: str,
        history: Optional[List[HistoricalDataPoint]] = None,
    ) -> Tuple[TradeDirection, int, str]:
        """
        Sentiment Surfer: Exact match of live SentimentSurferStrategy.
        6 sources scored [-100, +100], weighted with live weights, agreement gate.
        """
        hist = history or [data]
        price = data.btc_price if symbol == "BTC" else data.eth_price

        # Calculate actual 24h price change from history (not per-candle change)
        candles_24h = 1
        if len(hist) >= 3:
            time_diff = (hist[-1].timestamp - hist[0].timestamp).total_seconds()
            candle_secs = time_diff / (len(hist) - 1) if len(hist) > 1 else 86400
            candles_24h = max(1, int(86400 / candle_secs))

        lookback_24h = candles_24h + 1  # +1 because hist[-1] is current candle
        if len(hist) > lookback_24h:
            price_24h_ago = hist[-lookback_24h].btc_price if symbol == "BTC" else hist[-lookback_24h].eth_price
            price_change = (price - price_24h_ago) / price_24h_ago * 100 if price_24h_ago > 0 else 0
        else:
            price_change = data.btc_24h_change if symbol == "BTC" else data.eth_24h_change

        all_scores = []  # (score, reason, weight_key)

        # Source 1: News Sentiment (GDELT) — not available in backtest (excluded from agreement count)
        news_unavailable = True

        # Source 2: Fear & Greed (contrarian) — matches live _score_fear_greed
        fg = data.fear_greed_index
        extreme_fear, extreme_greed = 25, 75
        if fg < extreme_fear:
            fg_score = min(float((extreme_fear - fg) * 3), 100.0)
            fg_reason = f"Extreme Fear ({fg}) - contrarian bullish"
        elif fg > extreme_greed:
            fg_score = max(float(-(fg - extreme_greed) * 3), -100.0)
            fg_reason = f"Extreme Greed ({fg}) - contrarian bearish"
        else:
            fg_score, fg_reason = 0.0, f"Sentiment neutral (FGI={fg})"
        all_scores.append((fg_score, fg_reason, "fear_greed"))

        # Source 3: VWAP — matches live _score_vwap
        vwap_window = min(candles_24h, len(hist))
        if vwap_window >= 3:
            vwap_closes = [h.btc_price if symbol == "BTC" else h.eth_price for h in hist[-vwap_window:]]
            vwap_volumes = [
                h.btc_volume if symbol == "BTC" else getattr(h, "eth_volume", h.btc_volume)
                for h in hist[-vwap_window:]
            ]
            total_vol = sum(vwap_volumes)
            vwap = sum(c * v for c, v in zip(vwap_closes, vwap_volumes)) / total_vol if total_vol > 0 else price
            deviation = (price - vwap) / vwap if vwap > 0 else 0
            if abs(deviation) < 0.005:
                vwap_score, vwap_reason = 0.0, f"Price near VWAP ({deviation:+.2%})"
            else:
                vwap_score = max(min(deviation * 2000, 100), -100)
                vwap_reason = f"Price {'above' if vwap_score > 0 else 'below'} VWAP ({deviation:+.2%})"
        else:
            vwap_score, vwap_reason = 0.0, "VWAP insufficient data"
        all_scores.append((vwap_score, vwap_reason, "vwap"))

        # Source 4: Supertrend — matches live _score_supertrend
        if len(hist) >= max(14, candles_24h):
            st_closes = [h.btc_price if symbol == "BTC" else h.eth_price for h in hist]
            st_highs = [h.btc_high if symbol == "BTC" else h.eth_high for h in hist]
            st_lows = [h.btc_low if symbol == "BTC" else h.eth_low for h in hist]
            st_dir = _supertrend_direction(st_highs, st_lows, st_closes, 10, 3.0)
            if st_dir == "bullish":
                st_score, st_reason = 70.0, "Supertrend GREEN (uptrend)"
            elif st_dir == "bearish":
                st_score, st_reason = -70.0, "Supertrend RED (downtrend)"
            else:
                st_score, st_reason = 0.0, "Supertrend neutral"
        else:
            st_score, st_reason = 0.0, "Supertrend insufficient data"
        all_scores.append((st_score, st_reason, "supertrend"))

        # Source 5: Spot Volume — matches live _score_spot_volume
        taker_ratio = data.taker_buy_sell_ratio
        buy_ratio = taker_ratio / (taker_ratio + 1) if taker_ratio > 0 else 0.5
        if abs(buy_ratio - 0.5) < 0.05:
            vol_score, vol_reason = 0.0, f"Volume balanced (buy={buy_ratio:.1%})"
        else:
            vol_score = max(min((buy_ratio - 0.5) * 400, 100), -100)
            vol_reason = f"Volume {'accumulation' if vol_score > 0 else 'distribution'} (buy={buy_ratio:.1%})"
        all_scores.append((vol_score, vol_reason, "volume"))

        # Source 6: Price Momentum — matches live _score_momentum
        if abs(price_change) < 0.5:
            mom_score, mom_reason = 0.0, f"Momentum flat ({price_change:+.2f}%)"
        elif abs(price_change) > 2.0:
            mom_score = max(min(price_change * 20, 100), -100)
            mom_reason = f"Momentum {'bullish' if mom_score > 0 else 'bearish'} ({price_change:+.2f}%)"
        else:
            mom_score = price_change * 15
            mom_reason = f"Momentum {'bullish' if mom_score > 0 else 'bearish'} ({price_change:+.2f}%)"
        all_scores.append((mom_score, mom_reason, "momentum"))

        # Weighted aggregation — matches live weights exactly
        weights = {
            "news": 1.0, "fear_greed": 1.0, "vwap": 1.2,
            "supertrend": 1.2, "volume": 0.8, "momentum": 0.8,
        }
        total_weighted = sum(s * weights.get(k, 1.0) for s, _, k in all_scores)
        total_weight = sum(weights.get(k, 1.0) for _, _, k in all_scores)
        weighted_score = total_weighted / total_weight if total_weight > 0 else 0

        direction = TradeDirection.LONG if weighted_score >= 0 else TradeDirection.SHORT

        # Confidence = absolute weighted score, capped at 95 (matches live)
        confidence = min(int(abs(weighted_score)), 95)

        # Agreement count — exclude unavailable sources (News in backtest)
        available_sources = len(all_scores)
        if news_unavailable:
            available_sources = len(all_scores)  # News not in all_scores
            min_agreement = max(2, available_sources // 2)  # 2/5 or 3/6
        else:
            min_agreement = 3

        if direction == TradeDirection.LONG:
            agreement = sum(1 for s, _, _ in all_scores if s > 0)
        else:
            agreement = sum(1 for s, _, _ in all_scores if s < 0)

        # Gate: need min agreement AND confidence >= 40 (matches live should_trade)
        if agreement < min_agreement or confidence < 40:
            confidence = 0

        reasons = [r for _, r, _ in all_scores]
        reasons.append(f"Agreement: {agreement}/{available_sources}")
        return direction, confidence, " | ".join(reasons)

    def _signal_edge_indicator(
        self, data: HistoricalDataPoint, symbol: str,
        history: Optional[List[HistoricalDataPoint]] = None,
    ) -> Tuple[TradeDirection, int, str]:
        """
        Edge Indicator: Exact match of live EdgeIndicatorStrategy.
        EMA Ribbon (8/21) + ADX Chop Filter (0.8 multiplier) +
        Predator Momentum with EMA(3) smoothing + regime flip detection.
        """
        if not history or len(history) < 30:
            return TradeDirection.LONG, 0, "Insufficient history"

        closes = [h.btc_price if symbol == "BTC" else h.eth_price for h in history]
        highs = [h.btc_high if symbol == "BTC" else h.eth_high for h in history]
        lows = [h.btc_low if symbol == "BTC" else h.eth_low for h in history]
        price = closes[-1]
        reasons = []

        # --- Layer 1: EMA Ribbon (8/21) ---
        ema_fast = _ema(closes, 8)
        ema_slow = _ema(closes, 21)
        ema_f = ema_fast[-1] if ema_fast[-1] != 0 else price
        ema_s = ema_slow[-1] if ema_slow[-1] != 0 else price
        upper_band = max(ema_f, ema_s)
        lower_band = min(ema_f, ema_s)
        ema_fast_above = ema_f > ema_s

        bull_trend = price > upper_band
        bear_trend = price < lower_band

        if bull_trend:
            reasons.append("EMA Bull Trend")
        elif bear_trend:
            reasons.append("EMA Bear Trend")

        # --- Layer 2: ADX Trend Strength ---
        adx_val = _adx(highs, lows, closes, 14)
        adx_threshold = 18.0
        is_trending = adx_val >= adx_threshold

        # --- Layer 3: Predator Momentum Score ---
        macd_data = _macd(closes, 12, 26, 9)
        hist_val = macd_data["histogram"]
        hist_series = macd_data["histogram_series"]
        stdev_macd = _stdev(hist_series, min(100, len(hist_series))) if hist_series else 1e-10
        macd_norm = _tanh(hist_val / stdev_macd) if stdev_macd > 1e-10 else 0

        rsi_values = _rsi(closes, 14)
        rsi_smoothed = _ema(rsi_values, 5)
        if len(rsi_smoothed) >= 2 and rsi_smoothed[-1] != 0 and rsi_smoothed[-2] != 0:
            rsi_drift = rsi_smoothed[-1] - rsi_smoothed[-2]
        else:
            rsi_drift = 0.0
        rsi_norm = _tanh(rsi_drift / 2.0)

        trend_bonus = 0.6 if ema_fast_above else -0.6
        raw_score = macd_norm + rsi_norm + trend_bonus
        momentum_score = max(-1.0, min(1.0, raw_score))

        # --- Score Series & EMA(3) Smoothing (matches live) ---
        score_series = self._build_score_series_backtest(closes)
        smooth_len = 3
        if score_series and len(score_series) >= smooth_len:
            smoothed_series = _ema(score_series, smooth_len)
            smoothed_score = smoothed_series[-1] if smoothed_series[-1] != 0 else momentum_score
        else:
            smoothed_score = momentum_score

        # --- Regime Detection (from smoothed score, matches live) ---
        pos_thresh = 0.20
        neg_thresh = -0.20
        if smoothed_score > pos_thresh:
            regime = 1
            reasons.append(f"Momentum Bull ({smoothed_score:+.2f})")
        elif smoothed_score < neg_thresh:
            regime = -1
            reasons.append(f"Momentum Bear ({smoothed_score:+.2f})")
        else:
            regime = 0

        # --- Regime Flip Detection (matches live _get_previous_regime) ---
        prev_regime = 0
        if score_series and len(score_series) >= smooth_len + 1:
            prev_series = score_series[:-1]
            if len(prev_series) >= smooth_len:
                prev_smoothed = _ema(prev_series, smooth_len)
                prev_val = prev_smoothed[-1] if prev_smoothed and prev_smoothed[-1] != 0 else 0.0
                if prev_val > pos_thresh:
                    prev_regime = 1
                elif prev_val < neg_thresh:
                    prev_regime = -1

        regime_flip_bull = regime == 1 and prev_regime != 1
        regime_flip_bear = regime == -1 and prev_regime != -1

        # --- Confidence (matches live _calculate_confidence exactly) ---
        confidence = 50

        # ADX: live uses 0.8 multiplier (not 1.5), int(deficit) penalty (not *1.2)
        if is_trending:
            adx_bonus = min(int((adx_val - adx_threshold) * 0.8), 25)
            confidence += adx_bonus
            reasons.append(f"ADX Trending ({adx_val:.0f})")
        else:
            chop_penalty = min(int(adx_threshold - adx_val), 20)
            confidence -= chop_penalty
            reasons.append(f"ADX Choppy ({adx_val:.0f})")

        # Momentum magnitude (uses smoothed score, matches live)
        abs_score = abs(smoothed_score)
        if abs_score > 0.5:
            confidence += 20
        elif abs_score > 0.3:
            confidence += 12
        elif abs_score > 0.15:
            confidence += 5

        # Full alignment bonus
        if (bull_trend and regime == 1 and is_trending) or \
           (bear_trend and regime == -1 and is_trending):
            confidence += 10
            reasons.append("FULL ALIGNMENT")

        # Regime flip bonus (matches live, NOT entry cross)
        if regime_flip_bull or regime_flip_bear:
            confidence += 10
            reasons.append("REGIME FLIP")

        confidence = max(0, min(95, confidence))

        # --- Direction Logic (matches live _determine_direction) ---
        if bull_trend and is_trending and smoothed_score >= 0:
            direction = TradeDirection.LONG
        elif bear_trend and is_trending and smoothed_score <= 0:
            direction = TradeDirection.SHORT
        elif is_trending and regime == 1 and not bear_trend:
            direction = TradeDirection.LONG
        elif is_trending and regime == -1 and not bull_trend:
            direction = TradeDirection.SHORT
        else:
            if regime == 1:
                direction = TradeDirection.LONG
            elif regime == -1:
                direction = TradeDirection.SHORT
            elif ema_fast_above:
                direction = TradeDirection.LONG
            else:
                direction = TradeDirection.SHORT

        # Gate: ADX chop filter (matches live should_trade — choppy = no trade)
        if not is_trending:
            confidence = 0

        return direction, confidence, " | ".join(reasons) or "Neutral"

    def _signal_claude_edge_indicator(
        self, data: HistoricalDataPoint, symbol: str,
        history: Optional[List[HistoricalDataPoint]] = None,
    ) -> Tuple[TradeDirection, int, str]:
        """
        Claude Edge Indicator: Exact match of live ClaudeEdgeIndicatorStrategy.
        Edge base + 6 enhancements: ATR TP/SL, Volume confirmation,
        HTF proxy (EMA 21/50), RSI divergence, Regime sizing, Trailing stop.
        """
        if not history or len(history) < 30:
            return TradeDirection.LONG, 0, "Insufficient history"

        closes = [h.btc_price if symbol == "BTC" else h.eth_price for h in history]
        highs = [h.btc_high if symbol == "BTC" else h.eth_high for h in history]
        lows = [h.btc_low if symbol == "BTC" else h.eth_low for h in history]
        price = closes[-1]
        reasons = []

        # === BASE LAYERS (same as Edge Indicator) ===

        # Layer 1: EMA Ribbon (8/21)
        ema_fast = _ema(closes, 8)
        ema_slow = _ema(closes, 21)
        ema_f = ema_fast[-1] if ema_fast[-1] != 0 else price
        ema_s = ema_slow[-1] if ema_slow[-1] != 0 else price
        upper_band = max(ema_f, ema_s)
        lower_band = min(ema_f, ema_s)
        ema_fast_above = ema_f > ema_s
        bull_trend = price > upper_band
        bear_trend = price < lower_band

        if bull_trend:
            reasons.append("EMA Bull Trend")
        elif bear_trend:
            reasons.append("EMA Bear Trend")

        # Layer 2: ADX
        adx_val = _adx(highs, lows, closes, 14)
        adx_threshold = 18.0
        is_trending = adx_val >= adx_threshold

        # Layer 3: Predator Momentum
        macd_data = _macd(closes, 12, 26, 9)
        hist_val = macd_data["histogram"]
        hist_series = macd_data["histogram_series"]
        stdev_macd = _stdev(hist_series, min(100, len(hist_series))) if hist_series else 1e-10
        macd_norm = _tanh(hist_val / stdev_macd) if stdev_macd > 1e-10 else 0

        rsi_values = _rsi(closes, 14)
        rsi_smoothed = _ema(rsi_values, 5)
        if len(rsi_smoothed) >= 2 and rsi_smoothed[-1] != 0 and rsi_smoothed[-2] != 0:
            rsi_drift = rsi_smoothed[-1] - rsi_smoothed[-2]
        else:
            rsi_drift = 0.0
        rsi_norm = _tanh(rsi_drift / 2.0)
        trend_bonus = 0.6 if ema_fast_above else -0.6

        raw_score = macd_norm + rsi_norm + trend_bonus
        momentum_score = max(-1.0, min(1.0, raw_score))

        # Score Series & EMA(3) Smoothing
        score_series = self._build_score_series_backtest(closes)
        smooth_len = 3
        if score_series and len(score_series) >= smooth_len:
            smoothed_series = _ema(score_series, smooth_len)
            smoothed_score = smoothed_series[-1] if smoothed_series[-1] != 0 else momentum_score
        else:
            smoothed_score = momentum_score

        pos_thresh, neg_thresh = 0.20, -0.20
        if smoothed_score > pos_thresh:
            regime = 1
        elif smoothed_score < neg_thresh:
            regime = -1
        else:
            regime = 0

        # Regime flip
        prev_regime = 0
        if score_series and len(score_series) >= smooth_len + 1:
            prev_series = score_series[:-1]
            if len(prev_series) >= smooth_len:
                prev_smoothed = _ema(prev_series, smooth_len)
                prev_val = prev_smoothed[-1] if prev_smoothed and prev_smoothed[-1] != 0 else 0.0
                if prev_val > pos_thresh:
                    prev_regime = 1
                elif prev_val < neg_thresh:
                    prev_regime = -1

        regime_flip_bull = regime == 1 and prev_regime != 1
        regime_flip_bear = regime == -1 and prev_regime != -1

        # === CONFIDENCE (base, same as Edge) ===
        confidence = 50

        if is_trending:
            adx_bonus = min(int((adx_val - adx_threshold) * 0.8), 25)
            confidence += adx_bonus
            reasons.append(f"ADX Trending ({adx_val:.0f})")
        else:
            chop_penalty = min(int(adx_threshold - adx_val), 20)
            confidence -= chop_penalty
            reasons.append(f"ADX Choppy ({adx_val:.0f})")

        abs_score = abs(smoothed_score)
        if abs_score > 0.5:
            confidence += 20
        elif abs_score > 0.3:
            confidence += 12
        elif abs_score > 0.15:
            confidence += 5

        if (bull_trend and regime == 1 and is_trending) or \
           (bear_trend and regime == -1 and is_trending):
            confidence += 10

        if regime_flip_bull or regime_flip_bear:
            confidence += 10
            reasons.append("REGIME FLIP")

        # === ENHANCEMENT #2: Volume Confirmation ===
        taker_ratio = data.taker_buy_sell_ratio
        buy_ratio = taker_ratio / (taker_ratio + 1) if taker_ratio > 0 else 0.5
        strong_thresh, weak_thresh = 0.58, 0.42
        if buy_ratio >= strong_thresh:
            vol_score = min((buy_ratio - 0.5) / (strong_thresh - 0.5), 1.0)
        elif buy_ratio <= weak_thresh:
            vol_score = max((buy_ratio - 0.5) / (0.5 - weak_thresh), -1.0)
        else:
            vol_score = (buy_ratio - 0.5) * 2.0

        # Volume confirms or contradicts momentum direction
        if (regime >= 0 and vol_score > 0.3) or (regime <= 0 and vol_score < -0.3):
            vol_bonus = min(int(abs(vol_score) * 10), 8)
            confidence += vol_bonus
            reasons.append(f"Vol Confirms ({vol_score:+.2f})")
        elif (regime > 0 and vol_score < -0.3) or (regime < 0 and vol_score > 0.3):
            confidence -= 3

        # === ENHANCEMENT #3: Multi-Timeframe (sync proxy using EMA 21/50) ===
        if len(closes) >= 50:
            htf_ema_fast = _ema(closes, 21)
            htf_ema_slow = _ema(closes, 50)
            htf_f = htf_ema_fast[-1]
            htf_s = htf_ema_slow[-1]
            if htf_f != 0 and htf_s != 0:
                htf_upper = max(htf_f, htf_s)
                htf_lower = min(htf_f, htf_s)
                htf_bullish = price > htf_upper
                htf_bearish = price < htf_lower
                if (regime >= 0 and htf_bullish) or (regime <= 0 and htf_bearish):
                    confidence += 5
                    reasons.append("HTF Aligned")
                elif (regime > 0 and htf_bearish) or (regime < 0 and htf_bullish):
                    confidence -= 3

        # === ENHANCEMENT #6: RSI Divergence ===
        div_data = _detect_rsi_divergence(closes, rsi_values, 20)
        if div_data["bullish_divergence"] and regime >= 0:
            confidence += 8
            reasons.append("Bullish Divergence")
        elif div_data["bearish_divergence"] and regime <= 0:
            confidence += 8
            reasons.append("Bearish Divergence")
        elif div_data["bearish_divergence"] and regime > 0:
            confidence -= 10
        elif div_data["bullish_divergence"] and regime < 0:
            confidence -= 10

        confidence = max(0, min(95, confidence))

        # === Direction (same as Edge) ===
        if bull_trend and is_trending and smoothed_score >= 0:
            direction = TradeDirection.LONG
        elif bear_trend and is_trending and smoothed_score <= 0:
            direction = TradeDirection.SHORT
        elif is_trending and regime == 1 and not bear_trend:
            direction = TradeDirection.LONG
        elif is_trending and regime == -1 and not bull_trend:
            direction = TradeDirection.SHORT
        else:
            if regime == 1:
                direction = TradeDirection.LONG
            elif regime == -1:
                direction = TradeDirection.SHORT
            elif ema_fast_above:
                direction = TradeDirection.LONG
            else:
                direction = TradeDirection.SHORT

        # Gate: ADX chop filter
        if not is_trending:
            confidence = 0

        # === ENHANCEMENT #1: ATR-based TP/SL ===
        atr_val = _atr(highs, lows, closes, 14)
        if atr_val <= 0:
            atr_val = price * 0.015  # Fallback estimate
        tp_dist = atr_val * 2.5
        sl_dist = atr_val * 1.5
        if direction == TradeDirection.LONG:
            tp_price = price + tp_dist
            sl_price = price - sl_dist
        else:
            tp_price = price - tp_dist
            sl_price = price + sl_dist

        # === ENHANCEMENT #5: Regime-based position sizing ===
        conf_clamped = max(40, min(95, confidence))
        position_scale = round(0.5 + (conf_clamped - 40) / 55.0 * 0.5, 2)

        # === ENHANCEMENT #4: Trailing stop metadata ===
        breakeven_dist = atr_val * 1.0
        trail_dist = atr_val * 1.5
        breakeven_trigger = (price + breakeven_dist) if direction == TradeDirection.LONG else (price - breakeven_dist)

        # Store metadata for engine to use
        self._signal_metadata = {
            "take_profit": round(tp_price, 2),
            "stop_loss": round(sl_price, 2),
            "position_scale": position_scale,
            "trailing_enabled": True,
            "breakeven_trigger": round(breakeven_trigger, 2),
            "trail_distance": round(trail_dist, 2),
        }

        return direction, confidence, " | ".join(reasons) or "Neutral"

    def _signal_degen(
        self, data: HistoricalDataPoint, symbol: str,
        history: Optional[List[HistoricalDataPoint]] = None,
    ) -> Tuple[TradeDirection, int, str]:
        """
        Degen: All-data strategy simulating LLM analysis.
        Uses every available data source + technical indicators from history.
        """
        hist = history or [data]
        score = 0
        reasons = []
        price_change = data.btc_24h_change if symbol == "BTC" else data.eth_24h_change

        # 1. Fear & Greed (contrarian)
        fg = data.fear_greed_index
        if fg < 20:
            score += 20
            reasons.append(f"Extreme Fear ({fg})")
        elif fg < 35:
            score += 10
        elif fg > 80:
            score -= 20
            reasons.append(f"Extreme Greed ({fg})")
        elif fg > 65:
            score -= 10

        # 2. Long/Short Ratio (contrarian)
        ls = data.long_short_ratio
        if ls > 2.5:
            score -= 20
            reasons.append(f"Crowded Longs ({ls:.2f})")
        elif ls > 1.8:
            score -= 10
        elif ls < 0.4:
            score += 20
            reasons.append(f"Crowded Shorts ({ls:.2f})")
        elif ls < 0.6:
            score += 10

        # 3. Funding Rate (contrarian)
        fr = data.funding_rate_btc if symbol == "BTC" else data.funding_rate_eth
        if fr > 0.0008:
            score -= 15
            reasons.append(f"Very High Funding ({fr*100:.4f}%)")
        elif fr > 0.0004:
            score -= 8
        elif fr < -0.0003:
            score += 15
            reasons.append(f"Neg Funding ({fr*100:.4f}%)")
        elif fr < -0.0001:
            score += 8

        # 4. Open Interest trend
        oi_change = data.open_interest_change_24h
        if oi_change > 5 and price_change > 2:
            score -= 8
            reasons.append("OI Rising + Price Up (crowded)")
        elif oi_change > 5 and price_change < -2:
            score += 8
            reasons.append("OI Rising + Price Down (squeeze)")
        elif oi_change < -5:
            score += 5

        # 5. Taker volume
        ratio = data.taker_buy_sell_ratio
        if ratio > 1.3:
            score += 10
            reasons.append(f"Buy Pressure ({ratio:.2f})")
        elif ratio < 0.7:
            score -= 10
            reasons.append(f"Sell Pressure ({ratio:.2f})")

        # 6. Technical: RSI from price history
        if len(hist) >= 20:
            closes = [h.btc_price if symbol == "BTC" else h.eth_price for h in hist]
            rsi_vals = _rsi(closes, 14)
            rsi_now = rsi_vals[-1]
            if rsi_now < 30:
                score += 12
                reasons.append(f"RSI Oversold ({rsi_now:.0f})")
            elif rsi_now > 70:
                score -= 12
                reasons.append(f"RSI Overbought ({rsi_now:.0f})")

            # EMA trend
            ema_f = _ema(closes, 8)
            ema_s = _ema(closes, 21)
            if ema_f[-1] > ema_s[-1] and ema_f[-1] != 0:
                score += 5
            elif ema_f[-1] < ema_s[-1] and ema_f[-1] != 0:
                score -= 5

        # 7. Stablecoin flows
        flow = data.stablecoin_flow_7d
        if flow > 2_000_000_000:
            score += 5
        elif flow < -2_000_000_000:
            score -= 5

        # 8. Volatility
        vol = data.historical_volatility
        if vol > 80:
            score -= 5
        elif vol < 25:
            score += 3

        # 9. Macro (DXY)
        dxy = data.dxy_index
        if dxy > 107:
            score -= 5
            reasons.append(f"Strong USD ({dxy:.1f})")
        elif dxy < 100 and dxy > 0:
            score += 5

        # 10. Funding divergence (Binance vs Bitget)
        if data.funding_rate_bitget != 0:
            spread = abs(fr - data.funding_rate_bitget)
            if spread > 0.0003:
                score += 5 if fr > data.funding_rate_bitget else -5

        confidence = 45 + int(abs(score) * 0.8)
        confidence = max(0, min(95, confidence))

        # Require decent signal strength
        if abs(score) < 15:
            confidence = min(confidence, self.config.low_confidence_min - 1)

        direction = TradeDirection.LONG if score >= 0 else TradeDirection.SHORT
        return direction, confidence, " | ".join(reasons) or f"Degen Score {score:+d}"

    def _signal_llm_signal(
        self, data: HistoricalDataPoint, symbol: str
    ) -> Tuple[TradeDirection, int, str]:
        """
        LLM Signal / AI Companion: Uses degen logic as proxy for LLM analysis.
        """
        return self._signal_degen(data, symbol, history=None)

    # ------------------------------------------------------------------ #
    #  SIGNAL GENERATION (dispatcher)                                     #
    # ------------------------------------------------------------------ #

    def _generate_signal(
        self, data: HistoricalDataPoint, symbol: str = "BTC",
        history: Optional[List[HistoricalDataPoint]] = None,
    ) -> Tuple[TradeDirection, int, str]:
        """Dispatch to strategy-specific signal generation."""
        st = self.config.strategy_type
        if st == "sentiment_surfer":
            return self._signal_sentiment_surfer(data, symbol)
        if st == "llm_signal":
            return self._signal_llm(data, symbol)
        if st == "degen":
            return self._signal_degen(data, symbol)
        # Default: liquidation_hunter (and any unknown type)
        return self._signal_liquidation_hunter(data, symbol, history)

    # ------------------------------------------------------------------ #
    #  Liquidation Hunter — contrarian leverage + sentiment               #
    # ------------------------------------------------------------------ #

    def _signal_liquidation_hunter(
        self, data: HistoricalDataPoint, symbol: str = "BTC",
        history: Optional[List[HistoricalDataPoint]] = None,
    ) -> Tuple[TradeDirection, int, str]:
        """
        Contrarian strategy: bet against crowded positions.

        Primary: L/S Ratio + Fear & Greed (contrarian).
        Secondary: Funding rate, Open Interest.
        Always picks a side — no neutral.
        """
        # Strategies that need full history for indicator calculations
        if self.strategy_type == "edge_indicator":
            return self._signal_edge_indicator(data, symbol, history or [data])
        if self.strategy_type == "claude_edge_indicator":
            return self._signal_claude_edge_indicator(data, symbol, history or [data])
        if self.strategy_type == "sentiment_surfer":
            return self._signal_sentiment_surfer(data, symbol, history or [data])
        if self.strategy_type == "degen":
            return self._signal_degen(data, symbol, history or [data])
        if self.strategy_type == "llm_signal":
            return self._signal_llm_signal(data, symbol)

        # Default: Liquidation Hunter — matches live 3-step logic exactly
        # Live uses ONLY: Leverage + Sentiment + Funding
        # Live thresholds: crowded_longs=2.5, crowded_shorts=0.4,
        #   extreme_fear=20, extreme_greed=80, high_conf=85, low_conf=60
        reasons = []
        confidence = 50

        funding_rate = data.funding_rate_btc if symbol == "BTC" else data.funding_rate_eth
        price_change = data.btc_24h_change if symbol == "BTC" else data.eth_24h_change

        # Step 1: Analyze Leverage — use config values (user-configurable)
        crowded_longs = self.config.long_short_crowded_longs
        crowded_shorts = self.config.long_short_crowded_shorts
        leverage_dir = None

        if data.long_short_ratio > crowded_longs:
            excess = (data.long_short_ratio - crowded_longs) / crowded_longs * 100
            leverage_conf = min(int(excess * 2), 30)
            leverage_dir = TradeDirection.SHORT
            reasons.append(f"Crowded Longs (L/S={data.long_short_ratio:.2f})")
            confidence += leverage_conf
        elif data.long_short_ratio < crowded_shorts:
            excess = (crowded_shorts - data.long_short_ratio) / crowded_shorts * 100
            leverage_conf = min(int(excess * 2), 30)
            leverage_dir = TradeDirection.LONG
            reasons.append(f"Crowded Shorts (L/S={data.long_short_ratio:.2f})")
            confidence += leverage_conf
        else:
            reasons.append(f"L/S Neutral ({data.long_short_ratio:.2f})")

        # Step 2: Analyze Sentiment (live: extreme_fear=20, extreme_greed=80)
        extreme_fear = 20
        extreme_greed = 80
        sentiment_dir = None

        if data.fear_greed_index > extreme_greed:
            excess = data.fear_greed_index - extreme_greed
            sentiment_conf = min(excess, 20)
            sentiment_dir = TradeDirection.SHORT
            reasons.append(f"Extreme Greed (FGI={data.fear_greed_index})")
            confidence += sentiment_conf
        elif data.fear_greed_index < extreme_fear:
            excess = extreme_fear - data.fear_greed_index
            sentiment_conf = min(excess, 20)
            sentiment_dir = TradeDirection.LONG
            reasons.append(f"Extreme Fear (FGI={data.fear_greed_index})")
            confidence += sentiment_conf
        else:
            reasons.append(f"Sentiment Neutral (FGI={data.fear_greed_index})")

        # Step 3: Determine Direction (live: high_confidence_min=85)
        final_direction = None
        high_confidence_min = 85
        low_confidence_min = 60

        if leverage_dir and sentiment_dir:
            if leverage_dir == sentiment_dir:
                final_direction = leverage_dir
                confidence = max(confidence, high_confidence_min)
                reasons.append(f"ALIGNMENT: {leverage_dir.value.upper()}")
            else:
                final_direction = leverage_dir
                confidence = min(confidence, 70)
                reasons.append("CONFLICT: Following Leverage")
        elif leverage_dir:
            final_direction = leverage_dir
        elif sentiment_dir:
            final_direction = sentiment_dir
        else:
            final_direction = TradeDirection.LONG if price_change > 0 else TradeDirection.SHORT
            confidence = max(low_confidence_min, min(confidence, 65))
            reasons.append(f"Trend: {price_change:+.2f}%")

        # Step 4: Funding Rate Adjustment (live: 0.0005 / -0.0002)
        if funding_rate > 0.0005:
            adjustment = 20 if final_direction == TradeDirection.SHORT else -10
            confidence += adjustment
            reasons.append(f"High Funding ({funding_rate*100:.4f}%)")
        elif funding_rate < -0.0002:
            adjustment = 20 if final_direction == TradeDirection.LONG else -10
            confidence += adjustment
            reasons.append(f"Neg Funding ({funding_rate*100:.4f}%)")
        else:
            reasons.append(f"Funding Neutral ({funding_rate*100:.4f}%)")

        # Step 5: Clamp (live: low_confidence_min=60)
        confidence = max(low_confidence_min, min(confidence, 95))

        return final_direction, confidence, " | ".join(reasons)

    # ------------------------------------------------------------------ #
    #  Sentiment Surfer — multi-source voting system                      #
    # ------------------------------------------------------------------ #

    def _signal_sentiment_surfer(
        self, data: HistoricalDataPoint, symbol: str = "BTC"
    ) -> Tuple[TradeDirection, int, str]:
        """
        Balanced strategy with 6-source voting.

        Sources: Sentiment, Leverage, Funding, Taker Volume,
        Stablecoin Flows, Macro (DXY).
        Needs >= 3/6 source agreement to enter.
        """
        funding_rate = data.funding_rate_btc if symbol == "BTC" else data.funding_rate_eth
        price_change = data.btc_24h_change if symbol == "BTC" else data.eth_24h_change

        # Score each source: positive = LONG, negative = SHORT
        scores: List[Tuple[float, float, str]] = []  # (score, weight, label)

        # Source 1: Sentiment (contrarian) — weight 1.0
        fgi = data.fear_greed_index
        if fgi < self.config.fear_greed_extreme_fear:
            scores.append(((self.config.fear_greed_extreme_fear - fgi) * 3, 1.0, f"FGI Bullish ({fgi})"))
        elif fgi > self.config.fear_greed_extreme_greed:
            scores.append((-(fgi - self.config.fear_greed_extreme_greed) * 3, 1.0, f"FGI Bearish ({fgi})"))
        else:
            scores.append((0, 1.0, f"FGI Neutral ({fgi})"))

        # Source 2: Leverage (contrarian) — weight 1.0
        ls = data.long_short_ratio
        if ls > self.config.long_short_crowded_longs:
            scores.append((-(ls - self.config.long_short_crowded_longs) * 40, 1.0, f"L/S Bearish ({ls:.2f})"))
        elif ls < self.config.long_short_crowded_shorts:
            scores.append(((self.config.long_short_crowded_shorts - ls) * 40, 1.0, f"L/S Bullish ({ls:.2f})"))
        else:
            scores.append((0, 1.0, f"L/S Neutral ({ls:.2f})"))

        # Source 3: Funding rate — weight 0.8
        if funding_rate > self.config.funding_rate_high:
            scores.append((-50, 0.8, f"Funding Bearish ({funding_rate*100:.4f}%)"))
        elif funding_rate < self.config.funding_rate_low:
            scores.append((50, 0.8, f"Funding Bullish ({funding_rate*100:.4f}%)"))
        else:
            scores.append((0, 0.8, "Funding Neutral"))

        # Source 4: Taker Buy/Sell Volume — weight 1.2
        ratio = data.taker_buy_sell_ratio
        if ratio > 1.2:
            scores.append((-40, 1.2, f"Taker Sell-bias ({ratio:.2f})"))
        elif ratio < 0.8:
            scores.append((40, 1.2, f"Taker Buy-bias ({ratio:.2f})"))
        else:
            scores.append(((ratio - 1.0) * 100, 1.2, f"Taker ({ratio:.2f})"))

        # Source 5: Stablecoin flows — weight 0.8
        flow = data.stablecoin_flow_7d
        if flow > 1_000_000_000:
            scores.append((30, 0.8, "Stables Inflow"))
        elif flow < -1_000_000_000:
            scores.append((-30, 0.8, "Stables Outflow"))
        else:
            scores.append((0, 0.8, "Stables Neutral"))

        # Source 6: Momentum (price change) — weight 1.2
        if abs(price_change) > 1.0:
            scores.append((price_change * 15, 1.2, f"Momentum {price_change:+.1f}%"))
        else:
            scores.append((0, 1.2, "Momentum Flat"))

        # Voting: count long vs short
        long_votes = sum(1 for s, _, _ in scores if s > 10)
        short_votes = sum(1 for s, _, _ in scores if s < -10)
        min_agreement = 3

        # Weighted score
        total_weight = sum(w for _, w, _ in scores)
        weighted_score = sum(s * w for s, w, _ in scores) / total_weight if total_weight > 0 else 0

        reasons = [label for _, _, label in scores]

        if long_votes >= min_agreement and long_votes > short_votes:
            direction = TradeDirection.LONG
            confidence = min(95, 40 + int(abs(weighted_score) * 0.3) + long_votes * 5)
            reasons.append(f"VOTE: {long_votes}/6 LONG")
        elif short_votes >= min_agreement and short_votes > long_votes:
            direction = TradeDirection.SHORT
            confidence = min(95, 40 + int(abs(weighted_score) * 0.3) + short_votes * 5)
            reasons.append(f"VOTE: {short_votes}/6 SHORT")
        else:
            # No agreement — low confidence fallback
            direction = TradeDirection.LONG if weighted_score > 0 else TradeDirection.SHORT
            confidence = max(30, min(50, 35 + int(abs(weighted_score) * 0.1)))
            reasons.append(f"WEAK: {long_votes}L/{short_votes}S")

        # Volatility risk adjustment
        vol_adj, vol_reason = self._analyze_volatility(data)
        confidence += vol_adj
        if vol_adj != 0:
            reasons.append(vol_reason)

        confidence = max(30, min(confidence, 95))
        return direction, confidence, " | ".join(reasons)

    # ------------------------------------------------------------------ #
    #  LLM Signal — simulated balanced multi-factor analysis              #
    # ------------------------------------------------------------------ #

    def _signal_llm(
        self, data: HistoricalDataPoint, symbol: str = "BTC"
    ) -> Tuple[TradeDirection, int, str]:
        """
        Simulates LLM analysis: balanced, conservative, all-source model.

        Since we can't call an LLM for each historical bar, we simulate
        a balanced multi-factor model that weights ALL available data equally.
        Higher confidence threshold — only trades strong setups.
        """
        funding_rate = data.funding_rate_btc if symbol == "BTC" else data.funding_rate_eth
        price_change = data.btc_24h_change if symbol == "BTC" else data.eth_24h_change

        # Score each factor on a -100 to +100 scale
        factor_scores: List[Tuple[float, str]] = []

        # Factor 1: Sentiment (contrarian)
        fgi = data.fear_greed_index
        if fgi < 20:
            factor_scores.append((80, f"Extreme Fear ({fgi})"))
        elif fgi < 35:
            factor_scores.append((40, f"Fear ({fgi})"))
        elif fgi > 80:
            factor_scores.append((-80, f"Extreme Greed ({fgi})"))
        elif fgi > 65:
            factor_scores.append((-40, f"Greed ({fgi})"))
        else:
            factor_scores.append((0, f"Neutral Sentiment ({fgi})"))

        # Factor 2: Leverage (contrarian)
        ls = data.long_short_ratio
        if ls > 2.0:
            factor_scores.append((-(ls - 1.0) * 30, f"Crowded Longs ({ls:.2f})"))
        elif ls < 0.5:
            factor_scores.append(((1.0 - ls) * 30, f"Crowded Shorts ({ls:.2f})"))
        else:
            factor_scores.append((0, f"L/S Balanced ({ls:.2f})"))

        # Factor 3: Funding rate
        if funding_rate > 0.001:
            factor_scores.append((-60, "Very High Funding"))
        elif funding_rate > self.config.funding_rate_high:
            factor_scores.append((-30, "High Funding"))
        elif funding_rate < -0.0005:
            factor_scores.append((60, "Very Neg Funding"))
        elif funding_rate < self.config.funding_rate_low:
            factor_scores.append((30, "Neg Funding"))
        else:
            factor_scores.append((0, "Funding Neutral"))

        # Factor 4: Open Interest momentum
        oi_change = data.open_interest_change_24h
        if oi_change > 5 and price_change > 0:
            factor_scores.append((-25, "OI+Price Rising (squeeze risk)"))
        elif oi_change > 5 and price_change < 0:
            factor_scores.append((25, "OI Rising+Price Down (capitulation)"))
        elif oi_change < -5:
            factor_scores.append((15 if price_change > 0 else -15, "OI Deleveraging"))
        else:
            factor_scores.append((0, "OI Stable"))

        # Factor 5: Taker Volume
        taker = data.taker_buy_sell_ratio
        if taker > 1.3:
            factor_scores.append((-30, "Heavy Buying (contrarian)"))
        elif taker < 0.7:
            factor_scores.append((30, "Heavy Selling (contrarian)"))
        else:
            factor_scores.append((0, "Volume Balanced"))

        # Factor 6: Top Traders (trend confirmation)
        top_ls = data.top_trader_long_short_ratio
        if top_ls > 1.5:
            factor_scores.append((20, "TopTraders Long"))
        elif top_ls < 0.7:
            factor_scores.append((-20, "TopTraders Short"))
        else:
            factor_scores.append((0, "TopTraders Neutral"))

        # Factor 7: Stablecoin flows
        flow = data.stablecoin_flow_7d
        if flow > 2_000_000_000:
            factor_scores.append((25, "Large Stablecoin Inflow"))
        elif flow < -2_000_000_000:
            factor_scores.append((-25, "Large Stablecoin Outflow"))
        else:
            factor_scores.append((0, "Stables Neutral"))

        # Factor 8: Macro (DXY)
        dxy = data.dxy_index
        if dxy > 107:
            factor_scores.append((-20, "Strong USD"))
        elif dxy > 0 and dxy < 100:
            factor_scores.append((20, "Weak USD"))
        else:
            factor_scores.append((0, "USD Neutral"))

        # Factor 9: Momentum
        if price_change > 3:
            factor_scores.append((-20, f"Overextended Up ({price_change:+.1f}%)"))
        elif price_change < -3:
            factor_scores.append((20, f"Overextended Down ({price_change:+.1f}%)"))
        elif abs(price_change) > 1:
            factor_scores.append((price_change * 5, f"Trend ({price_change:+.1f}%)"))
        else:
            factor_scores.append((0, f"Flat ({price_change:+.1f}%)"))

        # Factor 10: Volatility
        vol = data.historical_volatility
        vol_penalty = 0
        if vol > 100:
            vol_penalty = -15
        elif vol > 70:
            vol_penalty = -8

        # Aggregate: sum of non-zero signals (neutrals don't dilute)
        total_score = sum(s for s, _ in factor_scores) + vol_penalty
        active_count = sum(1 for s, _ in factor_scores if abs(s) > 5)

        reasons = [label for _, label in factor_scores if True]

        if abs(total_score) < 10:
            # Very weak signal — low confidence
            direction = TradeDirection.LONG if total_score >= 0 else TradeDirection.SHORT
            confidence = max(30, 35 + active_count * 3)
            reasons.append(f"LLM: Weak ({total_score:+.0f}, {active_count} active)")
        else:
            direction = TradeDirection.LONG if total_score > 0 else TradeDirection.SHORT
            # Confidence: based on total score + how many factors are active
            confidence = min(90, 40 + int(abs(total_score) * 0.2) + active_count * 4)
            reasons.append(f"LLM Score: {total_score:+.0f} ({active_count} factors)")

        return direction, confidence, " | ".join(reasons)

    # ------------------------------------------------------------------ #
    #  Degen — aggressive trend-following simulated AI                    #
    # ------------------------------------------------------------------ #

    def _signal_degen(
        self, data: HistoricalDataPoint, symbol: str = "BTC"
    ) -> Tuple[TradeDirection, int, str]:
        """
        Aggressive 1h-style signal: trend-following, NOT contrarian.

        Uses taker volume, top traders, and momentum as PRIMARY signals.
        OI and funding as confirmation. Always decisive (no neutral).
        Lower confidence threshold = more trades.
        """
        funding_rate = data.funding_rate_btc if symbol == "BTC" else data.funding_rate_eth
        price_change = data.btc_24h_change if symbol == "BTC" else data.eth_24h_change

        reasons = []
        score = 0  # Positive = LONG, negative = SHORT

        # Primary: Taker Volume (TREND-FOLLOWING, not contrarian)
        taker = data.taker_buy_sell_ratio
        if taker > 1.2:
            score += 35
            reasons.append(f"Buyers Aggressive ({taker:.2f})")
        elif taker < 0.8:
            score -= 35
            reasons.append(f"Sellers Aggressive ({taker:.2f})")
        else:
            diff = (taker - 1.0) * 50
            score += int(diff)
            reasons.append(f"Taker Ratio ({taker:.2f})")

        # Primary: Top Trader positioning (FOLLOW smart money)
        top_ls = data.top_trader_long_short_ratio
        if top_ls > 1.3:
            score += 30
            reasons.append(f"TopTraders LONG ({top_ls:.2f})")
        elif top_ls < 0.7:
            score -= 30
            reasons.append(f"TopTraders SHORT ({top_ls:.2f})")
        else:
            reasons.append(f"TopTraders Neutral ({top_ls:.2f})")

        # Primary: Price Momentum (TREND-FOLLOWING)
        if price_change > 2:
            score += 25
            reasons.append(f"Strong Uptrend ({price_change:+.1f}%)")
        elif price_change < -2:
            score -= 25
            reasons.append(f"Strong Downtrend ({price_change:+.1f}%)")
        elif abs(price_change) > 0.5:
            score += int(price_change * 10)
            reasons.append(f"Trend ({price_change:+.1f}%)")
        else:
            reasons.append(f"Flat ({price_change:+.1f}%)")

        # Secondary: Open Interest confirmation
        oi_change = data.open_interest_change_24h
        if oi_change > 3 and score > 0:
            score += 15
            reasons.append(f"OI Confirms ({oi_change:+.1f}%)")
        elif oi_change > 3 and score < 0:
            score -= 10  # OI rising against our direction = risk
        elif oi_change < -3:
            score += -5 if score > 0 else 5  # Deleveraging reduces conviction
            reasons.append(f"OI Falling ({oi_change:+.1f}%)")

        # Secondary: Funding rate (light contrarian touch)
        if funding_rate > 0.001 and score > 0:
            score -= 10
            reasons.append("High Funding Warning")
        elif funding_rate < -0.0005 and score < 0:
            score += 10
            reasons.append("Neg Funding Warning")

        # Forced decisiveness: ALWAYS pick a direction
        if score > 0:
            direction = TradeDirection.LONG
        elif score < 0:
            direction = TradeDirection.SHORT
        else:
            # Truly neutral → follow last 24h trend
            direction = TradeDirection.LONG if price_change >= 0 else TradeDirection.SHORT
            reasons.append("Coin Flip → Trend")

        # Confidence: aggressive (lower threshold, higher base)
        confidence = min(95, 50 + int(abs(score) * 0.4))

        reasons.append(f"DEGEN Score: {score:+d}")
        return direction, confidence, " | ".join(reasons)

    # ------------------------------------------------------------------ #
    #  POSITION MANAGEMENT                                                #
    # ------------------------------------------------------------------ #

    def _calculate_position_size(self, confidence: int) -> Tuple[float, float]:
        """Calculate position size based on confidence."""
        base_size_pct = self.config.position_size_percent

        if confidence >= 85:
            multiplier = 1.5
        elif confidence >= 75:
            multiplier = 1.25
        elif confidence >= 65:
            multiplier = 1.0
        elif confidence >= 55:
            multiplier = 0.75
        else:
            multiplier = 0.5

        position_pct = min(base_size_pct * multiplier, 25.0)
        position_usdt = self.capital * (position_pct / 100)

        return position_pct, position_usdt

    def _calculate_targets(
        self, direction: TradeDirection, entry_price: float
    ) -> Tuple[float, float]:
        """Calculate take profit and stop loss prices."""
        tp_pct = self.config.take_profit_percent / 100
        sl_pct = self.config.stop_loss_percent / 100

        if direction == TradeDirection.LONG:
            take_profit = entry_price * (1 + tp_pct)
            stop_loss = entry_price * (1 - sl_pct)
        else:
            take_profit = entry_price * (1 - tp_pct)
            stop_loss = entry_price * (1 + sl_pct)

        return take_profit, stop_loss

    def _get_dynamic_loss_limit(self) -> float:
        """Calculate dynamic loss limit (Profit Lock-In feature)."""
        if not self.config.enable_profit_lock:
            return self.config.daily_loss_limit_percent

        daily_return = (self.daily_pnl / self.config.starting_capital) * 100

        if daily_return <= 0:
            return self.config.daily_loss_limit_percent

        locked_profit = daily_return * (self.config.profit_lock_percent / 100)

        # Allow losses only down to the locked profit level
        max_allowed_loss = daily_return - locked_profit
        new_limit = min(self.config.daily_loss_limit_percent, max_allowed_loss)

        return max(new_limit, self.config.min_profit_floor)

    def _can_trade(self) -> Tuple[bool, str]:
        """Check if trading is allowed based on limits."""
        if self.daily_trades_count >= self.config.max_trades_per_day:
            return False, f"Daily trade limit ({self.config.max_trades_per_day})"

        day_start_balance = self.capital - self.daily_pnl
        if day_start_balance > 0:
            daily_return = (self.daily_pnl / day_start_balance) * 100
        else:
            daily_return = 0.0
        loss_limit = self._get_dynamic_loss_limit()

        if daily_return < -loss_limit:
            return False, f"Loss limit ({loss_limit:.2f}%)"

        return True, "OK"

    def _check_exit(
        self, trade: BacktestTrade, current_data: HistoricalDataPoint, next_data: Optional[HistoricalDataPoint]
    ) -> Tuple[bool, TradeResult, float]:
        """Check if a trade should be exited using intraday high/low.

        Conservative approach: if BOTH TP and SL are hit within the
        same candle, assume SL was hit first (worst case).
        """
        if trade.symbol == "BTC":
            high = current_data.btc_high
            low = current_data.btc_low
            close = current_data.btc_price
        else:
            high = current_data.eth_high
            low = current_data.eth_low
            close = current_data.eth_price

        if trade.direction == TradeDirection.LONG:
            tp_hit = high >= trade.take_profit_price
            sl_hit = low <= trade.stop_loss_price
            if tp_hit and sl_hit:
                # Both hit in same candle — conservative: assume SL first
                return True, TradeResult.STOP_LOSS, trade.stop_loss_price
            if tp_hit:
                return True, TradeResult.TAKE_PROFIT, trade.take_profit_price
            if sl_hit:
                return True, TradeResult.STOP_LOSS, trade.stop_loss_price
        else:
            tp_hit = low <= trade.take_profit_price
            sl_hit = high >= trade.stop_loss_price
            if tp_hit and sl_hit:
                return True, TradeResult.STOP_LOSS, trade.stop_loss_price
            if tp_hit:
                return True, TradeResult.TAKE_PROFIT, trade.take_profit_price
            if sl_hit:
                return True, TradeResult.STOP_LOSS, trade.stop_loss_price

        if next_data is None:
            return True, TradeResult.TIME_EXIT, close

        return False, TradeResult.OPEN, 0.0

    def _close_trade(
        self, trade: BacktestTrade, exit_date: str, exit_price: float, result: TradeResult,
        funding_rate: float, exit_candle: Optional[HistoricalDataPoint] = None,
    ):
        """Close a trade and update statistics.

        If self.execution_simulator is set and exit_candle is provided,
        uses the simulator for realistic volatility-based costs.
        Otherwise falls back to the legacy fixed-rate model.
        """
        if trade.entry_price <= 0:
            logger.error(f"Cannot close trade {trade.id}: entry_price is {trade.entry_price}")
            return

        if self.execution_simulator and exit_candle:
            self._close_trade_simulated(trade, exit_date, exit_price, result, funding_rate, exit_candle)
            return

        # --- Legacy cost model (fixed rates) ---
        trade.exit_date = exit_date
        trade.exit_price = exit_price
        trade.result = result

        # Apply slippage: fills are worse than target price
        slip = self.config.slippage_percent / 100
        if trade.direction == TradeDirection.LONG:
            effective_entry = trade.entry_price * (1 + slip)
            effective_exit = exit_price * (1 - slip)
            price_pnl = (effective_exit - effective_entry) / trade.entry_price
        else:
            effective_entry = trade.entry_price * (1 - slip)
            effective_exit = exit_price * (1 + slip)
            price_pnl = (effective_entry - effective_exit) / trade.entry_price

        trade.pnl_percent = price_pnl * 100 * trade.leverage
        trade.pnl = trade.position_value * (price_pnl * trade.leverage)

        trade.fees = trade.position_value * (self.config.trading_fee_percent / 100) * 2

        # Funding: estimate based on holding duration
        # Binance charges 3x/day (every 8h). If trade is open < 8h,
        # there's a chance no funding was paid. For realism, scale by
        # how many 8h periods the trade was open.
        if trade.entry_date and trade.exit_date and trade.entry_date != trade.exit_date:
            # Multi-day hold: full daily funding rate applies
            trade.funding_paid = abs(trade.position_value * funding_rate)
        else:
            # Intraday hold: ~1/3 chance of crossing a funding window
            trade.funding_paid = abs(trade.position_value * funding_rate) * 0.33

        trade.net_pnl = trade.pnl - trade.fees - trade.funding_paid

        self.capital += trade.net_pnl
        self.daily_pnl += trade.net_pnl
        self.daily_closed_count += 1
        self.daily_fees += trade.fees
        self.daily_funding += trade.funding_paid

        if trade.symbol in self.open_positions:
            del self.open_positions[trade.symbol]

        logger.debug(
            f"Closed {trade.direction.value} {trade.symbol} @ ${exit_price:.2f} | "
            f"Result: {result.value} | PnL: ${trade.net_pnl:.2f} ({trade.pnl_percent:+.2f}%)"
        )

    def _close_trade_simulated(
        self, trade: BacktestTrade, exit_date: str, exit_price: float,
        result: TradeResult, funding_rate: float, exit_candle: HistoricalDataPoint,
    ):
        """Close trade using ExecutionSimulator for realistic costs.

        Uses volatility-based slippage, exchange-specific fees,
        and exact 8h funding window counting.
        """
        sim = self.execution_simulator

        # Exit candle volatility: (high - low) / close
        if trade.symbol == "ETH":
            exit_close = exit_candle.eth_price
            exit_range = ((exit_candle.eth_high - exit_candle.eth_low) / exit_close) if exit_close > 0 else 0.0
        else:
            exit_close = exit_candle.btc_price
            exit_range = ((exit_candle.btc_high - exit_candle.btc_low) / exit_close) if exit_close > 0 else 0.0

        exit_is_trigger = result in (TradeResult.TAKE_PROFIT, TradeResult.STOP_LOSS)
        direction = trade.direction.value  # "long" or "short"

        pnl_result = sim.calculate_trade_pnl(
            entry_price=trade.entry_price,
            exit_price=exit_price,
            direction=direction,
            position_value=trade.position_value,
            leverage=trade.leverage,
            funding_rate=funding_rate,
            entry_timestamp=trade.entry_timestamp,
            exit_timestamp=exit_candle.timestamp,
            entry_candle_range=trade.entry_candle_range,
            exit_candle_range=exit_range,
            exit_is_trigger=exit_is_trigger,
        )

        trade.exit_date = exit_date
        trade.exit_price = exit_price
        trade.result = result
        trade.pnl = pnl_result["pnl"]
        trade.pnl_percent = pnl_result["pnl_percent"]
        trade.fees = pnl_result["fees"]
        trade.funding_paid = pnl_result["funding_paid"]
        trade.net_pnl = pnl_result["net_pnl"]

        self.capital += trade.net_pnl
        self.daily_pnl += trade.net_pnl
        self.daily_closed_count += 1
        self.daily_fees += trade.fees
        self.daily_funding += trade.funding_paid

        if trade.symbol in self.open_positions:
            del self.open_positions[trade.symbol]

        logger.debug(
            f"Closed [SIM] {trade.direction.value} {trade.symbol} @ ${exit_price:.2f} | "
            f"Result: {result.value} | PnL: ${trade.net_pnl:.2f} ({trade.pnl_percent:+.2f}%) | "
            f"Fees: ${trade.fees:.2f} | Funding: ${trade.funding_paid:.2f}"
        )

    # ------------------------------------------------------------------ #
    #  BACKTEST EXECUTION                                                 #
    # ------------------------------------------------------------------ #

    def run(self, data_points: List[HistoricalDataPoint]) -> "BacktestResult":
        """Run the backtest over historical data."""
        from src.backtest.report import BacktestResult

        self.reset()

        if not data_points:
            logger.error("No data points provided for backtest")
            return BacktestResult.empty()

        logger.info(f"Starting backtest with ${self.config.starting_capital:,.2f}")
        logger.info(f"Period: {data_points[0].date_str} to {data_points[-1].date_str}")
        logger.info(f"Data points: {len(data_points)}")

        symbols = [self.symbol]

        for i, data in enumerate(data_points):
            if data.date_str != self.current_date:
                if self.current_date:
                    self._save_daily_stats()
                self.current_date = data.date_str
                self.daily_trades_count = 0
                self.daily_pnl = 0.0
                self.daily_closed_count = 0
                self.daily_fees = 0.0
                self.daily_funding = 0.0

            next_data = data_points[i + 1] if i + 1 < len(data_points) else None

            for symbol in list(self.open_positions.keys()):
                trade = self.open_positions[symbol]
                should_exit, result, exit_price = self._check_exit(trade, data, next_data)

                if should_exit:
                    funding_rate = data.funding_rate_btc if symbol == "BTC" else data.funding_rate_eth
                    self._close_trade(trade, data.date_str, exit_price, result, funding_rate)

            can_trade, reason = self._can_trade()
            if not can_trade:
                continue

            for symbol in symbols:
                if symbol in self.open_positions:
                    continue

                if self.daily_trades_count >= self.config.max_trades_per_day:
                    break

                history_slice = data_points[max(0, i - 200):i + 1]
                direction, confidence, reason = self._generate_signal(data, symbol, history=history_slice)
                signal_meta = dict(self._signal_metadata)
                self._signal_metadata = {}

                if confidence < self._get_min_confidence():
                    continue

                # Realistic entry: use NEXT candle's open (not current close)
                # This prevents look-ahead bias — you can't enter at the
                # price used to generate the signal.
                if next_data is not None:
                    entry_price = next_data.btc_open if symbol == "BTC" else next_data.eth_open
                else:
                    entry_price = data.btc_price if symbol == "BTC" else data.eth_price

                if entry_price <= 0:
                    continue

                _, position_usdt = self._calculate_position_size(confidence)

                # Apply strategy-specific position scale (Claude Edge regime sizing)
                if signal_meta.get("position_scale"):
                    position_usdt *= signal_meta["position_scale"]

                if position_usdt < 10:
                    continue

                # Strategy-specific target overrides (Claude Edge ATR-based TP/SL)
                if signal_meta.get("take_profit"):
                    take_profit = signal_meta["take_profit"]
                    stop_loss = signal_meta["stop_loss"]
                else:
                    take_profit, stop_loss = self._calculate_targets(direction, entry_price)

                self.trade_counter += 1
                position_size = (position_usdt * self.config.leverage) / entry_price

                trade = BacktestTrade(
                    id=self.trade_counter,
                    symbol=symbol,
                    direction=direction,
                    entry_date=data.date_str,
                    entry_price=entry_price,
                    position_size=position_size,
                    position_value=position_usdt,
                    leverage=self.config.leverage,
                    confidence=confidence,
                    reason=reason,
                    take_profit_price=take_profit,
                    stop_loss_price=stop_loss,
                )

                self.trades.append(trade)
                self.open_positions[symbol] = trade
                self.daily_trades_count += 1

                logger.debug(
                    f"Opened {direction.value} {symbol} @ ${entry_price:.2f} | "
                    f"Confidence: {confidence}% | TP: ${take_profit:.2f} | SL: ${stop_loss:.2f}"
                )

        # Close remaining open positions at last price
        last_data = data_points[-1]
        for symbol in list(self.open_positions.keys()):
            trade = self.open_positions[symbol]
            exit_price = last_data.btc_price if symbol == "BTC" else last_data.eth_price
            funding_rate = last_data.funding_rate_btc if symbol == "BTC" else last_data.funding_rate_eth
            self._close_trade(trade, last_data.date_str, exit_price, TradeResult.TIME_EXIT, funding_rate)

        self._save_daily_stats()

        return self._generate_result(data_points)

    async def run_unified(
        self,
        data_points: List[HistoricalDataPoint],
        strategy,
        mock_fetcher,
        interval: str = "1h",
    ) -> "BacktestResult":
        """Run backtest using LIVE strategy code with injected historical data.

        Same position management logic as run() (TP/SL, fees, slippage,
        daily limits, next-candle-open entry) but signal generation uses
        the actual strategy's generate_signal() + should_trade() methods.

        Args:
            data_points: Historical data (including warmup buffer)
            strategy: Live strategy instance (e.g. EdgeIndicatorStrategy)
            mock_fetcher: BacktestMarketDataFetcher instance to inject data
        """
        from src.backtest.report import BacktestResult
        from src.strategy.base import SignalDirection

        self.reset()

        if not data_points:
            logger.error("No data points provided for unified backtest")
            return BacktestResult.empty()

        logger.info(f"Starting UNIFIED backtest with ${self.config.starting_capital:,.2f}")
        logger.info(f"Period: {data_points[0].date_str} to {data_points[-1].date_str}")
        logger.info(f"Data points: {len(data_points)}, Strategy: {type(strategy).__name__}")

        symbols = [self.symbol]
        full_symbol = f"{self.symbol}USDT"

        for i, data in enumerate(data_points):
            if data.date_str != self.current_date:
                if self.current_date:
                    self._save_daily_stats()
                self.current_date = data.date_str
                self.daily_trades_count = 0
                self.daily_pnl = 0.0
                self.daily_closed_count = 0
                self.daily_fees = 0.0
                self.daily_funding = 0.0

            next_data = data_points[i + 1] if i + 1 < len(data_points) else None

            # Check exits for open positions (same logic as run())
            for symbol in list(self.open_positions.keys()):
                trade = self.open_positions[symbol]
                should_exit, result, exit_price = self._check_exit(trade, data, next_data)

                if should_exit:
                    funding_rate = data.funding_rate_btc if symbol == "BTC" else data.funding_rate_eth
                    self._close_trade(trade, data.date_str, exit_price, result, funding_rate, exit_candle=data)

            can_trade, reason = self._can_trade()
            if not can_trade:
                continue

            for symbol in symbols:
                if symbol in self.open_positions:
                    continue

                if self.daily_trades_count >= self.config.max_trades_per_day:
                    break

                # Inject historical data into mock fetcher
                history_slice = data_points[max(0, i - 200):i + 1]
                mock_fetcher.set_state(data, history_slice, symbol, interval)

                # Use LIVE strategy code for signal generation
                try:
                    signal = await strategy.generate_signal(full_symbol)
                    should_trade, trade_reason = await strategy.should_trade(signal)
                except Exception as e:
                    logger.debug(f"Signal generation failed at {data.date_str}: {e}")
                    continue

                if not should_trade:
                    continue

                # Map signal direction to engine direction
                if signal.direction == SignalDirection.LONG:
                    direction = TradeDirection.LONG
                else:
                    direction = TradeDirection.SHORT

                confidence = signal.confidence

                # Next-candle-open entry (prevents look-ahead bias)
                if next_data is not None:
                    entry_price = next_data.btc_open if symbol == "BTC" else next_data.eth_open
                else:
                    entry_price = data.btc_price if symbol == "BTC" else data.eth_price

                if entry_price <= 0:
                    continue

                _, position_usdt = self._calculate_position_size(confidence)

                # Use strategy's TP/SL directly (e.g. ATR-based for ClaudeEdge)
                take_profit = signal.target_price
                stop_loss = signal.stop_loss

                # Validate TP/SL — recalculate from entry if strategy returned
                # targets based on signal-time price (not next-candle-open)
                if take_profit > 0 and stop_loss > 0 and signal.entry_price > 0:
                    price_ratio = entry_price / signal.entry_price
                    if abs(price_ratio - 1.0) > 0.001:
                        # Adjust TP/SL proportionally to the actual entry price
                        if direction == TradeDirection.LONG:
                            tp_dist = (take_profit - signal.entry_price) / signal.entry_price
                            sl_dist = (signal.entry_price - stop_loss) / signal.entry_price
                            take_profit = entry_price * (1 + tp_dist)
                            stop_loss = entry_price * (1 - sl_dist)
                        else:
                            tp_dist = (signal.entry_price - take_profit) / signal.entry_price
                            sl_dist = (stop_loss - signal.entry_price) / signal.entry_price
                            take_profit = entry_price * (1 - tp_dist)
                            stop_loss = entry_price * (1 + sl_dist)

                # Fallback: if strategy didn't provide TP/SL, use config defaults
                if take_profit <= 0 or stop_loss <= 0:
                    take_profit, stop_loss = self._calculate_targets(direction, entry_price)

                # Position scale from strategy metadata (if available)
                if hasattr(signal, 'metrics_snapshot') and signal.metrics_snapshot:
                    pos_scale = signal.metrics_snapshot.get("position_scale")
                    if pos_scale:
                        position_usdt *= pos_scale

                if position_usdt < 10:
                    continue

                self.trade_counter += 1
                position_size = (position_usdt * self.config.leverage) / entry_price

                # Compute entry candle volatility for ExecutionSimulator
                entry_candle = next_data if next_data is not None else data
                if symbol == "ETH":
                    _ec = entry_candle.eth_price
                    _entry_range = ((entry_candle.eth_high - entry_candle.eth_low) / _ec) if _ec > 0 else 0.0
                else:
                    _ec = entry_candle.btc_price
                    _entry_range = ((entry_candle.btc_high - entry_candle.btc_low) / _ec) if _ec > 0 else 0.0

                trade = BacktestTrade(
                    id=self.trade_counter,
                    symbol=symbol,
                    direction=direction,
                    entry_date=data.date_str,
                    entry_price=entry_price,
                    position_size=position_size,
                    position_value=position_usdt,
                    leverage=self.config.leverage,
                    confidence=confidence,
                    reason=signal.reason,
                    take_profit_price=take_profit,
                    stop_loss_price=stop_loss,
                    entry_timestamp=entry_candle.timestamp,
                    entry_candle_range=_entry_range,
                )

                self.trades.append(trade)
                self.open_positions[symbol] = trade
                self.daily_trades_count += 1

                logger.debug(
                    f"[UNIFIED] Opened {direction.value} {symbol} @ ${entry_price:.2f} | "
                    f"Confidence: {confidence}% | TP: ${take_profit:.2f} | SL: ${stop_loss:.2f}"
                )

        # Close remaining open positions at last price
        last_data = data_points[-1]
        for symbol in list(self.open_positions.keys()):
            trade = self.open_positions[symbol]
            exit_price = last_data.btc_price if symbol == "BTC" else last_data.eth_price
            funding_rate = last_data.funding_rate_btc if symbol == "BTC" else last_data.funding_rate_eth
            self._close_trade(
                trade, last_data.date_str, exit_price, TradeResult.TIME_EXIT,
                funding_rate, exit_candle=last_data,
            )

        self._save_daily_stats()

        return self._generate_result(data_points)

    def _save_daily_stats(self):
        """Save statistics for the current day."""
        if not self.current_date:
            return

        starting = self.capital - self.daily_pnl
        daily_return = (self.daily_pnl / starting) * 100 if starting > 0 else 0
        cumulative_return = (
            ((self.capital - self.config.starting_capital) / self.config.starting_capital) * 100
            if self.config.starting_capital > 0 else 0
        )

        stats = DailyBacktestStats(
            date=self.current_date,
            starting_balance=starting,
            ending_balance=self.capital,
            trades_opened=self.daily_trades_count,
            trades_closed=self.daily_closed_count,
            daily_pnl=self.daily_pnl,
            daily_fees=self.daily_fees,
            daily_funding=self.daily_funding,
            daily_return_percent=daily_return,
            cumulative_return_percent=cumulative_return,
        )

        self.daily_stats.append(stats)

    def _generate_result(self, data_points: List[HistoricalDataPoint]) -> "BacktestResult":
        """Generate the final backtest result."""
        from src.backtest.report import BacktestResult

        closed_trades = [t for t in self.trades if t.result != TradeResult.OPEN]
        winning_trades = [t for t in closed_trades if t.net_pnl > 0]
        losing_trades = [t for t in closed_trades if t.net_pnl <= 0]

        total_pnl = sum(t.net_pnl for t in closed_trades)
        total_fees = sum(t.fees for t in closed_trades)
        total_funding = sum(t.funding_paid for t in closed_trades)

        peak = self.config.starting_capital
        max_drawdown = 0.0
        equity = self.config.starting_capital

        # Sort by exit date for correct chronological drawdown calculation
        sorted_closed = sorted(closed_trades, key=lambda t: t.exit_date or "")
        for trade in sorted_closed:
            equity += trade.net_pnl
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        monthly_returns = {}
        for stats in self.daily_stats:
            month = stats.date[:7]
            if month not in monthly_returns:
                monthly_returns[month] = 0.0
            monthly_returns[month] += stats.daily_pnl

        avg_win = sum(t.net_pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.net_pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0

        gross_profit = sum(t.net_pnl for t in winning_trades)
        gross_loss = abs(sum(t.net_pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        return BacktestResult(
            start_date=data_points[0].date_str,
            end_date=data_points[-1].date_str,
            starting_capital=self.config.starting_capital,
            ending_capital=self.capital,
            total_return_percent=((self.capital - self.config.starting_capital) / self.config.starting_capital) * 100,
            max_drawdown_percent=max_drawdown,
            total_trades=len(closed_trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=(len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0,
            average_win=avg_win,
            average_loss=avg_loss,
            profit_factor=profit_factor,
            total_pnl=total_pnl,
            total_fees=total_fees,
            total_funding=total_funding,
            monthly_returns=monthly_returns,
            trades=self.trades,
            daily_stats=self.daily_stats,
            config=self.config,
        )
