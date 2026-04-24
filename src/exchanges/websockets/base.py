"""Abstract base class for exchange WebSocket clients (#216).

Subclasses implement ``_connect_transport``, ``_subscribe`` and
``_parse_message`` — this base class handles the reconnect-with-
exponential-backoff loop, the event dispatch into the
:class:`RiskStateManager`, and the ``is_connected`` health bit that the
``/api/health`` endpoint surfaces.

Reconnect strategy
------------------
On any connection loss the client walks the backoff schedule
``1s, 2s, 4s, 8s, 30s (capped)`` before retrying. The cap repeats
forever — we never give up on a live trading session. When the
connection comes back, the base class fires the optional
``on_reconnect`` callback exactly once so the higher-level
:class:`WebSocketManager` can trigger a one-shot
``RiskStateManager.reconcile`` sweep for every open trade — push events
that arrived during the outage are NOT replayed.

Thread-safety
-------------
Intended for use from a single asyncio task per client. The public
methods ``connect``, ``disconnect``, ``subscribe`` and ``run_forever``
are coroutines; the ``is_connected`` property is a plain bool read and
therefore safe from any task.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Optional, Sequence

from src.observability.metrics import EXCHANGE_WEBSOCKET_CONNECTED
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Backoff ladder — retries sleep 1s, 2s, 4s, 8s, then cap at 30s for every
# further attempt. Tuned so a 5-minute outage results in ~10 cheap retries
# instead of a thundering herd of connections.
_BACKOFF_SCHEDULE_SECONDS: Sequence[float] = (1.0, 2.0, 4.0, 8.0, 30.0)

# Event callback signature: ``(user_id, exchange, event_type, payload)``.
EventCallback = Callable[[int, str, str, dict], Awaitable[None]]
ReconnectCallback = Callable[[int, str], Awaitable[None]]


class ExchangeWebSocketClient(ABC):
    """Base class for a single ``(user_id, exchange)`` WebSocket session.

    Parameters
    ----------
    user_id:
        The owning user. Propagated to ``on_event`` so the RSM can look
        up trades without another DB hit.
    exchange:
        Canonical exchange name (``"bitget"``, ``"hyperliquid"`` …).
    on_event:
        Async callback invoked for every parsed event. Exceptions are
        caught and logged — one bad event MUST NOT tear down the
        subscription.
    on_reconnect:
        Optional async callback invoked each time the connection has
        been re-established after a drop. Used by the manager to issue
        the "missed events" reconcile sweep.
    """

    def __init__(
        self,
        *,
        user_id: int,
        exchange: str,
        on_event: EventCallback,
        on_reconnect: Optional[ReconnectCallback] = None,
    ) -> None:
        self.user_id = user_id
        self.exchange = exchange
        self._on_event = on_event
        self._on_reconnect = on_reconnect
        self._connected: bool = False
        self._stop_requested: bool = False
        self._task: Optional[asyncio.Task[None]] = None
        self._transport: Any = None  # provided by subclass

    # ── Health ─────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """``True`` while the underlying transport is open and authenticated."""
        return self._connected

    # ── Public lifecycle ───────────────────────────────────────────

    async def connect(self) -> None:
        """Open the transport, authenticate if needed, and subscribe.

        Raises whatever the subclass raises — the :meth:`run_forever`
        loop catches those and retries with backoff. A direct caller
        (e.g. a test) gets the exception bubbled up.
        """
        self._transport = await self._connect_transport()
        try:
            await self._subscribe()
        except Exception:
            # Clean up the transport so we don't leak a half-open socket
            # when subscribe fails (e.g. auth rejected).
            await self._safe_close_transport()
            raise
        self._connected = True
        EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange=self.exchange).set(1)
        logger.info(
            "ws.connected user=%s exchange=%s",
            self.user_id, self.exchange,
            extra={"event_type": "exchange_ws", "phase": "connect",
                   "user_id": self.user_id, "exchange": self.exchange},
        )

    async def disconnect(self) -> None:
        """Stop the run loop and close the transport.

        Idempotent — safe to call multiple times. A pending
        ``run_forever`` task is awaited so callers can rely on full
        teardown once ``disconnect`` returns.
        """
        self._stop_requested = True
        self._connected = False
        EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange=self.exchange).set(0)
        await self._safe_close_transport()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as e:  # noqa: BLE001 — never let teardown raise
                logger.debug(
                    "ws.disconnect_task_error user=%s exchange=%s error=%s",
                    self.user_id, self.exchange, e,
                )
        self._task = None

    def start(self) -> asyncio.Task[None]:
        """Kick off the ``run_forever`` loop as a background task.

        Returns the task so the manager can cancel it on shutdown. Safe
        to call once; subsequent calls return the existing task.
        """
        if self._task is None or self._task.done():
            self._stop_requested = False
            self._task = asyncio.create_task(self.run_forever())
        return self._task

    async def run_forever(self) -> None:
        """Connect, read messages, reconnect on drop until stopped.

        Exceptions from ``_connect_transport`` or ``_subscribe`` are
        caught and treated as "reconnect required". ``_read_once`` is
        called in a tight loop; a ``ConnectionError`` or the transport
        returning ``None`` flips us back into the reconnect path.
        """
        attempt = 0
        while not self._stop_requested:
            try:
                if not self._connected:
                    await self.connect()
                    if attempt > 0 and self._on_reconnect is not None:
                        # One-shot resync — deliberately do NOT replay
                        # missed frames. The manager uses this to force a
                        # reconcile sweep for all open trades.
                        try:
                            await self._on_reconnect(self.user_id, self.exchange)
                        except Exception as e:  # noqa: BLE001
                            logger.warning(
                                "ws.reconnect_callback_error user=%s exchange=%s error=%s",
                                self.user_id, self.exchange, e,
                            )
                    attempt = 0
                message = await self._read_once()
                if message is None:
                    raise ConnectionError("transport returned None (closed)")
                await self._handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self._connected = False
                EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange=self.exchange).set(0)
                await self._safe_close_transport()
                if self._stop_requested:
                    break
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "ws.reconnect user=%s exchange=%s attempt=%s delay=%.1fs error=%s",
                    self.user_id, self.exchange, attempt + 1, delay, e,
                    extra={"event_type": "exchange_ws", "phase": "reconnect",
                           "user_id": self.user_id, "exchange": self.exchange,
                           "attempt": attempt + 1, "delay_s": delay},
                )
                attempt += 1
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    raise

    # ── Abstract transport hooks ───────────────────────────────────

    @abstractmethod
    async def _connect_transport(self) -> Any:
        """Open and authenticate the underlying transport.

        Returns whatever object ``_read_once`` / ``_subscribe`` expect —
        typically a ``websockets.WebSocketClientProtocol`` for direct
        clients, or an SDK-provided handle (e.g. Hyperliquid ``Info``).
        """

    @abstractmethod
    async def _subscribe(self) -> None:
        """Send the subscription frame(s) for this client."""

    @abstractmethod
    async def _read_once(self) -> Optional[Any]:
        """Read a single message from the transport.

        Return ``None`` to signal the transport closed cleanly; raise
        for protocol/transport errors.
        """

    @abstractmethod
    def _parse_message(self, raw: Any) -> Optional[dict]:
        """Translate a raw frame to the canonical event dict.

        Returns ``None`` for frames that should be ignored (heartbeats,
        snapshot replays, events that don't describe a trade state
        change). Returned dicts MUST carry at minimum ``event_type``
        and a ``payload`` sub-dict including ``symbol``.
        """

    # ── Subclass helpers ───────────────────────────────────────────

    async def subscribe(self) -> None:
        """Public alias for :meth:`_subscribe` — callable after ``connect``."""
        await self._subscribe()

    async def _handle_message(self, raw: Any) -> None:
        """Parse a frame and dispatch it to :attr:`_on_event`.

        Isolates exceptions so a single bad frame doesn't kill the run
        loop; the message is logged and dropped.
        """
        try:
            event = self._parse_message(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "ws.parse_error user=%s exchange=%s error=%s",
                self.user_id, self.exchange, e,
            )
            return
        if event is None:
            return
        event_type = event.get("event_type")
        payload = event.get("payload") or {}
        if not event_type:
            logger.debug(
                "ws.drop_unnamed_event user=%s exchange=%s raw_keys=%s",
                self.user_id, self.exchange, list(event.keys()),
            )
            return
        try:
            await self._on_event(self.user_id, self.exchange, event_type, payload)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "ws.dispatch_error user=%s exchange=%s event=%s error=%s",
                self.user_id, self.exchange, event_type, e,
            )

    async def _safe_close_transport(self) -> None:
        """Close the transport if it exposes a ``close`` coroutine.

        Swallows every exception — teardown must not raise into the
        caller and hide an earlier failure.
        """
        transport = self._transport
        self._transport = None
        if transport is None:
            return
        close = getattr(transport, "close", None)
        if close is None:
            return
        try:
            result = close()
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "ws.close_error user=%s exchange=%s error=%s",
                self.user_id, self.exchange, e,
            )

    @staticmethod
    def _backoff_delay(attempt: int) -> float:
        """Return the sleep duration for ``attempt`` (0-indexed).

        The schedule is ``1s, 2s, 4s, 8s, 30s`` and every further attempt
        also uses the 30s cap.
        """
        if attempt < 0:
            attempt = 0
        if attempt >= len(_BACKOFF_SCHEDULE_SECONDS):
            return _BACKOFF_SCHEDULE_SECONDS[-1]
        return _BACKOFF_SCHEDULE_SECONDS[attempt]


__all__ = [
    "ExchangeWebSocketClient",
    "EventCallback",
    "ReconnectCallback",
]
