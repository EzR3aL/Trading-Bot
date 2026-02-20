"""
LLM Signal Generation Strategy (Stufe 1 / Level 1).

Delegates trading signal generation to an external LLM provider.
Each cycle:
1. Fetch fresh market data (no memory of past trades)
2. Format data + user prompt into LLM request
3. Send to configured LLM provider
4. Parse response into LONG/SHORT + confidence
5. Return TradeSignal

Based on the myquant.gg approach: stateless, no learning, prompt-driven.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.ai.providers import get_provider_class
from src.ai.providers.base import LLMResponse, sanitize_error, sanitize_text
from src.data.data_source_registry import DEFAULT_SOURCES
from src.data.market_data import MarketDataFetcher
from src.strategy.base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_CUSTOM_PROMPT_LENGTH = 4000  # ~1000 tokens — prevents token exhaustion

DEFAULT_PROMPT = """You are a professional cryptocurrency trading analyst.
Analyze the provided market data and decide: LONG or SHORT.

Your response MUST follow this exact format:
DIRECTION: [LONG or SHORT]
CONFIDENCE: [number from 0 to 100]
REASONING: [2-3 sentences explaining your analysis]

Consider these factors:
- Fear & Greed Index: Extreme fear often means buy opportunity (contrarian), extreme greed means sell signal
- Long/Short Ratio: When too many traders are long, a squeeze to the downside is likely (and vice versa)
- Funding Rate: High positive funding means longs are paying shorts — potential for reversal down
- VWAP: Price above VWAP is bullish, below is bearish
- Supertrend: Confirms the current trend direction
- Volume: High buy ratio (>55%) is bullish, high sell ratio is bearish
- Price momentum: Strong 24h moves may continue or reverse depending on context

