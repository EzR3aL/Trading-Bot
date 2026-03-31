"""
Contrarian Liquidation Hunter Strategy

ROLE: Act as an "Institutional Market Maker" - maximize pain for the majority.

CORE LOGIC:
1. Analyze Leverage: Check Long/Short Account Ratio
   - IF Ratio > 2.0 (Crowded Longs): Signal is SHORT
   - IF Ratio < 0.5 (Crowded Shorts): Signal is LONG

2. Analyze Cost: Check Funding Rate
   - IF Rate > 0.05% (Expensive to Long): Strengthen SHORT confidence +20
   - IF Rate < -0.02% (Expensive to Short): Strengthen LONG confidence +20

3. Analyze Sentiment: Check Fear & Greed Index
   - IF Index > 75: Bias SHORT (Extreme Greed)
   - IF Index < 25: Bias LONG (Extreme Fear)

DECISION MATRIX:
- If Leverage AND Sentiment align (e.g., Crowded Longs + Extreme Greed):
  -> Bet AGAINST them with HIGH Confidence (85-95)
- If signals are mixed:
  -> Follow 24h trend with LOW Confidence (55-65)

CONSTRAINTS:
- NO NEUTRALITY: Must always pick a side
- Prioritize Liquidations: If Long/Short ratio is extreme, IGNORE news and price trend
- Be Decisive: No "market is uncertain" - say "High leverage signals a squeeze"
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.data.market_data import MarketDataFetcher
from src.strategy.base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default parameter values
DEFAULTS = {
    "fear_greed_extreme_fear": 20,
    "fear_greed_extreme_greed": 80,
    "long_short_crowded_longs": 2.5,
    "long_short_crowded_shorts": 0.4,
    "funding_rate_high": 0.0005,
    "funding_rate_low": -0.0002,
    "high_confidence_min": 85,
    "low_confidence_min": 60,
    # Data
    "kline_interval": "1h",
    "kline_count": 200,
    # Exit: ATR Trailing Stop
    "trailing_stop_enabled": True,
    "trailing_breakeven_atr": 1.0,
    "trailing_trail_atr": 1.5,
    "atr_period": 14,
    # Exit: Thesis invalidation
    "exit_on_thesis_invalid": True,
    "thesis_cooldown_minutes": 30,
    # Exit: Max hold time (only closes in profit)
    "max_hold_hours": 24,
}

RISK_PROFILES = {
    "standard": {},  # = DEFAULTS
    "conservative": {
        "long_short_crowded_longs": 3.0,
        "long_short_crowded_shorts": 0.3,
        "low_confidence_min": 70,
        "trailing_breakeven_atr": 1.5,
        "trailing_trail_atr": 2.5,
        "thesis_cooldown_minutes": 60,
        "max_hold_hours": 48,
    },
    "aggressive": {
        "long_short_crowded_longs": 2.0,
        "long_short_crowded_shorts": 0.5,
        "low_confidence_min": 50,
        "trailing_breakeven_atr": 0.5,
        "trailing_trail_atr": 1.0,
        "thesis_cooldown_minutes": 15,
        "max_hold_hours": 12,
    },
}


class LiquidationHunterStrategy(BaseStrategy):
    """
    Contrarian Liquidation Hunter Strategy Implementation.

    This strategy acts as an institutional market maker, betting against
    the crowd when leverage and sentiment reach extreme levels.
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, data_fetcher: Optional[MarketDataFetcher] = None):
        super().__init__(params)
        self.data_fetcher = data_fetcher
        # Merge: DEFAULTS → RISK_PROFILE → explicit user params
        self._p = {**DEFAULTS, **self.params}
        profile = self._p.get("risk_profile", "standard")
        if profile in RISK_PROFILES:
            for key, val in RISK_PROFILES[profile].items():
                if key not in self.params:  # User has not explicitly overridden
                    self._p[key] = val

    async def _ensure_fetcher(self):
        """Ensure data fetcher is available."""
        if self.data_fetcher is None:
            self.data_fetcher = MarketDataFetcher()
            await self.data_fetcher._ensure_session()

    def _analyze_leverage(self, long_short_ratio: float) -> Tuple[Optional[SignalDirection], int, str]:
        crowded_longs = self._p["long_short_crowded_longs"]
        crowded_shorts = self._p["long_short_crowded_shorts"]

        if long_short_ratio > crowded_longs:
            excess = (long_short_ratio - crowded_longs) / crowded_longs * 100
            confidence_boost = min(int(excess * 2), 30)
            reason = f"Crowded Longs detected (L/S Ratio: {long_short_ratio:.2f} > {crowded_longs}). Long squeeze imminent."
            logger.info(f"LEVERAGE SIGNAL: SHORT (L/S={long_short_ratio:.2f}, boost={confidence_boost})")
            return SignalDirection.SHORT, confidence_boost, reason

        elif long_short_ratio < crowded_shorts:
            excess = (crowded_shorts - long_short_ratio) / crowded_shorts * 100
            confidence_boost = min(int(excess * 2), 30)
            reason = f"Crowded Shorts detected (L/S Ratio: {long_short_ratio:.2f} < {crowded_shorts}). Short squeeze incoming."
            logger.info(f"LEVERAGE SIGNAL: LONG (L/S={long_short_ratio:.2f}, boost={confidence_boost})")
            return SignalDirection.LONG, confidence_boost, reason

        return None, 0, f"L/S Ratio neutral ({long_short_ratio:.2f})"

    def _analyze_funding_rate(self, funding_rate: float, base_direction: Optional[SignalDirection]) -> Tuple[int, str]:
        high_threshold = self._p["funding_rate_high"]
        low_threshold = self._p["funding_rate_low"]
        funding_pct = funding_rate * 100

        if funding_rate > high_threshold:
            adjustment = 20 if base_direction == SignalDirection.SHORT else -10
            reason = f"High Funding Rate ({funding_pct:.4f}%) - expensive to hold longs."
            logger.info(f"FUNDING SIGNAL: Supports SHORT (rate={funding_pct:.4f}%)")
            return adjustment, reason

        elif funding_rate < low_threshold:
            adjustment = 20 if base_direction == SignalDirection.LONG else -10
            reason = f"Negative Funding Rate ({funding_pct:.4f}%) - expensive to hold shorts."
            logger.info(f"FUNDING SIGNAL: Supports LONG (rate={funding_pct:.4f}%)")
            return adjustment, reason

        return 0, f"Funding Rate neutral ({funding_pct:.4f}%)"

    def _analyze_sentiment(self, fear_greed: int) -> Tuple[Optional[SignalDirection], int, str]:
        extreme_fear = self._p["fear_greed_extreme_fear"]
        extreme_greed = self._p["fear_greed_extreme_greed"]

        if fear_greed > extreme_greed:
            excess = fear_greed - extreme_greed
            confidence_boost = min(excess, 20)
            reason = f"Extreme Greed ({fear_greed}) - market euphoria, reversal expected."
            logger.info(f"SENTIMENT SIGNAL: SHORT (FGI={fear_greed})")
            return SignalDirection.SHORT, confidence_boost, reason

        elif fear_greed < extreme_fear:
            excess = extreme_fear - fear_greed
            confidence_boost = min(excess, 20)
            reason = f"Extreme Fear ({fear_greed}) - capitulation phase, bounce expected."
            logger.info(f"SENTIMENT SIGNAL: LONG (FGI={fear_greed})")
            return SignalDirection.LONG, confidence_boost, reason

        return None, 0, f"Sentiment neutral (FGI={fear_greed})"

    def _get_trend_direction(self, price_change_24h: float) -> SignalDirection:
        if price_change_24h > 0:
            return SignalDirection.LONG
        return SignalDirection.SHORT

    def _calculate_targets(self, direction: SignalDirection, current_price: float, klines=None) -> Tuple:
        """Calculate TP/SL prices. Returns (None, None) if not configured by user."""
        tp_pct_raw = self._p.get("take_profit_percent")
        sl_pct_raw = self._p.get("stop_loss_percent")

        take_profit = None
        stop_loss = None

        if tp_pct_raw is not None and current_price > 0:
            tp_pct = float(tp_pct_raw) / 100
            if direction == SignalDirection.LONG:
                take_profit = round(current_price * (1 + tp_pct), 2)
            else:
                take_profit = round(current_price * (1 - tp_pct), 2)

        if sl_pct_raw is not None and current_price > 0:
            sl_pct = float(sl_pct_raw) / 100
            if direction == SignalDirection.LONG:
                stop_loss = round(current_price * (1 - sl_pct), 2)
            else:
                stop_loss = round(current_price * (1 + sl_pct), 2)

        return take_profit, stop_loss

    async def generate_signal(self, symbol: str = "BTCUSDT") -> TradeSignal:
        await self._ensure_fetcher()

        logger.info(f"=== Generating Signal for {symbol} ===")

        try:
            metrics = await self.data_fetcher.fetch_all_metrics()
        except Exception as e:
            logger.error(f"Failed to fetch metrics for {symbol}: {e}")
            return TradeSignal(
                direction=SignalDirection.LONG, confidence=0, symbol=symbol,
                entry_price=0.0, target_price=0.0, stop_loss=0.0,
                reason=f"Metrics fetch failed: {e}", metrics_snapshot={},
                timestamp=datetime.now(),
            )

        # Fetch symbol-specific data (funding rate, price) for the actual traded symbol.
        # fetch_all_metrics only has BTC/ETH — for other symbols we need direct lookups.
        if "BTC" in symbol:
            funding_rate = metrics.funding_rate_btc or 0.0
            current_price = metrics.btc_price or 0.0
            price_change = metrics.btc_24h_change_percent or 0.0
        elif "ETH" in symbol:
            funding_rate = metrics.funding_rate_eth or 0.0
            current_price = metrics.eth_price or 0.0
            price_change = metrics.eth_24h_change_percent or 0.0
        else:
            try:
                funding_rate = await self.data_fetcher.get_funding_rate_binance(symbol) or 0.0
            except Exception as e:
                logger.warning("Failed to fetch funding rate for %s: %s", symbol, e)
                funding_rate = 0.0
            try:
                ticker = await self.data_fetcher.get_24h_ticker(symbol) or {}
                current_price = ticker.get("price", 0)
                price_change = ticker.get("price_change_percent", 0)
            except Exception as e:
                logger.warning("Failed to fetch ticker for %s: %s", symbol, e)
                current_price = 0
                price_change = 0

        reasons = []
        confidence = 50

        # Step 1: Analyze Leverage
        long_short_ratio = metrics.long_short_ratio if metrics.long_short_ratio is not None else 1.0
        leverage_direction, leverage_conf, leverage_reason = self._analyze_leverage(long_short_ratio)
        reasons.append(leverage_reason)
        confidence += leverage_conf

        # Step 2: Analyze Sentiment
        fear_greed = metrics.fear_greed_index if metrics.fear_greed_index is not None else 50
        sentiment_direction, sentiment_conf, sentiment_reason = self._analyze_sentiment(fear_greed)
        reasons.append(sentiment_reason)
        confidence += sentiment_conf

        # Step 3: Determine Direction
        final_direction = None
        high_confidence_min = self._p["high_confidence_min"]
        low_confidence_min = self._p["low_confidence_min"]

        if leverage_direction and sentiment_direction:
            if leverage_direction == sentiment_direction:
                final_direction = leverage_direction
                confidence = max(confidence, high_confidence_min)
                reasons.append(
                    f"ALIGNMENT: Leverage ({leverage_direction.value.upper()}) + "
                    f"Sentiment ({sentiment_direction.value.upper()}) = "
                    f"HIGH CONFIDENCE {leverage_direction.value.upper()}"
                )
            else:
                final_direction = leverage_direction
                confidence = min(confidence, 70)
                reasons.append(
                    f"CONFLICT: Leverage says {leverage_direction.value.upper()}, "
                    f"Sentiment says {sentiment_direction.value.upper()}. "
                    f"Following Leverage signal."
                )
        elif leverage_direction:
            final_direction = leverage_direction
            reasons.append(f"Leverage-driven signal: {leverage_direction.value.upper()}")
        elif sentiment_direction:
            final_direction = sentiment_direction
            reasons.append(f"Sentiment-driven signal: {sentiment_direction.value.upper()}")
        else:
            final_direction = self._get_trend_direction(price_change)
            confidence = max(low_confidence_min, min(confidence, 65))
            reasons.append(
                f"No extreme signals. Following 24h trend "
                f"({price_change:+.2f}%): {final_direction.value.upper()}"
            )

        # Step 4: Analyze Funding Rate
        funding_adj, funding_reason = self._analyze_funding_rate(funding_rate, final_direction)
        confidence += funding_adj
        reasons.append(funding_reason)

        # Step 5: Clamp Confidence
        confidence = max(low_confidence_min, min(confidence, 95))

        # Step 6: Calculate Targets
        if current_price <= 0:
            logger.error(f"Invalid price for {symbol}: {current_price}.")
            take_profit, stop_loss = 0.0, 0.0
        else:
            take_profit, stop_loss = self._calculate_targets(final_direction, current_price)

        full_reason = " | ".join(reasons)

        signal = TradeSignal(
            direction=final_direction,
            confidence=confidence,
            symbol=symbol,
            entry_price=current_price,
            target_price=take_profit,
            stop_loss=stop_loss,
            reason=full_reason,
            metrics_snapshot=metrics.to_dict(),
            timestamp=datetime.now(),
        )

        logger.info(f"=== SIGNAL: {signal.direction.value.upper()} {signal.confidence}% @ ${signal.entry_price:,.2f} ===")

        return signal

    async def should_trade(self, signal: TradeSignal) -> Tuple[bool, str]:
        min_confidence = self._p["low_confidence_min"]

        if signal.confidence < min_confidence:
            return False, f"Confidence ({signal.confidence}%) below minimum ({min_confidence}%)"

        if signal.entry_price <= 0:
            return False, "Invalid entry price"

        # Validate TP/SL direction if set
        if signal.target_price is not None and signal.stop_loss is not None:
            if signal.direction == SignalDirection.LONG:
                if signal.target_price <= signal.entry_price:
                    return False, f"TP ({signal.target_price}) must be above entry ({signal.entry_price}) for LONG"
                if signal.stop_loss >= signal.entry_price:
                    return False, f"SL ({signal.stop_loss}) must be below entry ({signal.entry_price}) for LONG"
            else:
                if signal.target_price >= signal.entry_price:
                    return False, f"TP ({signal.target_price}) must be below entry ({signal.entry_price}) for SHORT"
                if signal.stop_loss <= signal.entry_price:
                    return False, f"SL ({signal.stop_loss}) must be above entry ({signal.entry_price}) for SHORT"

        return True, f"Signal approved with {signal.confidence}% confidence"

    # ------------------------------------------------------------------
    # Exit logic (3 layers)
    # ------------------------------------------------------------------

    async def should_exit(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        metrics_at_entry: dict | None = None,
        current_price: float | None = None,
        highest_price: float | None = None,
        entry_time: datetime | None = None,
        **kwargs,
    ) -> Tuple[bool, str]:
        """Check if an open position should be closed.

        3-layer exit system:
        1. ATR Trailing Stop — protect profits (aggressive, cascade-tuned)
        2. Thesis Invalidation — L/S ratio + sentiment normalized
        3. Max Hold Time — close after N hours, but only when in profit
        """
        try:
            await self._ensure_fetcher()

            interval = self._p["kline_interval"]
            count = self._p["kline_count"]
            klines = await self.data_fetcher.get_binance_klines(symbol, interval, count)

            if current_price is None and klines:
                try:
                    current_price = float(klines[-1][4])
                except (IndexError, ValueError, TypeError):
                    pass

            if not current_price or not entry_price:
                return False, "Missing price data for exit check"

            # --- Layer 1: ATR Trailing Stop ---
            if self._p.get("trailing_stop_enabled") and highest_price and klines:
                trail_exit, trail_reason = self._check_trailing_stop(
                    side, entry_price, current_price, highest_price, klines,
                )
                if trail_exit:
                    return True, trail_reason

            # --- Layer 2: Thesis Invalidation ---
            if self._p.get("exit_on_thesis_invalid") and entry_time:
                cooldown_mins = self._p.get("thesis_cooldown_minutes", 30)
                now = datetime.now(timezone.utc)
                entry_utc = entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=timezone.utc)
                elapsed_mins = (now - entry_utc).total_seconds() / 60

                if elapsed_mins >= cooldown_mins:
                    thesis_exit, thesis_reason = await self._check_thesis_invalidation(
                        side, metrics_at_entry,
                    )
                    if thesis_exit:
                        return True, thesis_reason

            # --- Layer 3: Max Hold Time (only in profit) ---
            max_hours = self._p.get("max_hold_hours")
            if max_hours and entry_time:
                now = datetime.now(timezone.utc)
                entry_utc = entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=timezone.utc)
                elapsed_hours = (now - entry_utc).total_seconds() / 3600

                if elapsed_hours >= max_hours:
                    if side == "long":
                        in_profit = current_price > entry_price
                    else:
                        in_profit = current_price < entry_price

                    if in_profit:
                        pnl_pct = abs(current_price - entry_price) / entry_price * 100
                        return True, (
                            "Max Haltezeit: %.0fh überschritten (Limit: %.0fh). "
                            "Trade im Profit (+%.2f%%), Gewinnmitnahme."
                            % (elapsed_hours, max_hours, pnl_pct)
                        )
                    else:
                        logger.debug(
                            "[%s] Max hold reached (%.0fh) but trade in loss — keeping open",
                            symbol, elapsed_hours,
                        )

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
        """ATR-based trailing stop with breakeven floor."""
        atr_series = MarketDataFetcher.calculate_atr(klines, self._p["atr_period"])
        atr_val = atr_series[-1] if atr_series else current_price * 0.015

        breakeven_atr = self._p.get("trailing_breakeven_atr", 1.0)
        trail_atr = self._p.get("trailing_trail_atr", 1.5)
        trail_distance = atr_val * trail_atr
        breakeven_threshold = atr_val * breakeven_atr

        if side == "long":
            was_profitable = (highest_price - entry_price) >= breakeven_threshold
            if not was_profitable:
                return False, ""

            trailing_stop = max(highest_price - trail_distance, entry_price)
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

            trailing_stop = min(highest_price + trail_distance, entry_price)
            if current_price >= trailing_stop:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                return True, (
                    "Trailing Stop: Preis $%.2f über Stop $%.2f "
                    "(Tiefst=$%.2f, ATR=%.0f, Trail=%.1fx). PnL=%.2f%%"
                    % (current_price, trailing_stop, highest_price, atr_val, trail_atr, pnl_pct)
                )

        return False, ""

    async def _check_thesis_invalidation(
        self,
        side: str,
        metrics_at_entry: dict | None,
    ) -> Tuple[bool, str]:
        """Check if the original entry thesis is still valid.

        The thesis is invalidated when:
        - L/S ratio returns to neutral range (no longer crowded)
        - AND sentiment returns to neutral range (no longer extreme)
        """
        try:
            metrics = await self.data_fetcher.fetch_all_metrics()
        except Exception as e:
            logger.warning("Thesis check: metrics fetch failed: %s", e)
            return False, ""

        long_short_ratio = metrics.long_short_ratio if metrics.long_short_ratio is not None else 1.0
        fear_greed = metrics.fear_greed_index if metrics.fear_greed_index is not None else 50

        crowded_longs = self._p["long_short_crowded_longs"]
        crowded_shorts = self._p["long_short_crowded_shorts"]
        extreme_fear = self._p["fear_greed_extreme_fear"]
        extreme_greed = self._p["fear_greed_extreme_greed"]

        # Check if L/S ratio has normalized (back in neutral range)
        ratio_neutral = crowded_shorts <= long_short_ratio <= crowded_longs

        # Check if sentiment has normalized
        sentiment_neutral = extreme_fear <= fear_greed <= extreme_greed

        if ratio_neutral and sentiment_neutral:
            return True, (
                "These invalidiert: L/S Ratio normalisiert (%.2f, neutral: %.1f-%.1f) "
                "und Sentiment neutral (FGI=%d, neutral: %d-%d). Kaskaden-Potenzial aufgebraucht."
                % (long_short_ratio, crowded_shorts, crowded_longs,
                   fear_greed, extreme_fear, extreme_greed)
            )

        return False, ""

    @classmethod
    def get_description(cls) -> str:
        return (
            "Contrarian strategy that bets against crowded positions. "
            "Analyzes leverage ratios, funding rates, and Fear & Greed sentiment "
            "to identify liquidation cascade opportunities."
        )

    @classmethod
    def get_param_schema(cls) -> Dict[str, Any]:
        return {
            "risk_profile": {
                "type": "select",
                "label": "Risikoprofil",
                "description": (
                    "Konservativ = weniger Trades, weite Stops, längere Haltezeit. "
                    "Standard = ausgewogen. "
                    "Aggressiv = mehr Trades, enge Stops, schnelle Gewinnmitnahme."
                ),
                "default": "standard",
                "options": ["conservative", "standard", "aggressive"],
            },
            "fear_greed_extreme_fear": {
                "type": "int",
                "label": "Extreme-Angst-Schwelle",
                "description": "Fear & Greed unter diesem Wert = Extreme Angst (LONG gehen)",
                "default": 20,
                "min": 5,
                "max": 40,
            },
            "fear_greed_extreme_greed": {
                "type": "int",
                "label": "Extreme-Gier-Schwelle",
                "description": "Fear & Greed über diesem Wert = Extreme Gier (SHORT gehen)",
                "default": 80,
                "min": 60,
                "max": 95,
            },
            "funding_rate_high": {
                "type": "float",
                "label": "Hohe Funding Rate",
                "description": "Funding Rate über diesem Wert verstärkt SHORT (z.B. 0.0005 = 0.05%)",
                "default": 0.0005,
                "min": 0.0001,
                "max": 0.005,
            },
            "funding_rate_low": {
                "type": "float",
                "label": "Niedrige Funding Rate",
                "description": "Funding Rate unter diesem Wert verstärkt LONG (z.B. -0.0002 = -0.02%)",
                "default": -0.0002,
                "min": -0.005,
                "max": -0.0001,
            },
        }

    async def close(self):
        """Clean up resources."""
        if self.data_fetcher:
            await self.data_fetcher.close()


# Register with the strategy registry
StrategyRegistry.register("liquidation_hunter", LiquidationHunterStrategy)
