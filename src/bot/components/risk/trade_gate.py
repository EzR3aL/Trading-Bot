"""TradeGate — ``can_trade`` gating layer for one bot (#326 Phase 1 PR-6).

Owns the trade-limit gate the bot worker calls on every tick: global
trade-count cap, global daily-loss cap, per-symbol trade-count cap, and
per-symbol loss cap. Reads :class:`DailyStats` from
:class:`DailyStatsAggregator` (composition — TradeGate does not own the
snapshot, only the gating logic). Mutates the snapshot's
``is_trading_halted`` / ``halt_reason`` / ``halted_symbols`` fields when
a cap trips — the same side effects the legacy :class:`RiskManager` had.

Split rationale
---------------
Before PR-6 the logic lived in :class:`RiskManager` across two code
paths (documented as the Phase-0 eager/lazy split):

* **Eager path** — :meth:`RiskManager.record_trade_exit` post-PnL block
  checks per-symbol loss against the configured cap and stamps
  ``halted_symbols[symbol]`` immediately after the losing trade.
* **Lazy path** — :meth:`RiskManager.can_trade` re-evaluates per-symbol
  loss on every call and stamps ``halted_symbols[symbol]`` if the cap
  has been crossed (e.g. the PnL moved via a direct ``symbol_pnl``
  mutation that did not go through ``record_trade_exit``).

PR-6 consolidates both paths into :meth:`TradeGate.check_and_halt` —
:meth:`can_trade` calls it for the lazy path, and the façade's
``record_trade_exit`` calls it for the eager path. The exact observable
reason strings are preserved (the two paths historically used slightly
different phrasings — both are kept byte-identical so the Phase-0
characterization tests don't churn).

Side-effect contract (Phase 0 lock)
-----------------------------------
* ``can_trade`` may call :meth:`_halt_trading` which sets
  ``is_trading_halted=True`` + ``halt_reason`` — locked by
  ``test_blocks_global_daily_loss_limit_and_halts``.
* ``can_trade`` may stamp ``halted_symbols[symbol]`` on the lazy branch
  — locked by ``test_can_trade_halts_on_pending_symbol_loss``.
* :meth:`check_and_halt` stamps ``halted_symbols[symbol]`` on the eager
  branch (called from ``record_trade_exit``) — locked by
  ``test_record_trade_exit_halts_symbol_on_loss_limit``.
* Persistence write-through: each side effect calls the ``save_stats``
  callback supplied at construction time so the DB row reflects the
  new halt state (legacy: ``RiskManager._save_daily_stats``).

Return contract (Phase 0 lock)
------------------------------
``can_trade`` returns ``tuple[bool, str]`` with free-form reason
strings. Hoisting to an Enum is a follow-up concern — Phase 1 preserves
the strings byte-identical.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from src.bot.components.risk.daily_stats import DailyStatsAggregator
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Default no-op persistence hook — lets the aggregator be used standalone
# in tests (no DB wiring needed). The façade supplies a real callback.
def _noop_save() -> None:  # pragma: no cover - trivial
    return None


class TradeGate:
    """Gate for ``can_trade`` decisions + per-symbol halt bookkeeping.

    Implements :class:`src.bot.components.risk.protocols.TradeGateProtocol`.
    Composition: holds a reference to the :class:`DailyStatsAggregator`
    that owns the mutable snapshot. Reads stats via
    :meth:`DailyStatsAggregator.get_daily_stats`; mutations to halt state
    happen on that same snapshot object so all readers (façade,
    persistence layer, orchestrator) see the update without a sync step.
    """

    def __init__(
        self,
        aggregator: DailyStatsAggregator,
        max_trades_per_day: Optional[int] = None,
        daily_loss_limit_percent: Optional[float] = None,
        per_symbol_limits: Optional[Dict[str, Dict]] = None,
        enable_profit_lock: bool = True,
        profit_lock_percent: float = 75.0,
        min_profit_floor: float = 0.5,
        save_stats: Callable[[], None] = _noop_save,
    ) -> None:
        """Wire the gate.

        Args:
            aggregator: DailyStats owner. TradeGate does not own the
                snapshot — it only reads + mutates halt state on it.
            max_trades_per_day: Global max trades per day. ``None`` means
                no cap.
            daily_loss_limit_percent: Global daily loss cap (percent of
                starting balance). ``None`` means no cap.
            per_symbol_limits: Per-symbol overrides, e.g.
                ``{"BTCUSDT": {"max_trades": 5, "loss_limit": 3.0}}``.
            enable_profit_lock: Toggle Profit Lock-In (dynamic loss cap
                that tightens as the day's return climbs).
            profit_lock_percent: Percentage of gains to lock in.
            min_profit_floor: Minimum profit floor (percent).
            save_stats: Persistence hook called after every halt-state
                mutation. Legacy: ``RiskManager._save_daily_stats``.
        """
        self._aggregator = aggregator
        self.max_trades = max_trades_per_day
        self.daily_loss_limit = daily_loss_limit_percent
        self.per_symbol_limits = per_symbol_limits or {}
        self.enable_profit_lock = enable_profit_lock
        self.profit_lock_percent = profit_lock_percent
        self.min_profit_floor = min_profit_floor
        self._save_stats = save_stats

    # ─── Halt-state access (proxies to the DailyStats snapshot) ────────

    @property
    def halted_symbols(self) -> Dict[str, str]:
        """Read-through view of ``DailyStats.halted_symbols``.

        Pre-init the dict is empty — matches the legacy behaviour where
        ``RiskManager.halted_symbols`` was ``{}`` before ``initialize_day``.
        Mutations on the returned dict persist because it IS the snapshot's
        dict (same reference semantics as the legacy code that did
        ``rm._daily_stats.halted_symbols[symbol] = reason``).
        """
        stats = self._aggregator.get_daily_stats()
        if stats is None:
            return {}
        return stats.halted_symbols

    # ─── Gate ─────────────────────────────────────────────────────────

    def can_trade(self, symbol: Optional[str] = None) -> tuple[bool, str]:
        """Check if trading is allowed for the requested scope.

        Returns ``(allowed, reason)``. Free-form reason strings preserved
        byte-identical from the legacy implementation — the Phase-0
        characterization tests pin the exact wording.
        """
        stats = self._aggregator.get_daily_stats()
        if stats is None:
            return False, "Daily stats not initialized. Call initialize_day() first."

        # Global halt short-circuits everything (including per-symbol).
        if stats.is_trading_halted:
            return False, f"Trading halted: {stats.halt_reason}"

        # Per-symbol halt — set by either the eager (record_trade_exit)
        # or lazy (this same method on a previous call) path.
        if symbol and symbol in stats.halted_symbols:
            return False, f"{symbol} halted: {stats.halted_symbols[symbol]}"

        # Per-symbol gating — evaluated when the caller passes a symbol.
        if symbol:
            sym_limits = self.per_symbol_limits.get(symbol, {})
            effective_max_trades = sym_limits.get("max_trades", self.max_trades)
            effective_loss_limit = sym_limits.get("loss_limit", self.daily_loss_limit)

            if effective_max_trades is not None:
                symbol_count = stats.symbol_trades.get(symbol, 0)
                if symbol_count >= effective_max_trades:
                    return (
                        False,
                        f"{symbol}: trade limit reached "
                        f"({symbol_count}/{effective_max_trades})",
                    )

            # Lazy per-symbol-loss path — re-evaluate current PnL against
            # cap. If crossed, stamp ``halted_symbols`` and return blocked.
            if effective_loss_limit is not None and stats.starting_balance > 0:
                symbol_pnl = stats.symbol_pnl.get(symbol, 0.0)
                symbol_loss_pct = abs(
                    min(0, (symbol_pnl / stats.starting_balance) * 100)
                )
                if symbol_loss_pct >= effective_loss_limit:
                    halt_reason = (
                        f"Loss limit exceeded "
                        f"({symbol_loss_pct:.2f}% >= {effective_loss_limit:.2f}%)"
                    )
                    stats.halted_symbols[symbol] = halt_reason
                    self._save_stats()
                    logger.warning(f"{symbol} HALTED: {halt_reason}")
                    return False, f"{symbol}: {halt_reason}"

        # Global (no symbol) gating — trade-count + loss-limit.
        if symbol is None:
            if self.max_trades is not None:
                if stats.trades_executed >= self.max_trades:
                    return (
                        False,
                        f"Global trade limit reached "
                        f"({stats.trades_executed}/{self.max_trades})",
                    )

            if self.daily_loss_limit is not None and stats.starting_balance > 0:
                current_loss_pct = abs(min(0, stats.return_percent))
                if current_loss_pct >= self.daily_loss_limit:
                    self._halt_trading(
                        f"Daily loss limit exceeded "
                        f"({current_loss_pct:.2f}% >= {self.daily_loss_limit:.2f}%)"
                    )
                    return (
                        False,
                        f"Daily loss limit exceeded "
                        f"({current_loss_pct:.2f}% >= {self.daily_loss_limit}%)",
                    )

        return True, "Trading allowed"

    # ─── Eager halt path — called from RiskManager.record_trade_exit ──

    def check_and_halt(self, symbol: str) -> None:
        """Eager per-symbol loss check — invoked post-PnL update.

        Mirrors the lazy branch inside :meth:`can_trade` but uses the
        legacy eager-path wording (``Loss limit reached: X%``) for
        byte-identical observable behaviour. The façade calls this once
        per ``record_trade_exit``; it stamps ``halted_symbols[symbol]``
        iff the cap is crossed.

        No-op if stats are not initialised, the symbol has no configured
        loss cap, or the starting balance is zero (defensive — legacy
        behaviour).
        """
        stats = self._aggregator.get_daily_stats()
        if stats is None:
            return

        sym_limits = self.per_symbol_limits.get(symbol, {})
        effective_loss_limit = sym_limits.get("loss_limit", self.daily_loss_limit)
        if effective_loss_limit is None or stats.starting_balance <= 0:
            return

        symbol_pnl_total = stats.symbol_pnl.get(symbol, 0.0)
        symbol_loss_pct = abs(
            min(0, (symbol_pnl_total / stats.starting_balance) * 100)
        )
        if symbol_loss_pct >= effective_loss_limit:
            stats.halted_symbols[symbol] = f"Loss limit reached: {symbol_loss_pct:.2f}%"
            self._save_stats()
            logger.warning(
                f"{symbol} HALTED: Loss limit {symbol_loss_pct:.2f}% "
                f">= {effective_loss_limit}%"
            )

    # ─── Global halt primitive ────────────────────────────────────────

    def _halt_trading(self, reason: str) -> None:
        """Mark the day globally halted. Mirrors legacy ``RiskManager._halt_trading``."""
        stats = self._aggregator.get_daily_stats()
        if stats is None:
            return
        stats.is_trading_halted = True
        stats.halt_reason = reason
        self._save_stats()
        logger.warning(f"TRADING HALTED: {reason}")

    # ─── Informational accessors ─────────────────────────────────────

    def get_remaining_trades(self, symbol: Optional[str] = None) -> int:
        """Trades remaining for today (per-symbol if ``symbol`` given).

        ``999`` when no cap is configured (legacy sentinel — preserves
        downstream ``min(remaining, x)`` callers).
        """
        stats = self._aggregator.get_daily_stats()
        if symbol:
            sym_limits = self.per_symbol_limits.get(symbol, {})
            effective_max = sym_limits.get("max_trades", self.max_trades)
            if effective_max is None:
                return 999
            if stats is None:
                return effective_max
            symbol_count = stats.symbol_trades.get(symbol, 0)
            return max(0, effective_max - symbol_count)

        if self.max_trades is None:
            return 999
        if stats is None:
            return self.max_trades
        return max(0, self.max_trades - stats.trades_executed)

    def get_remaining_risk_budget(self) -> Optional[float]:
        """Remaining loss-limit percentage budget. ``None`` if no cap."""
        if self.daily_loss_limit is None:
            return None
        stats = self._aggregator.get_daily_stats()
        if stats is None:
            return self.daily_loss_limit

        current_loss = abs(min(0, stats.return_percent))
        return max(0, self.daily_loss_limit - current_loss)

    def get_dynamic_loss_limit(self, symbol: Optional[str] = None) -> Optional[float]:
        """Profit-lock-in adjusted loss cap for the current stats.

        Returns ``None`` when no base cap is set. When profit-lock is
        disabled or the day is not yet profitable, returns the base cap
        unchanged. When the day IS profitable, tightens the cap so the
        worst possible loss leaves at least :attr:`min_profit_floor` of
        gains intact — floored at 0.5% to avoid a zero / negative cap.
        """
        if self.daily_loss_limit is None:
            return None

        stats = self._aggregator.get_daily_stats()
        if not self.enable_profit_lock or stats is None:
            return self.daily_loss_limit

        current_return = stats.return_percent
        if current_return <= 0:
            return self.daily_loss_limit

        max_allowed_loss = current_return - self.min_profit_floor
        new_limit = min(self.daily_loss_limit, max_allowed_loss)
        new_limit = max(new_limit, 0.5)

        logger.debug(
            f"Profit Lock-In: Return={current_return:.2f}%, "
            f"Dynamic Limit={new_limit:.2f}% (Standard: {self.daily_loss_limit}%)"
        )
        return new_limit
