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
    #  SIGNAL GENERATION                                                  #
    # ------------------------------------------------------------------ #

    def _generate_signal(
        self, data: HistoricalDataPoint, symbol: str = "BTC"
    ) -> Tuple[TradeDirection, int, str]:
        """
        Generate a trade signal based on historical data point.

        Combines analysis from all available data sources:
        1. Long/Short Ratio (contrarian)
        2. Fear & Greed Index (contrarian)
        3. Funding Rate (trend confirmation)
        4. Open Interest changes
        5. Taker Buy/Sell Volume (contrarian)
        6. Top Trader positioning (confirmation)
        7. Cross-exchange funding divergence
        8. Stablecoin flows (money flow)
        9. Volatility (risk adjustment)
        10. Macro indicators (DXY)

        Returns:
            Tuple of (direction, confidence, reason)
        """
        reasons = []
        confidence = 50

        if symbol == "BTC":
            funding_rate = data.funding_rate_btc
            price_change = data.btc_24h_change
        else:
            funding_rate = data.funding_rate_eth
            price_change = data.eth_24h_change

        # Step 1: Primary - Analyze Leverage
        leverage_dir, leverage_conf, leverage_reason = self._analyze_leverage(data.long_short_ratio)
        reasons.append(leverage_reason)
        confidence += leverage_conf

        # Step 2: Primary - Analyze Sentiment
        sentiment_dir, sentiment_conf, sentiment_reason = self._analyze_sentiment(data.fear_greed_index)
        reasons.append(sentiment_reason)
        confidence += sentiment_conf

        # Step 3: Determine Base Direction
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

        # Step 4: Funding Rate Adjustment
        funding_adj, funding_reason = self._analyze_funding_rate(funding_rate, final_direction)
        confidence += funding_adj
        reasons.append(funding_reason)

        # Step 5: Open Interest Analysis
        oi_adj, oi_reason = self._analyze_open_interest(data, final_direction)
        confidence += oi_adj
        if oi_adj != 0:
            reasons.append(oi_reason)

        # Step 6: Taker Volume Analysis
        taker_adj, taker_reason = self._analyze_taker_volume(data, final_direction)
        confidence += taker_adj
        if taker_adj != 0:
            reasons.append(taker_reason)

        # Step 7: Top Trader Analysis
        top_adj, top_reason = self._analyze_top_traders(data, final_direction)
        confidence += top_adj
        if top_adj != 0:
            reasons.append(top_reason)

        # Step 8: Cross-Exchange Funding Divergence
        div_adj, div_reason = self._analyze_funding_divergence(data, final_direction)
        confidence += div_adj
        if div_adj != 0:
            reasons.append(div_reason)

        # Step 9: Stablecoin Flows
        stable_adj, stable_reason = self._analyze_stablecoin_flows(data, final_direction)
        confidence += stable_adj
        if stable_adj != 0:
            reasons.append(stable_reason)

        # Step 10: Volatility Risk Adjustment
        vol_adj, vol_reason = self._analyze_volatility(data)
        confidence += vol_adj
        if vol_adj != 0:
            reasons.append(vol_reason)

        # Step 11: Macro (DXY)
        macro_adj, macro_reason = self._analyze_macro(data, final_direction)
        confidence += macro_adj
        if macro_adj != 0:
            reasons.append(macro_reason)

        # Clamp confidence
        confidence = max(self.config.low_confidence_min, min(confidence, 95))

        return final_direction, confidence, " | ".join(reasons)

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
