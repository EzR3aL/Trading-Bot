"""
Claude Edge Strategy — Hybrid: Technical Analysis + LLM Evaluation.

CORE LOGIC:
1. Calculates the same technical indicators as Edge Indicator (RSI, MACD, BB)
2. Collects sentiment data (Fear & Greed, News)
3. Sends everything to an LLM with a specialized prompt
4. LLM evaluates whether the technical signals make sense in current context

Combines the speed of technical analysis with the contextual understanding of LLMs.

DATA SOURCES: spot_price, fear_greed, news_sentiment, vwap, supertrend,
              spot_volume, volatility, funding_rate
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.ai.providers import get_provider_class
from src.ai.providers.base import LLMResponse, sanitize_error, sanitize_text
from src.data.market_data import MarketDataFetcher
from src.strategy.base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _calculate_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calculate_macd(
    closes: List[float], fast: int = 12, slow: int = 26, signal_period: int = 9
) -> Tuple[float, float, float]:
    if len(closes) < slow + signal_period:
        return 0.0, 0.0, 0.0

    def _ema(data: List[float], period: int) -> List[float]:
        k = 2.0 / (period + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal_period)
    macd_val = macd_line[-1]
    signal_val = signal_line[-1]
    return macd_val, signal_val, macd_val - signal_val


def _calculate_bollinger(
    closes: List[float], period: int = 20, num_std: float = 2.0
) -> Tuple[float, float, float]:
    if len(closes) < period:
        return 0.0, 0.0, 0.0
    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((x - middle) ** 2 for x in window) / period
    std = variance ** 0.5
    return middle, middle + num_std * std, middle - num_std * std


CLAUDE_EDGE_SOURCES: List[str] = [
    "spot_price",
    "fear_greed",
    "news_sentiment",
    "vwap",
    "supertrend",
    "spot_volume",
    "volatility",
    "funding_rate",
]

CLAUDE_EDGE_PROMPT = """You are an expert crypto trading analyst. You are given both technical indicators AND market sentiment data.

Your task: Evaluate whether the TECHNICAL signals are reliable in the current market context.

TECHNICAL INDICATORS:
{technical_summary}

MARKET CONTEXT:
{market_context}

ANALYSIS RULES:
1. Technical signals in trending markets are more reliable than in choppy markets.
2. Extreme sentiment (fear/greed) can override technical signals — watch for reversals.
3. High volatility reduces confidence in all signals.
4. Funding rate extremes suggest overcrowded positions — contrarian signals may be stronger.
5. News sentiment can catalyze or invalidate technical setups.

CRITICAL: You MUST choose a direction. No neutral stances.

