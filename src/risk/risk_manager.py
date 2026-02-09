"""
Risk Management Module for the Bitget Trading Bot.

Handles:
- Daily loss limits
- Position sizing
- Trade count limits
- Drawdown protection
- Risk-adjusted returns tracking
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

from src.utils.logger import get_logger, TradeLogger
from config import settings

logger = get_logger(__name__)


@dataclass
class DailyStats:
    """Daily trading statistics."""
    date: str
    starting_balance: float
    current_balance: float
    trades_executed: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    total_fees: float
    total_funding: float
    max_drawdown: float
    is_trading_halted: bool = False
    halt_reason: str = ""

    @property
    def net_pnl(self) -> float:
        """Net PnL after fees and funding."""
        return self.total_pnl - self.total_fees - abs(self.total_funding)

    @property
    def return_percent(self) -> float:
        """Return percentage for the day."""
        if self.starting_balance == 0:
            return 0.0
        return (self.net_pnl / self.starting_balance) * 100

    @property
    def win_rate(self) -> float:
        """Win rate percentage."""
        total = self.winning_trades + self.losing_trades
        if total == 0:
            return 0.0
        return (self.winning_trades / total) * 100

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "date": self.date,
            "starting_balance": self.starting_balance,
            "current_balance": self.current_balance,
            "trades_executed": self.trades_executed,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl": self.total_pnl,
            "total_fees": self.total_fees,
            "total_funding": self.total_funding,
            "net_pnl": self.net_pnl,
            "return_percent": self.return_percent,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
            "is_trading_halted": self.is_trading_halted,
            "halt_reason": self.halt_reason,
        }


class RiskManager:
    """
    Manages trading risk according to configured limits.

    Key Features:
    - Daily loss limit enforcement
    - Maximum trades per day limit
    - Position sizing based on risk
    - Drawdown monitoring
    - Trade statistics tracking
    - Profit Lock-In (dynamic loss limits)
    """

    def __init__(
        self,
        max_trades_per_day: Optional[int] = None,
        daily_loss_limit_percent: Optional[float] = None,
        position_size_percent: Optional[float] = None,
        data_dir: str = "data/risk",
        enable_profit_lock: bool = True,
        profit_lock_percent: float = 75.0,
        min_profit_floor: float = 0.5,
    ):
        """
        Initialize the risk manager.

        Args:
            max_trades_per_day: Maximum number of trades allowed per day
            daily_loss_limit_percent: Maximum loss percentage before halting
            position_size_percent: Default position size as percentage of balance
            data_dir: Directory to store risk data
        """
        self.max_trades = max_trades_per_day or settings.trading.max_trades_per_day
        self.daily_loss_limit = daily_loss_limit_percent or settings.trading.daily_loss_limit_percent
        self.position_size_pct = position_size_percent or settings.trading.position_size_percent

        # Profit Lock-In settings
        self.enable_profit_lock = enable_profit_lock
        self.profit_lock_percent = profit_lock_percent  # Lock 75% of gains
        self.min_profit_floor = min_profit_floor  # Minimum profit to keep (0.5%)

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.trade_logger = TradeLogger()
        self._daily_stats: Optional[DailyStats] = None
        self._load_daily_stats()

    def _get_stats_file(self, for_date: Optional[str] = None) -> Path:
        """Get the path to the daily stats file."""
        date_str = for_date or datetime.now().strftime("%Y-%m-%d")
        return self.data_dir / f"daily_stats_{date_str}.json"

    def _load_daily_stats(self) -> None:
        """Load today's stats from file or create new."""
        today = datetime.now().strftime("%Y-%m-%d")
        stats_file = self._get_stats_file(today)

        if stats_file.exists():
            try:
                with open(stats_file, "r") as f:
                    data = json.load(f)
                    # Remove computed properties that are not dataclass fields
                    for key in ("net_pnl", "return_percent", "win_rate"):
                        data.pop(key, None)
                    self._daily_stats = DailyStats(**data)
                    logger.info(f"Loaded daily stats: {self._daily_stats.trades_executed} trades, "
                               f"PnL: ${self._daily_stats.net_pnl:.2f}")
            except Exception as e:
                logger.error(f"Error loading daily stats: {e}")
                self._daily_stats = None

    def _save_daily_stats(self) -> None:
        """Save current daily stats to file."""
        if self._daily_stats:
            stats_file = self._get_stats_file(self._daily_stats.date)
            try:
                with open(stats_file, "w") as f:
                    json.dump(self._daily_stats.to_dict(), f, indent=2)
            except Exception as e:
                logger.error(f"Error saving daily stats: {e}")

    def initialize_day(self, starting_balance: float) -> DailyStats:
        """
        Initialize a new trading day.

        Args:
            starting_balance: Account balance at start of day

        Returns:
            DailyStats for the new day
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # Check if we already have stats for today
        if self._daily_stats and self._daily_stats.date == today:
            logger.info(f"Day already initialized. Trades: {self._daily_stats.trades_executed}")
            return self._daily_stats

        self._daily_stats = DailyStats(
            date=today,
            starting_balance=starting_balance,
            current_balance=starting_balance,
            trades_executed=0,
            winning_trades=0,
            losing_trades=0,
            total_pnl=0.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
        )

        self._save_daily_stats()
        logger.info(f"Initialized new trading day with balance: ${starting_balance:,.2f}")

        return self._daily_stats

    def get_dynamic_loss_limit(self) -> float:
        """
        Calculate dynamic loss limit based on current daily PnL.

        Implements the Profit Lock-In feature:
        - When in profit, reduces allowed loss to lock in gains
        - Example: If +4% profit, with 75% lock, only allows -1% loss
          (keeping minimum +0.5% profit)

        Returns:
            Current effective loss limit as percentage
        """
        if not self.enable_profit_lock or not self._daily_stats:
            return self.daily_loss_limit

        current_return = self._daily_stats.return_percent

        if current_return <= 0:
            # Not in profit, use standard loss limit
            return self.daily_loss_limit

        # Calculate how much profit to lock
        # locked_profit = current_return * (profit_lock_percent / 100)
        # The max allowed loss = current_return - min_profit_floor
        # But capped at standard loss limit

        max_allowed_loss = current_return - self.min_profit_floor
        new_limit = min(self.daily_loss_limit, max_allowed_loss)

        # Ensure at least some small loss is allowed for flexibility
        new_limit = max(new_limit, 0.5)

        logger.debug(
            f"Profit Lock-In: Return={current_return:.2f}%, "
            f"Dynamic Limit={new_limit:.2f}% (Standard: {self.daily_loss_limit}%)"
        )

        return new_limit

    def can_trade(self) -> tuple[bool, str]:
        """
        Check if trading is allowed based on risk limits.

        Returns:
            Tuple of (can_trade: bool, reason: str)
        """
        if not self._daily_stats:
            return False, "Daily stats not initialized. Call initialize_day() first."

        # Check if trading is halted
        if self._daily_stats.is_trading_halted:
            return False, f"Trading halted: {self._daily_stats.halt_reason}"

        # Check trade count limit
        if self._daily_stats.trades_executed >= self.max_trades:
            return False, f"Daily trade limit reached ({self.max_trades} trades)"

        # Check dynamic loss limit (includes Profit Lock-In)
        current_loss_limit = self.get_dynamic_loss_limit()
        loss_percent = abs(min(0, self._daily_stats.return_percent))

        if loss_percent >= current_loss_limit:
            self._halt_trading(f"Loss limit exceeded ({loss_percent:.2f}% > {current_loss_limit:.2f}%)")
            return False, f"Loss limit exceeded: {loss_percent:.2f}%"

        return True, "Trading allowed"

    def _halt_trading(self, reason: str) -> None:
        """Halt trading for the day."""
        if self._daily_stats:
            self._daily_stats.is_trading_halted = True
            self._daily_stats.halt_reason = reason
            self._save_daily_stats()
            logger.warning(f"TRADING HALTED: {reason}")

    def calculate_position_size(
        self,
        balance: float,
        entry_price: float,
        confidence: int = 50,
        leverage: int = 1,
    ) -> tuple[float, float]:
        """
        Calculate position size based on risk parameters.

        Args:
            balance: Available balance in USDT
            entry_price: Entry price of the asset
            confidence: Strategy confidence (0-100)
            leverage: Leverage to use

        Returns:
            Tuple of (position_size_usdt, position_size_base)
        """
        # Base position size
        base_size_pct = self.position_size_pct

        # Scale with confidence
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

        # Calculate position value
        position_pct = min(base_size_pct * multiplier, 25.0)  # Cap at 25% of balance
        position_usdt = balance * (position_pct / 100)

        # Calculate base currency amount
        position_base = (position_usdt * leverage) / entry_price

        logger.info(
            f"Position Size: {position_pct:.1f}% = ${position_usdt:,.2f} USDT "
            f"= {position_base:.6f} @ ${entry_price:,.2f} (leverage: {leverage}x)"
        )

        return position_usdt, position_base

    def record_trade_entry(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        leverage: int,
        confidence: int,
        reason: str,
        order_id: str,
    ) -> bool:
        """
        Record a trade entry and update daily stats.

        Args:
            symbol: Trading pair
            side: long or short
            size: Position size
            entry_price: Entry price
            leverage: Leverage used
            confidence: Strategy confidence
            reason: Trade reason
            order_id: Exchange order ID

        Returns:
            True if recorded successfully
        """
        if not self._daily_stats:
            logger.error("Daily stats not initialized!")
            return False

        # Update trade count
        self._daily_stats.trades_executed += 1

        # Log the trade
        self.trade_logger.log_trade_entry(
            symbol=symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            leverage=leverage,
            confidence=confidence,
            reason=reason,
            order_id=order_id,
        )

        self._save_daily_stats()
        logger.info(f"Trade entry recorded. Trades today: {self._daily_stats.trades_executed}/{self.max_trades}")

        return True

    def record_trade_exit(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        exit_price: float,
        fees: float,
        funding_paid: float,
        reason: str,
        order_id: str,
    ) -> bool:
        """
        Record a trade exit and update daily stats.

        Args:
            symbol: Trading pair
            side: long or short
            size: Position size
            entry_price: Entry price
            exit_price: Exit price
            fees: Trading fees paid
            funding_paid: Funding payments
            reason: Exit reason
            order_id: Exchange order ID

        Returns:
            True if recorded successfully
        """
        if not self._daily_stats:
            logger.error("Daily stats not initialized!")
            return False

        # Calculate PnL
        if side.lower() == "long":
            pnl = (exit_price - entry_price) * size
        else:  # short
            pnl = (entry_price - exit_price) * size

        pnl_percent = (pnl / (entry_price * size)) * 100

        # Update stats
        self._daily_stats.total_pnl += pnl
        self._daily_stats.total_fees += fees
        self._daily_stats.total_funding += funding_paid
        self._daily_stats.current_balance += (pnl - fees - funding_paid)

        if pnl > 0:
            self._daily_stats.winning_trades += 1
        else:
            self._daily_stats.losing_trades += 1

        # Update max drawdown
        current_drawdown = abs(min(0, self._daily_stats.return_percent))
        self._daily_stats.max_drawdown = max(self._daily_stats.max_drawdown, current_drawdown)

        # Log the trade
        self.trade_logger.log_trade_exit(
            symbol=symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            pnl_percent=pnl_percent,
            fees=fees,
            funding_paid=funding_paid,
            reason=reason,
            order_id=order_id,
        )

        self._save_daily_stats()

        logger.info(
            f"Trade exit recorded: PnL=${pnl:.2f} ({pnl_percent:+.2f}%) | "
            f"Day PnL: ${self._daily_stats.net_pnl:.2f} ({self._daily_stats.return_percent:+.2f}%)"
        )

        # Check if we hit loss limit
        if self._daily_stats.return_percent <= -self.daily_loss_limit:
            self._halt_trading(f"Daily loss limit reached: {self._daily_stats.return_percent:.2f}%")

        return True

    def get_daily_stats(self) -> Optional[DailyStats]:
        """Get current daily statistics."""
        return self._daily_stats

    def get_remaining_trades(self) -> int:
        """Get number of trades remaining for today."""
        if not self._daily_stats:
            return self.max_trades
        return max(0, self.max_trades - self._daily_stats.trades_executed)

    def get_remaining_risk_budget(self) -> float:
        """Get remaining risk budget as percentage."""
        if not self._daily_stats:
            return self.daily_loss_limit

        current_loss = abs(min(0, self._daily_stats.return_percent))
        return max(0, self.daily_loss_limit - current_loss)

    def get_historical_stats(self, days: int = 30) -> List[Dict]:
        """
        Get historical daily stats.

        Args:
            days: Number of days to fetch

        Returns:
            List of daily stats dictionaries
        """
        stats = []
        current_date = datetime.now()

        for i in range(days):
            check_date = current_date - timedelta(days=i)
            date_str = check_date.strftime("%Y-%m-%d")
            stats_file = self._get_stats_file(date_str)

            if stats_file.exists():
                try:
                    with open(stats_file, "r") as f:
                        stats.append(json.load(f))
                except Exception:
                    pass

        return stats

    def get_performance_summary(self, days: int = 30) -> Dict:
        """
        Calculate performance summary over a period.

        Args:
            days: Number of days to analyze

        Returns:
            Performance summary dictionary
        """
        historical = self.get_historical_stats(days)

        if not historical:
            return {
                "period_days": 0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "total_fees": 0.0,
                "average_daily_return": 0.0,
                "max_drawdown": 0.0,
                "sharpe_estimate": 0.0,
            }

        total_trades = sum(d.get("trades_executed", 0) for d in historical)
        winning = sum(d.get("winning_trades", 0) for d in historical)
        losing = sum(d.get("losing_trades", 0) for d in historical)
        total_pnl = sum(d.get("net_pnl", 0) for d in historical)
        total_fees = sum(d.get("total_fees", 0) for d in historical)
        returns = [d.get("return_percent", 0) for d in historical]
        max_dd = max(d.get("max_drawdown", 0) for d in historical)

        avg_return = sum(returns) / len(returns) if returns else 0
        return_std = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5 if returns else 1

        # Simple Sharpe estimate (annualized)
        sharpe = (avg_return / return_std * (252 ** 0.5)) if return_std > 0 else 0

        return {
            "period_days": len(historical),
            "total_trades": total_trades,
            "winning_trades": winning,
            "losing_trades": losing,
            "win_rate": (winning / (winning + losing) * 100) if (winning + losing) > 0 else 0,
            "total_pnl": total_pnl,
            "total_fees": total_fees,
            "average_daily_return": avg_return,
            "max_drawdown": max_dd,
            "sharpe_estimate": sharpe,
        }
