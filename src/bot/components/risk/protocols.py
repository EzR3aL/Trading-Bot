"""Structural Protocols for future risk-state components (ARCH-H2, #326).

The current ``src/risk/risk_manager.RiskManager`` bundles four distinct
responsibilities that Phase 1 of issue #326 will split into separate
composition-owned components:

1. **DailyStatsAggregator** — PnL aggregation, trade count tracking,
   per-symbol PnL, net PnL / win rate / return-percent calculations.
   Owns the mutable ``DailyStats`` snapshot.
2. **TradeGate** — ``can_trade(symbol=None)`` branch evaluation:
   global/per-symbol trade-count limits, daily loss limits, profit
   lock-in, halted-symbol tracking. Reads DailyStats, mutates
   ``halted_symbols`` + ``is_trading_halted``.
3. **AlertThrottler** — dedupe + midnight-reset of risk alerts. Today
   lives inlined in ``BotWorker._risk_alerts_sent`` / ``_risk_alerts_last_reset``
   (see ``src/bot/bot_worker.py:142``). Phase 1 lifts it out so the
   dedupe key + reset cadence is testable in isolation.
4. **RiskStatePersistence** — DB truth-source for DailyStats (#188):
   ``load_stats_from_db`` + ``_save_stats_to_db`` in the current
   manager. Swallows exceptions today; Phase 1 freezes that contract.

Until Phase 1 lands, these Protocols have no runtime callers. They
exist so the extraction PRs (#326 PR-4..PR-7) don't invent a new shape
per extraction, and so Phase 2 can type-check the façade wiring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, Tuple, runtime_checkable

if TYPE_CHECKING:
    from src.risk.risk_manager import DailyStats


# ── Protocols ────────────────────────────────────────────────────────


@runtime_checkable
class DailyStatsAggregatorProtocol(Protocol):
    """Owns the mutable ``DailyStats`` snapshot for one bot.

    Phase 1 will lift this out of ``RiskManager``. The component must
    stay source-of-truth for the in-memory snapshot; ``RiskStatePersistence``
    writes / reads on its behalf.
    """

    def initialize_day(self, starting_balance: float) -> "DailyStats":
        """Start or resume today's DailyStats. Idempotent same-day."""
        ...

    def get_daily_stats(self) -> "Optional[DailyStats]":
        """Return the current DailyStats snapshot, or ``None`` if not initialized."""
        ...

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
        """Increment trade counts + per-symbol counts; emit trade log."""
        ...

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
        """Update PnL, fees, funding, drawdown; emit trade log."""
        ...


@runtime_checkable
class TradeGateProtocol(Protocol):
    """``can_trade`` branch evaluator — global + per-symbol gating."""

    def can_trade(self, symbol: Optional[str] = None) -> Tuple[bool, str]:
        """Return ``(allowed, reason)`` for the requested scope.

        Reasons are free-form strings today (Phase 1 may freeze them
        into an Enum once the characterization tests lock the set).
        """
        ...

    def get_remaining_trades(self, symbol: Optional[str] = None) -> int:
        """Trades remaining for today; ``999`` when no cap is set."""
        ...

    def get_remaining_risk_budget(self) -> Optional[float]:
        """Loss-limit percent still available, or ``None`` if no limit."""
        ...

    def get_dynamic_loss_limit(self, symbol: Optional[str] = None) -> Optional[float]:
        """Profit-lock-in adjusted loss limit for the current stats."""
        ...


@runtime_checkable
class AlertThrottlerProtocol(Protocol):
    """Dedupe + midnight-reset for risk alerts.

    Today this is a set + a last-reset timestamp owned by ``BotWorker``.
    Phase 1 lifts it here; the Protocol freezes the invariants the
    characterization tests pin down (first-hit-sends, same-key-dedupes,
    reset-after-24h, new-key-sends).
    """

    def should_emit(self, alert_key: str) -> bool:
        """Return ``True`` iff this key has not been emitted since the
        last reset. Must atomically record the emission so a second call
        with the same key returns ``False``."""
        ...

    def maybe_reset(self) -> None:
        """Clear the dedupe set when the reset window (≥24h) has elapsed
        since the last reset."""
        ...

    def reset(self) -> None:
        """Unconditional clear — called from daily-summary + bot stop."""
        ...


@runtime_checkable
class RiskStatePersistenceProtocol(Protocol):
    """DB truth-source for DailyStats (Epic #188).

    Write path is fire-and-forget (schedules an asyncio task from a
    sync caller); read path is awaited from the bot's async init. Both
    currently swallow exceptions and log a warning — Phase 0's
    characterization tests lock that contract.
    """

    async def load_stats(self) -> "Optional[DailyStats]":
        """Load today's snapshot from DB. Returns ``None`` on miss or
        any read error (exceptions are swallowed + logged)."""
        ...

    async def save_stats(self, stats: "DailyStats") -> None:
        """Upsert today's snapshot. Swallows write errors + logs."""
        ...


# ── Dependencies ────────────────────────────────────────────────────


@dataclass
class RiskComponentDeps:
    """Shared dependency bundle for risk components (ARCH-H2, #326).

    Mirrors the ``BotWorkerDeps`` pattern from ARCH-H1 (see
    ``src/bot/components/deps.py``): each component receives one of
    these rather than 6–10 individual arguments, so Phase 1's four
    extraction PRs can keep stable constructor signatures.

    Field semantics
    ---------------
    * ``bot_config_id`` — required for persistence. ``None`` means the
      aggregator runs in memory-only mode (tests + orchestrator pre-wire).
    * ``max_trades_per_day`` / ``daily_loss_limit_percent`` /
      ``position_size_percent`` — mirror ``RiskManager.__init__`` so the
      Phase 2 façade can forward them unchanged.
    * ``per_symbol_limits`` — per-symbol overrides; empty dict when
      unset so components don't have to None-check.
    * ``enable_profit_lock`` / ``profit_lock_percent`` / ``min_profit_floor``
      — Profit Lock-In dials; default matches the current
      ``RiskManager`` defaults (enabled, 75%, 0.5%).
    * ``notifier`` — callable for AlertThrottler to dispatch alerts.
      Phase 1 will wire this to ``BotWorker._send_notification``. Held
      as ``Any`` callable here so the scaffold doesn't depend on the
      concrete ``Notifier`` component import cycle.
    * ``session_factory`` — optional async session factory for the
      persistence component. ``None`` disables DB I/O (memory-only).

    Instances are immutable from a component's POV. Field mutation is
    the sole responsibility of the façade that constructs them.
    """

    # Identity
    bot_config_id: Optional[int] = None

    # Risk limits — forwarded from BotConfig
    max_trades_per_day: Optional[int] = None
    daily_loss_limit_percent: Optional[float] = None
    position_size_percent: Optional[float] = None
    per_symbol_limits: dict = field(default_factory=dict)

    # Profit Lock-In dials (match current RiskManager defaults)
    enable_profit_lock: bool = True
    profit_lock_percent: float = 75.0
    min_profit_floor: float = 0.5

    # Wiring for alert dispatch + DB persistence
    notifier: Optional[Callable[..., Any]] = None
    session_factory: Optional[Callable[..., Any]] = None