Be decisive. Always pick either LONG or SHORT."""


class LLMSignalStrategy(BaseStrategy):
    """Strategy that uses an LLM provider for signal generation."""

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self.data_fetcher: Optional[MarketDataFetcher] = None

        # Extract LLM-specific params
        self.llm_provider_name = self.params.get("llm_provider", "groq")
        self.llm_model = self.params.get("llm_model", "")
        self.llm_api_key = self.params.get("llm_api_key", "")
        self.custom_prompt = self.params.get("custom_prompt", "").strip()
        if len(self.custom_prompt) > MAX_CUSTOM_PROMPT_LENGTH:
            raise ValueError(
                f"Custom prompt too long: {len(self.custom_prompt)} chars "
                f"(max {MAX_CUSTOM_PROMPT_LENGTH}). Shorten your prompt."
            )
        self.temperature = float(self.params.get("temperature", 0.3))
        tp_raw = self.params.get("take_profit_percent")
        sl_raw = self.params.get("stop_loss_percent")
        self.take_profit_percent = float(tp_raw) if tp_raw is not None else None
        self.stop_loss_percent = float(sl_raw) if sl_raw is not None else None

        # Data sources selection (from Bot Builder cards)
        self.selected_sources: List[str] = self.params.get("data_sources", DEFAULT_SOURCES)

        if not self.llm_api_key:
            raise ValueError(
                f"No API key provided for LLM provider '{self.llm_provider_name}'. "
                "Configure it in Settings → LLM Keys."
            )

        # Initialize provider (model_override=None falls back to class default)
        provider_class = get_provider_class(self.llm_provider_name)
        self.provider = provider_class(
            self.llm_api_key,
            model_override=self.llm_model or None,
        )
        self.prompt = self.custom_prompt if self.custom_prompt else DEFAULT_PROMPT

    async def _ensure_fetcher(self):
        """Lazy-initialize the market data fetcher."""
        if self.data_fetcher is None:
            self.data_fetcher = MarketDataFetcher()
            await self.data_fetcher._ensure_session()

    async def generate_signal(self, symbol: str) -> TradeSignal:
        """Generate a trading signal using the LLM."""
        await self._ensure_fetcher()

        logger.info(
            f"[LLM:{self.llm_provider_name}] Fetching {len(self.selected_sources)} "
            f"data sources for {symbol}..."
        )

        # Fetch only selected data sources
        try:
            fetched = await self.data_fetcher.fetch_selected_metrics(
                self.selected_sources, symbol
            )
        except Exception as e:
            logger.error(f"[LLM:{self.llm_provider_name}] Data fetch error: {e}")
            raise

        # Build market data dict for LLM from fetched results
        market_data: Dict[str, Any] = {"symbol": symbol}
        current_price = 0.0

        # Extract current price from spot_price ticker if available
        if "spot_price" in fetched and isinstance(fetched["spot_price"], dict):
            ticker = fetched["spot_price"]
            current_price = ticker.get("price", 0)
            market_data["current_price"] = round(current_price, 2)
            market_data["price_change_24h_pct"] = round(ticker.get("price_change_percent", 0), 2)
            market_data["volume_24h"] = ticker.get("quote_volume_24h", 0)

        # Map each source to market_data keys
        if "fear_greed" in fetched:
            fg = fetched["fear_greed"]
            if isinstance(fg, tuple) and len(fg) == 2:
                market_data["fear_greed_index"] = fg[0]
                market_data["fear_greed_label"] = fg[1]
        if "long_short_ratio" in fetched:
            market_data["long_short_ratio"] = round(float(fetched["long_short_ratio"]), 3)
        if "top_trader_ls_ratio" in fetched:
            market_data["top_trader_long_short_ratio"] = round(float(fetched["top_trader_ls_ratio"]), 3)
        if "funding_rate" in fetched:
            market_data["funding_rate"] = round(float(fetched["funding_rate"]), 6)
        if "predicted_funding" in fetched:
            market_data["predicted_funding_rate"] = round(float(fetched["predicted_funding"]), 6)
        if "open_interest" in fetched:
            market_data["open_interest"] = round(float(fetched["open_interest"]), 0)
        if "oi_history" in fetched and fetched["oi_history"]:
            oi_hist = fetched["oi_history"]
            if len(oi_hist) >= 2:
                first_oi = float(oi_hist[0].get("sumOpenInterest", 0))
                last_oi = float(oi_hist[-1].get("sumOpenInterest", 0))
                if first_oi > 0:
                    market_data["oi_change_24h_pct"] = round(((last_oi - first_oi) / first_oi) * 100, 2)
        if "liquidations" in fetched and fetched["liquidations"]:
            liqs = fetched["liquidations"]
            market_data["recent_liquidations_count"] = len(liqs)
        if "news_sentiment" in fetched and isinstance(fetched["news_sentiment"], dict):
            market_data["news_sentiment_tone"] = round(fetched["news_sentiment"].get("average_tone", 0), 2)
            market_data["news_article_count"] = fetched["news_sentiment"].get("article_count", 0)
        if "options_oi" in fetched and isinstance(fetched["options_oi"], dict):
            market_data["options_open_interest"] = fetched["options_oi"].get("total_oi", 0)
        if "max_pain" in fetched and isinstance(fetched["max_pain"], dict):
            market_data["max_pain_price"] = fetched["max_pain"].get("max_pain_price", 0)
        if "put_call_ratio" in fetched and isinstance(fetched["put_call_ratio"], dict):
            market_data["put_call_ratio"] = round(fetched["put_call_ratio"].get("ratio", 0), 3)
        if "coingecko_market" in fetched and isinstance(fetched["coingecko_market"], dict):
            cg = fetched["coingecko_market"]
            market_data["btc_dominance_pct"] = round(cg.get("btc_dominance_pct", 0), 1)
            market_data["total_market_cap_usd"] = cg.get("total_market_cap_usd", 0)
        if "vwap" in fetched:
            vwap_val = float(fetched["vwap"])
            market_data["vwap_24h"] = round(vwap_val, 2)
            if current_price > 0:
                market_data["price_vs_vwap"] = "above" if current_price > vwap_val else "below"
        if "supertrend" in fetched and isinstance(fetched["supertrend"], dict):
            market_data["supertrend_direction"] = fetched["supertrend"].get("direction", "unknown")
        if "spot_volume" in fetched and isinstance(fetched["spot_volume"], dict):
            market_data["volume_buy_ratio"] = round(fetched["spot_volume"].get("buy_ratio", 0.5), 3)
        if "oiwap" in fetched:
            market_data["oiwap"] = round(float(fetched["oiwap"]), 2)
        if "volatility" in fetched:
            market_data["volatility_24h_pct"] = round(float(fetched["volatility"]), 2)
        if "trend_sma" in fetched:
            market_data["trend_direction"] = fetched["trend_sma"]
        if "cme_gap" in fetched and isinstance(fetched["cme_gap"], dict):
            cme = fetched["cme_gap"]
            market_data["cme_gap_pct"] = round(cme.get("gap_pct", 0), 2)
            market_data["cme_gap_direction"] = cme.get("gap_direction", "none")

        # Call LLM
        logger.info(
            f"[LLM:{self.llm_provider_name}] Sending to "
            f"{self.provider.get_display_name()}..."
        )

        try:
            llm_response: LLMResponse = await self.provider.generate_signal(
                prompt=self.prompt,
                market_data=market_data,
                temperature=self.temperature,
            )
        except Exception as e:
            logger.error(f"[LLM:{self.llm_provider_name}] API call failed: {e}")
            # Return a low-confidence signal rather than crashing the bot
            safe_error = sanitize_error(e, self.llm_provider_name)
            return TradeSignal(
                direction=SignalDirection.LONG,
                confidence=0,
                symbol=symbol,
                entry_price=current_price,
                target_price=current_price,
                stop_loss=current_price,
                reason=f"[LLM ERROR] {safe_error}",
                metrics_snapshot={
                    "llm_provider": self.llm_provider_name,
                    "llm_error": safe_error,
                },
                timestamp=datetime.utcnow(),
            )

        # Convert to SignalDirection
        direction = (
            SignalDirection.LONG
            if llm_response.direction.upper() == "LONG"
            else SignalDirection.SHORT
        )

        # Calculate TP/SL (None = no TP/SL, trades closed by rotation or manually)
        target_price = None
        stop_loss = None
        if current_price > 0 and self.take_profit_percent is not None and self.stop_loss_percent is not None:
            if direction == SignalDirection.LONG:
                target_price = current_price * (1 + self.take_profit_percent / 100)
                stop_loss = current_price * (1 - self.stop_loss_percent / 100)
            else:
                target_price = current_price * (1 - self.take_profit_percent / 100)
                stop_loss = current_price * (1 + self.stop_loss_percent / 100)

        # Build reason string (sanitized)
        safe_reasoning = sanitize_text(llm_response.reasoning, max_length=400)
        reason = f"[{self.provider.get_display_name()}] {safe_reasoning}"

        # Store LLM metadata + all fetched data in metrics_snapshot
        metrics_snapshot = {
            **{k: v for k, v in market_data.items() if k != "symbol"},
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
            target_price=round(target_price, 2) if target_price is not None else None,
            stop_loss=round(stop_loss, 2) if stop_loss is not None else None,
            reason=reason,
            metrics_snapshot=metrics_snapshot,
            timestamp=datetime.utcnow(),
        )

        logger.info(
            f"[LLM:{self.llm_provider_name}] Signal: {direction.value.upper()} "
            f"@ ${current_price:,.2f} (confidence: {llm_response.confidence}%, "
            f"tokens: {llm_response.tokens_used})"
        )

        return signal

    async def should_trade(self, signal: TradeSignal) -> Tuple[bool, str]:
        """Decide if the signal should be executed based on confidence."""
        min_confidence = 60

        if signal.confidence < min_confidence:
            return False, (
                f"LLM confidence too low: {signal.confidence}% < {min_confidence}%"
            )

        if signal.entry_price <= 0:
            return False, "Could not determine entry price"

        return True, f"LLM signal accepted (confidence: {signal.confidence}%)"

    @classmethod
    def get_param_schema(cls) -> Dict[str, Any]:
        """Return parameter schema for the BotBuilder UI."""
        from src.ai.providers import MODEL_CATALOG

        # Build family options
        family_options = []
        for key, family in MODEL_CATALOG.items():
            label = family["family_name"]
            if family.get("free"):
                label += " - Free"
            family_options.append({"value": key, "label": label})

        # Build model options grouped by family
        model_options_map: Dict[str, list] = {}
        for key, family in MODEL_CATALOG.items():
            model_options_map[key] = [
                {"value": m["id"], "label": m["name"]}
                for m in family["models"]
            ]

        return {
            "llm_provider": {
                "type": "select",
                "label": "Modell-Familie",
                "description": "Welcher KI-Anbieter für die Analyse verwendet wird",
                "default": "groq",
                "options": family_options,
            },
            "llm_model": {
                "type": "dependent_select",
                "label": "Modell",
                "description": "Welches Modell vom gewählten Anbieter verwendet wird",
                "default": "",
                "depends_on": "llm_provider",
                "options_map": model_options_map,
            },
            "custom_prompt": {
                "type": "textarea",
                "label": "Analyse-Prompt",
                "description": "Eigene Anweisungen für die KI (leer lassen für Standard-Prompt)",
                "default": "",
            },
            "temperature": {
                "type": "float",
                "label": "Temperatur",
                "description": "0.0 = deterministisch, 1.0 = kreativ",
                "default": 0.3,
                "min": 0.0,
                "max": 1.0,
            },
        }

    @classmethod
    def get_description(cls) -> str:
        return (
            "AI-powered signal generation using large language models. "
            "The LLM analyzes market data each cycle and provides "
            "LONG/SHORT recommendations with confidence scores."
        )

    async def close(self):
        """Clean up resources and clear sensitive data from memory."""
        if self.data_fetcher:
            await self.data_fetcher.close()
        if self.provider:
            await self.provider.close()
        self.llm_api_key = ""


# Register the strategy
StrategyRegistry.register("llm_signal", LLMSignalStrategy)
