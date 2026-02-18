"""
Backtest Engine for the Contrarian Liquidation Hunter Strategy.

Simulates trading over historical data and calculates performance metrics.
Uses multi-source data analysis for signal generation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Dict, Tuple

from src.backtest.historical_data import HistoricalDataPoint
from src.utils.logger import get_logger
from config import settings

logger = get_logger(__name__)


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
    trading_fee_percent: float = 0.06

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

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
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
        self.current_date = ""

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
    #  SIGNAL GENERATION — dispatcher                                     #
    # ------------------------------------------------------------------ #

    def _generate_signal(
        self, data: HistoricalDataPoint, symbol: str = "BTC"
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
        return self._signal_liquidation_hunter(data, symbol)

    # ------------------------------------------------------------------ #
    #  Liquidation Hunter — contrarian leverage + sentiment               #
    # ------------------------------------------------------------------ #

    def _signal_liquidation_hunter(
        self, data: HistoricalDataPoint, symbol: str = "BTC"
    ) -> Tuple[TradeDirection, int, str]:
        """
        Contrarian strategy: bet against crowded positions.

        Primary: L/S Ratio + Fear & Greed (contrarian).
        Secondary: Funding rate, Open Interest.
        Always picks a side — no neutral.
        """
        reasons = []
        confidence = 50

        funding_rate = data.funding_rate_btc if symbol == "BTC" else data.funding_rate_eth
        price_change = data.btc_24h_change if symbol == "BTC" else data.eth_24h_change

        # Primary: Leverage (heavy weight)
        leverage_dir, leverage_conf, leverage_reason = self._analyze_leverage(data.long_short_ratio)
        reasons.append(leverage_reason)
        confidence += leverage_conf

        # Primary: Sentiment (heavy weight)
        sentiment_dir, sentiment_conf, sentiment_reason = self._analyze_sentiment(data.fear_greed_index)
        reasons.append(sentiment_reason)
        confidence += sentiment_conf

        # Determine direction — never neutral
        final_direction = None
        if leverage_dir and sentiment_dir:
            if leverage_dir == sentiment_dir:
                final_direction = leverage_dir
                confidence = max(confidence, self.config.high_confidence_min)
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
            confidence = max(self.config.low_confidence_min, min(confidence, 65))
            reasons.append(f"Trend: {price_change:+.2f}%")

        # Secondary: Funding rate confirmation
        funding_adj, funding_reason = self._analyze_funding_rate(funding_rate, final_direction)
        confidence += funding_adj
        reasons.append(funding_reason)

        # Secondary: Open Interest
        oi_adj, oi_reason = self._analyze_open_interest(data, final_direction)
        confidence += oi_adj
        if oi_adj != 0:
            reasons.append(oi_reason)

        # Volatility risk
        vol_adj, vol_reason = self._analyze_volatility(data)
        confidence += vol_adj
        if vol_adj != 0:
            reasons.append(vol_reason)

        confidence = max(self.config.low_confidence_min, min(confidence, 95))
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
            scores.append((0, 0.8, f"Funding Neutral"))

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
            scores.append((30, 0.8, f"Stables Inflow"))
        elif flow < -1_000_000_000:
            scores.append((-30, 0.8, f"Stables Outflow"))
        else:
            scores.append((0, 0.8, f"Stables Neutral"))

        # Source 6: Momentum (price change) — weight 1.2
        if abs(price_change) > 1.0:
            scores.append((price_change * 15, 1.2, f"Momentum {price_change:+.1f}%"))
        else:
            scores.append((0, 1.2, f"Momentum Flat"))

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
            factor_scores.append((-60, f"Very High Funding"))
        elif funding_rate > self.config.funding_rate_high:
            factor_scores.append((-30, f"High Funding"))
        elif funding_rate < -0.0005:
            factor_scores.append((60, f"Very Neg Funding"))
        elif funding_rate < self.config.funding_rate_low:
            factor_scores.append((30, f"Neg Funding"))
        else:
            factor_scores.append((0, f"Funding Neutral"))

        # Factor 4: Open Interest momentum
        oi_change = data.open_interest_change_24h
        if oi_change > 5 and price_change > 0:
            factor_scores.append((-25, f"OI+Price Rising (squeeze risk)"))
        elif oi_change > 5 and price_change < 0:
            factor_scores.append((25, f"OI Rising+Price Down (capitulation)"))
        elif oi_change < -5:
            factor_scores.append((15 if price_change > 0 else -15, f"OI Deleveraging"))
        else:
            factor_scores.append((0, f"OI Stable"))

        # Factor 5: Taker Volume
        taker = data.taker_buy_sell_ratio
        if taker > 1.3:
            factor_scores.append((-30, f"Heavy Buying (contrarian)"))
        elif taker < 0.7:
            factor_scores.append((30, f"Heavy Selling (contrarian)"))
        else:
            factor_scores.append((0, f"Volume Balanced"))

        # Factor 6: Top Traders (trend confirmation)
        top_ls = data.top_trader_long_short_ratio
        if top_ls > 1.5:
            factor_scores.append((20, f"TopTraders Long"))
        elif top_ls < 0.7:
            factor_scores.append((-20, f"TopTraders Short"))
        else:
            factor_scores.append((0, f"TopTraders Neutral"))

        # Factor 7: Stablecoin flows
        flow = data.stablecoin_flow_7d
        if flow > 2_000_000_000:
            factor_scores.append((25, f"Large Stablecoin Inflow"))
        elif flow < -2_000_000_000:
            factor_scores.append((-25, f"Large Stablecoin Outflow"))
        else:
            factor_scores.append((0, f"Stables Neutral"))

        # Factor 8: Macro (DXY)
        dxy = data.dxy_index
        if dxy > 107:
            factor_scores.append((-20, f"Strong USD"))
        elif dxy > 0 and dxy < 100:
            factor_scores.append((20, f"Weak USD"))
        else:
            factor_scores.append((0, f"USD Neutral"))

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
            reasons.append(f"High Funding Warning")
        elif funding_rate < -0.0005 and score < 0:
            score += 10
            reasons.append(f"Neg Funding Warning")

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
        min_floor = self.config.min_profit_floor

        max_allowed_loss = daily_return - min_floor
        new_limit = min(self.config.daily_loss_limit_percent, max_allowed_loss)

        return max(new_limit, 0.5)

    def _can_trade(self) -> Tuple[bool, str]:
        """Check if trading is allowed based on limits."""
        if self.daily_trades_count >= self.config.max_trades_per_day:
            return False, f"Daily trade limit ({self.config.max_trades_per_day})"

        daily_return = (self.daily_pnl / self.config.starting_capital) * 100
        loss_limit = self._get_dynamic_loss_limit()

        if daily_return < -loss_limit:
            return False, f"Loss limit ({loss_limit:.2f}%)"

        return True, "OK"

    def _check_exit(
        self, trade: BacktestTrade, current_data: HistoricalDataPoint, next_data: Optional[HistoricalDataPoint]
    ) -> Tuple[bool, TradeResult, float]:
        """Check if a trade should be exited using intraday high/low."""
        if trade.symbol == "BTC":
            high = current_data.btc_high
            low = current_data.btc_low
            close = current_data.btc_price
        else:
            high = current_data.eth_high
            low = current_data.eth_low
            close = current_data.eth_price

        if trade.direction == TradeDirection.LONG:
            if high >= trade.take_profit_price:
                return True, TradeResult.TAKE_PROFIT, trade.take_profit_price
            if low <= trade.stop_loss_price:
                return True, TradeResult.STOP_LOSS, trade.stop_loss_price
        else:
            if low <= trade.take_profit_price:
                return True, TradeResult.TAKE_PROFIT, trade.take_profit_price
            if high >= trade.stop_loss_price:
                return True, TradeResult.STOP_LOSS, trade.stop_loss_price

        if next_data is None:
            return True, TradeResult.TIME_EXIT, close

        return False, TradeResult.OPEN, 0.0

    def _close_trade(
        self, trade: BacktestTrade, exit_date: str, exit_price: float, result: TradeResult, funding_rate: float
    ):
        """Close a trade and update statistics."""
        trade.exit_date = exit_date
        trade.exit_price = exit_price
        trade.result = result

        if trade.direction == TradeDirection.LONG:
            price_pnl = (exit_price - trade.entry_price) / trade.entry_price
        else:
            price_pnl = (trade.entry_price - exit_price) / trade.entry_price

        trade.pnl_percent = price_pnl * 100 * trade.leverage
        trade.pnl = trade.position_value * (price_pnl * trade.leverage)

        trade.fees = trade.position_value * (self.config.trading_fee_percent / 100) * 2
        trade.funding_paid = abs(trade.position_value * funding_rate)
        trade.net_pnl = trade.pnl - trade.fees - trade.funding_paid

        self.capital += trade.net_pnl
        self.daily_pnl += trade.net_pnl

        if trade.symbol in self.open_positions:
            del self.open_positions[trade.symbol]

        logger.debug(
            f"Closed {trade.direction.value} {trade.symbol} @ ${exit_price:.2f} | "
            f"Result: {result.value} | PnL: ${trade.net_pnl:.2f} ({trade.pnl_percent:+.2f}%)"
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

        symbols = ["BTC", "ETH"]

        for i, data in enumerate(data_points):
            if data.date_str != self.current_date:
                if self.current_date:
                    self._save_daily_stats()
                self.current_date = data.date_str
                self.daily_trades_count = 0
                self.daily_pnl = 0.0

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

                entry_price = data.btc_price if symbol == "BTC" else data.eth_price
                if entry_price <= 0:
                    continue

                direction, confidence, reason = self._generate_signal(data, symbol)

                if confidence < self.config.low_confidence_min:
                    continue

                _, position_usdt = self._calculate_position_size(confidence)

                if position_usdt < 10:
                    continue

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

    def _save_daily_stats(self):
        """Save statistics for the current day."""
        if not self.current_date:
            return

        starting = self.capital - self.daily_pnl
        daily_return = (self.daily_pnl / starting) * 100 if starting > 0 else 0
        cumulative_return = ((self.capital - self.config.starting_capital) / self.config.starting_capital) * 100

        stats = DailyBacktestStats(
            date=self.current_date,
            starting_balance=starting,
            ending_balance=self.capital,
            trades_opened=self.daily_trades_count,
            trades_closed=sum(1 for t in self.trades if t.exit_date == self.current_date),
            daily_pnl=self.daily_pnl,
            daily_fees=sum(t.fees for t in self.trades if t.exit_date == self.current_date),
            daily_funding=sum(t.funding_paid for t in self.trades if t.exit_date == self.current_date),
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

        for trade in closed_trades:
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
