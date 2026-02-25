"""
Claude-Edge Indicator Strategy

ROLE: Enhanced version of the Edge Indicator with 6 improvements
identified from backtest analysis:

1. ATR-based TP/SL     - Dynamic targets based on volatility instead of fixed %
2. Volume confirmation  - Buy/sell volume ratio adds to momentum score
3. Multi-timeframe      - 4h EMA ribbon alignment for higher-timeframe confirmation
4. Trailing stop        - Metadata for breakeven + trailing stop logic
5. Regime-based sizing  - Position size scales 0.5-1.0 based on confidence
6. RSI divergence       - Detects price/RSI divergence for early reversals

DATA SOURCE: Binance kline data (OHLCV) - same as Edge Indicator.
Multi-timeframe uses a second kline fetch for 4h data (skipped in backtest).
"""

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.data.market_data import MarketDataFetcher
from src.strategy.base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default parameter values (extends Edge Indicator defaults)
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
    # Momentum Score
    "momentum_smooth_period": 3,
    "momentum_bull_threshold": 0.20,
    "momentum_bear_threshold": -0.20,
    # Trade filters
    "min_confidence": 40,
    # ATR-based Risk (optional — only used if user configures multipliers)
    "atr_period": 14,
    # Volume confirmation
    "volume_weight": 0.3,
    "volume_strong_threshold": 0.58,
    "volume_weak_threshold": 0.42,
    # Multi-timeframe
    "htf_interval": "4h",
    "htf_kline_count": 100,
    "htf_ema_fast": 8,
    "htf_ema_slow": 21,
    "use_htf_filter": True,
    # Trailing stop
    "trailing_stop_enabled": True,
    "trailing_breakeven_atr": 1.0,
    "trailing_trail_atr": 1.5,
    # Regime sizing
    "min_position_scale": 0.5,
    "max_position_scale": 1.0,
    # RSI divergence
    "divergence_lookback": 20,
    "divergence_confidence_bonus": 8,
    "divergence_confidence_penalty": 10,
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


