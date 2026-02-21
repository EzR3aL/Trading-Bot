"""
SentimentSurfer Strategy

ROLE: Balanced signal generator that combines market sentiment with technical indicators.

CORE LOGIC:
6 data sources, each scored -100 to +100, aggregated with configurable weights.

1. News Sentiment (GDELT): Positive media tone = bullish, negative = bearish
2. Fear & Greed Index: Contrarian - extreme fear = bullish, extreme greed = bearish
3. VWAP/OIWAP: Price above fair value = bullish momentum, below = bearish
4. Supertrend: ATR-based trend direction - green = bullish, red = bearish
5. Spot Volume: Taker buy dominance = accumulation, sell dominance = distribution
6. Price Momentum: 24h price change direction and magnitude

DECISION:
- Weighted average of all scores determines direction and confidence
- Requires minimum source agreement (default 3 of 6) for trade entry
- "Focus on balance" = no single source dominates, all must confirm
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.data.market_data import MarketDataFetcher
from src.strategy.base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default parameter values
DEFAULTS = {
    # Fear & Greed thresholds (contrarian)
    "fear_greed_extreme_fear": 25,
    "fear_greed_extreme_greed": 75,
    # Supertrend parameters
    "supertrend_atr_period": 10,
    "supertrend_multiplier": 3.0,
    # VWAP/OIWAP
    "vwap_period_hours": 24,
    "use_oiwap": True,
    # Volume analysis
    "volume_period_hours": 24,
    # News sentiment
    "news_lookback_hours": 24,
    # Scoring weights
    "weight_news": 1.0,
    "weight_fear_greed": 1.0,
    "weight_vwap": 1.2,
    "weight_supertrend": 1.2,
    "weight_volume": 0.8,
    "weight_momentum": 0.8,
    # Trade filters
    "min_agreement": 3,
    "min_confidence": 40,
    # Risk
    "take_profit_percent": 3.5,
    "stop_loss_percent": 1.5,
    # Data
    "kline_interval": "1h",
    "kline_count": 200,
}


class SentimentSurferStrategy(BaseStrategy):
    """
    Balanced strategy combining market sentiment with technical indicators.

    Uses 6 data sources with weighted scoring to generate trade signals.
    Requires minimum source agreement before entering a trade.
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

    # ==================== Scoring Functions ====================

    def _score_news_sentiment(self, average_tone: float) -> Tuple[float, str]:
        """Score news sentiment from GDELT tone (-10 to +10)."""
        if abs(average_tone) <= 1.0:
            return 0.0, f"News neutral (tone={average_tone:.2f})"

        if average_tone > 3.0:
            score = min(average_tone * 15, 100)
        elif average_tone < -3.0:
            score = max(average_tone * 15, -100)
        else:
            score = average_tone * 10

        direction = "bullish" if score > 0 else "bearish"
        return score, f"News {direction} (tone={average_tone:.2f}, score={score:.0f})"

    def _score_fear_greed(self, fgi: int) -> Tuple[float, str]:
        """Score Fear & Greed Index (contrarian)."""
        extreme_fear = self._p["fear_greed_extreme_fear"]
        extreme_greed = self._p["fear_greed_extreme_greed"]

        if fgi < extreme_fear:
            score = (extreme_fear - fgi) * 3
            return min(score, 100), f"Extreme Fear ({fgi}) - contrarian bullish (score={score:.0f})"
        elif fgi > extreme_greed:
            score = -(fgi - extreme_greed) * 3
            return max(score, -100), f"Extreme Greed ({fgi}) - contrarian bearish (score={score:.0f})"

        return 0.0, f"Sentiment neutral (FGI={fgi})"

    def _score_vwap(self, current_price: float, vwap: float, oiwap: float = 0.0) -> Tuple[float, str]:
        """Score price position relative to VWAP (and OIWAP if available)."""
        if vwap <= 0 or current_price <= 0:
            return 0.0, "VWAP data unavailable"

        # Blend VWAP and OIWAP when available
        if oiwap > 0 and self._p.get("use_oiwap", True):
            reference_price = 0.6 * vwap + 0.4 * oiwap
            label = "VWAP/OIWAP"
        else:
            reference_price = vwap
            label = "VWAP"

        deviation = (current_price - reference_price) / reference_price

        if abs(deviation) < 0.005:  # Within 0.5% = neutral
            return 0.0, f"Price near {label} ({deviation:+.2%})"

        score = max(min(deviation * 2000, 100), -100)
        direction = "above" if score > 0 else "below"
        return score, f"Price {direction} {label} ({deviation:+.2%}, score={score:.0f})"

    def _score_supertrend(self, supertrend: Dict[str, Any]) -> Tuple[float, str]:
        """Score Supertrend indicator direction."""
        direction = supertrend.get("direction", "neutral")

        if direction == "bullish":
            return 70.0, f"Supertrend GREEN (uptrend, value={supertrend.get('value', 0):.2f})"
        elif direction == "bearish":
            return -70.0, f"Supertrend RED (downtrend, value={supertrend.get('value', 0):.2f})"

        return 0.0, "Supertrend neutral"

    def _score_spot_volume(self, volume_data: Dict[str, Any]) -> Tuple[float, str]:
        """Score spot volume buy/sell ratio."""
        buy_ratio = volume_data.get("buy_ratio", 0.5)

        if abs(buy_ratio - 0.5) < 0.05:  # Within 45-55% = neutral
            return 0.0, f"Volume balanced (buy={buy_ratio:.1%})"

        score = max(min((buy_ratio - 0.5) * 400, 100), -100)
        label = "accumulation" if score > 0 else "distribution"
        return score, f"Volume {label} (buy={buy_ratio:.1%}, score={score:.0f})"

    def _score_momentum(self, price_change_24h: float) -> Tuple[float, str]:
        """Score 24h price momentum."""
        if abs(price_change_24h) < 0.5:  # Less than 0.5% = noise
            return 0.0, f"Momentum flat ({price_change_24h:+.2f}%)"

        if abs(price_change_24h) > 2.0:
            score = max(min(price_change_24h * 20, 100), -100)
        else:
            score = price_change_24h * 15

        direction = "bullish" if score > 0 else "bearish"
        return score, f"Momentum {direction} ({price_change_24h:+.2f}%, score={score:.0f})"

    # ==================== Aggregation ====================

    def _aggregate_scores(
        self, scores: List[Tuple[float, str, str]]
    ) -> Tuple[SignalDirection, int, int, str]:
        """
        Aggregate all source scores into a final signal.

        Args:
            scores: List of (score, reason, weight_key) tuples

        Returns:
            (direction, confidence, agreement_count, combined_reason)
        """
        weight_keys = {
            "news": self._p["weight_news"],
            "fear_greed": self._p["weight_fear_greed"],
            "vwap": self._p["weight_vwap"],
            "supertrend": self._p["weight_supertrend"],
            "volume": self._p["weight_volume"],
            "momentum": self._p["weight_momentum"],
        }

        total_weighted = 0.0
        total_weight = 0.0
        reasons = []

        for score, reason, key in scores:
            weight = weight_keys.get(key, 1.0)
            total_weighted += score * weight
            total_weight += weight
            reasons.append(reason)

        if total_weight == 0:
            return SignalDirection.LONG, 0, 0, "No data available"

        weighted_score = total_weighted / total_weight

        # Direction
        direction = SignalDirection.LONG if weighted_score >= 0 else SignalDirection.SHORT

        # Confidence (absolute weighted score, capped at 95)
        confidence = min(int(abs(weighted_score)), 95)

        # Agreement count
        if direction == SignalDirection.LONG:
            agreement = sum(1 for s, _, _ in scores if s > 0)
        else:
            agreement = sum(1 for s, _, _ in scores if s < 0)

        return direction, confidence, agreement, " | ".join(reasons)

    def _calculate_targets(
        self, direction: SignalDirection, current_price: float
    ) -> Tuple[float, float]:
        """Calculate take profit and stop loss prices."""
        tp_pct = self._p["take_profit_percent"] / 100
        sl_pct = self._p["stop_loss_percent"] / 100

        if direction == SignalDirection.LONG:
            take_profit = current_price * (1 + tp_pct)
            stop_loss = current_price * (1 - sl_pct)
        else:
            take_profit = current_price * (1 - tp_pct)
            stop_loss = current_price * (1 + sl_pct)

        return round(take_profit, 2), round(stop_loss, 2)

    # ==================== Signal Generation ====================

    async def generate_signal(self, symbol: str = "BTCUSDT") -> TradeSignal:
        """Generate a trade signal using all 6 data sources."""
        await self._ensure_fetcher()

        logger.info(f"=== SentimentSurfer: Generating Signal for {symbol} ===")

        period = self._p["vwap_period_hours"]
        interval = self._p["kline_interval"]
        kline_count = self._p["kline_count"]

        # Fetch all data in parallel
        results = await asyncio.gather(
            self.data_fetcher.fetch_all_metrics(require_reliable=False),
            self.data_fetcher.get_news_sentiment(lookback_hours=self._p["news_lookback_hours"]),
            self.data_fetcher.get_binance_klines(symbol, interval, max(period, kline_count)),
            return_exceptions=True,
        )

        # Unpack with error handling
        if isinstance(results[0], Exception):
            logger.error(f"Failed to fetch base metrics: {results[0]}")
            metrics = None
        else:
            metrics = results[0]

        if isinstance(results[1], Exception):
            logger.error(f"Failed to fetch news sentiment: {results[1]}")
            news = {"average_tone": 0.0, "article_count": 0}
        else:
            news = results[1]

        if isinstance(results[2], Exception):
            logger.error(f"Failed to fetch klines: {results[2]}")
            klines = []
        else:
            klines = results[2]

        # Get price data
        if "BTC" in symbol:
            current_price = metrics.btc_price if metrics else 0
            price_change = metrics.btc_24h_change_percent if metrics else 0
        else:
            current_price = metrics.eth_price if metrics else 0
            price_change = metrics.eth_24h_change_percent if metrics else 0

        fear_greed = metrics.fear_greed_index if metrics else 50

        # Calculate technical indicators from klines
        vwap = MarketDataFetcher.calculate_vwap(klines)
        supertrend = MarketDataFetcher.calculate_supertrend(
            klines,
            atr_period=self._p["supertrend_atr_period"],
            multiplier=self._p["supertrend_multiplier"],
        )
        volume_data = MarketDataFetcher.get_spot_volume_analysis(klines)

        # Calculate OIWAP if enabled
        oiwap = 0.0
        if self._p.get("use_oiwap", True) and klines:
            oiwap = await self.data_fetcher.calculate_oiwap(symbol, klines, period)

        # Score all 6 sources
        scores: List[Tuple[float, str, str]] = [
            (*self._score_news_sentiment(news.get("average_tone", 0)), "news"),
            (*self._score_fear_greed(fear_greed), "fear_greed"),
            (*self._score_vwap(current_price, vwap, oiwap), "vwap"),
            (*self._score_supertrend(supertrend), "supertrend"),
            (*self._score_spot_volume(volume_data), "volume"),
            (*self._score_momentum(price_change), "momentum"),
        ]

        # Log individual scores
        for score, reason, key in scores:
            logger.info(f"  [{key}] score={score:+.0f} | {reason}")

        # Aggregate
        direction, confidence, agreement, full_reason = self._aggregate_scores(scores)

        # Calculate targets
        if current_price <= 0:
            logger.error(f"Invalid price for {symbol}: {current_price}")
            take_profit, stop_loss = 0.0, 0.0
        else:
            take_profit, stop_loss = self._calculate_targets(direction, current_price)

        # Build metrics snapshot
        snapshot = {}
        if metrics:
            snapshot = metrics.to_dict()
        snapshot["news_tone"] = news.get("average_tone", 0)
        snapshot["news_articles"] = news.get("article_count", 0)
        snapshot["vwap"] = vwap
        snapshot["oiwap"] = oiwap
        snapshot["supertrend"] = supertrend
        snapshot["volume_buy_ratio"] = volume_data.get("buy_ratio", 0.5)
        snapshot["agreement"] = f"{agreement}/6"
        snapshot["scores"] = {key: score for score, _, key in scores}

        signal = TradeSignal(
            direction=direction,
            confidence=confidence,
            symbol=symbol,
            entry_price=current_price,
            target_price=take_profit,
            stop_loss=stop_loss,
            reason=full_reason,
            metrics_snapshot=snapshot,
            timestamp=datetime.now(),
        )

        logger.info(
            f"=== SIGNAL: {signal.direction.value.upper()} {signal.confidence}% "
            f"@ ${signal.entry_price:,.2f} (agreement: {agreement}/6) ==="
        )

        return signal

    async def should_trade(self, signal: TradeSignal) -> Tuple[bool, str]:
        """Gate: check confidence and source agreement."""
        min_confidence = self._p["min_confidence"]
        min_agreement = self._p["min_agreement"]

        if signal.entry_price <= 0:
            return False, "Invalid entry price"

        agreement = int(signal.metrics_snapshot.get("agreement", "0/6").split("/")[0])

        if agreement < min_agreement:
            return False, (
                f"Insufficient agreement: {agreement}/6 sources agree "
                f"(need {min_agreement})"
            )

        if signal.confidence < min_confidence:
            return False, (
                f"Confidence ({signal.confidence}%) below minimum ({min_confidence}%)"
            )

        return True, (
            f"Signal approved: {signal.confidence}% confidence, "
            f"{agreement}/6 sources agree"
        )

    @classmethod
    def get_description(cls) -> str:
        return (
            "Combines market sentiment with technical indicators to predict price movements. "
            "Uses 6 data sources: News (GDELT), Fear & Greed, VWAP/OIWAP, Supertrend, "
            "Spot Volume, and Price Momentum. Requires balanced agreement across sources."
        )

    @classmethod
    def get_param_schema(cls) -> Dict[str, Any]:
        return {
            "fear_greed_extreme_fear": {
                "type": "int",
                "label": "Extreme-Angst-Schwelle",
                "description": "Fear & Greed unter diesem Wert = konträres Bullish-Signal",
                "default": 25,
                "min": 5,
                "max": 45,
            },
            "fear_greed_extreme_greed": {
                "type": "int",
                "label": "Extreme-Gier-Schwelle",
                "description": "Fear & Greed über diesem Wert = konträres Bearish-Signal",
                "default": 75,
                "min": 55,
                "max": 95,
            },
            "supertrend_atr_period": {
                "type": "int",
                "label": "Supertrend ATR Periode",
                "description": "Anzahl Kerzen für ATR-Berechnung (höher = glätter)",
                "default": 10,
                "min": 5,
                "max": 30,
            },
            "supertrend_multiplier": {
                "type": "float",
                "label": "Supertrend Multiplikator",
                "description": "ATR-Multiplikator für Bandbreite (höher = weniger Signale)",
                "default": 3.0,
                "min": 1.0,
                "max": 6.0,
            },
            "vwap_period_hours": {
                "type": "int",
                "label": "VWAP Periode (Stunden)",
                "description": "Anzahl Stunden für die VWAP-Berechnung",
                "default": 24,
                "min": 4,
                "max": 72,
            },
            "use_oiwap": {
                "type": "bool",
                "label": "OIWAP verwenden",
                "description": "OI-gewichteten Durchschnittspreis mit VWAP mischen (für genaueren Fair Value)",
                "default": True,
            },
            "weight_news": {
                "type": "float",
                "label": "Nachrichten-Gewichtung",
                "description": "Gewichtung der GDELT-Nachrichten-Stimmung im Scoring",
                "default": 1.0,
                "min": 0.0,
                "max": 3.0,
            },
            "weight_fear_greed": {
                "type": "float",
                "label": "Fear & Greed Gewichtung",
                "description": "Gewichtung des Fear & Greed Index im Scoring",
                "default": 1.0,
                "min": 0.0,
                "max": 3.0,
            },
            "weight_vwap": {
                "type": "float",
                "label": "VWAP Gewichtung",
                "description": "Gewichtung der VWAP/OIWAP-Position im Scoring",
                "default": 1.2,
                "min": 0.0,
                "max": 3.0,
            },
            "weight_supertrend": {
                "type": "float",
                "label": "Supertrend Gewichtung",
                "description": "Gewichtung des Supertrend-Indikators im Scoring",
                "default": 1.2,
                "min": 0.0,
                "max": 3.0,
            },
            "weight_volume": {
                "type": "float",
                "label": "Volumen-Gewichtung",
                "description": "Gewichtung der Spot-Volumen-Analyse im Scoring",
                "default": 0.8,
                "min": 0.0,
                "max": 3.0,
            },
            "weight_momentum": {
                "type": "float",
                "label": "Momentum-Gewichtung",
                "description": "Gewichtung des 24h-Preis-Momentums im Scoring",
                "default": 0.8,
                "min": 0.0,
                "max": 3.0,
            },
            "min_agreement": {
                "type": "int",
                "label": "Min. Quellen-Übereinstimmung",
                "description": "Mindestanzahl Quellen die übereinstimmen müssen (von 6)",
                "default": 3,
                "min": 1,
                "max": 6,
            },
            "min_confidence": {
                "type": "int",
                "label": "Min. Konfidenz",
                "description": "Minimaler Konfidenz-Score um einen Trade auszuführen",
                "default": 40,
                "min": 10,
                "max": 80,
            },
        }

    async def close(self):
        """Clean up resources."""
        if self.data_fetcher:
            await self.data_fetcher.close()


# Register with the strategy registry
StrategyRegistry.register("sentiment_surfer", SentimentSurferStrategy)
