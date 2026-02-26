"""
Kline-based Backtest Engine for Technical Strategies.

Simulates trading over historical kline (OHLCV) data using strategies
that only depend on candlestick data (e.g., Edge Indicator).

Usage:
    engine = KlineBacktestEngine(config)
    result = engine.run(klines, strategy_cls, strategy_params)
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Type

from src.data.market_data import MarketDataFetcher
from src.strategy.base import BaseStrategy, SignalDirection, TradeSignal
from src.utils.logger import get_logger

logger = get_logger(__name__)


class KlineTradeResult(Enum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TIME_EXIT = "time_exit"


@dataclass
class KlineTrade:
    """A single trade in the kline backtest."""
    id: int
    direction: str  # "long" or "short"
    entry_bar: int
    entry_price: float
    take_profit: Optional[float]
    stop_loss: Optional[float]
    confidence: int
    reason: str
    position_value: float
    leverage: int

    exit_bar: Optional[int] = None
    exit_price: Optional[float] = None
    result: Optional[KlineTradeResult] = None
    pnl: float = 0.0
    pnl_percent: float = 0.0
    fees: float = 0.0
    net_pnl: float = 0.0
    bars_held: int = 0

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "direction": self.direction,
            "entry_bar": self.entry_bar,
            "entry_price": self.entry_price,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "confidence": self.confidence,
            "reason": self.reason,
            "exit_bar": self.exit_bar,
            "exit_price": self.exit_price,
            "result": self.result.value if self.result else None,
            "pnl": round(self.pnl, 2),
            "pnl_percent": round(self.pnl_percent, 2),
            "fees": round(self.fees, 2),
            "net_pnl": round(self.net_pnl, 2),
            "bars_held": self.bars_held,
        }


@dataclass
class KlineBacktestConfig:
    """Configuration for kline-based backtest."""
    starting_capital: float = 10000.0
    leverage: int = 3
    position_size_percent: float = 10.0
    trading_fee_percent: float = 0.06
    max_bars_in_trade: int = 50
    cooldown_bars: int = 2
    min_confidence: int = 40


@dataclass
class KlineBacktestResult:
    """Complete kline backtest result."""
    interval: str
    starting_capital: float
    ending_capital: float
    total_return_percent: float
    max_drawdown_percent: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float
    sharpe_ratio: Optional[float]
    total_pnl: float
    total_fees: float
    trades: List[KlineTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    total_bars: int = 0
    avg_bars_held: float = 0.0

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"=== Backtest: {self.interval} ===\n"
            f"  Capital: ${self.starting_capital:,.2f} -> ${self.ending_capital:,.2f}\n"
            f"  Return: {self.total_return_percent:+.2f}%\n"
            f"  Max Drawdown: {self.max_drawdown_percent:.2f}%\n"
            f"  Trades: {self.total_trades} (W:{self.winning_trades} L:{self.losing_trades})\n"
            f"  Win Rate: {self.win_rate:.1f}%\n"
            f"  Profit Factor: {self.profit_factor:.2f}\n"
            f"  Sharpe Ratio: {self.sharpe_ratio:.2f}\n"
            f"  Avg Bars Held: {self.avg_bars_held:.1f}\n"
            f"  Total Fees: ${self.total_fees:.2f}\n"
        )

    def to_dict(self) -> Dict:
        return {
            "interval": self.interval,
            "starting_capital": self.starting_capital,
            "ending_capital": round(self.ending_capital, 2),
            "total_return_percent": round(self.total_return_percent, 2),
            "max_drawdown_percent": round(self.max_drawdown_percent, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 1),
            "average_win": round(self.average_win, 2),
            "average_loss": round(self.average_loss, 2),
            "profit_factor": round(self.profit_factor, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2) if self.sharpe_ratio else None,
            "total_pnl": round(self.total_pnl, 2),
            "total_fees": round(self.total_fees, 2),
            "total_bars": self.total_bars,
            "avg_bars_held": round(self.avg_bars_held, 1),
        }


class KlineBacktestEngine:
    """
    Backtest engine for strategies that operate on kline (OHLCV) data.

    Walks through klines bar-by-bar, generates signals using a sliding
    window of past candles, and simulates trade execution with TP/SL.
    """

    def __init__(self, config: Optional[KlineBacktestConfig] = None):
        self.config = config or KlineBacktestConfig()

    def run(
        self,
        klines: List[List],
        strategy_cls: Type[BaseStrategy],
        strategy_params: Optional[Dict[str, Any]] = None,
        interval: str = "1h",
        lookback: int = 200,
    ) -> KlineBacktestResult:
        """
        Run a backtest over kline data.

        Args:
            klines: Full list of OHLCV klines
            strategy_cls: Strategy class to test
            strategy_params: Parameters for the strategy
            interval: Kline interval label (for reporting)
            lookback: Number of bars the strategy needs for indicators

        Returns:
            KlineBacktestResult with all metrics
        """
        capital = self.config.starting_capital
        trades: List[KlineTrade] = []
        equity_curve = [capital]
        trade_counter = 0
        open_trade: Optional[KlineTrade] = None
        cooldown_remaining = 0

        if len(klines) <= lookback:
            return self._empty_result(interval, capital)

        # Create strategy instance (no data_fetcher needed - we feed data directly)
        params = {**(strategy_params or {}), "kline_interval": interval, "kline_count": lookback}
        strategy = strategy_cls(params=params)

        for bar_idx in range(lookback, len(klines)):
            # Get current bar's OHLC
            current_bar = klines[bar_idx]
            try:
                bar_high = float(current_bar[2])
                bar_low = float(current_bar[3])
                bar_close = float(current_bar[4])
            except (IndexError, ValueError, TypeError):
                equity_curve.append(capital)
                continue

            # Check open trade for exit
            if open_trade is not None:
                open_trade.bars_held += 1
                exited = False

                # Check TP/SL against high/low (skip None targets)
                if open_trade.direction == "long":
                    if open_trade.take_profit is not None and bar_high >= open_trade.take_profit:
                        exited = True
                        exit_price = open_trade.take_profit
                        result = KlineTradeResult.TAKE_PROFIT
                    elif open_trade.stop_loss is not None and bar_low <= open_trade.stop_loss:
                        exited = True
                        exit_price = open_trade.stop_loss
                        result = KlineTradeResult.STOP_LOSS
                else:  # short
                    if open_trade.take_profit is not None and bar_low <= open_trade.take_profit:
                        exited = True
                        exit_price = open_trade.take_profit
                        result = KlineTradeResult.TAKE_PROFIT
                    elif open_trade.stop_loss is not None and bar_high >= open_trade.stop_loss:
                        exited = True
                        exit_price = open_trade.stop_loss
                        result = KlineTradeResult.STOP_LOSS

                # Time exit
                if not exited and open_trade.bars_held >= self.config.max_bars_in_trade:
                    exited = True
                    exit_price = bar_close
                    result = KlineTradeResult.TIME_EXIT

                if exited:
                    capital = self._close_trade(open_trade, bar_idx, exit_price, result, capital)
                    open_trade = None
                    cooldown_remaining = self.config.cooldown_bars

                equity_curve.append(capital)
                continue

            # Cooldown
            if cooldown_remaining > 0:
                cooldown_remaining -= 1
                equity_curve.append(capital)
                continue

            # Generate signal from lookback window
            window = klines[bar_idx - lookback:bar_idx]
            signal = self._generate_signal_sync(strategy, window)

            if (signal and signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)
                    and signal.confidence >= self.config.min_confidence and signal.entry_price > 0):
                # Open new trade
                trade_counter += 1
                pos_value = capital * (self.config.position_size_percent / 100)

                direction = "long" if signal.direction == SignalDirection.LONG else "short"

                open_trade = KlineTrade(
                    id=trade_counter,
                    direction=direction,
                    entry_bar=bar_idx,
                    entry_price=signal.entry_price,
                    take_profit=signal.target_price,
                    stop_loss=signal.stop_loss,
                    confidence=signal.confidence,
                    reason=signal.reason[:100],
                    position_value=pos_value,
                    leverage=self.config.leverage,
                )
                trades.append(open_trade)

            equity_curve.append(capital)

        # Close any remaining trade at last close
        if open_trade is not None:
            try:
                last_close = float(klines[-1][4])
            except (IndexError, ValueError, TypeError):
                last_close = open_trade.entry_price
            capital = self._close_trade(
                open_trade, len(klines) - 1, last_close, KlineTradeResult.TIME_EXIT, capital
            )
            equity_curve.append(capital)

        return self._build_result(interval, trades, equity_curve, len(klines))

    def _generate_signal_sync(self, strategy: BaseStrategy, klines_window: List[List]) -> Optional[TradeSignal]:
        """Generate a signal synchronously by calling indicator methods directly."""
        closes = []
        for k in klines_window:
            try:
                closes.append(float(k[4]))
            except (IndexError, ValueError, TypeError):
                continue

        if not closes or len(closes) < strategy._p.get("ema_slow_period", 21) + 10:
            return None

        current_price = closes[-1]
        if current_price <= 0:
            return None

        # Calculate indicators directly
        ribbon = strategy._calculate_ema_ribbon(closes)
        adx_data = MarketDataFetcher.calculate_adx(klines_window, strategy._p.get("adx_period", 14))
        momentum = strategy._calculate_predator_momentum(closes, klines_window, ribbon["ema_fast_above"])

        direction, reason = strategy._determine_direction(ribbon, momentum, adx_data)
        confidence = strategy._calculate_confidence(adx_data, momentum, ribbon)
        take_profit, stop_loss = strategy._calculate_targets(direction, current_price, klines_window)

        return TradeSignal(
            direction=direction,
            confidence=confidence,
            symbol="BTCUSDT",
            entry_price=current_price,
            target_price=take_profit,
            stop_loss=stop_loss,
            reason=reason,
            metrics_snapshot={},
            timestamp=datetime.now(),
        )

    def _close_trade(
        self, trade: KlineTrade, bar_idx: int, exit_price: float,
        result: KlineTradeResult, capital: float
    ) -> float:
        """Close a trade and return updated capital."""
        trade.exit_bar = bar_idx
        trade.exit_price = exit_price
        trade.result = result

        if trade.direction == "long":
            price_pnl_pct = (exit_price - trade.entry_price) / trade.entry_price
        else:
            price_pnl_pct = (trade.entry_price - exit_price) / trade.entry_price

        trade.pnl_percent = price_pnl_pct * 100 * trade.leverage
        trade.pnl = trade.position_value * price_pnl_pct * trade.leverage
        trade.fees = trade.position_value * (self.config.trading_fee_percent / 100) * 2
        trade.net_pnl = trade.pnl - trade.fees

        return capital + trade.net_pnl

    def _build_result(
        self, interval: str, trades: List[KlineTrade],
        equity_curve: List[float], total_bars: int
    ) -> KlineBacktestResult:
        """Build the final result from trades and equity curve."""
        starting = self.config.starting_capital
        ending = equity_curve[-1] if equity_curve else starting

        closed = [t for t in trades if t.result is not None]
        winners = [t for t in closed if t.net_pnl > 0]
        losers = [t for t in closed if t.net_pnl <= 0]

        total_pnl = sum(t.net_pnl for t in closed)
        total_fees = sum(t.fees for t in closed)

        avg_win = sum(t.net_pnl for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t.net_pnl for t in losers) / len(losers) if losers else 0

        gross_profit = sum(t.net_pnl for t in winners)
        gross_loss = abs(sum(t.net_pnl for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.99

        # Max drawdown
        peak = starting
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio (per-trade returns)
        trade_returns = [t.pnl_percent / 100 for t in closed]
        sharpe = self._calculate_sharpe(trade_returns)

        avg_bars = sum(t.bars_held for t in closed) / len(closed) if closed else 0

        return KlineBacktestResult(
            interval=interval,
            starting_capital=starting,
            ending_capital=ending,
            total_return_percent=((ending - starting) / starting) * 100 if starting > 0 else 0,
            max_drawdown_percent=max_dd,
            total_trades=len(closed),
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=(len(winners) / len(closed) * 100) if closed else 0,
            average_win=avg_win,
            average_loss=avg_loss,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe,
            total_pnl=total_pnl,
            total_fees=total_fees,
            trades=trades,
            equity_curve=equity_curve,
            total_bars=total_bars,
            avg_bars_held=avg_bars,
        )

    def _empty_result(self, interval: str, capital: float) -> KlineBacktestResult:
        return KlineBacktestResult(
            interval=interval,
            starting_capital=capital,
            ending_capital=capital,
            total_return_percent=0,
            max_drawdown_percent=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0,
            average_win=0,
            average_loss=0,
            profit_factor=0,
            sharpe_ratio=None,
            total_pnl=0,
            total_fees=0,
        )

    @staticmethod
    def _calculate_sharpe(returns: List[float], risk_free: float = 0.0) -> Optional[float]:
        if len(returns) < 2:
            return None
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(variance) if variance > 0 else 0
        if std == 0:
            return None
        return round((mean - risk_free) / std * math.sqrt(len(returns)), 2)
