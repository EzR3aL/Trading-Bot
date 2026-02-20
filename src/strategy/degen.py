"""
Degen Strategy — Pre-configured LLM prediction arena strategy.

Inspired by myquant.gg's Degen bot:
- Fixed system prompt optimised for 1h BTC directional calls
- 19 fixed data sources (no user selection)
- User only configures LLM provider, model, and temperature

Data sources used (all free):
  1. Bitcoin price (CoinGecko / Binance)
  2. Futures Volume (Binance 24h ticker)
  3. Futures Premium / Funding Rate (Binance premiumIndex)
  4. Tape / Trade Flow — taker buy/sell ratio (Binance klines)
  5. Spot Volume Analysis (Binance klines)
  6. Order Book Depth (Binance depth)
  7. Perp/Spot Volume Ratio (calculated)
  8. Market Cap & Float (CoinGecko)
  9. VWAP / OIWAP (calculated from klines)
  10. Realized Volatility (calculated from klines)
  11. Total Return with Funding (calculated)
  12. Supertrend Indicator (calculated from klines)
  13. Binance Long/Short Ratio (Binance futures)
  14. Liquidation Risk Score (Binance forceOrders + funding)
  15. Cumulative Volume Delta (Binance klines)
  16. Coinbase Premium Index (Coinbase vs Binance spread)
  17. Bybit Futures OI + Funding + Volume (Bybit V5 API)
  18. Deribit Options Extended: IV, Skew, Put/Call Ratio
  19. Deribit DVOL — Crypto Volatility Index
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.ai.providers import get_provider_class
from src.ai.providers.base import LLMResponse, sanitize_error, sanitize_text
from src.data.market_data import MarketDataFetcher
from src.strategy.base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Fixed system prompt (not user-editable) ──────────────────────────────────

DEGEN_SYSTEM_PROMPT = """You are an elite crypto trader competing in a prediction arena.
Your goal is to predict the movement of Bitcoin (BTC) over the next hour.

CRITICAL RULES:
1. You MUST choose a direction: 'LONG' (Bullish) or 'SHORT' (Bearish).
2. NEUTRAL stances are STRICTLY FORBIDDEN. You must make a decisive call.
3. Provide a confidence score (0-100) based on the strength of the signals.
4. Predict a specific closing price for 1 hour from now.
5. Provide a concise reasoning (max 3 sentences) explaining your decision based on the provided context.

Go long if you see bullish signals and short if bearish