Respond in this EXACT format:
DIRECTION: [LONG or SHORT]
CONFIDENCE: [0-100]
REASONING: [2-3 sentences explaining your analysis]"""

DEFAULTS = {
    "rsi_period": 14,
    "bb_period": 20,
    "bb_std": 2.0,
    "min_confidence": 60,
    "take_profit_percent": 3.0,
    "stop_loss_percent": 1.5,
}


class ClaudeEdgeStrategy(BaseStrategy):
    """Hybrid strategy: Technical indicators + LLM contextual evaluation."""

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self._p = {**DEFAULTS, **self.params}
        self.data_fetcher: Optional[MarketDataFetcher] = None

        self.llm_provider_name = self.params.get("llm_provider", "groq")
        self.llm_model = self.params.get("llm_model", "")
        self.llm_api_key = self.params.get("llm_api_key", "")
        self.temperature = float(self.params.get("temperature", 0.3))

        if not self.llm_api_key:
            raise ValueError(
                f"No API key provided for LLM provider '{self.llm_provider_name}'. "
                "Configure it in Settings -> LLM Keys."
            )

        provider_class = get_provider_class(self.llm_provider_name)
        self.provider = provider_class(
            self.llm_api_key,
            model_override=self.llm_model or None,
        )

        tp_raw = self.params.get("take_profit_percent")
        sl_raw = self.params.get("stop_loss_percent")
        self.take_profit_percent = float(tp_raw) if tp_raw is not None else None
        self.stop_loss_percent = float(sl_raw) if sl_raw is not None else None

    async def _ensure_fetcher(self):
        if self.data_fetcher is None:
            self.data_fetcher = MarketDataFetcher()
            await self.data_fetcher._ensure_session()

    def _build_technical_summary(
        self, rsi: float, macd: float, signal: float, histogram: float,
        bb_upper: float, bb_middle: float, bb_lower: float,
        current_price: float, vwap: float, supertrend: Dict[str, Any],
        volume_data: Dict[str, Any],
    ) -> str:
        lines = [
            f"Current Price: ${current_price:,.2f}",
            f"RSI(14): {rsi:.1f} ({'OVERSOLD' if rsi < 30 else 'OVERBOUGHT' if rsi > 70 else 'neutral'})",
            f"MACD: {macd:.6f}, Signal: {signal:.6f}, Histogram: {histogram:.6f} ({'bullish' if histogram > 0 else 'bearish'})",
            f"Bollinger Bands: Upper=${bb_upper:,.2f}, Middle=${bb_middle:,.2f}, Lower=${bb_lower:,.2f}",
            f"  Price position: {'below lower band (oversold)' if current_price < bb_lower else 'above upper band (overbought)' if current_price > bb_upper else 'within bands'}",
            f"VWAP: ${vwap:,.2f} (price {'above' if current_price > vwap else 'below'} by {abs(current_price - vwap) / vwap * 100:.2f}%)",
            f"Supertrend: {supertrend.get('direction', 'unknown')} (value=${supertrend.get('value', 0):,.2f})",
            f"Volume: Buy ratio {volume_data.get('buy_ratio', 0.5):.1%}",
        ]
        return "\n".join(lines)

    def _build_market_context(self, fetched: Dict[str, Any]) -> str:
        lines = []

        if "fear_greed" in fetched:
            fg = fetched["fear_greed"]
            if isinstance(fg, tuple) and len(fg) == 2:
                lines.append(f"Fear & Greed Index: {fg[0]} ({fg[1]})")

        if "news_sentiment" in fetched and isinstance(fetched["news_sentiment"], dict):
            ns = fetched["news_sentiment"]
            tone = ns.get("average_tone", 0)
            count = ns.get("article_count", 0)
            lines.append(f"News Sentiment: tone={tone:.2f} ({count} articles)")

        if "volatility" in fetched:
            rv = float(fetched["volatility"])
            level = "low" if rv < 2 else "moderate" if rv < 5 else "high"
            lines.append(f"Realized Volatility (24h): {rv:.2f}% ({level})")

        if "funding_rate" in fetched:
            fr = float(fetched["funding_rate"])
            bias = "longs paying" if fr > 0 else "shorts paying" if fr < 0 else "neutral"
            lines.append(f"Funding Rate: {fr:.6f} ({bias})")

        return "\n".join(lines) if lines else "No additional market context available."

    async def generate_signal(self, symbol: str) -> TradeSignal:
        await self._ensure_fetcher()
        logger.info(f"[ClaudeEdge:{self.llm_provider_name}] Generating signal for {symbol}...")

        # Fetch klines + market data in parallel
        klines_coro = self.data_fetcher.get_binance_klines(symbol, "1h", 50)
        metrics_coro = self.data_fetcher.fetch_selected_metrics(CLAUDE_EDGE_SOURCES, symbol)

        results = await asyncio.gather(klines_coro, metrics_coro, return_exceptions=True)

        klines = results[0] if not isinstance(results[0], Exception) else []
        fetched = results[1] if not isinstance(results[1], Exception) else {}

        if isinstance(results[0], Exception):
            logger.error(f"[ClaudeEdge] Kline fetch error: {results[0]}")
        if isinstance(results[1], Exception):
            logger.error(f"[ClaudeEdge] Metrics fetch error: {results[1]}")

        # Get current price
        current_price = 0.0
        if "spot_price" in fetched and isinstance(fetched["spot_price"], dict):
            current_price = fetched["spot_price"].get("price", 0)
        elif klines and len(klines) > 0:
            current_price = float(klines[-1][4])

        # Calculate technical indicators
        closes = [float(k[4]) for k in klines] if klines else []
        rsi = _calculate_rsi(closes, self._p["rsi_period"]) if closes else 50.0
        macd_val, signal_val, histogram = _calculate_macd(closes) if closes else (0, 0, 0)
        bb_middle, bb_upper, bb_lower = _calculate_bollinger(
            closes, self._p["bb_period"], self._p["bb_std"]
        ) if closes else (0, 0, 0)

        supertrend = MarketDataFetcher.calculate_supertrend(klines) if klines else {}
        volume_data = MarketDataFetcher.get_spot_volume_analysis(klines) if klines else {}
        vwap = MarketDataFetcher.calculate_vwap(klines) if klines else 0.0

        # Build prompts
        technical_summary = self._build_technical_summary(
            rsi, macd_val, signal_val, histogram,
            bb_upper, bb_middle, bb_lower,
            current_price, vwap, supertrend, volume_data,
        )
        market_context = self._build_market_context(fetched)

        prompt = CLAUDE_EDGE_PROMPT.format(
            technical_summary=technical_summary,
            market_context=market_context,
        )

        logger.info(f"[ClaudeEdge:{self.llm_provider_name}] Sending to {self.provider.get_display_name()}...")

        try:
            llm_response: LLMResponse = await self.provider.generate_signal(
                prompt=prompt,
                market_data={"_raw_user_message": f"Analyze {symbol} and provide your trading decision."},
                temperature=self.temperature,
            )
        except Exception as e:
            logger.error(f"[ClaudeEdge] LLM call failed: {e}")
            safe_error = sanitize_error(e, self.llm_provider_name)
            return TradeSignal(
                direction=SignalDirection.LONG,
                confidence=0,
                symbol=symbol,
                entry_price=current_price,
                target_price=current_price,
                stop_loss=current_price,
                reason=f"[LLM ERROR] {safe_error}",
                metrics_snapshot={"llm_provider": self.llm_provider_name, "llm_error": safe_error},
                timestamp=datetime.utcnow(),
            )

        direction = (
            SignalDirection.LONG
            if llm_response.direction.upper() == "LONG"
            else SignalDirection.SHORT
        )

        # TP/SL
        target_price = current_price
        stop_loss = current_price
        if current_price > 0 and self.take_profit_percent and self.stop_loss_percent:
            if direction == SignalDirection.LONG:
                target_price = current_price * (1 + self.take_profit_percent / 100)
                stop_loss = current_price * (1 - self.stop_loss_percent / 100)
            else:
                target_price = current_price * (1 - self.take_profit_percent / 100)
                stop_loss = current_price * (1 + self.stop_loss_percent / 100)

        safe_reasoning = sanitize_text(llm_response.reasoning, max_length=400)
        reason = f"[ClaudeEdge/{self.provider.get_display_name()}] {safe_reasoning}"

        metrics_snapshot = {
            "rsi": round(rsi, 2),
            "macd": round(macd_val, 6),
            "macd_histogram": round(histogram, 6),
            "bb_upper": round(bb_upper, 2),
            "bb_lower": round(bb_lower, 2),
            "vwap": round(vwap, 2),
            "supertrend": supertrend,
            "llm_provider": self.llm_provider_name,
            "llm_model": llm_response.model_used,
            "llm_reasoning": sanitize_text(llm_response.reasoning, max_length=500),
            "llm_tokens_used": llm_response.tokens_used,
            "llm_temperature": self.temperature,
            "data_sources_used": list(fetched.keys()),
        }

        signal = TradeSignal(
            direction=direction,
            confidence=llm_response.confidence,
            symbol=symbol,
            entry_price=current_price,
            target_price=round(target_price, 2),
            stop_loss=round(stop_loss, 2),
            reason=reason,
            metrics_snapshot=metrics_snapshot,
            timestamp=datetime.utcnow(),
        )

        logger.info(
            f"[ClaudeEdge:{self.llm_provider_name}] Signal: {direction.value.upper()} "
            f"@ ${current_price:,.2f} (confidence: {llm_response.confidence}%, "
            f"tokens: {llm_response.tokens_used})"
        )
        return signal

    async def should_trade(self, signal: TradeSignal) -> Tuple[bool, str]:
        min_conf = self._p["min_confidence"]
        if signal.confidence < min_conf:
            return False, f"Confidence too low: {signal.confidence}% < {min_conf}%"
        if signal.entry_price <= 0:
            return False, "Could not determine entry price"
        return True, f"Claude Edge signal accepted (confidence: {signal.confidence}%)"

    @classmethod
    def get_param_schema(cls) -> Dict[str, Any]:
        from src.ai.providers import MODEL_CATALOG

        family_options = []
        for key, family in MODEL_CATALOG.items():
            label = family["family_name"]
            if family.get("free"):
                label += " - Free"
            family_options.append({"value": key, "label": label})

        model_options_map: Dict[str, list] = {}
        for key, family in MODEL_CATALOG.items():
            model_options_map[key] = [
                {"value": m["id"], "label": m["name"]}
                for m in family["models"]
            ]

        return {
            "llm_provider": {
                "type": "select",
                "label": "Model Family",
                "description": "KI-Provider fuer die Claude Edge Analyse",
                "default": "groq",
                "options": family_options,
            },
            "llm_model": {
                "type": "dependent_select",
                "label": "Model",
                "description": "Welches Modell vom gewaehlten Provider",
                "default": "",
                "depends_on": "llm_provider",
                "options_map": model_options_map,
            },
            "temperature": {
                "type": "float",
                "label": "Temperature",
                "description": "0.0 = deterministisch, 1.0 = kreativ (empfohlen: 0.3)",
                "default": 0.3,
                "min": 0.0,
                "max": 1.0,
            },
            "rsi_period": {
                "type": "int",
                "label": "RSI Period",
                "description": "Anzahl Kerzen fuer RSI-Berechnung",
                "default": 14,
                "min": 5,
                "max": 50,
            },
            "min_confidence": {
                "type": "int",
                "label": "Min LLM Confidence",
                "description": "Minimale LLM-Konfidenz fuer Trade-Einstieg",
                "default": 60,
                "min": 30,
                "max": 90,
            },
        }

    @classmethod
    def get_description(cls) -> str:
        return (
            "Hybrid-Strategie: Technische Analyse (RSI, MACD, Bollinger) + KI-Bewertung. "
            "Berechnet Indikatoren und laesst ein LLM bewerten, ob die technischen Signale "
            "im aktuellen Marktkontext sinnvoll sind. Das Beste aus beiden Welten."
        )

    async def close(self):
        if self.data_fetcher:
            await self.data_fetcher.close()
        if self.provider:
            await self.provider.close()
        self.llm_api_key = ""


StrategyRegistry.register("claude_edge", ClaudeEdgeStrategy)
