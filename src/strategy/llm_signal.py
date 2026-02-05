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
from typing import Any, Dict, Optional, Tuple

from src.ai.providers import get_provider_class
from src.ai.providers.base import LLMResponse, sanitize_error, sanitize_text
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
        self.llm_api_key = self.params.get("llm_api_key", "")
        self.custom_prompt = self.params.get("custom_prompt", "").strip()
        if len(self.custom_prompt) > MAX_CUSTOM_PROMPT_LENGTH:
            raise ValueError(
                f"Custom prompt too long: {len(self.custom_prompt)} chars "
                f"(max {MAX_CUSTOM_PROMPT_LENGTH}). Shorten your prompt."
            )
        self.temperature = float(self.params.get("temperature", 0.3))
        self.take_profit_percent = float(self.params.get("take_profit_percent", 4.0))
        self.stop_loss_percent = float(self.params.get("stop_loss_percent", 1.5))

        if not self.llm_api_key:
            raise ValueError(
                f"No API key provided for LLM provider '{self.llm_provider_name}'. "
                "Configure it in Settings → LLM Keys."
            )

        # Initialize provider
        provider_class = get_provider_class(self.llm_provider_name)
        self.provider = provider_class(self.llm_api_key)
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
            f"[LLM:{self.llm_provider_name}] Fetching market data for {symbol}..."
        )

        # Fetch market data in parallel
        try:
            metrics, klines = await asyncio.gather(
                self.data_fetcher.fetch_all_metrics(require_reliable=False),
                self.data_fetcher.get_binance_klines(symbol, "1h", 24),
                return_exceptions=True,
            )
        except Exception as e:
            logger.error(f"[LLM:{self.llm_provider_name}] Data fetch error: {e}")
            raise

        # Handle partial failures
        if isinstance(metrics, Exception):
            logger.warning(f"[LLM:{self.llm_provider_name}] Metrics fetch failed: {metrics}")
            metrics = None
        if isinstance(klines, Exception):
            logger.warning(f"[LLM:{self.llm_provider_name}] Klines fetch failed: {klines}")
            klines = []

        # Compute technical indicators from klines
        vwap = 0.0
        supertrend_dir = "unknown"
        buy_ratio = 0.5
        current_price = 0.0

        if klines:
            vwap = MarketDataFetcher.calculate_vwap(klines)
            supertrend = MarketDataFetcher.calculate_supertrend(klines)
            supertrend_dir = supertrend.get("direction", "unknown")
            volume_analysis = MarketDataFetcher.get_spot_volume_analysis(klines)
            buy_ratio = volume_analysis.get("buy_ratio", 0.5)

        # Get current price
        if metrics and not isinstance(metrics, Exception):
            if "BTC" in symbol.upper():
                current_price = metrics.btc_price
            elif "ETH" in symbol.upper():
                current_price = metrics.eth_price

        # Fallback: get price from last kline
        if current_price == 0 and klines:
            current_price = float(klines[-1][4])  # close price

        # Build market data dict for LLM
        market_data = {"symbol": symbol}

        if metrics and not isinstance(metrics, Exception):
            market_data.update({
                "current_price": round(current_price, 2),
                "fear_greed_index": metrics.fear_greed_index,
                "fear_greed_label": metrics.fear_greed_classification,
                "long_short_ratio": round(metrics.long_short_ratio, 3),
                "funding_rate_btc": round(metrics.funding_rate_btc, 6),
                "btc_24h_change_percent": round(metrics.btc_24h_change_percent, 2),
                "eth_24h_change_percent": round(metrics.eth_24h_change_percent, 2),
                "btc_open_interest": round(metrics.btc_open_interest, 0),
            })

        if klines:
            market_data.update({
                "vwap_24h": round(vwap, 2),
                "supertrend_direction": supertrend_dir,
                "volume_buy_ratio": round(buy_ratio, 3),
                "price_vs_vwap": "above" if current_price > vwap else "below",
            })

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

        # Calculate TP/SL
        if current_price > 0:
            if direction == SignalDirection.LONG:
                target_price = current_price * (1 + self.take_profit_percent / 100)
                stop_loss = current_price * (1 - self.stop_loss_percent / 100)
            else:
                target_price = current_price * (1 - self.take_profit_percent / 100)
                stop_loss = current_price * (1 + self.stop_loss_percent / 100)
        else:
            target_price = 0.0
            stop_loss = 0.0

        # Build reason string (sanitized)
        safe_reasoning = sanitize_text(llm_response.reasoning, max_length=400)
        reason = f"[{self.provider.get_display_name()}] {safe_reasoning}"

        # Store LLM metadata in metrics_snapshot
        metrics_dict = {}
        if metrics and not isinstance(metrics, Exception):
            metrics_dict = {
                "fear_greed_index": metrics.fear_greed_index,
                "long_short_ratio": metrics.long_short_ratio,
                "funding_rate_btc": metrics.funding_rate_btc,
                "btc_24h_change": metrics.btc_24h_change_percent,
            }

        metrics_snapshot = {
            **metrics_dict,
            "llm_provider": self.llm_provider_name,
            "llm_model": llm_response.model_used,
            "llm_reasoning": sanitize_text(llm_response.reasoning, max_length=500),
            "llm_tokens_used": llm_response.tokens_used,
            "llm_temperature": self.temperature,
            "vwap": vwap,
            "supertrend": supertrend_dir,
            "buy_ratio": buy_ratio,
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
        return {
            "llm_provider": {
                "type": "select",
                "label": "LLM Provider",
                "description": "Which AI model to use for analysis",
                "default": "groq",
                "options": [
                    {"value": "groq", "label": "Groq (Llama 3.3 70B) - Free"},
                    {"value": "gemini", "label": "Google Gemini 2.0 Flash - Free"},
                    {"value": "openai", "label": "OpenAI GPT-4o-mini"},
                    {"value": "anthropic", "label": "Anthropic Claude Haiku 4.5"},
                    {"value": "mistral", "label": "Mistral Small"},
                    {"value": "xai", "label": "xAI Grok"},
                    {"value": "perplexity", "label": "Perplexity Sonar"},
                ],
            },
            "custom_prompt": {
                "type": "textarea",
                "label": "Analysis Prompt",
                "description": "Custom instructions for the AI (leave empty for default)",
                "default": "",
            },
            "temperature": {
                "type": "float",
                "label": "Temperature",
                "description": "0.0 = deterministic, 1.0 = creative",
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
