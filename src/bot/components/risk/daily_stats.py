"""DailyStatsAggregator — PnL/trade-count aggregation for one bot (#326 Phase 1 PR-5).

Owns the mutable :class:`DailyStats` snapshot that used to live directly
on ``RiskManager._daily_stats``. The aggregator is a *pure* state
component: it knows nothing about persistence, the trade logger, or the
risk-limit gates. The façade (``RiskManager``) wires:

* the persistence layer (DB save / load),
* the :class:`TradeLogger` side-effect,
* the ``can_trade`` / loss-limit gating around record_trade_exit.

Split rationale
---------------
The current ``RiskManager.record_trade_entry`` / ``record_trade_exit``
mix three concerns: (a) counter/PnL mutation, (b) trade-logger side
effect, (c) DB persistence. Phase 1 PR-5 extracts only (a) — the thin
delegator on the façade keeps (b) + (c) orchestration untouched so the
per-symbol loss-limit halting in ``record_trade_exit`` (which belongs to
the TradeGate component, PR-6) stays co-located until PR-6 lands.

Midnight-reset trigger
----------------------
The aggregator does not schedule its own reset — ``initialize_day`` is
idempotent for the same UTC date and *replaces* the snapshot when the
date changes. The bot worker calls ``initialize_day`` once per tick via
the façade; that's where the midnight rollover happens.

DB-load strip-computed-fields helper
------------------------------------
``DailyStats`` exposes ``net_pnl`` / ``return_percent`` / ``win_rate``
as ``@property`` computed fields. The persistence layer serialises the
dataclass via ``DailyStats.to_dict()`` which includes those computed
values; on load we must strip them before ``DailyStats(**data)`` or the
dataclass constructor raises ``TypeError: unexpected keyword argument``.
:func:`DailyStatsAggregator.hydrate_from_dict` encapsulates that strip
so every consumer goes through the same path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# DailyStats dataclass — unchanged from the legacy location, re-homed here.
# ---------------------------------------------------------------------------


@dataclass
class DailyStats:
    """Daily trading statistics snapshot (one per UTC date per bot)."""

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
    # Per-symbol tracking for per-asset risk limits
    symbol_trades: Dict[str, int] = field(default_factory=dict)
    symbol_pnl: Dict[str, float] = field(default_factory=dict)
    halted_symbols: Dict[str, str] = field(default_factory=dict)

    @property
    def net_pnl(self) -> float:
        """Net PnL after fees and funding."""
        return self.total_pnl - self.total_fees - self.total_funding

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
        """Convert to dictionary (computed fields included for DB serialisation)."""
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
            "symbol_trades": self.symbol_trades,
            "symbol_pnl": self.symbol_pnl,
            "halted_symbols": self.halted_symbols,
        }


# Computed @property field names — stripped on DB-load so the dataclass
# constructor does not receive unexpected keyword arguments.
_COMPUTED_FIELDS = ("net_pnl", "return_percent", "win_rate")


# ---------------------------------------------------------------------------
# DailyStatsAggregator — owns the mutable DailyStats snapshot.
# ---------------------------------------------------------------------------


class DailyStatsAggregator:
    """Aggregates PnL + trade counts for the current UTC day.

    Implements :class:`src.bot.components.risk.protocols.DailyStatsAggregatorProtocol`
    partially — the Protocol's ``record_trade_entry`` / ``record_trade_exit``
    signatures are kept on the :class:`RiskManager` façade because they
    include trade-logger and persistence orchestration. The aggregator
    exposes the *pure* mutation primitives that those façade methods
    call: :meth:`record_entry` and :meth:`record_exit`.
    """

    def __init__(self) -> None:
        self._daily_stats: Optional[DailyStats] = None

    # ─── Snapshot access ──────────────────────────────────────────────

    def get_daily_stats(self) -> Optional[DailyStats]:
        """Return the current snapshot, or ``None`` if not initialised."""
        return self._daily_stats

    # ─── Lifecycle ────────────────────────────────────────────────────

    def initialize_day(self, starting_balance: float) -> DailyStats:
        """Start or resume today's :class:`DailyStats`.

        Idempotent for the same UTC date — same-day re-invocations return
        the existing snapshot without zeroing counters (safe for bot
        restarts within a day). A new UTC date replaces the snapshot, which
        is the implicit midnight-reset path the bot worker relies on.
        """
        today = datetime.now().strftime("%Y-%m-%d")

        if self._daily_stats and self._daily_stats.date == today:
            logger.info(
                f"Day already initialized. Trades: {self._daily_stats.trades_executed}"
            )
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
        logger.info(f"Initialized new trading day with balance: ${starting_balance:,.2f}")
        return self._daily_stats

    def hydrate(self, stats: DailyStats) -> None:
        """Replace the snapshot with a pre-built :class:`DailyStats`.

        Used by the persistence layer after ``load_stats_from_db``.
        """
        self._daily_stats = stats

    # ─── DB-load strip helper ─────────────────────────────────────────

    @staticmethod
    def hydrate_from_dict(data: dict) -> DailyStats:
        """Build a :class:`DailyStats` from a persisted dict payload.

        Strips the ``@property`` computed fields (``net_pnl`` /
        ``return_percent`` / ``win_rate``) before passing to the dataclass
        constructor — ``DailyStats(**data)`` would otherwise raise
        ``TypeError: __init__() got an unexpected keyword argument``.

        The input dict is mutated in place (the persistence layer treats
        it as ephemeral scratch space — see
        ``test_loads_daily_stats_from_db_row`` for the contract lock).
        """
        for key in _COMPUTED_FIELDS:
            data.pop(key, None)
        return DailyStats(**data)

    # ─── Pure aggregation primitives ─────────────────────────────────

    def record_entry(self, symbol: str) -> bool:
        """Increment the global trade counter + per-symbol count.

        Returns ``False`` (with an error log) if stats were not
        initialised — matches the legacy ``RiskManager.record_trade_entry``
        safety path so the observable behaviour is identical.
        """
        if not self._daily_stats:
            logger.error("Daily stats not initialized!")
            return False

        self._daily_stats.trades_executed += 1
        self._daily_stats.symbol_trades[symbol] = (
            self._daily_stats.symbol_trades.get(symbol, 0) + 1
        )
        return True

    def record_exit(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        exit_price: float,
        fees: float,
        funding_paid: float,
    ) -> Optional[Tuple[float, float]]:
        """Update PnL, fees, funding, drawdown + win/loss counters.

        Returns ``(pnl, pnl_percent)`` from :func:`src.bot.pnl.calculate_pnl`
        on success, or ``None`` if stats were not initialised (matches
        the legacy safety path).
        """
        if not self._daily_stats:
            logger.error("Daily stats not initialized!")
            return None

        # Localised import — matches the legacy lazy import so a broken
        # ``src.bot.pnl`` does not block aggregator construction.
        from src.bot.pnl import calculate_pnl

        pnl, pnl_percent = calculate_pnl(side, entry_price, exit_price, size)

        self._daily_stats.total_pnl += pnl
        self._daily_stats.total_fees += fees
        self._daily_stats.total_funding += funding_paid
        self._daily_stats.current_balance += pnl - fees - funding_paid
        self._daily_stats.symbol_pnl[symbol] = (
            self._daily_stats.symbol_pnl.get(symbol, 0.0) + pnl
        )

        if pnl > 0:
            self._daily_stats.winning_trades += 1
        else:
            self._daily_stats.losing_trades += 1

        # Update max drawdown against the current return_percent.
        current_drawdown = abs(min(0, self._daily_stats.return_percent))
        self._daily_stats.max_drawdown = max(
            self._daily_stats.max_drawdown, current_drawdown
        )

        return pnl, pnl_percent
