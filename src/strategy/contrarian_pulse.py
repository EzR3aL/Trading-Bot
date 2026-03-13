"""
Contrarian Pulse Strategy v2 — Fear & Greed Contrarian Scalper for BTC.

Pure algorithmic strategy (no LLM required).

Uses the Fear & Greed Index as a contrarian indicator:
- LONG when F&G < 30 (Extreme Fear = buying opportunity)
- SHORT when F&G > 70 (Extreme Greed = shorting opportunity)
- HOLD when F&G 30-70 (neutral zone)

v2 improvements:
- Ultra-extreme F&G (< 20 / > 80) bypasses EMA filter (+1 extra confirmation required)
- RSI divergence detection replaces redundant CVD
- EMA200 proximity check replaces meaningless OI>0
- Graduated confidence scoring (proportional to F&G extremity)

Confirmed by:
1. 50/200 EMA trend alignment + RSI filter (bypassed on ultra-extreme F&G)
2. 1+ derivatives confirmation signals (all meaningful, no free passes):
   - Buy/Sell Volume Split (buy-dominant for LONG, sell-dominant for SHORT)
   - RSI Divergence (bullish/bearish divergence as contrarian signal)
   - Long/Short Ratio (< 1.3 for LONG, > 1.4 for SHORT)
   - EMA200 Proximity (price within ±3% = support/resistance zone)
   - Funding Rate (negative supports LONG, high positive supports SHORT)

Data sources (all available in backtest):
  1. Fear & Greed Index (Alternative.me / historical)
  2. Binance Klines (1h, 200 candles) for EMA 50/200, RSI 14, Volume
  3. Binance Long/Short Ratio
  4. Binance Funding Rate
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.data.market_data import MarketDataFetcher
from src.strategy.base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Configurable defaults ────────────────────────────────────────────────────

DEFAULTS = {
    # Fear & Greed thresholds (widened based on real-data backtest results:
    # 35/65 outperformed 30/70 on 1h and 30m with +2.13% vs +1.03%)
    "fg_extreme_fear": 35,
    "fg_extreme_greed": 65,
    # Ultra-extreme F&G bypasses EMA filter (signal strong enough alone)
    "fg_ultra_fear": 25,
    "fg_ultra_greed": 75,
    # EMA
    "ema_fast": 50,
    "ema_slow": 200,
    "ema200_proximity_pct": 3.0,  # Price within ±3% of EMA200 = support/resistance zone
    # RSI
    "rsi_period": 14,
    "rsi_long_max": 55,      # RSI must be below this for LONG
    "rsi_short_min": 45,     # RSI must be above this for SHORT
    "rsi_divergence_lookback": 10,  # Candles to check for RSI divergence
    # Derivatives thresholds
    "buy_ratio_bullish": 0.52,
    "sell_ratio_bearish": 0.52,
    "lsr_long_max": 1.3,     # L/S ratio below = not overcrowded longs
    "lsr_short_min": 1.4,    # L/S ratio above = overcrowded longs (short target)
    "funding_rate_short_threshold": 0.0001,   # Positive = supports SHORT
    "funding_rate_long_threshold": -0.00005,  # Slightly negative = supports LONG
    # Min confirmations needed from derivatives signals
    # (v2: lowered from 2 to 1 because confirmations are now meaningful —
    #  no free OI pass, RSI divergence replaces redundant CVD)
    "min_confirmations": 1,
    # Confidence scoring
    "base_confidence": 60,
    "fg_extreme_bonus": 15,   # Bonus when F&G is very extreme (<15 or >85)
    "ema_alignment_bonus": 10,
    "confirmation_bonus": 5,  # Per additional confirmation beyond minimum
    "min_confidence": 55,
    # Risk defaults (optimized: 2:1 R:R per backtest results)
    "default_tp_pct": 2.0,
    "default_sl_pct": 1.0,
    # Data
    "kline_interval": "1h",
    "kline_count": 200,
}


class ContrarianPulseStrategy(BaseStrategy):
    """
    Fear & Greed Contrarian Scalper — pure algorithmic strategy.

    No LLM required. Implements the F&G contrarian logic directly in Python.
    Uses EMA 50/200 trend, RSI, and derivatives confirmation signals.
    """

    def __init__(
        self,
        params: Optional[Dict[str, Any]] = None,
        data_fetcher: Optional[MarketDataFetcher] = None,
    ):
        super().__init__(params)
        self.data_fetcher: Optional[MarketDataFetcher] = data_fetcher
        self._p = {**DEFAULTS, **self.params}

    async def _ensure_fetcher(self):
        if self.data_fetcher is None:
            self.data_fetcher = MarketDataFetcher()
            await self.data_fetcher._ensure_session()

    # ── Signal generation ─────────────────────────────────────────────────────

    async def generate_signal(self, symbol: str) -> TradeSignal:
        """Generate signal using pure algorithmic F&G contrarian logic."""
        await self._ensure_fetcher()

        logger.info(f"[ContrarianPulse] Generating signal for {symbol}...")

        # Step 1: Fetch all required data
        try:
            metrics = await self.data_fetcher.fetch_all_metrics()
        except Exception as e:
            logger.error(f"[ContrarianPulse] Metrics fetch failed: {e}")
            return self._neutral_signal(symbol, 0, f"Metrics fetch failed: {e}")

        # Get price
        current_price = metrics.btc_price if "BTC" in symbol else metrics.eth_price
        if current_price <= 0:
            return self._neutral_signal(symbol, 0, "Could not determine price")

        # Fetch klines for EMA/RSI/CVD calculations
        interval = self._p["kline_interval"]
        kline_count = self._p["kline_count"]
        try:
            klines = await self.data_fetcher.get_binance_klines(
                symbol, interval, kline_count
            )
        except Exception as e:
            logger.warning(f"[ContrarianPulse] Kline fetch failed: {e}")
            klines = []

        # Step 2: Analyze Fear & Greed (primary signal)
        fear_greed = metrics.fear_greed_index if metrics.fear_greed_index is not None else 50
        fg_direction, fg_reason = self._analyze_fear_greed(fear_greed)

        if fg_direction is None:
            return self._neutral_signal(
                symbol, current_price,
                f"F&G neutral zone ({fear_greed}). No trade.",
                fear_greed=fear_greed,
            )

        # Step 3: Analyze EMA trend + RSI confirmation
        # Ultra-extreme F&G bypasses EMA filter (conviction strong enough)
        ultra_fear = self._p["fg_ultra_fear"]
        ultra_greed = self._p["fg_ultra_greed"]
        is_ultra_extreme = (
            (fg_direction == SignalDirection.LONG and fear_greed < ultra_fear)
            or (fg_direction == SignalDirection.SHORT and fear_greed > ultra_greed)
        )

        ema_ok, ema_reason, technicals = self._analyze_technicals(
            klines, current_price, fg_direction
        )

        if not ema_ok and not is_ultra_extreme:
            return self._neutral_signal(
                symbol, current_price,
                f"F&G says {fg_direction.value.upper()} but technicals disagree: {ema_reason}",
                fear_greed=fear_greed,
            )

        if not ema_ok and is_ultra_extreme:
            ema_reason = f"EMA bypassed (ultra-extreme F&G={fear_greed})"

        # Step 4: Count derivatives confirmations
        confirmations, deriv_reasons = self._count_confirmations(
            klines, metrics, fg_direction
        )

        # Ultra-extreme F&G needs +1 extra confirmation when EMA is bypassed
        min_conf = self._p["min_confirmations"]
        if is_ultra_extreme and not ema_ok:
            min_conf = min_conf + 1

        if confirmations < min_conf:
            return self._neutral_signal(
                symbol, current_price,
                f"F&G + {'EMA bypassed' if is_ultra_extreme else 'EMA aligned'} "
                f"but only {confirmations}/{min_conf} "
                f"derivatives confirmations. {' | '.join(deriv_reasons)}",
                fear_greed=fear_greed,
            )

        # Step 5: Calculate confidence score
        confidence = self._calculate_confidence(
            fear_greed, fg_direction, confirmations, ema_ok
        )

        # Step 6: Calculate TP/SL
        tp_pct = float(self._p.get("take_profit_percent", self._p["default_tp_pct"]))
        sl_pct = float(self._p.get("stop_loss_percent", self._p["default_sl_pct"]))

        if fg_direction == SignalDirection.LONG:
            target_price = round(current_price * (1 + tp_pct / 100), 2)
            stop_loss = round(current_price * (1 - sl_pct / 100), 2)
        else:
            target_price = round(current_price * (1 - tp_pct / 100), 2)
            stop_loss = round(current_price * (1 + sl_pct / 100), 2)

        # Build reason
        all_reasons = [fg_reason, ema_reason] + deriv_reasons
        reason = " | ".join(all_reasons)

        # Build metrics snapshot
        snapshot = {
            "fear_greed": fear_greed,
            "fear_greed_classification": metrics.fear_greed_classification,
            "long_short_ratio": metrics.long_short_ratio,
            "funding_rate": metrics.funding_rate_btc,
            "open_interest": metrics.btc_open_interest,
            "confirmations": confirmations,
            **technicals,
        }

        signal = TradeSignal(
            direction=fg_direction,
            confidence=confidence,
            symbol=symbol,
            entry_price=current_price,
            target_price=target_price,
            stop_loss=stop_loss,
            reason=reason,
            metrics_snapshot=snapshot,
            timestamp=datetime.now(timezone.utc),
        )

        logger.info(
            f"[ContrarianPulse] Signal: {fg_direction.value.upper()} "
            f"@ ${current_price:,.2f} (confidence: {confidence}%, "
            f"F&G: {fear_greed}, confirmations: {confirmations})"
        )
        return signal

    # ── Fear & Greed Analysis ─────────────────────────────────────────────────

    def _analyze_fear_greed(
        self, fear_greed: int
    ) -> Tuple[Optional[SignalDirection], str]:
        """Analyze F&G as contrarian indicator."""
        extreme_fear = self._p["fg_extreme_fear"]
        extreme_greed = self._p["fg_extreme_greed"]

        if fear_greed < extreme_fear:
            reason = (
                f"Extreme Fear ({fear_greed} < {extreme_fear}) — "
                f"contrarian LONG signal"
            )
            return SignalDirection.LONG, reason

        if fear_greed > extreme_greed:
            reason = (
                f"Extreme Greed ({fear_greed} > {extreme_greed}) — "
                f"contrarian SHORT signal"
            )
            return SignalDirection.SHORT, reason

        return None, f"F&G neutral ({fear_greed})"

    # ── Technical Analysis (EMA + RSI) ────────────────────────────────────────

    def _analyze_technicals(
        self,
        klines: list,
        current_price: float,
        direction: SignalDirection,
    ) -> Tuple[bool, str, dict]:
        """Check EMA 50/200 trend and RSI alignment."""
        technicals: Dict[str, Any] = {}

        if not klines or len(klines) < 50:
            return False, "Insufficient kline data for EMA calculation", technicals

        closes = [float(k[4]) for k in klines]
        ema_fast_period = self._p["ema_fast"]
        ema_slow_period = self._p["ema_slow"]

        ema_fast = MarketDataFetcher.calculate_ema(closes, ema_fast_period)
        ema_slow = (
            MarketDataFetcher.calculate_ema(closes, ema_slow_period)
            if len(closes) >= ema_slow_period
            else []
        )

        rsi_values = MarketDataFetcher.calculate_rsi(klines, self._p["rsi_period"])

        ema_fast_val = ema_fast[-1] if ema_fast else 0
        ema_slow_val = ema_slow[-1] if ema_slow else 0
        rsi_val = rsi_values[-1] if rsi_values else 50

        technicals["ema_fast"] = round(ema_fast_val, 2)
        technicals["ema_slow"] = round(ema_slow_val, 2)
        technicals["rsi"] = round(rsi_val, 2)

        # Check EMA trend
        if ema_slow_val <= 0:
            # Not enough data for slow EMA — relax the condition
            ema_trend_ok = True
            trend_label = "insufficient data (relaxed)"
        elif direction == SignalDirection.LONG:
            ema_trend_ok = ema_fast_val > ema_slow_val
            trend_label = (
                f"bullish (EMA{ema_fast_period}={ema_fast_val:,.0f} > "
                f"EMA{ema_slow_period}={ema_slow_val:,.0f})"
                if ema_trend_ok
                else f"bearish (EMA{ema_fast_period}={ema_fast_val:,.0f} < "
                f"EMA{ema_slow_period}={ema_slow_val:,.0f})"
            )
        else:  # SHORT
            ema_trend_ok = ema_fast_val < ema_slow_val
            trend_label = (
                f"bearish (EMA{ema_fast_period}={ema_fast_val:,.0f} < "
                f"EMA{ema_slow_period}={ema_slow_val:,.0f})"
                if ema_trend_ok
                else f"bullish (EMA{ema_fast_period}={ema_fast_val:,.0f} > "
                f"EMA{ema_slow_period}={ema_slow_val:,.0f})"
            )

        # Check RSI
        if direction == SignalDirection.LONG:
            rsi_ok = rsi_val < self._p["rsi_long_max"]
            rsi_label = f"RSI {rsi_val:.1f} < {self._p['rsi_long_max']}" if rsi_ok else f"RSI {rsi_val:.1f} >= {self._p['rsi_long_max']} (overbought)"
        else:
            rsi_ok = rsi_val > self._p["rsi_short_min"]
            rsi_label = f"RSI {rsi_val:.1f} > {self._p['rsi_short_min']}" if rsi_ok else f"RSI {rsi_val:.1f} <= {self._p['rsi_short_min']} (oversold)"

        technicals["ema_trend"] = trend_label
        technicals["rsi_label"] = rsi_label

        if not ema_trend_ok:
            return False, f"EMA trend {trend_label} — contradicts {direction.value.upper()}", technicals
        if not rsi_ok:
            return False, f"{rsi_label} — contradicts {direction.value.upper()}", technicals

        return True, f"Technicals aligned: {trend_label}, {rsi_label}", technicals

    # ── Derivatives Confirmations ─────────────────────────────────────────────

    def _count_confirmations(
        self,
        klines: list,
        metrics,
        direction: SignalDirection,
    ) -> Tuple[int, List[str]]:
        """Count how many derivatives signals confirm the direction.

        5 signals (each independent, no free passes):
        1. Volume buy/sell split
        2. RSI divergence (replaces redundant CVD — much stronger contrarian signal)
        3. Long/Short Ratio
        4. Price proximity to EMA200 (replaces meaningless OI>0 check)
        5. Funding Rate
        """
        confirmations = 0
        reasons: List[str] = []

        # 1. Buy/Sell Volume Split (from klines)
        if klines and len(klines) >= 10:
            vol_analysis = MarketDataFetcher.get_spot_volume_analysis(klines[-24:])
            buy_ratio = vol_analysis.get("buy_ratio", 0.5)

            if direction == SignalDirection.LONG:
                if buy_ratio > self._p["buy_ratio_bullish"]:
                    confirmations += 1
                    reasons.append(f"Vol buy-dominant ({buy_ratio:.1%})")
                else:
                    reasons.append(f"Vol neutral ({buy_ratio:.1%})")
            else:
                sell_ratio = 1 - buy_ratio
                if sell_ratio > self._p["sell_ratio_bearish"]:
                    confirmations += 1
                    reasons.append(f"Vol sell-dominant ({sell_ratio:.1%})")
                else:
                    reasons.append(f"Vol neutral ({buy_ratio:.1%})")

        # 2. RSI Divergence (powerful contrarian signal)
        if klines and len(klines) >= 30:
            divergence = self._detect_rsi_divergence(klines, direction)
            if divergence:
                confirmations += 1
                reasons.append(f"RSI divergence detected ({divergence})")
            else:
                reasons.append("No RSI divergence")

        # 3. Long/Short Ratio
        lsr = metrics.long_short_ratio if metrics.long_short_ratio is not None else 1.0
        if direction == SignalDirection.LONG:
            if lsr < self._p["lsr_long_max"]:
                confirmations += 1
                reasons.append(f"L/S {lsr:.2f} < {self._p['lsr_long_max']} (not overcrowded)")
            else:
                reasons.append(f"L/S {lsr:.2f} >= {self._p['lsr_long_max']}")
        else:
            if lsr > self._p["lsr_short_min"]:
                confirmations += 1
                reasons.append(f"L/S {lsr:.2f} > {self._p['lsr_short_min']} (squeeze target)")
            else:
                reasons.append(f"L/S {lsr:.2f} <= {self._p['lsr_short_min']}")

        # 4. Price proximity to EMA200 (support/resistance zone)
        if klines and len(klines) >= 200:
            closes = [float(k[4]) for k in klines]
            ema200 = MarketDataFetcher.calculate_ema(closes, 200)
            if ema200:
                current_price = closes[-1]
                ema200_val = ema200[-1]
                distance_pct = abs(current_price - ema200_val) / ema200_val * 100
                proximity_threshold = self._p["ema200_proximity_pct"]

                if distance_pct <= proximity_threshold:
                    confirmations += 1
                    reasons.append(
                        f"Price near EMA200 ({distance_pct:.1f}% away, "
                        f"threshold {proximity_threshold}%)"
                    )
                else:
                    reasons.append(f"Price {distance_pct:.1f}% from EMA200")
            else:
                reasons.append("EMA200 unavailable")
        else:
            reasons.append("Insufficient data for EMA200")

        # 5. Funding Rate
        funding = metrics.funding_rate_btc if metrics.funding_rate_btc is not None else 0
        if direction == SignalDirection.LONG:
            if funding < self._p["funding_rate_long_threshold"]:
                confirmations += 1
                reasons.append(f"Funding negative ({funding:.6f}) — supports LONG")
            else:
                reasons.append(f"Funding {funding:.6f}")
        else:
            if funding > self._p["funding_rate_short_threshold"]:
                confirmations += 1
                reasons.append(f"Funding high ({funding:.6f}) — supports SHORT")
            else:
                reasons.append(f"Funding {funding:.6f}")

        return confirmations, reasons

    def _detect_rsi_divergence(
        self, klines: list, direction: SignalDirection
    ) -> Optional[str]:
        """Detect RSI divergence — price and RSI moving in opposite directions.

        Bullish divergence: Price makes lower low, RSI makes higher low → LONG
        Bearish divergence: Price makes higher high, RSI makes lower high → SHORT
        """
        lookback = self._p["rsi_divergence_lookback"]
        rsi_values = MarketDataFetcher.calculate_rsi(klines, self._p["rsi_period"])
        if not rsi_values or len(rsi_values) < lookback:
            return None

        closes = [float(k[4]) for k in klines]
        recent_closes = closes[-lookback:]
        recent_rsi = rsi_values[-lookback:]

        # Find local extremes in the lookback window
        mid = lookback // 2

        if direction == SignalDirection.LONG:
            # Bullish divergence: price lower low, RSI higher low
            price_current_low = min(recent_closes[mid:])
            price_earlier_low = min(recent_closes[:mid])
            rsi_current_low = min(recent_rsi[mid:])
            rsi_earlier_low = min(recent_rsi[:mid])

            if price_current_low < price_earlier_low and rsi_current_low > rsi_earlier_low:
                return f"bullish: price lower low but RSI higher low"

        else:  # SHORT
            # Bearish divergence: price higher high, RSI lower high
            price_current_high = max(recent_closes[mid:])
            price_earlier_high = max(recent_closes[:mid])
            rsi_current_high = max(recent_rsi[mid:])
            rsi_earlier_high = max(recent_rsi[:mid])

            if price_current_high > price_earlier_high and rsi_current_high < rsi_earlier_high:
                return f"bearish: price higher high but RSI lower high"

        return None

    # ── Confidence Scoring ────────────────────────────────────────────────────

    def _calculate_confidence(
        self,
        fear_greed: int,
        direction: SignalDirection,
        confirmations: int,
        ema_aligned: bool,
    ) -> int:
        """Calculate confidence score based on signal quality.

        Graduated F&G bonus: more extreme F&G = proportionally higher confidence.
        E.g. F&G=5 gives full bonus, F&G=25 gives partial bonus.
        """
        confidence = self._p["base_confidence"]

        # Graduated F&G extremity bonus (proportional, not binary)
        fg_bonus = self._p["fg_extreme_bonus"]
        if direction == SignalDirection.LONG:
            extreme_threshold = self._p["fg_extreme_fear"]
            # F&G=0 gives full bonus, F&G=threshold gives 0
            fg_ratio = max(0, (extreme_threshold - fear_greed) / extreme_threshold)
            confidence += int(fg_bonus * fg_ratio)
        elif direction == SignalDirection.SHORT:
            extreme_threshold = self._p["fg_extreme_greed"]
            # F&G=100 gives full bonus, F&G=threshold gives 0
            fg_ratio = max(0, (fear_greed - extreme_threshold) / (100 - extreme_threshold))
            confidence += int(fg_bonus * fg_ratio)

        # EMA alignment bonus
        if ema_aligned:
            confidence += self._p["ema_alignment_bonus"]

        # Extra confirmations bonus (beyond minimum)
        min_conf = self._p["min_confirmations"]
        extra = max(0, confirmations - min_conf)
        confidence += extra * self._p["confirmation_bonus"]

        return min(confidence, 95)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _neutral_signal(
        self,
        symbol: str,
        price: float,
        reason: str,
        fear_greed: int = 50,
    ) -> TradeSignal:
        """Return a NEUTRAL (HOLD) signal."""
        return TradeSignal(
            direction=SignalDirection.NEUTRAL,
            confidence=0,
            symbol=symbol,
            entry_price=price,
            target_price=None,
            stop_loss=None,
            reason=f"[ContrarianPulse] HOLD — {reason}",
            metrics_snapshot={"fear_greed": fear_greed},
            timestamp=datetime.now(timezone.utc),
        )

    # ── Gate ──────────────────────────────────────────────────────────────────

    async def should_trade(self, signal: TradeSignal) -> Tuple[bool, str]:
        if signal.direction == SignalDirection.NEUTRAL:
            return False, "Contrarian Pulse: HOLD — no trade"

        min_conf = self._p["min_confidence"]
        if signal.confidence < min_conf:
            return False, (
                f"Contrarian Pulse confidence {signal.confidence}% < {min_conf}%"
            )

        if signal.entry_price <= 0:
            return False, "Invalid entry price"

        # Validate TP/SL direction
        if signal.target_price is not None and signal.stop_loss is not None:
            if signal.direction == SignalDirection.LONG:
                if signal.target_price <= signal.entry_price:
                    return False, "TP must be above entry for LONG"
                if signal.stop_loss >= signal.entry_price:
                    return False, "SL must be below entry for LONG"
            else:
                if signal.target_price >= signal.entry_price:
                    return False, "TP must be below entry for SHORT"
                if signal.stop_loss <= signal.entry_price:
                    return False, "SL must be above entry for SHORT"

        return True, f"Signal approved ({signal.confidence}% confidence)"

    # ── Schema ────────────────────────────────────────────────────────────────

    @classmethod
    def get_param_schema(cls) -> Dict[str, Any]:
        return {
            "fg_extreme_fear": {
                "type": "int",
                "label": "Extreme-Angst-Schwelle",
                "description": "F&G unter diesem Wert = Extreme Angst → LONG (konträr)",
                "default": 35,
                "min": 10,
                "max": 45,
            },
            "fg_extreme_greed": {
                "type": "int",
                "label": "Extreme-Gier-Schwelle",
                "description": "F&G über diesem Wert = Extreme Gier → SHORT (konträr)",
                "default": 65,
                "min": 55,
                "max": 90,
            },
            "fg_ultra_fear": {
                "type": "int",
                "label": "Ultra-Angst (EMA-Bypass)",
                "description": "F&G unter diesem Wert überspringt den EMA-Filter (Signal stark genug)",
                "default": 25,
                "min": 5,
                "max": 35,
            },
            "fg_ultra_greed": {
                "type": "int",
                "label": "Ultra-Gier (EMA-Bypass)",
                "description": "F&G über diesem Wert überspringt den EMA-Filter (Signal stark genug)",
                "default": 75,
                "min": 65,
                "max": 95,
            },
            "min_confirmations": {
                "type": "int",
                "label": "Min. Derivate-Bestätigungen",
                "description": "Mindestens so viele Derivate-Signale müssen bestätigen (max 5)",
                "default": 1,
                "min": 1,
                "max": 5,
            },
            "rsi_long_max": {
                "type": "int",
                "label": "RSI-Maximum für LONG",
                "description": "RSI muss unter diesem Wert liegen für LONG-Einstieg",
                "default": 55,
                "min": 40,
                "max": 70,
            },
            "rsi_short_min": {
                "type": "int",
                "label": "RSI-Minimum für SHORT",
                "description": "RSI muss über diesem Wert liegen für SHORT-Einstieg",
                "default": 45,
                "min": 30,
                "max": 60,
            },
            "rsi_divergence_lookback": {
                "type": "int",
                "label": "RSI-Divergenz Lookback",
                "description": "Anzahl Kerzen für RSI-Divergenz-Erkennung",
                "default": 10,
                "min": 5,
                "max": 30,
            },
            "ema200_proximity_pct": {
                "type": "float",
                "label": "EMA200-Nähe (%)",
                "description": "Preis innerhalb ±X% von EMA200 = Support/Resistance-Zone",
                "default": 3.0,
                "min": 1.0,
                "max": 10.0,
            },
            "lsr_long_max": {
                "type": "float",
                "label": "Max L/S Ratio für LONG",
                "description": "Long/Short Ratio muss unter diesem Wert sein für LONG",
                "default": 1.3,
                "min": 0.8,
                "max": 2.0,
            },
            "lsr_short_min": {
                "type": "float",
                "label": "Min L/S Ratio für SHORT",
                "description": "Long/Short Ratio muss über diesem Wert sein für SHORT (Squeeze-Ziel)",
                "default": 1.4,
                "min": 1.0,
                "max": 3.0,
            },
        }

    @classmethod
    def get_description(cls) -> str:
        return (
            "Kontäre Fear & Greed Scalping-Strategie v2 für BTC. "
            "Nutzt den F&G Index als Kontraindikator (Long bei Extreme Fear, "
            "Short bei Extreme Greed), bestätigt durch 50/200 EMA-Trend, RSI "
            "und Derivate-Signale (RSI-Divergenz, L/S Ratio, Volume, EMA200-Nähe, Funding). "
            "Ultra-extreme F&G (< 20 / > 80) überspringt den EMA-Filter. "
            "Rein algorithmisch — kein LLM erforderlich."
        )

    async def close(self):
        if self.data_fetcher:
            await self.data_fetcher.close()


# Register (hidden: superseded by Liquidation Hunter which shares 70% of signal sources
# but has superior exit logic. To re-enable, set hidden=False.)
StrategyRegistry.register("contrarian_pulse", ContrarianPulseStrategy, hidden=True)