Your response MUST follow this exact format:
DIRECTION: [LONG or SHORT]
CONFIDENCE: [number from 0 to 100]
REASONING: [2-3 sentences explaining your analysis]"""

# ── Fixed data sources ────────────────────────────────────────────────────────

DEGEN_SOURCES: List[str] = [
    "spot_price",              # 1.  Bitcoin price & 24h change
    "fear_greed",              #     Bonus: Fear & Greed Index
    "news_sentiment",          #     Bonus: News headlines
    "funding_rate",            # 3.  Futures premium / funding rate
    "open_interest",           # 2.  Open interest (for futures context)
    "long_short_ratio",        # 13. Binance Long/Short Ratio
    "order_book",              # 6.  Order Book Depth
    "liquidations",            # 14. Liquidation Risk Score
    "supertrend",              # 12. Supertrend (requires klines)
    "vwap",                    # 9.  VWAP (requires klines)
    "oiwap",                   # 9.  OIWAP (requires klines)
    "spot_volume",             # 4+5. Tape/Trade flow & Spot Volume
    "volatility",              # 10. Realized Volatility
    "coingecko_market",        # 8.  Market Cap & Float
    "cvd",                     # 15. Cumulative Volume Delta
    "coinbase_premium",        # 16. Coinbase Premium Index
    "bybit_futures",           # 17. Bybit OI + Funding + Volume
    "deribit_options_extended", # 18. Options IV, Skew, Put/Call
    "deribit_dvol",            # 19. Deribit Volatility Index (DVOL)
]

MIN_CONFIDENCE = 55


class DegenStrategy(BaseStrategy):
    """Pre-configured LLM strategy with fixed prompt and 14 data sources."""

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self.data_fetcher: Optional[MarketDataFetcher] = None

        # LLM config (user-selectable)
        self.llm_provider_name = self.params.get("llm_provider", "groq")
        self.llm_model = self.params.get("llm_model", "")
        self.llm_api_key = self.params.get("llm_api_key", "")
        self.temperature = float(self.params.get("temperature", 0.3))

        # TP/SL from bot config
        tp_raw = self.params.get("take_profit_percent")
        sl_raw = self.params.get("stop_loss_percent")
        self.take_profit_percent = float(tp_raw) if tp_raw is not None else None
        self.stop_loss_percent = float(sl_raw) if sl_raw is not None else None

        if not self.llm_api_key:
            raise ValueError(
                f"No API key provided for LLM provider '{self.llm_provider_name}'. "
                "Configure it in Settings → LLM Keys."
            )

        provider_class = get_provider_class(self.llm_provider_name)
        self.provider = provider_class(
            self.llm_api_key,
            model_override=self.llm_model or None,
        )

    async def _ensure_fetcher(self):
        if self.data_fetcher is None:
            self.data_fetcher = MarketDataFetcher()
            await self.data_fetcher._ensure_session()

    # ── Signal generation ─────────────────────────────────────────────────────

    async def generate_signal(self, symbol: str) -> TradeSignal:
        """Fetch all 14 data sources, build Degen-format JSON, call LLM."""
        await self._ensure_fetcher()

        logger.info(f"[Degen:{self.llm_provider_name}] Fetching {len(DEGEN_SOURCES)} sources for {symbol}...")

        try:
            fetched = await self.data_fetcher.fetch_selected_metrics(DEGEN_SOURCES, symbol)
        except Exception as e:
            logger.error(f"[Degen] Data fetch error: {e}")
            raise

        # ── Build the Degen-format market context ─────────────────────────────
        market_context = self._build_market_context(symbol, fetched)
        current_price = market_context.get("bitcoin", {}).get("usd", 0)

        # ── Call LLM ──────────────────────────────────────────────────────────
        user_message = f"Current Market Context:\n{json.dumps(market_context, indent=2)}\n\nAnalyze the data and make your prediction."

        logger.info(f"[Degen:{self.llm_provider_name}] Sending to {self.provider.get_display_name()}...")

        try:
            llm_response: LLMResponse = await self.provider.generate_signal(
                prompt=DEGEN_SYSTEM_PROMPT,
                market_data={"_raw_user_message": user_message},
                temperature=self.temperature,
            )
        except Exception as e:
            logger.error(f"[Degen] LLM call failed: {e}")
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
        target_price = None
        stop_loss = None
        if current_price > 0 and self.take_profit_percent is not None and self.stop_loss_percent is not None:
            if direction == SignalDirection.LONG:
                target_price = current_price * (1 + self.take_profit_percent / 100)
                stop_loss = current_price * (1 - self.stop_loss_percent / 100)
            else:
                target_price = current_price * (1 - self.take_profit_percent / 100)
                stop_loss = current_price * (1 + self.stop_loss_percent / 100)

        safe_reasoning = sanitize_text(llm_response.reasoning, max_length=400)
        reason = f"[Degen/{self.provider.get_display_name()}] {safe_reasoning}"

        metrics_snapshot = {
            **{k: v for k, v in market_context.items() if k not in ("_raw",)},
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
            target_price=round(target_price, 2) if target_price else round(current_price * 1.03, 2),
            stop_loss=round(stop_loss, 2) if stop_loss else round(current_price * 0.98, 2),
            reason=reason,
            metrics_snapshot=metrics_snapshot,
            timestamp=datetime.utcnow(),
        )

        logger.info(
            f"[Degen:{self.llm_provider_name}] Signal: {direction.value.upper()} "
            f"@ ${current_price:,.2f} (confidence: {llm_response.confidence}%, "
            f"tokens: {llm_response.tokens_used})"
        )
        return signal

    # ── Market context builder (matches Degen arena format) ───────────────────

    def _build_market_context(self, symbol: str, fetched: Dict[str, Any]) -> dict:
        """Build the Degen-specific JSON structure from fetched data."""
        ctx: Dict[str, Any] = {}

        # ── bitcoin ──
        price = 0.0
        change_24h = 0.0
        vol_24h = 0.0
        if "spot_price" in fetched and isinstance(fetched["spot_price"], dict):
            ticker = fetched["spot_price"]
            price = ticker.get("price", 0)
            change_24h = ticker.get("price_change_percent", 0)
            vol_24h = ticker.get("quote_volume_24h", 0)
        ctx["bitcoin"] = {
            "usd": round(price, 2),
            "usd_24h_vol": round(vol_24h, 2),
            "usd_24h_change": round(change_24h, 3),
        }

        # ── fearGreed ──
        if "fear_greed" in fetched:
            fg = fetched["fear_greed"]
            if isinstance(fg, tuple) and len(fg) == 2:
                ctx["fearGreed"] = {
                    "value": str(fg[0]),
                    "value_classification": fg[1],
                }

        # ── news ──
        if "news_sentiment" in fetched and isinstance(fetched["news_sentiment"], dict):
            ns = fetched["news_sentiment"]
            ctx["news"] = {
                "summary": {
                    "count24h": ns.get("article_count", 0),
                    "averageTone": round(ns.get("average_tone", 0), 2),
                    "interpretation": (
                        "Positive tone" if ns.get("average_tone", 0) > 1
                        else "Negative tone" if ns.get("average_tone", 0) < -1
                        else "Neutral tone"
                    ),
                }
            }

        # ── derivatives ──
        deriv: Dict[str, Any] = {}
        if "funding_rate" in fetched:
            fr = float(fetched["funding_rate"])
            deriv["premiumIndex"] = {
                "fundingRate": f"{fr:.8f}",
                "markPrice": str(round(price, 2)),
            }
        if "open_interest" in fetched:
            oi = float(fetched["open_interest"])
            deriv["openInterest"] = {
                "current": str(round(oi, 3)),
                "trend": "rising" if oi > 0 else "falling",
            }
        if "long_short_ratio" in fetched:
            lsr = round(float(fetched["long_short_ratio"]), 4)
            trend = "bullish" if lsr > 1 else "bearish"
            interp = f"Long/short ratio: {lsr:.2f}."
            if lsr > 2.0:
                interp += " High long bias — contrarian SHORT signal. Risk of long liquidations."
            elif lsr < 0.5:
                interp += " High short bias — contrarian LONG signal. Risk of short squeeze."
            else:
                interp += " Moderate positioning."
            deriv["longShortRatio"] = {
                "current": lsr,
                "trend": trend,
                "interpretation": interp,
            }
        if deriv:
            ctx["derivatives"] = deriv

        # ── orderBook ──
        if "order_book" in fetched and isinstance(fetched["order_book"], dict):
            ctx["orderBook"] = fetched["order_book"]

        # ── liquidations ──
        liq_ctx: Dict[str, Any] = {}
        if "liquidations" in fetched and isinstance(fetched["liquidations"], list):
            liqs = fetched["liquidations"]
            buy_liqs = sum(1 for l in liqs if l.get("side", "").upper() == "BUY")
            sell_liqs = len(liqs) - buy_liqs
            risk = "high" if len(liqs) > 50 else "moderate" if len(liqs) > 20 else "low"
            liq_ctx = {
                "estimatedRisk": risk,
                "recentCount": len(liqs),
                "buyLiquidations": buy_liqs,
                "sellLiquidations": sell_liqs,
                "interpretation": (
                    f"{risk.capitalize()} liquidation activity. "
                    f"{buy_liqs} long liquidations vs {sell_liqs} short liquidations."
                ),
            }
        if "funding_rate" in fetched:
            fr = float(fetched["funding_rate"])
            liq_ctx["fundingRateExtreme"] = {
                "current": fr,
                "interpretation": (
                    "Low funding rate. Market is relatively balanced."
                    if abs(fr) < 0.0005
                    else f"Elevated funding rate ({fr:.6f}). Longs paying shorts."
                    if fr > 0
                    else f"Negative funding rate ({fr:.6f}). Shorts paying longs."
                ),
            }
        if liq_ctx:
            ctx["liquidations"] = liq_ctx

        # ── supertrend ──
        if "supertrend" in fetched and isinstance(fetched["supertrend"], dict):
            st = fetched["supertrend"]
            direction = st.get("direction", "unknown").upper()
            st_val = st.get("value", 0)
            atr = st.get("atr", 0)
            pct_above = ((price - st_val) / st_val * 100) if st_val > 0 else 0
            ctx["supertrend"] = {
                "trend": direction,
                "value": round(st_val, 2),
                "atr": round(atr, 2),
                "currentPrice": round(price, 2),
                "signal": f"Price {abs(pct_above):.2f}% {'above' if pct_above > 0 else 'below'} Supertrend at ${st_val:,.0f}",
            }

        # ── spot volume / tape ──
        if "spot_volume" in fetched and isinstance(fetched["spot_volume"], dict):
            sv = fetched["spot_volume"]
            buy_ratio = sv.get("buy_ratio", 0.5)
            ctx["spotVolume"] = {
                "buyRatio": round(buy_ratio, 4),
                "sellRatio": round(1 - buy_ratio, 4),
                "interpretation": (
                    "Balanced" if 0.45 <= buy_ratio <= 0.55
                    else "Buy dominant (accumulation)" if buy_ratio > 0.55
                    else "Sell dominant (distribution)"
                ),
            }

        # ── VWAP / OIWAP ──
        vwap_ctx: Dict[str, Any] = {}
        if "vwap" in fetched:
            vwap_val = round(float(fetched["vwap"]), 2)
            diff = price - vwap_val
            vwap_ctx["vwap"] = vwap_val
            vwap_ctx["priceVsVwap"] = round(diff, 2)
            vwap_ctx["priceVsVwapLabel"] = "Above VWAP (bullish)" if diff > 0 else "Below VWAP (bearish)"
        if "oiwap" in fetched:
            vwap_ctx["oiwap"] = round(float(fetched["oiwap"]), 2)
        if vwap_ctx:
            ctx["vwap"] = vwap_ctx

        # ── volatility (realized) ──
        if "volatility" in fetched:
            rv = round(float(fetched["volatility"]), 2)
            ctx["realizedVol"] = {
                "rv24h_pct": rv,
                "interpretation": (
                    "Low volatility" if rv < 2
                    else "Moderate volatility" if rv < 5
                    else "High volatility"
                ),
            }

        # ── market cap ──
        if "coingecko_market" in fetched and isinstance(fetched["coingecko_market"], dict):
            cg = fetched["coingecko_market"]
            ctx["marketCap"] = {
                "btcDominancePct": round(cg.get("btc_dominance_pct", 0), 1),
                "totalMarketCapUsd": cg.get("total_market_cap_usd", 0),
                "activeCryptos": cg.get("active_cryptocurrencies", 0),
            }

        # ── total return (calculated) ──
        if price > 0 and change_24h != 0:
            funding_drag = 0.0
            if "funding_rate" in fetched:
                fr_8h = float(fetched["funding_rate"])
                funding_drag = fr_8h * 3 * 100  # 3 funding periods per day
            ctx["totalReturn"] = {
                "return24h_pct": round(change_24h, 3),
                "fundingDrag24h_pct": round(funding_drag, 3),
                "netReturn24h_pct": round(change_24h - funding_drag, 3),
            }

        # ── CVD (Cumulative Volume Delta) ──
        if "cvd" in fetched and isinstance(fetched["cvd"], dict):
            cvd = fetched["cvd"]
            ctx["cvd"] = {
                "total": cvd.get("cvd_total", 0),
                "trend": cvd.get("cvd_trend", "neutral"),
                "takerBuyRatio": cvd.get("taker_buy_ratio", 0.5),
                "interpretation": (
                    f"CVD is {cvd.get('cvd_trend', 'neutral')}. "
                    f"Taker buy ratio: {cvd.get('taker_buy_ratio', 0.5):.1%}"
                ),
            }

        # ── Coinbase Premium ──
        if "coinbase_premium" in fetched and isinstance(fetched["coinbase_premium"], dict):
            cp = fetched["coinbase_premium"]
            ctx["coinbasePremium"] = {
                "premiumPct": cp.get("premium_pct", 0),
                "signal": cp.get("signal", "neutral"),
                "interpretation": (
                    f"Coinbase premium: {cp.get('premium_pct', 0):.4f}%. "
                    f"{'US institutional buying pressure.' if cp.get('signal') == 'bullish' else 'US selling pressure.' if cp.get('signal') == 'bearish' else 'Neutral flow.'}"
                ),
            }

        # ── Bybit Futures ──
        if "bybit_futures" in fetched and isinstance(fetched["bybit_futures"], dict):
            bf = fetched["bybit_futures"]
            ctx["bybitFutures"] = {
                "openInterest": bf.get("open_interest", 0),
                "fundingRate": bf.get("funding_rate", 0),
                "volume24h": bf.get("volume_24h", 0),
            }

        # ── Deribit Options Extended ──
        if "deribit_options_extended" in fetched and isinstance(fetched["deribit_options_extended"], dict):
            dox = fetched["deribit_options_extended"]
            ctx["optionsExtended"] = {
                "avgIV": dox.get("avg_iv", 0),
                "putCallRatio": dox.get("put_call_ratio", 0),
                "skew25Delta": dox.get("skew_25delta", 0),
                "interpretation": (
                    f"Avg IV: {dox.get('avg_iv', 0):.1f}%, "
                    f"P/C ratio: {dox.get('put_call_ratio', 0):.2f}, "
                    f"Skew: {dox.get('skew_25delta', 0):.1f}%"
                ),
            }

        # ── Deribit DVOL ──
        if "deribit_dvol" in fetched and isinstance(fetched["deribit_dvol"], dict):
            dv = fetched["deribit_dvol"]
            ctx["dvol"] = {
                "current": dv.get("dvol_current", 0),
                "change24hPct": dv.get("dvol_change_pct", 0),
                "signal": dv.get("signal", "neutral"),
                "interpretation": (
                    f"DVOL at {dv.get('dvol_current', 0):.1f} "
                    f"({dv.get('dvol_change_pct', 0):+.1f}% 24h). "
                    f"{'Rising fear/uncertainty.' if dv.get('signal') == 'fear_rising' else 'Complacency building.' if dv.get('signal') == 'complacency' else 'Volatility stable.'}"
                ),
            }

        return ctx

    # ── Gate ──────────────────────────────────────────────────────────────────

    async def should_trade(self, signal: TradeSignal) -> Tuple[bool, str]:
        if signal.confidence < MIN_CONFIDENCE:
            return False, (
                f"Degen confidence too low: {signal.confidence}% < {MIN_CONFIDENCE}%"
            )
        if signal.entry_price <= 0:
            return False, "Could not determine entry price"
        return True, f"Degen signal accepted (confidence: {signal.confidence}%)"

    # ── Schema (only LLM provider/model/temperature) ─────────────────────────

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
                "label": "Modell-Familie",
                "description": "Welcher KI-Anbieter für die Degen-Analyse verwendet wird",
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
            "temperature": {
                "type": "float",
                "label": "Temperatur",
                "description": "0.0 = deterministisch, 1.0 = kreativ (empfohlen: 0.3)",
                "default": 0.3,
                "min": 0.0,
                "max": 1.0,
            },
        }

    @classmethod
    def get_description(cls) -> str:
        return (
            "KI-gesteuerte Arena-Strategie mit festem Prompt und 14 Datenquellen. "
            "Nutzt Binance-Derivatives, Order Book, Supertrend, VWAP und mehr "
            "für 1h BTC-Vorhersagen. Inspiriert vom Degen Prediction Bot."
        )

    async def close(self):
        if self.data_fetcher:
            await self.data_fetcher.close()
        if self.provider:
            await self.provider.close()
        self.llm_api_key = ""


# Register
StrategyRegistry.register("degen", DegenStrategy)
