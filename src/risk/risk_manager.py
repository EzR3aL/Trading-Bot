"""
Risk Management Module for the Bitget Trading Bot.

Handles:
- Daily loss limits
- Position sizing
- Trade count limits
- Drawdown protection
- Risk-adjusted returns tracking

Composition note (#326 Phase 1 PR-5 + PR-6):
The daily stats aggregation (PnL counters, trade counter, per-symbol
PnL, win/loss tracking, DailyStats snapshot lifecycle) lives in
``src.bot.components.risk.daily_stats.DailyStatsAggregator``. The
trade-limit gate (``can_trade`` branches, per-symbol halt logic,
global halt primitive, dynamic loss limits, remaining-trades/budget)
lives in ``src.bot.components.risk.trade_gate.TradeGate``. This module
stays the public façade — re-exports ``DailyStats`` for backward
compatibility and delegates aggregator + gate calls. Persistence + the
trade-logger side effects continue to live here until PR-7
(RiskStatePersistence) lands.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict, List

from src.utils.logger import get_logger, TradeLogger

# Lazy imports for async DB — only used when bot_config_id is set.
# ``get_session`` is re-exported here so the Phase 0 characterization tests
# can continue to patch ``src.risk.risk_manager.get_session`` (locked
# observable behaviour). The persistence component routes its session
# acquisition through this module-level name.
_db_available = True
try:
    from src.models.session import get_session
except ImportError:
    _db_available = False
    get_session = None  # type: ignore[assignment]

logger = get_logger(__name__)

# ``DailyStats`` + ``DailyStatsAggregator`` live in
# ``src.bot.components.risk.daily_stats`` (extracted in #326 Phase 1 PR-5).
# Importing that module at the top of this file triggers the parent
# ``src.bot`` package init which in turn imports ``BotWorker`` → back
# into ``src.risk.risk_manager`` for ``RiskManager`` — a circular import
# cycle when ``src.risk`` is the first package loaded (e.g. directly via
# ``from src.risk.risk_manager import …`` in a test module).
#
# We resolve the cycle by importing the aggregator module at the bottom
# of this file, after ``RiskManager`` is fully defined, and exposing
# ``DailyStats`` / ``DailyStatsAggregator`` at module scope for legacy
# ``from src.risk.risk_manager import DailyStats`` callers. ``TYPE_CHECKING``
# provides the type references for readers + static analysers.
if TYPE_CHECKING:  # pragma: no cover
    from src.bot.components.risk.daily_stats import (
        DailyStats,
        DailyStatsAggregator,
    )

# Re-export so ``from src.risk.risk_manager import DailyStats`` keeps
# working (existing tests + callers rely on the legacy path). The actual
# binding happens via the deferred import at the bottom of this file.
__all__ = ["DailyStats", "RiskManager"]


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
        data_dir: str = os.getenv("RISK_DATA_DIR", "data/risk"),
        enable_profit_lock: bool = True,
        profit_lock_percent: float = 75.0,
        min_profit_floor: float = 0.5,
        per_symbol_limits: Optional[Dict[str, Dict]] = None,
        bot_config_id: Optional[int] = None,
    ):
        """
        Initialize the risk manager.

        Args:
            max_trades_per_day: Global max trades (fallback if no per-symbol limit)
            daily_loss_limit_percent: Global loss limit (fallback if no per-symbol limit)
            position_size_percent: Default position size as percentage of balance
            data_dir: Deprecated, kept for backward compatibility (ignored)
            enable_profit_lock: Enable dynamic loss limits based on current PnL
            profit_lock_percent: Percentage of gains to lock in
            min_profit_floor: Minimum profit floor percentage
            per_symbol_limits: Per-symbol overrides, e.g.
                {"BTCUSDT": {"max_trades": 5, "loss_limit": 3.0}}
            bot_config_id: Bot config ID for DB-based persistence (required for stats)
        """
        # Use explicit bot config values only — NULL means no limit / no override
        self.max_trades = max_trades_per_day
        self.daily_loss_limit = daily_loss_limit_percent
        self.position_size_pct = position_size_percent
        self.per_symbol_limits = per_symbol_limits or {}

        # Profit Lock-In settings
        self.enable_profit_lock = enable_profit_lock
        self.profit_lock_percent = profit_lock_percent  # Lock 75% of gains
        self.min_profit_floor = min_profit_floor  # Minimum profit to keep (0.5%)

        self.bot_config_id = bot_config_id
        self._use_db = bot_config_id is not None and _db_available

        # Persistence component owns DB I/O (ARCH-H2 Phase 1 PR-7, #326).
        # The session-factory is a closure over ``get_session`` in THIS
        # module so characterization tests that patch
        # ``src.risk.risk_manager.get_session`` still win — the lookup
        # happens at call-time, not at RiskManager-construction time.
        # The ``_use_db`` gate is re-checked in each façade delegator so
        # tests that flip ``rm._use_db = True`` after construction still
        # reach the DB path.
        #
        # Lazy import: ``src.bot.components.risk.persistence`` transitively
        # pulls in ``src.bot`` which auto-imports ``BotWorker`` which
        # imports this module. Deferring the import to __init__ breaks
        # that cycle (src.bot is always fully loaded before any
        # RiskManager is constructed at runtime).
        from src.bot.components.risk.persistence import RiskStatePersistence
        self._persistence = RiskStatePersistence(
            bot_config_id=bot_config_id,
            session_factory=self._get_session_proxy,
            dailystats_cls=DailyStats,
        )

        self.trade_logger = TradeLogger()
        # DailyStats aggregation is owned by ``DailyStatsAggregator``
        # (PR-5). ``TradeGate`` owns the ``can_trade`` branches + halt
        # state (PR-6). This façade forwards both and keeps the
        # persistence + trade-logger side-effects co-located until PR-7.
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
        # Note: record_trade_entry/exit are synchronous with no await points,
        # so they are safe under asyncio's single-threaded model without a lock.
        # Per-symbol locks in BotWorker prevent concurrent calls for the same symbol.
        #
        # Stats are loaded from DB via load_stats_from_db() after async init,
        # not from __init__ (no blocking file I/O).

    # ------------------------------------------------------------------
    # DailyStats snapshot proxy — all legacy reads/writes of
    # ``self._daily_stats`` are forwarded to the aggregator. A setter is
    # kept for test harnesses that assign ``rm._daily_stats = None`` to
    # force an uninitialised state between assertions.
    # ------------------------------------------------------------------
    @property
    def _daily_stats(self) -> Optional[DailyStats]:
        return self._daily_stats_aggregator.get_daily_stats()

    @_daily_stats.setter
    def _daily_stats(self, value: Optional[DailyStats]) -> None:
        if value is None:
            # Rebuild the aggregator so ``get_daily_stats()`` returns None.
            self._daily_stats_aggregator = DailyStatsAggregator()
        else:
            self._daily_stats_aggregator.hydrate(value)

    def _save_daily_stats(self) -> None:
        """Schedule an async DB write for current daily stats.

        DB is the single source of truth — no JSON file fallback.
        """
        if not self._daily_stats:
            return

        if self._use_db:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._save_stats_to_db())
            except RuntimeError:
                # No running event loop (e.g. called from sync context).
                # Stats remain in memory and will be persisted on the next
                # call that happens inside an async context.
                logger.debug("No running event loop — DB stats write deferred to next async call")

    def _get_session_proxy(self):
        """Return the current module-level ``get_session`` context manager.

        Indirection lets characterization tests patch
        ``src.risk.risk_manager.get_session`` after ``RiskManager`` is
        already constructed — the persistence component calls back into
        this proxy on every DB op, so each call picks up the currently
        bound name.
        """
        return get_session()

    async def _save_stats_to_db(self) -> None:
        """Persist current daily stats to the risk_stats table.

        Thin delegator to :class:`RiskStatePersistence` (ARCH-H2 Phase 1
        PR-7). Kept as ``_save_stats_to_db`` for backward-compat with
        the characterization test suite and the sync wrapper below.
        """
        if not self._daily_stats or not self._use_db:
            return
        await self._persistence.save_stats(self._daily_stats)

    async def load_stats_from_db(self) -> None:
        """Load today's stats from DB (call after async init).

        Thin delegator to :class:`RiskStatePersistence` (ARCH-H2 Phase 1
        PR-7). Assigns the loaded snapshot to ``self._daily_stats`` on
        hit; leaves it untouched on miss / error (the persistence
        component returns ``None`` and logs).
        """
        if not self._use_db:
            return
        stats = await self._persistence.load_stats()
        if stats is not None:
            self._daily_stats_aggregator.hydrate(stats)

    async def get_historical_stats_from_db(self, days: int = 30) -> List[Dict]:
        """Get historical stats from the database.

        Thin delegator to :class:`RiskStatePersistence` (ARCH-H2 Phase 1
        PR-7).
        """
        if not self._use_db:
            return []
        return await self._persistence.get_historical_stats(days)

    def initialize_day(self, starting_balance: float) -> DailyStats:
        """
        Initialize a new trading day. Delegates to ``DailyStatsAggregator``.

        Args:
            starting_balance: Account balance at start of day

        Returns:
            DailyStats for the new day
        """
        existing = self._daily_stats_aggregator.get_daily_stats()
        today = datetime.now().strftime("%Y-%m-%d")
        is_new_day = existing is None or existing.date != today

        stats = self._daily_stats_aggregator.initialize_day(starting_balance)

        # Only persist on a genuinely new/replaced snapshot — same-day
        # idempotent returns skip the DB write (no state mutation).
        if is_new_day:
            self._save_daily_stats()

        return stats

    def get_dynamic_loss_limit(self, symbol: Optional[str] = None) -> Optional[float]:
        """Profit-lock-in adjusted loss limit — delegates to :class:`TradeGate`."""
        return self._trade_gate.get_dynamic_loss_limit(symbol)

    def can_trade(self, symbol: Optional[str] = None) -> tuple[bool, str]:
        """Trade-limit gate — delegates to :class:`TradeGate`.

        Preserves the ``tuple[bool, str]`` contract + byte-identical
        reason strings (locked by the Phase-0 characterization tests).
        """
        return self._trade_gate.can_trade(symbol)

    def _halt_trading(self, reason: str) -> None:
        """Global-halt primitive — delegates to :class:`TradeGate`.

        Kept as a pseudo-private method because the legacy characterization
        tests exercise it directly (``rm._halt_trading("Test reason")``).
        """
        self._trade_gate._halt_trading(reason)

    @property
    def halted_symbols(self) -> Dict[str, str]:
        """Per-symbol halt reasons — delegates to :class:`TradeGate`.

        Returns the underlying ``DailyStats.halted_symbols`` dict by
        reference so legacy ``rm.halted_symbols[sym] = reason`` mutations
        keep working (same strategy PR-4 used for ``_risk_alerts_sent``).
        Pre-init returns ``{}`` — matches legacy.
        """
        return self._trade_gate.halted_symbols

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
        # Base position size (None = use full per-asset budget)
        base_size_pct = self.position_size_pct

        if base_size_pct is None:
            position_usdt = balance
            position_pct = 100.0
        else:
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
        # Delegate counter mutation to the aggregator. Returns False
        # (and logs an error) if stats were not initialised — matches
        # the legacy safety path.
        if not self._daily_stats_aggregator.record_entry(symbol):
            return False

        # Log the trade (façade-side side effect — not aggregator's job).
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
        stats = self._daily_stats_aggregator.get_daily_stats()
        symbol_count = stats.symbol_trades[symbol]
        limit_str = str(self.max_trades) if self.max_trades is not None else "∞"
        logger.info(f"Trade entry recorded. {symbol}: {symbol_count}/{limit_str} trades today")

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
        # Delegate PnL + counter mutation to the aggregator. Returns
        # ``None`` (and logs an error) if stats were not initialised.
        exit_result = self._daily_stats_aggregator.record_exit(
            symbol=symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            exit_price=exit_price,
            fees=fees,
            funding_paid=funding_paid,
        )
        if exit_result is None:
            return False
        pnl, pnl_percent = exit_result

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
            f"Trade exit recorded: {symbol} PnL=${pnl:.2f} ({pnl_percent:+.2f}%) | "
            f"Day PnL: ${self._daily_stats.net_pnl:.2f} ({self._daily_stats.return_percent:+.2f}%)"
        )

        # Eager per-symbol halt check — the gate stamps halted_symbols
        # on cap-crossing (PR-6 consolidation: was inlined here pre-PR-6).
        self._trade_gate.check_and_halt(symbol)

        return True

    def get_daily_stats(self) -> Optional[DailyStats]:
        """Get current daily statistics."""
        return self._daily_stats

    def get_remaining_trades(self, symbol: Optional[str] = None) -> int:
        """Remaining trades for today — delegates to :class:`TradeGate`."""
        return self._trade_gate.get_remaining_trades(symbol)

    def get_remaining_risk_budget(self) -> Optional[float]:
        """Remaining loss-limit percent — delegates to :class:`TradeGate`."""
        return self._trade_gate.get_remaining_risk_budget()

    def get_historical_stats(self, days: int = 30) -> List[Dict]:
        """Get historical daily stats from DB (sync wrapper).

        Deprecated: Use get_historical_stats_from_db() in async code.
        Returns empty list since JSON file storage was removed.
        """
        return []

    def get_performance_summary(self, days: int = 30) -> Dict:
        """
        Calculate performance summary over a period.

        Note: In async code, use get_historical_stats_from_db() instead
        for actual historical data from the database.

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


# ---------------------------------------------------------------------------
# Deferred import of the DailyStats aggregator — see the import-cycle
# rationale at the top of the module. By now ``RiskManager`` is fully
# defined, so when this import triggers ``src.bot.__init__`` →
# ``BotWorker`` → ``from src.risk.risk_manager import RiskManager``, the
# symbol is already bound.
# ---------------------------------------------------------------------------
from src.bot.components.risk.daily_stats import (  # noqa: E402
    DailyStats,
    DailyStatsAggregator,
)
from src.bot.components.risk.trade_gate import TradeGate  # noqa: E402
