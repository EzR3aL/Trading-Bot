"""
Edge Indicator Strategy

ROLE: Technical analysis strategy based on the TradingView "Trading Edge" indicator.
Combines three layers for signal generation:

1. EMA Ribbon (8/21) - Trend Direction
   - Bull: price above both EMAs
   - Bear: price below both EMAs
   - Neutral: price between EMAs (inside ribbon)

2. ADX / Chop Filter - Market Quality
   - ADX > threshold = trending market (trade allowed)
   - ADX < threshold = choppy market (no trade)

3. Predator Momentum Score - Timing & Confirmation
   - MACD histogram (12/26/9) normalized via tanh
   - RSI drift (RSI 14, smoothed EMA 5, first derivative) normalized via tanh
   - Trend bonus from EMA ribbon alignment (+/-0.6)
   - Combined into [-1, +1] score, smoothed with EMA
   - Regime detection: bull (>0.20), bear (<-0.20), neutral

DECISION:
- LONG: bullTrend + ADX trending + momentum regime bullish
- SHORT: bearTrend + ADX trending + momentum regime bearish
- NO TRADE: neutral trend OR choppy market

DATA SOURCE: Only Binance kline data (OHLCV) - single dependency, high reliability.
"""

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.data.market_data import MarketDataFetcher
from src.strategy.base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default parameter values
DEFAULTS = {
    # EMA Ribbon
    "ema_fast_period": 8,
    "ema_slow_period": 21,
    # ADX / Chop Filter
    "adx_period": 14,
    "adx_chop_threshold": 18.0,
    "use_adx_filter": True,
    # MACD
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    # RSI
    "rsi_period": 14,
    "rsi_smooth_period": 5,
    # Momentum Score (v2: relaxed thresholds for fewer premature exits)
    "momentum_smooth_period": 5,
    "momentum_bull_threshold": 0.35,
    "momentum_bear_threshold": -0.35,
    # Trade filters
    "min_confidence": 65,
    # ATR (for trailing stop)
    "atr_period": 14,
    # Trailing stop
    "trailing_stop_enabled": True,
    "trailing_breakeven_atr": 1.5,
    "trailing_trail_atr": 2.5,
    # Default SL safety net (optional, 0 = disabled)
    "default_sl_atr": 0,
    # MACD Floor (v2)
    "use_macd_floor": True,
    # Data
    "kline_interval": "1h",
    "kline_count": 200,
}


def _tanh(x: float) -> float:
    """Hyperbolic tangent, matching the Pine Script implementation."""
    try:
        e2x = math.exp(2 * x)
        return (e2x - 1) / (e2x + 1)
    except OverflowError:
        return 1.0 if x > 0 else -1.0


def _stdev(values: List[float], period: int) -> float:
    """Calculate rolling standard deviation of the last `period` values."""
    if not values or len(values) < period:
        return 1e-10
    window = values[-period:]
    mean = sum(window) / len(window)
    variance = sum((v - mean) ** 2 for v in window) / len(window)
    return max(math.sqrt(variance), 1e-10)


