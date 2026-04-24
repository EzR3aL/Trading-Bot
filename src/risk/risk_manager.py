"""Risk Management façade (#326 Phase 2 PR-8).

Thin composition façade over the risk components in
``src.bot.components.risk`` — DailyStatsAggregator (PnL counters),
TradeGate (can_trade + halt), RiskStatePersistence (DB I/O). This module
wires them together and owns the trade-logger side effect.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional

from src.utils.logger import TradeLogger, get_logger

# ``get_session`` re-exported so tests can patch
# ``src.risk.risk_manager.get_session``. Persistence routes through here.
_db_available = True
try:
    from src.models.session import get_session
except ImportError:
    _db_available = False
    get_session = None  # type: ignore[assignment]

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from src.bot.components.risk.daily_stats import DailyStats

__all__ = ["DailyStats", "RiskManager"]


def _classify_gate_reason(reason: str, symbol: Optional[str]) -> str:
    """Map a ``can_trade`` reason string to a Prometheus metric label."""
    if "not initialized" in reason:
        return "block_uninitialized"
    if reason.startswith("Trading halted"):
        return "block_global_halted"
    if symbol and reason.startswith(f"{symbol} halted"):
        return "block_symbol_halted"
    per_symbol = symbol is not None and reason.startswith(f"{symbol}:")
    if "trade limit" in reason:
        return "block_max_trades_symbol" if per_symbol else "block_max_trades"
    if "Loss limit" in reason or "loss limit" in reason:
        return "block_daily_loss_symbol" if per_symbol else "block_daily_loss"
    return "block_other"


class RiskManager:
    """Composition façade for per-bot risk state and gating."""

    def __init__(
        self,
        max_trades_per_day: Optional[int] = None,
        daily_loss_limit_percent: Optional[float] = None,
        position_size_percent: Optional[float] = None,
        data_dir: str = os.getenv("RISK_DATA_DIR", "data/risk"),
        enable_profit_lock: bool = True,
        profit_lock_percent: float = 75.0,
        min_profit_floor: float = 0.5,
        per_symbol_limits: Optional[Dict[str, Dict]] = None,
        bot_config_id: Optional[int] = None,
    ):
        self.max_trades = max_trades_per_day
        self.daily_loss_limit = daily_loss_limit_percent
        self.position_size_pct = position_size_percent
        self.per_symbol_limits = per_symbol_limits or {}
        self.enable_profit_lock = enable_profit_lock
        self.profit_lock_percent = profit_lock_percent
        self.min_profit_floor = min_profit_floor
        self.bot_config_id = bot_config_id
        self._use_db = bot_config_id is not None and _db_available

        # Lazy import to break the src.bot ↔ src.risk cycle.
        from src.bot.components.risk.persistence import RiskStatePersistence
        self._persistence = RiskStatePersistence(
            bot_config_id=bot_config_id,
            session_factory=self._get_session_proxy,
            dailystats_cls=DailyStats,
        )

        self.trade_logger = TradeLogger()
        self._daily_stats_aggregator = DailyStatsAggregator()
        self._trade_gate = TradeGate(
            aggregator=self._daily_stats_aggregator,
            max_trades_per_day=max_trades_per_day,
            daily_loss_limit_percent=daily_loss_limit_percent,
            per_symbol_limits=self.per_symbol_limits,
            enable_profit_lock=enable_profit_lock,
            profit_lock_percent=profit_lock_percent,
            min_profit_floor=min_profit_floor,
            save_stats=self._save_daily_stats,
        )

    def _save_daily_stats(self) -> None:
        """Schedule an async DB write for current daily stats."""
        if not self._daily_stats_aggregator.get_daily_stats():
            return
        if self._use_db:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._save_stats_to_db())
            except RuntimeError:
                logger.debug("No running event loop — DB stats write deferred")

    def _get_session_proxy(self):
        """Return the current module-level ``get_session`` context manager."""
        return get_session()

    async def _save_stats_to_db(self) -> None:
        """Persist current daily stats to the risk_stats table."""
        stats = self._daily_stats_aggregator.get_daily_stats()
        if not stats or not self._use_db:
            return
        await self._persistence.save_stats(stats)

    async def load_stats_from_db(self) -> None:
        """Load today's stats from DB (call after async init)."""
        if not self._use_db:
            return
        stats = await self._persistence.load_stats()
        if stats is not None:
            self._daily_stats_aggregator.hydrate(stats)

    async def get_historical_stats_from_db(self, days: int = 30) -> List[Dict]:
        """Get historical stats from the database."""
        if not self._use_db:
            return []
        return await self._persistence.get_historical_stats(days)

    def initialize_day(self, starting_balance: float) -> "DailyStats":
        """Initialize a new trading day. Delegates to the aggregator."""
        existing = self._daily_stats_aggregator.get_daily_stats()
        today = datetime.now().strftime("%Y-%m-%d")
        is_new_day = existing is None or existing.date != today
        stats = self._daily_stats_aggregator.initialize_day(starting_balance)
        if is_new_day:
            self._save_daily_stats()
        return stats

    def get_dynamic_loss_limit(self, symbol: Optional[str] = None) -> Optional[float]:
        """Profit-lock-in adjusted loss limit — delegates to TradeGate."""
        return self._trade_gate.get_dynamic_loss_limit(symbol)

    def can_trade(self, symbol: Optional[str] = None) -> tuple[bool, str]:
        """Trade-limit gate — delegates to TradeGate + emits metrics."""
        allowed, reason = self._trade_gate.can_trade(symbol)
        try:
            from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
            bot_id_label = (
                str(self.bot_config_id) if self.bot_config_id is not None else "unknown"
            )
            decision = "allow" if allowed else _classify_gate_reason(reason, symbol)
            RISK_TRADE_GATE_DECISIONS_TOTAL.labels(
                bot_id=bot_id_label, decision=decision
            ).inc()
        except Exception:  # noqa: BLE001 — metrics never break the gate
            pass
        return allowed, reason

    def calculate_position_size(
        self, balance: float, entry_price: float,
        confidence: int = 50, leverage: int = 1,
    ) -> tuple[float, float]:
        """Calculate position size based on risk parameters."""
        base_size_pct = self.position_size_pct
        if base_size_pct is None:
            position_usdt = balance
            position_pct = 100.0
        else:
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
            position_usdt = balance * (position_pct / 100)
        position_base = (position_usdt * leverage) / entry_price
        logger.info(
            f"Position Size: {position_pct:.1f}% = ${position_usdt:,.2f} USDT "
            f"= {position_base:.6f} @ ${entry_price:,.2f} (leverage: {leverage}x)"
        )
        return position_usdt, position_base

    def record_trade_entry(
        self, symbol: str, side: str, size: float, entry_price: float,
        leverage: int, confidence: int, reason: str, order_id: str,
    ) -> bool:
        """Record a trade entry and update daily stats."""
        if not self._daily_stats_aggregator.record_entry(symbol):
            return False
        self.trade_logger.log_trade_entry(
            symbol=symbol, side=side, size=size, entry_price=entry_price,
            leverage=leverage, confidence=confidence, reason=reason, order_id=order_id,
        )
        self._save_daily_stats()
        stats = self._daily_stats_aggregator.get_daily_stats()
        symbol_count = stats.symbol_trades[symbol]
        limit_str = str(self.max_trades) if self.max_trades is not None else "∞"
        logger.info(f"Trade entry recorded. {symbol}: {symbol_count}/{limit_str} trades today")
        return True

    def record_trade_exit(
        self, symbol: str, side: str, size: float, entry_price: float,
        exit_price: float, fees: float, funding_paid: float,
        reason: str, order_id: str,
    ) -> bool:
        """Record a trade exit and update daily stats."""
        exit_result = self._daily_stats_aggregator.record_exit(
            symbol=symbol, side=side, size=size,
            entry_price=entry_price, exit_price=exit_price,
            fees=fees, funding_paid=funding_paid,
        )
        if exit_result is None:
            return False
        pnl, pnl_percent = exit_result
        self.trade_logger.log_trade_exit(
            symbol=symbol, side=side, size=size,
            entry_price=entry_price, exit_price=exit_price,
            pnl=pnl, pnl_percent=pnl_percent,
            fees=fees, funding_paid=funding_paid,
            reason=reason, order_id=order_id,
        )
        self._save_daily_stats()
        stats = self._daily_stats_aggregator.get_daily_stats()
        logger.info(
            f"Trade exit recorded: {symbol} PnL=${pnl:.2f} ({pnl_percent:+.2f}%) | "
            f"Day PnL: ${stats.net_pnl:.2f} ({stats.return_percent:+.2f}%)"
        )
        self._trade_gate.check_and_halt(symbol)
        return True

    def get_daily_stats(self) -> "Optional[DailyStats]":
        """Get current daily statistics."""
        return self._daily_stats_aggregator.get_daily_stats()

    def get_remaining_trades(self, symbol: Optional[str] = None) -> int:
        """Remaining trades for today — delegates to TradeGate."""
        return self._trade_gate.get_remaining_trades(symbol)

    def get_remaining_risk_budget(self) -> Optional[float]:
        """Remaining loss-limit percent — delegates to TradeGate."""
        return self._trade_gate.get_remaining_risk_budget()

    def get_historical_stats(self, days: int = 30) -> List[Dict]:
        """Deprecated sync wrapper — always returns ``[]``."""
        return []

    def get_performance_summary(self, days: int = 30) -> Dict:
        """Calculate performance summary over a period."""
        historical = self.get_historical_stats(days)
        if not historical:
            return {
                "period_days": 0, "total_trades": 0, "winning_trades": 0,
                "losing_trades": 0, "win_rate": 0.0, "total_pnl": 0.0,
                "total_fees": 0.0, "average_daily_return": 0.0,
                "max_drawdown": 0.0, "sharpe_estimate": 0.0,
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


# Deferred imports — ``RiskManager`` is fully defined, so triggering
# ``src.bot.__init__`` → ``BotWorker`` → ``RiskManager`` resolves.
from src.bot.components.risk.daily_stats import (  # noqa: E402
    DailyStats,
    DailyStatsAggregator,
)
from src.bot.components.risk.trade_gate import TradeGate  # noqa: E402