class ClaudeEdgeIndicatorStrategy(BaseStrategy):
    """
    Enhanced Edge Indicator strategy with 6 improvements:
    ATR-based targets, volume confirmation, multi-timeframe alignment,
    trailing stop metadata, regime-based position sizing, RSI divergence.
    """

    def __init__(
        self,
        params: Optional[Dict[str, Any]] = None,
        data_fetcher: Optional[MarketDataFetcher] = None,
        backtest_mode: bool = False,
    ):
        super().__init__(params)
        self.data_fetcher = data_fetcher
        self.backtest_mode = backtest_mode
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
        """Calculate EMA 8/21 ribbon and determine trend."""
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
        """Calculate Predator Momentum composite score (same as Edge Indicator)."""
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

        scores = []
        for i in range(1, min_len):
            hist_val = hist_series[i] if i < len(hist_series) else 0.0
            hist_window = hist_series[max(0, i - 99):i + 1]
            sd = _stdev(hist_window, min(100, len(hist_window)))
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

    # ==================== Enhancement #1: ATR-based TP/SL ====================

    def _calculate_targets(
        self, direction: SignalDirection, current_price: float,
        klines: Optional[List[List]] = None,
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate TP/SL using ATR multipliers instead of fixed percentages.

        Returns (None, None) if ATR multipliers are not configured by the user.
        """
        tp_mult = self._p.get("atr_tp_multiplier")
        sl_mult = self._p.get("atr_sl_multiplier")

        if tp_mult is None and sl_mult is None:
            return None, None

        atr_value = 0.0
        if klines:
            atr_series = MarketDataFetcher.calculate_atr(klines, self._p["atr_period"])
            if atr_series:
                atr_value = atr_series[-1]

        if atr_value <= 0:
            atr_value = current_price * 0.015

        take_profit = None
        stop_loss = None

        if tp_mult is not None:
            tp_distance = atr_value * float(tp_mult)
            if direction == SignalDirection.LONG:
                take_profit = round(current_price + tp_distance, 2)
            else:
                take_profit = round(current_price - tp_distance, 2)

        if sl_mult is not None:
            sl_distance = atr_value * float(sl_mult)
            if direction == SignalDirection.LONG:
                stop_loss = round(current_price - sl_distance, 2)
            else:
                stop_loss = round(current_price + sl_distance, 2)

        return take_profit, stop_loss

    # ==================== Enhancement #2: Volume Confirmation ====================

    def _calculate_volume_score(self, klines: List[List]) -> Dict[str, Any]:
        """
        Calculate volume-based score from buy/sell ratio.

        Returns:
            {"volume_score": float (-1 to +1), "buy_ratio": float, "is_strong": bool}
        """
        vol_data = MarketDataFetcher.get_spot_volume_analysis(klines)
        buy_ratio = vol_data["buy_ratio"]

        strong_thresh = self._p["volume_strong_threshold"]
        weak_thresh = self._p["volume_weak_threshold"]

        # Map buy_ratio [0,1] to volume_score [-1, +1]
        # 0.5 -> 0, 0.58+ -> ~1, 0.42- -> ~-1
        if buy_ratio >= strong_thresh:
            volume_score = min((buy_ratio - 0.5) / (strong_thresh - 0.5), 1.0)
        elif buy_ratio <= weak_thresh:
            volume_score = max((buy_ratio - 0.5) / (0.5 - weak_thresh), -1.0)
        else:
            volume_score = (buy_ratio - 0.5) * 2.0

        is_strong = abs(volume_score) > 0.5

        return {
            "volume_score": round(volume_score, 4),
            "buy_ratio": round(buy_ratio, 4),
            "is_strong": is_strong,
        }

    # ==================== Enhancement #3: Multi-Timeframe ====================

    async def _check_htf_alignment(self, symbol: str) -> Dict[str, Any]:
        """
        Check higher-timeframe EMA ribbon alignment.

        Returns:
            {"htf_bullish": bool, "htf_bearish": bool, "htf_neutral": bool,
             "htf_ema_fast": float, "htf_ema_slow": float, "htf_available": bool}
        """
        default = {
            "htf_bullish": False, "htf_bearish": False, "htf_neutral": True,
            "htf_ema_fast": 0.0, "htf_ema_slow": 0.0, "htf_available": False,
        }

        if not self._p.get("use_htf_filter", True):
            return default

        try:
            htf_interval = self._p["htf_interval"]
            htf_count = self._p["htf_kline_count"]

            htf_klines = await self.data_fetcher.get_binance_klines(
                symbol, htf_interval, htf_count
            )

            if not htf_klines or len(htf_klines) < self._p["htf_ema_slow"] + 5:
                return default

            htf_closes = []
            for k in htf_klines:
                try:
                    htf_closes.append(float(k[4]))
                except (IndexError, ValueError, TypeError):
                    continue

            ema_fast = MarketDataFetcher.calculate_ema(htf_closes, self._p["htf_ema_fast"])
            ema_slow = MarketDataFetcher.calculate_ema(htf_closes, self._p["htf_ema_slow"])

            if not ema_fast or not ema_slow or ema_fast[-1] == 0 or ema_slow[-1] == 0:
                return default

            current = htf_closes[-1]
            upper = max(ema_fast[-1], ema_slow[-1])
            lower = min(ema_fast[-1], ema_slow[-1])

            return {
                "htf_bullish": current > upper,
                "htf_bearish": current < lower,
                "htf_neutral": lower <= current <= upper,
                "htf_ema_fast": round(ema_fast[-1], 2),
                "htf_ema_slow": round(ema_slow[-1], 2),
                "htf_available": True,
            }
        except Exception as e:
            logger.warning(f"HTF alignment check failed: {e}")
            return default

    def _check_htf_alignment_sync(self, klines: List[List]) -> Dict[str, Any]:
        """
        Synchronous HTF alignment check using provided klines.

        Used by the backtest engine which cannot make async calls.
        When klines are from the primary timeframe, this provides a
        long-period EMA check as a proxy for HTF alignment.
        """
        default = {
            "htf_bullish": False, "htf_bearish": False, "htf_neutral": True,
            "htf_ema_fast": 0.0, "htf_ema_slow": 0.0, "htf_available": False,
        }

        if not self._p.get("use_htf_filter", True):
            return default

        if not klines or len(klines) < 50:
            return default

        closes = []
        for k in klines:
            try:
                closes.append(float(k[4]))
            except (IndexError, ValueError, TypeError):
                continue

        # Use longer-period EMAs as a proxy for HTF alignment in backtest
        ema_fast = MarketDataFetcher.calculate_ema(closes, 21)
        ema_slow = MarketDataFetcher.calculate_ema(closes, 50)

        if not ema_fast or not ema_slow or ema_fast[-1] == 0 or ema_slow[-1] == 0:
            return default

        current = closes[-1]
        upper = max(ema_fast[-1], ema_slow[-1])
        lower = min(ema_fast[-1], ema_slow[-1])

        return {
            "htf_bullish": current > upper,
            "htf_bearish": current < lower,
            "htf_neutral": lower <= current <= upper,
            "htf_ema_fast": round(ema_fast[-1], 2),
            "htf_ema_slow": round(ema_slow[-1], 2),
            "htf_available": True,
        }

    # ==================== Enhancement #4: Trailing Stop ====================

    def _build_trailing_stop_metadata(
        self, direction: SignalDirection, entry_price: float,
        atr_value: float,
    ) -> Dict[str, Any]:
        """
        Build trailing stop parameters for the trade execution layer.

        Returns metadata that the bot worker can use to manage the trade:
        - breakeven_trigger: price at which to move SL to entry
        - trail_distance: ATR-based trailing distance
        """
        if not self._p["trailing_stop_enabled"] or atr_value <= 0:
            return {"trailing_enabled": False}

        breakeven_distance = atr_value * self._p["trailing_breakeven_atr"]
        trail_distance = atr_value * self._p["trailing_trail_atr"]

        if direction == SignalDirection.LONG:
            breakeven_trigger = entry_price + breakeven_distance
        else:
            breakeven_trigger = entry_price - breakeven_distance

        return {
            "trailing_enabled": True,
            "breakeven_trigger": round(breakeven_trigger, 2),
            "trail_distance": round(trail_distance, 2),
            "atr_value": round(atr_value, 2),
        }

    # ==================== Enhancement #5: Regime-Based Sizing ====================

    def _calculate_position_size_recommendation(self, confidence: int) -> float:
        """
        Scale position size 0.5-1.0 based on confidence.

        Low confidence (40-55) -> 0.5x
        Mid confidence (55-75) -> 0.7x
        High confidence (75+)  -> 1.0x
        """
        min_scale = self._p["min_position_scale"]
        max_scale = self._p["max_position_scale"]

        # Linear interpolation between 40-95 confidence
        confidence_clamped = max(40, min(95, confidence))
        t = (confidence_clamped - 40) / 55.0  # 0.0 to 1.0
        return round(min_scale + t * (max_scale - min_scale), 2)

    # ==================== Confidence Calculation ====================

    def _calculate_confidence(
        self,
        adx_data: Dict[str, Any],
        momentum: Dict[str, Any],
        ribbon: Dict[str, Any],
        volume_data: Optional[Dict[str, Any]] = None,
        divergence_data: Optional[Dict[str, Any]] = None,
        htf_data: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Calculate trade confidence with enhanced inputs.

        Base: 50
        + ADX strength bonus (0-25)
        + Momentum magnitude bonus (0-20)
        + Full alignment bonus (0-10)
        + Regime flip bonus (0-10)
        + Volume confirmation bonus (0-8)
        + HTF alignment bonus (0-5)
        +/- RSI divergence bonus/penalty
        - Chop penalty (0-20)
        """
        confidence = 50

        adx = adx_data.get("adx", 0)
        chop_threshold = self._p["adx_chop_threshold"]
        use_adx = self._p["use_adx_filter"]

        # ADX strength bonus
        if use_adx and adx > chop_threshold:
            excess = adx - chop_threshold
            confidence += min(int(excess * 0.8), 25)
        elif use_adx and adx < chop_threshold:
            deficit = chop_threshold - adx
            confidence -= min(int(deficit), 20)

        # Momentum magnitude bonus
        abs_score = abs(momentum.get("smoothed_score", 0))
        if abs_score > 0.5:
            confidence += 20
        elif abs_score > 0.3:
            confidence += 12
        elif abs_score > 0.15:
            confidence += 5

        # Full alignment bonus
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

        # Regime flip bonus
        if momentum.get("regime_flip_bull") or momentum.get("regime_flip_bear"):
            confidence += 10

        # Enhancement #2: Volume confirmation bonus
        if volume_data:
            vol_score = volume_data.get("volume_score", 0)
            regime = momentum.get("regime", 0)
            # Volume confirms direction: bullish momentum + buying volume
            if (regime >= 0 and vol_score > 0.3) or (regime <= 0 and vol_score < -0.3):
                confidence += min(int(abs(vol_score) * 10), 8)
            # Volume contradicts direction: small penalty
            elif (regime > 0 and vol_score < -0.3) or (regime < 0 and vol_score > 0.3):
                confidence -= 3

        # Enhancement #3: HTF alignment bonus
        if htf_data and htf_data.get("htf_available", False):
            regime = momentum.get("regime", 0)
            if (regime >= 0 and htf_data.get("htf_bullish")) or \
               (regime <= 0 and htf_data.get("htf_bearish")):
                confidence += 5
            elif (regime > 0 and htf_data.get("htf_bearish")) or \
                 (regime < 0 and htf_data.get("htf_bullish")):
                confidence -= 3

        # Enhancement #6: RSI divergence
        if divergence_data:
            regime = momentum.get("regime", 0)
            # Bullish divergence in bullish context -> bonus
            if divergence_data.get("bullish_divergence") and regime >= 0:
                confidence += self._p["divergence_confidence_bonus"]
            # Bearish divergence in bearish context -> bonus
            elif divergence_data.get("bearish_divergence") and regime <= 0:
                confidence += self._p["divergence_confidence_bonus"]
            # Divergence against direction -> penalty
            elif divergence_data.get("bearish_divergence") and regime > 0:
                confidence -= self._p["divergence_confidence_penalty"]
            elif divergence_data.get("bullish_divergence") and regime < 0:
                confidence -= self._p["divergence_confidence_penalty"]

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

    async def should_exit(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        metrics_at_entry: dict | None = None,
    ) -> Tuple[bool, str]:
        """Check if an open position should be closed based on current indicators."""
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

            ribbon = self._calculate_ema_ribbon(closes)
            momentum = self._calculate_predator_momentum(closes, klines, ribbon["ema_fast_above"])
            regime = momentum.get("regime", 0)

            if side == "long":
                if ribbon["bear_trend"]:
                    return True, (
                        "Trend reversal: Preis unter EMA-Ribbon (bearTrend). "
                        "Momentum=%.2f" % momentum['smoothed_score']
                    )
                if ribbon["neutral"] and regime == -1:
                    return True, (
                        "Trend schwaecht sich ab: Preis im Ribbon + baerisches Momentum "
                        "(score=%.2f)" % momentum['smoothed_score']
                    )
                if momentum.get("regime_flip_bear", False):
                    return True, (
                        "Regime-Flip: Momentum dreht bearish "
                        "(score=%.2f)" % momentum['smoothed_score']
                    )

            elif side == "short":
                if ribbon["bull_trend"]:
                    return True, (
                        "Trend reversal: Preis ueber EMA-Ribbon (bullTrend). "
                        "Momentum=%.2f" % momentum['smoothed_score']
                    )
                if ribbon["neutral"] and regime == 1:
                    return True, (
                        "Trend schwaecht sich ab: Preis im Ribbon + bullisches Momentum "
                        "(score=%.2f)" % momentum['smoothed_score']
                    )
                if momentum.get("regime_flip_bull", False):
                    return True, (
                        "Regime-Flip: Momentum dreht bullish "
                        "(score=%.2f)" % momentum['smoothed_score']
                    )

            return False, ""

        except Exception as e:
            logger.error("Exit check error for %s: %s", symbol, e)
            return False, ""

    async def generate_signal(self, symbol: str = "BTCUSDT") -> TradeSignal:
        """Generate a trade signal using the enhanced Claude-Edge layers."""
        await self._ensure_fetcher()

        logger.info(f"=== ClaudeEdge: Generating Signal for {symbol} ===")

        interval = self._p["kline_interval"]
        count = self._p["kline_count"]

        klines = await self.data_fetcher.get_binance_klines(symbol, interval, count)

        if not klines or len(klines) < self._p["ema_slow_period"] + 10:
            logger.error(f"Insufficient kline data: {len(klines) if klines else 0} candles")
            return TradeSignal(
                direction=SignalDirection.LONG,
                confidence=0,
                symbol=symbol,
                entry_price=0.0,
                target_price=None,
                stop_loss=None,
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
                direction=SignalDirection.LONG,
                confidence=0,
                symbol=symbol,
                entry_price=0.0,
                target_price=None,
                stop_loss=None,
                reason="Invalid price data",
                metrics_snapshot={"error": "invalid_price"},
                timestamp=datetime.now(),
            )

        # Layer 1: EMA Ribbon
        ribbon = self._calculate_ema_ribbon(closes)

        # Layer 2: ADX / Chop Filter
        adx_data = MarketDataFetcher.calculate_adx(klines, self._p["adx_period"])

        # Layer 3: Predator Momentum
        momentum = self._calculate_predator_momentum(
            closes, klines, ribbon["ema_fast_above"]
        )

        # Enhancement #2: Volume confirmation
        volume_data = self._calculate_volume_score(klines)

        # Enhancement #6: RSI divergence
        divergence_data = MarketDataFetcher.detect_rsi_divergence(
            klines, self._p["rsi_period"], self._p["divergence_lookback"]
        )

        # Enhancement #3: Multi-timeframe alignment
        # In backtest mode, use sync HTF check with existing klines
        # to avoid async API calls that are unavailable during backtesting
        if self.backtest_mode:
            htf_data = self._check_htf_alignment_sync(klines)
        else:
            htf_data = await self._check_htf_alignment(symbol)

        # Determine direction
        direction, reason = self._determine_direction(ribbon, momentum, adx_data)

        # Calculate confidence with all enhancements
        confidence = self._calculate_confidence(
            adx_data, momentum, ribbon,
            volume_data=volume_data,
            divergence_data=divergence_data,
            htf_data=htf_data,
        )

        # Enhancement #1: ATR-based targets
        take_profit, stop_loss = self._calculate_targets(direction, current_price, klines)

        # Enhancement #4: Trailing stop metadata
        atr_series = MarketDataFetcher.calculate_atr(klines, self._p["atr_period"])
        atr_value = atr_series[-1] if atr_series else current_price * 0.015
        trailing_meta = self._build_trailing_stop_metadata(direction, current_price, atr_value)

        # Enhancement #5: Position size recommendation
        position_scale = self._calculate_position_size_recommendation(confidence)

        # Build metrics snapshot
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
            # Claude-Edge enhancements
            "atr_value": round(atr_value, 2),
            "volume_score": volume_data["volume_score"],
            "buy_ratio": volume_data["buy_ratio"],
            "htf_bullish": htf_data.get("htf_bullish", False),
            "htf_bearish": htf_data.get("htf_bearish", False),
            "htf_available": htf_data.get("htf_available", False),
            "bullish_divergence": divergence_data.get("bullish_divergence", False),
            "bearish_divergence": divergence_data.get("bearish_divergence", False),
            "position_scale": position_scale,
            **trailing_meta,
        }

        signal = TradeSignal(
            direction=direction,
            confidence=confidence,
            symbol=symbol,
            entry_price=current_price,
            target_price=take_profit,
            stop_loss=stop_loss,
            reason=f"[Claude-Edge] {reason}",
            metrics_snapshot=snapshot,
            timestamp=datetime.now(),
        )

        logger.info(
            f"=== SIGNAL: {signal.direction.value.upper()} {signal.confidence}% "
            f"@ ${signal.entry_price:,.2f} (ATR-SL, vol={volume_data['volume_score']:.2f}, "
            f"scale={position_scale}) ==="
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
            f"ADX={signal.metrics_snapshot.get('adx', 0):.1f}, "
            f"scale={signal.metrics_snapshot.get('position_scale', 1.0)}"
        )

    @classmethod
    def get_description(cls) -> str:
        return (
            "Enhanced Edge Indicator with ATR-based TP/SL, volume confirmation, "
            "multi-timeframe (4h) alignment, trailing stop, regime-based position "
            "sizing, and RSI divergence detection. Only requires kline data."
        )

    @classmethod
    def get_param_schema(cls) -> Dict[str, Any]:
        return {
            "ema_fast_period": {
                "type": "int",
                "label": "EMA Schnell-Periode",
                "description": "Schnelle EMA-Periode für das Trend-Ribbon (Standard 8)",
                "default": 8,
                "min": 2,
                "max": 200,
            },
            "ema_slow_period": {
                "type": "int",
                "label": "EMA Langsam-Periode",
                "description": "Langsame EMA-Periode für das Trend-Ribbon (Standard 21)",
                "default": 21,
                "min": 5,
                "max": 400,
            },
            "adx_period": {
                "type": "int",
                "label": "ADX Periode",
                "description": "Berechnungsperiode für den ADX-Indikator (Standard 14)",
                "default": 14,
                "min": 2,
                "max": 100,
            },
            "adx_chop_threshold": {
                "type": "float",
                "label": "ADX Chop-Schwelle",
                "description": "ADX unter diesem Wert = seitwärts, kein Trading (Standard 18)",
                "default": 18.0,
                "min": 5.0,
                "max": 50.0,
            },
            "use_adx_filter": {
                "type": "bool",
                "label": "ADX Filter aktiv",
                "description": "ADX-basierten Chop-Filter aktivieren um Seitwärtsmärkte zu meiden",
                "default": True,
            },
            "atr_tp_multiplier": {
                "type": "float",
                "label": "ATR TP Multiplikator",
                "description": "Optional. Take Profit = Einstieg +/- ATR * Multiplikator. Wenn leer, kein automatisches TP.",
                "min": 1.0,
                "max": 5.0,
            },
            "atr_sl_multiplier": {
                "type": "float",
                "label": "ATR SL Multiplikator",
                "description": "Optional. Stop Loss = Einstieg -/+ ATR * Multiplikator. Wenn leer, kein automatisches SL.",
                "min": 0.5,
                "max": 3.0,
            },
            "volume_weight": {
                "type": "float",
                "label": "Volumen-Gewichtung",
                "description": "Gewichtung des Volumen-Scores im Momentum (Standard 0.3)",
                "default": 0.3,
                "min": 0.0,
                "max": 1.0,
            },
            "use_htf_filter": {
                "type": "bool",
                "label": "HTF Filter aktiv",
                "description": "4h Höher-Zeitrahmen-Abgleich aktivieren",
                "default": True,
            },
            "trailing_stop_enabled": {
                "type": "bool",
                "label": "Trailing Stop",
                "description": "Trailing Stop mit ATR-basiertem Breakeven aktivieren",
                "default": True,
            },
            "momentum_bull_threshold": {
                "type": "float",
                "label": "Momentum Bull-Schwelle",
                "description": "Momentum-Score über diesem Wert = bullisches Regime (Standard 0.20)",
                "default": 0.20,
                "min": 0.0,
                "max": 1.0,
            },
            "momentum_bear_threshold": {
                "type": "float",
                "label": "Momentum Bear-Schwelle",
                "description": "Momentum-Score unter diesem Wert = bärisches Regime (Standard -0.20)",
                "default": -0.20,
                "min": -1.0,
                "max": 0.0,
            },
            "min_confidence": {
                "type": "int",
                "label": "Min. Konfidenz",
                "description": "Minimaler Konfidenz-Score um einen Trade auszuführen",
                "default": 40,
                "min": 10,
                "max": 80,
            },
            "kline_interval": {
                "type": "select",
                "label": "Kline Intervall",
                "description": "Kerzen-Zeitrahmen für die Indikator-Berechnung. Tipp: Analyse-Takt (Zeitplan) sollte nicht deutlich kürzer sein als das Kline Intervall.",
                "default": "1h",
                "options": ["15m", "30m", "1h", "4h"],
            },
        }

    async def close(self):
        """Clean up resources."""
        if self.data_fetcher:
            await self.data_fetcher.close()


# Register with the strategy registry
StrategyRegistry.register("claude_edge_indicator", ClaudeEdgeIndicatorStrategy)