class EdgeIndicatorStrategy(BaseStrategy):
    """
    Technical analysis strategy based on the TradingView 'Trading Edge' indicator.

    Uses EMA Ribbon for trend, ADX for chop filtering, and a composite
    Predator Momentum score (MACD + RSI Drift + Trend Bonus) for signal timing.
    """

    def __init__(
        self,
        params: Optional[Dict[str, Any]] = None,
        data_fetcher: Optional[MarketDataFetcher] = None,
    ):
        super().__init__(params)
        self.data_fetcher = data_fetcher
        self._p = {**DEFAULTS, **self.params}

    async def _ensure_fetcher(self):
        """Ensure data fetcher is available."""
        if self.data_fetcher is None:
            self.data_fetcher = MarketDataFetcher()
            await self.data_fetcher._ensure_session()

    # ==================== Indicator Calculations ====================

    def _calculate_ema_ribbon(
        self, closes: List[float]
    ) -> Dict[str, Any]:
        """
        Calculate EMA 8/21 ribbon and determine trend.

        Returns:
            {
                "ema_fast": List[float], "ema_slow": List[float],
                "bull_trend": bool, "bear_trend": bool, "neutral": bool,
                "bull_enter": bool, "bear_enter": bool,
                "ema_fast_above": bool
            }
        """
        fast_period = self._p["ema_fast_period"]
        slow_period = self._p["ema_slow_period"]

        ema_fast = MarketDataFetcher.calculate_ema(closes, fast_period)
        ema_slow = MarketDataFetcher.calculate_ema(closes, slow_period)

        if not ema_fast or not ema_slow or ema_fast[-1] == 0 or ema_slow[-1] == 0:
            return {
                "ema_fast": ema_fast, "ema_slow": ema_slow,
                "bull_trend": False, "bear_trend": False, "neutral": True,
                "bull_enter": False, "bear_enter": False,
                "ema_fast_above": False,
            }

        current_close = closes[-1]
        upper = max(ema_fast[-1], ema_slow[-1])
        lower = min(ema_fast[-1], ema_slow[-1])

        bull_trend = current_close > upper
        bear_trend = current_close < lower
        neutral = not bull_trend and not bear_trend

        prev_close = closes[-2] if len(closes) >= 2 else current_close
        prev_upper = max(ema_fast[-2], ema_slow[-2]) if len(ema_fast) >= 2 and ema_fast[-2] != 0 else upper
        prev_lower = min(ema_fast[-2], ema_slow[-2]) if len(ema_fast) >= 2 and ema_fast[-2] != 0 else lower

        bull_enter = current_close > upper and prev_close <= prev_upper
        bear_enter = current_close < lower and prev_close >= prev_lower

        return {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "bull_trend": bull_trend,
            "bear_trend": bear_trend,
            "neutral": neutral,
            "bull_enter": bull_enter,
            "bear_enter": bear_enter,
            "ema_fast_above": ema_fast[-1] > ema_slow[-1],
        }

    def _calculate_predator_momentum(
        self, closes: List[float], klines: List[List], ema_fast_above: bool
    ) -> Dict[str, Any]:
        """
        Calculate the Predator Momentum composite score.

        Components:
        1. MACD Histogram normalized via tanh
        2. RSI Drift (first derivative of smoothed RSI) normalized via tanh
        3. Trend bonus from EMA ribbon
        """
        macd_fast = self._p["macd_fast"]
        macd_slow = self._p["macd_slow"]
        macd_signal = self._p["macd_signal"]
        rsi_period = self._p["rsi_period"]
        rsi_smooth_period = self._p["rsi_smooth_period"]
        smooth_len = self._p["momentum_smooth_period"]
        pos_thresh = self._p["momentum_bull_threshold"]
        neg_thresh = self._p["momentum_bear_threshold"]

        macd_data = MarketDataFetcher.calculate_macd(klines, macd_fast, macd_slow, macd_signal)
        macd_hist = macd_data["histogram"]
        histogram_series = macd_data["histogram_series"]

        stdev_macd = _stdev(histogram_series, min(100, len(histogram_series))) if histogram_series else 1e-10
        if self._p.get("use_macd_floor", True):
            atr_series_pm = MarketDataFetcher.calculate_atr(klines, self._p["atr_period"])
            atr_val_pm = atr_series_pm[-1] if atr_series_pm else closes[-1] * 0.015
            stdev_macd = max(stdev_macd, atr_val_pm * 0.01)
        macd_norm = _tanh(macd_hist / stdev_macd)

        rsi_values = MarketDataFetcher.calculate_rsi(klines, rsi_period)
        rsi_smoothed = MarketDataFetcher.calculate_ema(rsi_values, rsi_smooth_period)

        if len(rsi_smoothed) >= 2 and rsi_smoothed[-1] != 0 and rsi_smoothed[-2] != 0:
            rsi_drift = rsi_smoothed[-1] - rsi_smoothed[-2]
        else:
            rsi_drift = 0.0

        rsi_norm = _tanh(rsi_drift / 2.0)
        trend_bonus = 0.6 if ema_fast_above else -0.6

        raw_score = macd_norm + rsi_norm + trend_bonus
        score = max(-1.0, min(1.0, raw_score))

        smoothed_score = score

        score_series = self._build_score_series(
            klines, closes, macd_fast, macd_slow, macd_signal,
            rsi_period, rsi_smooth_period, ema_fast_above
        )

        if score_series and len(score_series) >= smooth_len:
            smoothed_series = MarketDataFetcher.calculate_ema(score_series, smooth_len)
            smoothed_score = smoothed_series[-1] if smoothed_series[-1] != 0 else score
        else:
            smoothed_score = score

        if smoothed_score > pos_thresh:
            regime = 1
        elif smoothed_score < neg_thresh:
            regime = -1
        else:
            regime = 0

        prev_regime = self._get_previous_regime(score_series, smooth_len, pos_thresh, neg_thresh)

        regime_flip_bull = regime == 1 and prev_regime != 1
        regime_flip_bear = regime == -1 and prev_regime != -1

        return {
            "score": round(score, 4),
            "smoothed_score": round(smoothed_score, 4),
            "regime": regime,
            "regime_flip_bull": regime_flip_bull,
            "regime_flip_bear": regime_flip_bear,
            "macd_norm": round(macd_norm, 4),
            "rsi_norm": round(rsi_norm, 4),
            "trend_bonus": trend_bonus,
        }

    def _build_score_series(
        self, klines: List[List], closes: List[float],
        macd_fast: int, macd_slow: int, macd_signal: int,
        rsi_period: int, rsi_smooth_period: int, ema_fast_above: bool
    ) -> List[float]:
        """Build the full momentum score series for smoothing."""
        if len(klines) < macd_slow + macd_signal + 10:
            return []

        macd_data = MarketDataFetcher.calculate_macd(klines, macd_fast, macd_slow, macd_signal)
        hist_series = macd_data["histogram_series"]

        rsi_values = MarketDataFetcher.calculate_rsi(klines, rsi_period)
        rsi_smoothed = MarketDataFetcher.calculate_ema(rsi_values, rsi_smooth_period)

        fast_period = self._p["ema_fast_period"]
        slow_period = self._p["ema_slow_period"]
        ema_fast = MarketDataFetcher.calculate_ema(closes, fast_period)
        ema_slow = MarketDataFetcher.calculate_ema(closes, slow_period)

        min_len = min(len(hist_series), len(rsi_smoothed) - 1, len(ema_fast), len(ema_slow))
        if min_len <= 1:
            return []

        # MACD Floor for _build_score_series
        atr_floor = 0.0
        if self._p.get("use_macd_floor", True):
            atr_series_bs = MarketDataFetcher.calculate_atr(klines, self._p["atr_period"])
            atr_floor = (atr_series_bs[-1] if atr_series_bs else closes[-1] * 0.015) * 0.01

        scores = []
        for i in range(1, min_len):
            hist_val = hist_series[i] if i < len(hist_series) else 0.0
            hist_window = hist_series[max(0, i - 99):i + 1]
            sd = _stdev(hist_window, min(100, len(hist_window)))
            if atr_floor > 0:
                sd = max(sd, atr_floor)
            m_norm = _tanh(hist_val / sd)

            rsi_idx = len(rsi_smoothed) - min_len + i
            rsi_prev_idx = rsi_idx - 1
            if rsi_idx < len(rsi_smoothed) and rsi_prev_idx >= 0:
                drift = rsi_smoothed[rsi_idx] - rsi_smoothed[rsi_prev_idx]
            else:
                drift = 0.0
            r_norm = _tanh(drift / 2.0)

            ema_f_idx = len(ema_fast) - min_len + i
            ema_s_idx = len(ema_slow) - min_len + i
            if ema_f_idx < len(ema_fast) and ema_s_idx < len(ema_slow):
                t_bonus = 0.6 if ema_fast[ema_f_idx] > ema_slow[ema_s_idx] else -0.6
            else:
                t_bonus = 0.0

            raw = m_norm + r_norm + t_bonus
            scores.append(max(-1.0, min(1.0, raw)))

        return scores

    def _get_previous_regime(
        self, score_series: List[float], smooth_len: int,
        pos_thresh: float, neg_thresh: float
    ) -> int:
        """Get the regime from the previous bar for flip detection."""
        if not score_series or len(score_series) < smooth_len + 1:
            return 0

        prev_series = score_series[:-1]
        if len(prev_series) < smooth_len:
            return 0

        smoothed = MarketDataFetcher.calculate_ema(prev_series, smooth_len)
        prev_smoothed = smoothed[-1] if smoothed and smoothed[-1] != 0 else 0.0

        if prev_smoothed > pos_thresh:
            return 1
        elif prev_smoothed < neg_thresh:
            return -1
        return 0

    # ==================== Confidence Calculation ====================

    def _calculate_confidence(
        self,
        adx_data: Dict[str, Any],
        momentum: Dict[str, Any],
        ribbon: Dict[str, Any],
    ) -> int:
        """
        Calculate trade confidence from indicator strength.

        Base: 50
        + ADX strength bonus (0-25)
        + Momentum magnitude bonus (0-20)
        + Full alignment bonus (0-10)
        + Regime flip bonus (0-10)
        - Chop penalty (0-20)
        """
        confidence = 50

        adx = adx_data.get("adx", 0)
        chop_threshold = self._p["adx_chop_threshold"]
        use_adx = self._p["use_adx_filter"]

        if use_adx and adx > chop_threshold:
            excess = adx - chop_threshold
            confidence += min(int(excess * 0.8), 25)
        elif use_adx and adx < chop_threshold:
            deficit = chop_threshold - adx
            confidence -= min(int(deficit), 20)

        abs_score = abs(momentum.get("smoothed_score", 0))
        if abs_score > 0.5:
            confidence += 20
        elif abs_score > 0.3:
            confidence += 12
        elif abs_score > 0.15:
            confidence += 5

        is_bull_aligned = (
            ribbon.get("bull_trend", False)
            and momentum.get("regime", 0) == 1
            and (not use_adx or adx > chop_threshold)
        )
        is_bear_aligned = (
            ribbon.get("bear_trend", False)
            and momentum.get("regime", 0) == -1
            and (not use_adx or adx > chop_threshold)
        )
        if is_bull_aligned or is_bear_aligned:
            confidence += 10

        if momentum.get("regime_flip_bull") or momentum.get("regime_flip_bear"):
            confidence += 10

        return max(0, min(confidence, 95))

    # ==================== Signal Generation ====================

    def _determine_direction(
        self, ribbon: Dict[str, Any], momentum: Dict[str, Any], adx_data: Dict[str, Any]
    ) -> Tuple[SignalDirection, str]:
        """Determine trade direction from combined indicator layers."""
        use_adx = self._p["use_adx_filter"]
        adx = adx_data.get("adx", 0)
        chop_threshold = self._p["adx_chop_threshold"]
        trend_ok = not use_adx or adx >= chop_threshold

        reasons = []

        if ribbon["bull_trend"]:
            reasons.append("EMA Ribbon: BULL (price > upper band)")
        elif ribbon["bear_trend"]:
            reasons.append("EMA Ribbon: BEAR (price < lower band)")
        else:
            reasons.append("EMA Ribbon: NEUTRAL (inside band)")

        if use_adx:
            if adx >= chop_threshold:
                reasons.append(f"ADX: TRENDING ({adx:.1f} > {chop_threshold})")
            else:
                reasons.append(f"ADX: CHOPPY ({adx:.1f} < {chop_threshold})")

        regime = momentum.get("regime", 0)
        score = momentum.get("smoothed_score", 0)
        if regime == 1:
            reasons.append(f"Momentum: BULL (score={score:.2f})")
        elif regime == -1:
            reasons.append(f"Momentum: BEAR (score={score:.2f})")
        else:
            reasons.append(f"Momentum: NEUTRAL (score={score:.2f})")

        if momentum.get("regime_flip_bull"):
            reasons.append("REGIME FLIP: -> BULL")
        elif momentum.get("regime_flip_bear"):
            reasons.append("REGIME FLIP: -> BEAR")

        if ribbon["bull_trend"] and trend_ok and regime >= 0:
            return SignalDirection.LONG, " | ".join(reasons)
        elif ribbon["bear_trend"] and trend_ok and regime <= 0:
            return SignalDirection.SHORT, " | ".join(reasons)
        elif trend_ok and regime == 1 and not ribbon["bear_trend"]:
            return SignalDirection.LONG, " | ".join(reasons)
        elif trend_ok and regime == -1 and not ribbon["bull_trend"]:
            return SignalDirection.SHORT, " | ".join(reasons)
        else:
            if regime == 1:
                return SignalDirection.LONG, " | ".join(reasons)
            elif regime == -1:
                return SignalDirection.SHORT, " | ".join(reasons)
            if ribbon.get("ema_fast_above"):
                return SignalDirection.LONG, " | ".join(reasons)
            return SignalDirection.SHORT, " | ".join(reasons)

    def _calculate_targets(
        self, direction: SignalDirection, current_price: float,
        klines: Optional[List[List]] = None,
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate TP/SL prices.

        SL priority: stop_loss_percent > default_sl_atr (2x ATR) > None
        TP: only from take_profit_percent (user-configured).
        """
        tp_pct_raw = self._p.get("take_profit_percent")
        sl_pct_raw = self._p.get("stop_loss_percent")
        default_sl = self._p.get("default_sl_atr", 2.0)

        take_profit = None
        stop_loss = None

        if tp_pct_raw is not None and current_price > 0:
            tp_pct = float(tp_pct_raw) / 100
            if direction == SignalDirection.LONG:
                take_profit = round(current_price * (1 + tp_pct), 2)
            else:
                take_profit = round(current_price * (1 - tp_pct), 2)

        if sl_pct_raw is not None and current_price > 0:
            # User-configured percent SL takes priority
            sl_pct = float(sl_pct_raw) / 100
            if direction == SignalDirection.LONG:
                stop_loss = round(current_price * (1 - sl_pct), 2)
            else:
                stop_loss = round(current_price * (1 + sl_pct), 2)
        elif default_sl > 0 and current_price > 0:
            # Default SL safety net: 2x ATR
            atr_value = 0.0
            if klines:
                atr_series = MarketDataFetcher.calculate_atr(
                    klines, self._p["atr_period"]
                )
                if atr_series:
                    atr_value = atr_series[-1]
            if atr_value <= 0:
                atr_value = current_price * 0.015
            sl_distance = atr_value * float(default_sl)
            if direction == SignalDirection.LONG:
                stop_loss = round(current_price - sl_distance, 2)
            else:
                stop_loss = round(current_price + sl_distance, 2)

        return take_profit, stop_loss


    # ==================== Exit Signal Logic ====================

    async def should_exit(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        metrics_at_entry: dict | None = None,
        current_price: float | None = None,
        highest_price: float | None = None,
        **kwargs,
    ) -> Tuple[bool, str]:
        """Check if an open position should be closed.

        Uses a two-layer exit system:
        1. ATR Trailing Stop + Breakeven protection (price-based)
        2. Indicator exits: EMA ribbon + momentum regime (signal-based)
        """
        try:
            await self._ensure_fetcher()

            interval = self._p["kline_interval"]
            count = self._p["kline_count"]
            klines = await self.data_fetcher.get_binance_klines(symbol, interval, count)

            if not klines or len(klines) < self._p["ema_slow_period"] + 10:
                return False, "Insufficient data for exit check"

            closes = []
            for k in klines:
                try:
                    closes.append(float(k[4]))
                except (IndexError, ValueError, TypeError):
                    continue

            if not closes:
                return False, "No valid close prices"

            if current_price is None:
                current_price = closes[-1]

            # --- Layer 1: ATR Trailing Stop + Breakeven ---
            if self._p.get("trailing_stop_enabled") and highest_price and entry_price:
                trail_exit, trail_reason = self._check_trailing_stop(
                    side, entry_price, current_price, highest_price, klines,
                )
                if trail_exit:
                    return True, trail_reason

            # --- Layer 2: Indicator-based exits ---
            ribbon = self._calculate_ema_ribbon(closes)
            momentum = self._calculate_predator_momentum(closes, klines, ribbon["ema_fast_above"])
            regime = momentum.get("regime", 0)

            indicator_exit = False
            indicator_reason = ""

            if side == "long":
                if ribbon["bear_trend"]:
                    indicator_exit = True
                    indicator_reason = (
                        "Trend reversal: Preis unter EMA-Ribbon (bearTrend). "
                        "Momentum=%.2f" % momentum['smoothed_score']
                    )
                elif ribbon["neutral"] and regime == -1:
                    indicator_exit = True
                    indicator_reason = (
                        "Trend schwaecht sich ab: Preis im Ribbon + baerisches Momentum "
                        "(score=%.2f)" % momentum['smoothed_score']
                    )
                elif momentum.get("regime_flip_bear", False):
                    indicator_exit = True
                    indicator_reason = (
                        "Regime-Flip: Momentum dreht bearish "
                        "(score=%.2f)" % momentum['smoothed_score']
                    )

            elif side == "short":
                if ribbon["bull_trend"]:
                    indicator_exit = True
                    indicator_reason = (
                        "Trend reversal: Preis ueber EMA-Ribbon (bullTrend). "
                        "Momentum=%.2f" % momentum['smoothed_score']
                    )
                elif ribbon["neutral"] and regime == 1:
                    indicator_exit = True
                    indicator_reason = (
                        "Trend schwaecht sich ab: Preis im Ribbon + bullisches Momentum "
                        "(score=%.2f)" % momentum['smoothed_score']
                    )
                elif momentum.get("regime_flip_bull", False):
                    indicator_exit = True
                    indicator_reason = (
                        "Regime-Flip: Momentum dreht bullish "
                        "(score=%.2f)" % momentum['smoothed_score']
                    )

            if indicator_exit:
                # Breakeven protection: if trade was profitable enough, don't exit at a loss
                if self._p.get("trailing_stop_enabled") and highest_price and entry_price:
                    breakeven_atr = self._p.get("trailing_breakeven_atr", 1.5)
                    atr_series = MarketDataFetcher.calculate_atr(klines, self._p["atr_period"])
                    atr_val = atr_series[-1] if atr_series else current_price * 0.015
                    breakeven_threshold = atr_val * breakeven_atr

                    if side == "long":
                        was_profitable = (highest_price - entry_price) >= breakeven_threshold
                        is_loss = current_price < entry_price
                    else:
                        was_profitable = (entry_price - highest_price) >= breakeven_threshold
                        is_loss = current_price > entry_price

                    if was_profitable and is_loss:
                        logger.info(
                            "Breakeven protection: blocking indicator exit at loss "
                            "(entry=%.2f, current=%.2f, highest=%.2f)",
                            entry_price, current_price, highest_price,
                        )
                        return False, ""

                return True, indicator_reason

            return False, ""

        except Exception as e:
            logger.error("Exit check error for %s: %s", symbol, e)
            return False, ""

    def _check_trailing_stop(
        self,
        side: str,
        entry_price: float,
        current_price: float,
        highest_price: float,
        klines: List[List],
    ) -> Tuple[bool, str]:
        """Check ATR-based trailing stop with breakeven floor."""
        atr_series = MarketDataFetcher.calculate_atr(klines, self._p["atr_period"])
        atr_val = atr_series[-1] if atr_series else current_price * 0.015

        breakeven_atr = self._p.get("trailing_breakeven_atr", 1.5)
        trail_atr = self._p.get("trailing_trail_atr", 2.5)
        trail_distance = atr_val * trail_atr
        breakeven_threshold = atr_val * breakeven_atr

        if side == "long":
            was_profitable = (highest_price - entry_price) >= breakeven_threshold
            if not was_profitable:
                return False, ""

            trailing_stop = highest_price - trail_distance
            trailing_stop = max(trailing_stop, entry_price)

            if current_price <= trailing_stop:
                pnl_pct = (current_price - entry_price) / entry_price * 100
                return True, (
                    "Trailing Stop: Preis $%.2f unter Stop $%.2f "
                    "(Hoechst=$%.2f, ATR=%.0f, Trail=%.1fx). PnL=%.2f%%"
                    % (current_price, trailing_stop, highest_price, atr_val, trail_atr, pnl_pct)
                )
        else:
            was_profitable = (entry_price - highest_price) >= breakeven_threshold
            if not was_profitable:
                return False, ""

            trailing_stop = highest_price + trail_distance
            trailing_stop = min(trailing_stop, entry_price)

            if current_price >= trailing_stop:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                return True, (
                    "Trailing Stop: Preis $%.2f ueber Stop $%.2f "
                    "(Tiefst=$%.2f, ATR=%.0f, Trail=%.1fx). PnL=%.2f%%"
                    % (current_price, trailing_stop, highest_price, atr_val, trail_atr, pnl_pct)
                )

        return False, ""

    async def generate_signal(self, symbol: str = "BTCUSDT") -> TradeSignal:
        """Generate a trade signal using the Edge Indicator layers."""
        await self._ensure_fetcher()

        logger.info(f"=== EdgeIndicator: Generating Signal for {symbol} ===")

        interval = self._p["kline_interval"]
        count = self._p["kline_count"]

        klines = await self.data_fetcher.get_binance_klines(symbol, interval, count)

        if not klines or len(klines) < self._p["ema_slow_period"] + 10:
            logger.error(f"Insufficient kline data: {len(klines) if klines else 0} candles")
            return TradeSignal(
                direction=SignalDirection.LONG, confidence=0, symbol=symbol,
                entry_price=0.0, target_price=0.0, stop_loss=0.0,
                reason="Insufficient kline data",
                metrics_snapshot={"error": "insufficient_data"},
                timestamp=datetime.now(),
            )

        closes = []
        for k in klines:
            try:
                closes.append(float(k[4]))
            except (IndexError, ValueError, TypeError):
                continue

        current_price = closes[-1] if closes else 0.0

        if current_price <= 0:
            logger.error(f"Invalid price for {symbol}: {current_price}")
            return TradeSignal(
                direction=SignalDirection.LONG, confidence=0, symbol=symbol,
                entry_price=0.0, target_price=0.0, stop_loss=0.0,
                reason="Invalid price data",
                metrics_snapshot={"error": "invalid_price"},
                timestamp=datetime.now(),
            )

        ribbon = self._calculate_ema_ribbon(closes)
        adx_data = MarketDataFetcher.calculate_adx(klines, self._p["adx_period"])
        momentum = self._calculate_predator_momentum(closes, klines, ribbon["ema_fast_above"])

        direction, reason = self._determine_direction(ribbon, momentum, adx_data)
        confidence = self._calculate_confidence(adx_data, momentum, ribbon)
        take_profit, stop_loss = self._calculate_targets(direction, current_price)

        snapshot = {
            "ema_fast": round(ribbon["ema_fast"][-1], 2) if ribbon["ema_fast"] else 0,
            "ema_slow": round(ribbon["ema_slow"][-1], 2) if ribbon["ema_slow"] else 0,
            "bull_trend": ribbon["bull_trend"],
            "bear_trend": ribbon["bear_trend"],
            "neutral": ribbon["neutral"],
            "bull_enter": ribbon["bull_enter"],
            "bear_enter": ribbon["bear_enter"],
            "adx": adx_data["adx"],
            "plus_di": adx_data["plus_di"],
            "minus_di": adx_data["minus_di"],
            "is_choppy": adx_data["adx"] < self._p["adx_chop_threshold"],
            "momentum_score": momentum["score"],
            "momentum_smoothed": momentum["smoothed_score"],
            "momentum_regime": momentum["regime"],
            "regime_flip_bull": momentum["regime_flip_bull"],
            "regime_flip_bear": momentum["regime_flip_bear"],
            "macd_norm": momentum["macd_norm"],
            "rsi_norm": momentum["rsi_norm"],
            "trend_bonus": momentum["trend_bonus"],
            "kline_interval": interval,
            "kline_count": len(klines),
        }

        signal = TradeSignal(
            direction=direction, confidence=confidence, symbol=symbol,
            entry_price=current_price, target_price=take_profit, stop_loss=stop_loss,
            reason=f"[Edge] {reason}", metrics_snapshot=snapshot,
            timestamp=datetime.now(),
        )

        logger.info(
            f"=== SIGNAL: {signal.direction.value.upper()} {signal.confidence}% "
            f"@ ${signal.entry_price:,.2f} ==="
        )

        return signal

    async def should_trade(self, signal: TradeSignal) -> Tuple[bool, str]:
        """Gate: check confidence, price validity, and chop filter."""
        min_confidence = self._p["min_confidence"]

        if signal.entry_price <= 0:
            return False, "Invalid entry price"

        is_choppy = signal.metrics_snapshot.get("is_choppy", False)
        if is_choppy and self._p["use_adx_filter"]:
            adx = signal.metrics_snapshot.get("adx", 0)
            return False, (
                f"Market is choppy (ADX={adx:.1f} < {self._p['adx_chop_threshold']})"
            )

        if signal.confidence < min_confidence:
            return False, (
                f"Confidence ({signal.confidence}%) below minimum ({min_confidence}%)"
            )

        return True, (
            f"Signal approved: {signal.confidence}% confidence, "
            f"ADX={signal.metrics_snapshot.get('adx', 0):.1f}"
        )

    @classmethod
    def get_description(cls) -> str:
        return (
            "Technical analysis strategy based on the TradingView 'Trading Edge' indicator. "
            "Combines EMA 8/21 Ribbon for trend direction, ADX for chop filtering, "
            "and a Predator Momentum score (MACD + RSI Drift + Trend Bonus) for timing. "
            "v2: Optimized exit thresholds let profitable trades run longer. "
            "Best on 1h and 4h. Only requires kline data - no external API dependencies."
        )

    @classmethod
    def get_param_schema(cls) -> Dict[str, Any]:
        return {
            "ema_fast_period": {
                "type": "int", "label": "EMA Schnell-Periode",
                "description": "Schnelle EMA-Periode für das Trend-Ribbon (Standard 8)",
                "default": 8, "min": 2, "max": 200,
            },
            "ema_slow_period": {
                "type": "int", "label": "EMA Langsam-Periode",
                "description": "Langsame EMA-Periode für das Trend-Ribbon (Standard 21)",
                "default": 21, "min": 5, "max": 400,
            },
            "adx_period": {
                "type": "int", "label": "ADX Periode",
                "description": "Berechnungsperiode für den ADX-Indikator (Standard 14)",
                "default": 14, "min": 2, "max": 100,
            },
            "adx_chop_threshold": {
                "type": "float", "label": "ADX Chop-Schwelle",
                "description": "ADX unter diesem Wert = seitwärts, kein Trading (Standard 18)",
                "default": 18.0, "min": 5.0, "max": 50.0,
            },
            "use_adx_filter": {
                "type": "bool", "label": "ADX Filter aktiv",
                "description": "ADX-basierten Chop-Filter aktivieren um Seitwärtsmärkte zu meiden",
                "default": True,
            },
            "momentum_bull_threshold": {
                "type": "float", "label": "Momentum Bull-Schwelle",
                "description": "Momentum-Score ueber diesem Wert = bullisches Regime. Hoeher = weniger Fehl-Exits, Trades laufen laenger (Standard 0.35)",
                "default": 0.35, "min": 0.0, "max": 1.0,
            },
            "momentum_bear_threshold": {
                "type": "float", "label": "Momentum Bear-Schwelle",
                "description": "Momentum-Score unter diesem Wert = baerisches Regime. Niedriger = weniger Fehl-Exits (Standard -0.35)",
                "default": -0.35, "min": -1.0, "max": 0.0,
            },
            "min_confidence": {
                "type": "int", "label": "Min. Konfidenz",
                "description": "Minimaler Konfidenz-Score um einen Trade auszuführen",
                "default": 65, "min": 10, "max": 90,
            },
            "kline_interval": {
                "type": "select", "label": "Kline Intervall",
                "description": "Kerzen-Zeitrahmen für die Indikator-Berechnung. Tipp: Analyse-Takt (Zeitplan) sollte nicht deutlich kürzer sein als das Kline Intervall.",
                "default": "1h", "options": ["15m", "30m", "1h", "4h"],
            },
            "take_profit_percent": {
                "type": "float", "label": "Take Profit %",
                "description": "Optional: Take-Profit in % vom Einstiegspreis. Leer = kein TP (Strategie-Exit).",
                "min": 0.5, "max": 20.0,
            },
            "stop_loss_percent": {
                "type": "float", "label": "Stop Loss %",
                "description": "Optional: Stop-Loss in % vom Einstiegspreis. Leer = kein SL (Strategie-Exit).",
                "min": 0.5, "max": 10.0,
            },
        }

    async def close(self):
        """Clean up resources."""
        if self.data_fetcher:
            await self.data_fetcher.close()


# Register with the strategy registry
StrategyRegistry.register("edge_indicator", EdgeIndicatorStrategy)
