"""Structural Protocols for future BotWorker components (ARCH-H1).

Each mixin currently bundled into ``BotWorker`` is scheduled to become a
composition-owned component. These Protocols pre-declare the public
surface each component MUST expose once extracted, so:

* Callers (``BotWorker`` and, eventually, tests) can type-check against
  the intended shape *before* the mixin is removed.
* Future FakeExecutor / FakePositionMonitor test doubles can satisfy the
  Protocol without inheriting the production classes.
* Reviewers can reject a component PR that silently drifts from the
  declared surface — a ``isinstance(comp, XProtocol)`` contract test
  guards that.

Until Phase 1 (notifier extract, PR-3) lands, these Protocols have no
runtime callers. They exist purely so later phases don't invent a new
shape per extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.models.database import TradeRecord
    from src.models.enums import ExitReason


@runtime_checkable
class TradeExecutorProtocol(Protocol):
    """Signal → exchange order placement."""

    async def open(self, signal: object) -> "TradeRecord | None":
        """Place an entry based on the incoming strategy signal.

        Returns the persisted ``TradeRecord`` on success, ``None`` if the
        signal was skipped (dedup, risk-reject, venue closed).
        """
        ...

    async def cancel_pending(self, trade_id: int) -> None:
        """Cancel any still-pending orders attached to this trade."""
        ...


@runtime_checkable
class PositionMonitorProtocol(Protocol):
    """Poll exchange for open-position state and emit close events."""

    async def poll_positions(self) -> None:
        """One polling tick over every open trade owned by this worker."""
        ...

    async def on_closed(self, trade: "TradeRecord") -> None:
        """Called by the monitor when a poll detects an exchange-side close."""
        ...


@runtime_checkable
class TradeCloserProtocol(Protocol):
    """Manual and strategy-driven closes."""

    async def close_manual(
        self, trade_id: int, reason: "ExitReason"
    ) -> "TradeRecord":
        """User-initiated close via dashboard or API."""
        ...

    async def run_due_exits(self) -> None:
        """Evaluate strategy-exit rules for open trades; close any due."""
        ...


@runtime_checkable
class NotifierProtocol(Protocol):
    """Discord / Telegram emission."""

    async def on_trade_opened(self, trade: "TradeRecord") -> None: ...

    async def on_trade_closed(self, trade: "TradeRecord") -> None: ...

    async def on_error(self, exc: Exception) -> None: ...
