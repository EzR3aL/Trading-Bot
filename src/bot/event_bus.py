"""Process-local pub/sub bus for trade lifecycle events (Issue #216, Section 2.2).

Backs the Server-Sent Events (SSE) trades stream. Each HTTP connection calls
:meth:`EventBus.subscribe` with the authenticated ``user_id`` and consumes an
``AsyncIterator`` of events that were published for that user. Other users'
events are never delivered — scoping happens at subscription time.

Design
------
* Single process, single event loop — an :class:`asyncio.Queue` per subscriber.
* ``publish(event_type, user_id, payload)`` never awaits a slow subscriber:
  if a queue is full the event is dropped for *that* subscriber only, with a
  warning. The other subscribers are unaffected.
* No external broker. This is explicitly sized for the current single-worker
  deployment; swapping in Redis later only touches this module.

The bus is process-global (singleton via :func:`get_event_bus`) so bot mixins
and the API router share one instance without threading it through DI.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional, Set

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Per-subscriber queue size. Large enough for a burst of trade events during
# normal trading; small enough that a dead consumer is noticed quickly.
_QUEUE_MAXSIZE = 64

# Event types emitted on this bus. Keep the list short and stable — the
# frontend uses the string values directly to decide what to invalidate.
EVENT_TRADE_OPENED = "trade_opened"
EVENT_TRADE_UPDATED = "trade_updated"
EVENT_TRADE_CLOSED = "trade_closed"


class EventBus:
    """Per-user async pub/sub bus. Process-local, no persistence."""

    def __init__(self) -> None:
        self._subscribers: Dict[int, Set[asyncio.Queue[str]]] = defaultdict(set)

    async def publish(
        self,
        event_type: str,
        user_id: int,
        trade_id: Optional[int] = None,
        data: Optional[dict] = None,
    ) -> None:
        """Publish an event to every subscriber bound to ``user_id``.

        The event is serialized once and enqueued per subscriber. Slow or
        dead subscribers drop the event (we never block the publisher).
        """
        payload = {
            "event": event_type,
            "trade_id": trade_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data or {},
        }
        serialized = json.dumps(payload, default=str)

        # Snapshot the queue list so a subscriber finishing mid-broadcast
        # doesn't mutate the set we're walking. Single-loop deployment — no
        # lock needed; register/unregister run synchronously.
        queues = list(self._subscribers.get(user_id, ()))

        for queue in queues:
            try:
                queue.put_nowait(serialized)
            except asyncio.QueueFull:
                # Dropping is preferred over blocking the bot loop on one
                # stuck subscriber. The SSE endpoint reconnects on close so
                # the user recovers on the next tick.
                logger.warning(
                    "event_bus.queue_full dropping event=%s user_id=%s",
                    event_type, user_id,
                )

    def register(self, user_id: int) -> "asyncio.Queue[str]":
        """Register a new subscriber synchronously and return its queue.

        Exposed so the SSE endpoint can register the subscriber BEFORE the
        first ``await`` — otherwise a publish that races the first
        ``__anext__`` is dropped because the bucket is empty.
        """
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers[user_id].add(queue)
        return queue

    def unregister(self, user_id: int, queue: "asyncio.Queue[str]") -> None:
        """Remove a previously-registered subscriber queue."""
        bucket = self._subscribers.get(user_id)
        if bucket is None:
            return
        bucket.discard(queue)
        if not bucket:
            self._subscribers.pop(user_id, None)

    async def subscribe(self, user_id: int) -> AsyncIterator[str]:
        """Yield JSON-encoded events scoped to ``user_id``.

        The iterator runs forever; the caller must cancel the task to stop.
        Each caller gets its own queue — duplicate subscriptions from the
        same user each receive every event.
        """
        queue = self.register(user_id)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self.unregister(user_id, queue)

    def subscriber_count(self, user_id: Optional[int] = None) -> int:
        """Return the number of live subscribers (for tests / metrics)."""
        if user_id is None:
            return sum(len(q) for q in self._subscribers.values())
        return len(self._subscribers.get(user_id, ()))


# ── Global singleton ────────────────────────────────────────────────

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Return the process-global :class:`EventBus` instance."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_event_bus() -> None:
    """Reset the global bus — test-only helper, not for production use."""
    global _bus
    _bus = None


# ── Fire-and-forget publish helpers ─────────────────────────────────
# Used from synchronous contexts (mixins without an explicit await) where we
# want to emit an event without holding up the caller. Failure is logged but
# never propagates.


def publish_trade_event(
    event_type: str,
    user_id: int,
    trade_id: Optional[int],
    data: Optional[dict] = None,
) -> None:
    """Fire-and-forget wrapper that schedules :meth:`EventBus.publish`.

    Safe to call from any async context (creates a background task). Swallows
    exceptions — event delivery is never a critical path.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — nothing to deliver to. Tests may hit this path
        # when a mixin method runs outside an event loop.
        return

    bus = get_event_bus()
    task = loop.create_task(bus.publish(event_type, user_id, trade_id, data))
    # Drop exceptions silently — the publisher's main flow must not break
    # because the bus failed.
    task.add_done_callback(
        lambda t: t.exception() if not t.cancelled() and t.exception() else None
    )


def build_trade_snapshot(trade: Any) -> dict:
    """Minimal, JSON-serializable snapshot for an event payload.

    Only pulls primitive fields so the bus never ships ORM objects or
    detached SQLAlchemy state across task boundaries.
    """
    def _iso(value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    return {
        "id": getattr(trade, "id", None),
        "symbol": getattr(trade, "symbol", None),
        "side": getattr(trade, "side", None),
        "status": getattr(trade, "status", None),
        "entry_price": getattr(trade, "entry_price", None),
        "exit_price": getattr(trade, "exit_price", None),
        "take_profit": getattr(trade, "take_profit", None),
        "stop_loss": getattr(trade, "stop_loss", None),
        "pnl": getattr(trade, "pnl", None),
        "pnl_percent": getattr(trade, "pnl_percent", None),
        "exchange": getattr(trade, "exchange", None),
        "demo_mode": getattr(trade, "demo_mode", None),
        "entry_time": _iso(getattr(trade, "entry_time", None)),
        "exit_time": _iso(getattr(trade, "exit_time", None)),
        "exit_reason": getattr(trade, "exit_reason", None),
    }
