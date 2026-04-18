"""
Risk-State-Manager with 2-Phase-Commit semantics (Issue #190, Epic #188).

``RiskStateManager.apply_intent`` is the single entry point that the bot
uses to set, replace, or clear a TP, SL, or trailing-stop leg of an open
position. It runs the following 2-Phase-Commit:

Phase A  — DB write intent          (*_intent + *_status=PENDING)
Phase B  — Exchange call            (cancel old → place new, if any)
Phase C  — Exchange readback        (source of truth)
Phase D  — DB write confirmation    (take_profit + *_order_id + *_status + risk_source)

Anti-patterns this module exists to prevent
-------------------------------------------
* **Pattern A — "probe but don't write"**: every value returned by
  Phase C (``confirmed_value`` / ``confirmed_order_id``) is written back
  to the DB in Phase D. Never log and discard.
* **Pattern C — silent cancel failures**: ``CancelFailed`` is always
  raised as a ``logger.warning`` (never DEBUG) and short-circuits
  ``apply_intent`` before attempting to place a new order. A stale
  exchange-side order must never be orphaned because we failed to
  cancel it.

Feature flag
------------
Gated by ``Settings.risk.risk_state_manager_enabled`` (env var
``RISK_STATE_MANAGER_ENABLED``, default off). The manager is safe to
instantiate even when the flag is off — callers decide whether to route
through it.

The ``get_position_tpsl`` / ``get_trailing_stop`` readback methods come
from Issue #191. Until those land per adapter, the default base-class
methods raise ``NotImplementedError`` and this module falls back to
"best effort": it uses the intended value and the order id returned by
the place call.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.risk_reasons import ExitReason
from src.exceptions import CancelFailed, ExchangeError
from src.exchanges.base import (
    CloseReasonSnapshot,
    ExchangeClient,
    PositionTpSlSnapshot,
    TrailingStopSnapshot,
)
from src.models.database import TradeRecord
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Window in which a strategy-exit signal beats any exchange-side reason.
# Tuned to be longer than one monitor cycle but short enough that an unrelated
# native trigger 5 minutes later is not misattributed.
_STRATEGY_EXIT_WINDOW_SECONDS = 60

# Bitget-style plan_type → ExitReason mapping. Other exchanges normalize to
# the same vocabulary in CloseReasonSnapshot.closed_by_plan_type so this map
# is exchange-agnostic.
_PLAN_TYPE_TO_REASON: Dict[str, str] = {
    "track_plan": ExitReason.TRAILING_STOP_NATIVE.value,
    "pos_profit": ExitReason.TAKE_PROFIT_NATIVE.value,
    "pos_loss": ExitReason.STOP_LOSS_NATIVE.value,
    "liquidation": ExitReason.LIQUIDATION.value,
    "manual": ExitReason.MANUAL_CLOSE_EXCHANGE.value,
}


# ── Enums & DTOs ────────────────────────────────────────────────────

class RiskLeg(str, Enum):
    """Which risk-leg of a position we are operating on."""
    TP = "tp"
    SL = "sl"
    TRAILING = "trailing"


class RiskOpStatus(str, Enum):
    """Terminal status of an ``apply_intent`` invocation."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CLEARED = "cleared"
    CANCEL_FAILED = "cancel_failed"


@dataclass
class RiskOpResult:
    """Outcome of an ``apply_intent`` call."""
    trade_id: int
    leg: RiskLeg
    status: RiskOpStatus
    value: Any  # float for TP/SL, dict for trailing, None for clears
    order_id: Optional[str]
    error: Optional[str] = None
    latency_ms: int = 0


@dataclass
class RiskStateSnapshot:
    """Result of ``reconcile`` — DB/exchange-aligned state for one trade."""
    trade_id: int
    tp: Optional[dict]
    sl: Optional[dict]
    trailing: Optional[dict]
    risk_source: str
    last_synced_at: datetime


# ── Type aliases for DI ──────────────────────────────────────────────

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ExchangeClientFactory = Callable[
    [int, str, bool], Any  # user_id, exchange, demo_mode → awaitable ExchangeClient
]


# ── Risk-source markers ──────────────────────────────────────────────

_RISK_SOURCE_NATIVE = "native_exchange"
_RISK_SOURCE_SOFTWARE = "software_bot"


# ── Manager ─────────────────────────────────────────────────────────

class RiskStateManager:
    """Applies TP/SL/trailing intents atomically with 2-Phase-Commit.

    Construction takes two factories so tests and callers can inject
    their own session/exchange wiring:

    * ``exchange_client_factory(user_id, exchange, demo_mode)``
      returns (awaitable or sync) an :class:`ExchangeClient` the
      manager uses for Phase B / Phase C calls.
    * ``session_factory()`` returns an async context manager yielding
      an :class:`AsyncSession`. Each phase acquires its own session so
      a stuck exchange call can't hold a DB transaction open.
    """

    def __init__(
        self,
        exchange_client_factory: ExchangeClientFactory,
        session_factory: SessionFactory,
    ) -> None:
        self._exchange_client_factory = exchange_client_factory
        self._session_factory = session_factory
        self._locks: Dict[Tuple[int, RiskLeg], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        # Strategy-exit cache: {trade_id: monotonic timestamp the position
        # monitor signalled "strategy wants to close this".} Consumed by
        # classify_close so a strategy-driven exit beats whatever the
        # exchange recorded in its order/plan history.
        self._strategy_exit_marks: Dict[int, float] = {}

    # ── Lock management ────────────────────────────────────────────

    def _get_lock(self, trade_id: int, leg: RiskLeg) -> asyncio.Lock:
        """Return the per-(trade, leg) lock, creating it lazily."""
        key = (trade_id, leg)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    # ── Public API ─────────────────────────────────────────────────

    async def apply_intent(
        self,
        trade_id: int,
        leg: RiskLeg,
        value: Any,
    ) -> RiskOpResult:
        """Run the 2-Phase-Commit for (trade_id, leg) → value.

        ``value`` semantics:
        * ``None``  → clear the leg (cancel-only).
        * ``float`` → target price for TP/SL.
        * ``dict``  → trailing payload with keys
          ``callback_rate``, ``activation_price``, ``trigger_price``.

        Returns a :class:`RiskOpResult` describing the terminal state.
        Never raises for exchange-side failures — those are reported
        via ``status`` + ``error``. Raises only for truly unexpected
        programmer errors (e.g. unknown ``leg`` value).
        """
        start = time.perf_counter()
        lock = self._get_lock(trade_id, leg)
        async with lock:
            # Phase A: write intent → PENDING
            trade = await self._write_intent_pending(trade_id, leg, value)
            if trade is None:
                return self._result(
                    trade_id, leg, RiskOpStatus.REJECTED,
                    value, None,
                    error=f"trade {trade_id} not found",
                    started_at=start,
                )

            user_id = trade["user_id"]
            exchange = trade["exchange"]
            demo_mode = trade["demo_mode"]
            symbol = trade["symbol"]
            side = trade["side"]
            size = trade["size"]
            existing_order_id = trade[f"{leg.value}_order_id"]

            # Phase B: talk to the exchange
            client = await self._acquire_client(user_id, exchange, demo_mode)
            try:
                new_order_id = await self._exchange_apply(
                    client=client,
                    leg=leg,
                    value=value,
                    symbol=symbol,
                    side=side,
                    size=size,
                    existing_order_id=existing_order_id,
                )
            except CancelFailed as e:
                # Pattern C: cancel failed → never attempt a place
                logger.warning(
                    "risk_state.cancel_failed trade=%s leg=%s error=%s",
                    trade_id, leg.value, e,
                    extra={
                        "event_type": "risk_state",
                        "trade_id": trade_id,
                        "leg": leg.value,
                        "phase": "exchange_cancel",
                        "outcome": "cancel_failed",
                    },
                )
                await self._write_status(trade_id, leg, RiskOpStatus.CANCEL_FAILED, error=str(e))
                return self._result(
                    trade_id, leg, RiskOpStatus.CANCEL_FAILED,
                    value, existing_order_id,
                    error=str(e),
                    started_at=start,
                )
            except ExchangeError as e:
                logger.warning(
                    "risk_state.exchange_rejected trade=%s leg=%s error=%s",
                    trade_id, leg.value, e,
                    extra={
                        "event_type": "risk_state",
                        "trade_id": trade_id,
                        "leg": leg.value,
                        "phase": "exchange_place",
                        "outcome": "rejected",
                    },
                )
                await self._write_status(trade_id, leg, RiskOpStatus.REJECTED, error=str(e))
                return self._result(
                    trade_id, leg, RiskOpStatus.REJECTED,
                    value, existing_order_id,
                    error=str(e),
                    started_at=start,
                )
            except Exception as e:  # noqa: BLE001 — any other exchange fault
                logger.warning(
                    "risk_state.exchange_unexpected trade=%s leg=%s error=%s",
                    trade_id, leg.value, e,
                    extra={
                        "event_type": "risk_state",
                        "trade_id": trade_id,
                        "leg": leg.value,
                        "phase": "exchange_place",
                        "outcome": "rejected",
                    },
                )
                await self._write_status(trade_id, leg, RiskOpStatus.REJECTED, error=str(e))
                return self._result(
                    trade_id, leg, RiskOpStatus.REJECTED,
                    value, existing_order_id,
                    error=str(e),
                    started_at=start,
                )

            # Phase C: readback (source of truth)
            confirmed_value, confirmed_order_id = await self._readback(
                client, leg, value, new_order_id, symbol, side,
            )

            # Phase D: write confirmation — MUST use readback values.
            final_status = (
                RiskOpStatus.CLEARED if value is None else RiskOpStatus.CONFIRMED
            )
            await self._write_confirmation(
                trade_id, leg, confirmed_value, confirmed_order_id, final_status,
            )

            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "risk_state.intent_applied trade=%s leg=%s outcome=%s latency_ms=%s",
                trade_id, leg.value, final_status.value, latency_ms,
                extra={
                    "event_type": "risk_state",
                    "trade_id": trade_id,
                    "leg": leg.value,
                    "phase": "exchange",
                    "outcome": "ok",
                    "latency_ms": latency_ms,
                },
            )
            return RiskOpResult(
                trade_id=trade_id,
                leg=leg,
                status=final_status,
                value=confirmed_value,
                order_id=confirmed_order_id,
                latency_ms=latency_ms,
            )

    async def reconcile(self, trade_id: int) -> RiskStateSnapshot:
        """Probe exchange state and align DB to it.

        Intended for the periodic reconciler loop (#192). Reads the
        current TP/SL + trailing from the exchange, compares with the
        DB row, and overwrites DB fields when they disagree (exchange
        is the source of truth).
        """
        trade = await self._load_trade(trade_id)
        if trade is None:
            raise ValueError(f"trade {trade_id} not found")

        client = await self._acquire_client(
            trade["user_id"], trade["exchange"], trade["demo_mode"],
        )

        symbol = trade["symbol"]
        side = trade["side"]

        tp_sl_snapshot: Optional[PositionTpSlSnapshot] = None
        trailing_snapshot: Optional[TrailingStopSnapshot] = None

        try:
            tp_sl_snapshot = await client.get_position_tpsl(symbol, side)
        except NotImplementedError:
            logger.debug(
                "risk_state.reconcile skip_tpsl trade=%s exchange=%s",
                trade_id, trade["exchange"],
            )

        try:
            trailing_snapshot = await client.get_trailing_stop(symbol, side)
        except NotImplementedError:
            logger.debug(
                "risk_state.reconcile skip_trailing trade=%s exchange=%s",
                trade_id, trade["exchange"],
            )

        now = datetime.now(timezone.utc)
        risk_source = _RISK_SOURCE_NATIVE
        has_native_anything = False

        async with self._session_factory() as session:
            db_trade = await session.get(TradeRecord, trade_id)
            if db_trade is None:  # pragma: no cover — row vanished mid-reconcile
                raise ValueError(f"trade {trade_id} vanished during reconcile")

            if tp_sl_snapshot is not None:
                db_trade.take_profit = tp_sl_snapshot.tp_price
                db_trade.tp_order_id = tp_sl_snapshot.tp_order_id
                db_trade.tp_status = (
                    RiskOpStatus.CONFIRMED.value
                    if tp_sl_snapshot.tp_order_id
                    else RiskOpStatus.CLEARED.value
                )
                db_trade.stop_loss = tp_sl_snapshot.sl_price
                db_trade.sl_order_id = tp_sl_snapshot.sl_order_id
                db_trade.sl_status = (
                    RiskOpStatus.CONFIRMED.value
                    if tp_sl_snapshot.sl_order_id
                    else RiskOpStatus.CLEARED.value
                )
                has_native_anything = has_native_anything or bool(
                    tp_sl_snapshot.tp_order_id or tp_sl_snapshot.sl_order_id
                )

            if trailing_snapshot is not None:
                db_trade.trailing_callback_rate = trailing_snapshot.callback_rate
                db_trade.trailing_activation_price = trailing_snapshot.activation_price
                db_trade.trailing_trigger_price = trailing_snapshot.trigger_price
                db_trade.trailing_order_id = trailing_snapshot.order_id
                db_trade.trailing_status = (
                    RiskOpStatus.CONFIRMED.value
                    if trailing_snapshot.order_id
                    else RiskOpStatus.CLEARED.value
                )
                has_native_anything = has_native_anything or bool(
                    trailing_snapshot.order_id
                )

            if not has_native_anything:
                risk_source = _RISK_SOURCE_SOFTWARE
            db_trade.risk_source = risk_source
            db_trade.last_synced_at = now
            await session.commit()

        tp_dict = (
            {
                "value": tp_sl_snapshot.tp_price,
                "status": (
                    RiskOpStatus.CONFIRMED.value
                    if tp_sl_snapshot.tp_order_id
                    else RiskOpStatus.CLEARED.value
                ),
                "order_id": tp_sl_snapshot.tp_order_id,
            }
            if tp_sl_snapshot is not None
            else None
        )
        sl_dict = (
            {
                "value": tp_sl_snapshot.sl_price,
                "status": (
                    RiskOpStatus.CONFIRMED.value
                    if tp_sl_snapshot.sl_order_id
                    else RiskOpStatus.CLEARED.value
                ),
                "order_id": tp_sl_snapshot.sl_order_id,
            }
            if tp_sl_snapshot is not None
            else None
        )
        trailing_dict = (
            {
                "value": {
                    "callback_rate": trailing_snapshot.callback_rate,
                    "activation_price": trailing_snapshot.activation_price,
                    "trigger_price": trailing_snapshot.trigger_price,
                },
                "status": (
                    RiskOpStatus.CONFIRMED.value
                    if trailing_snapshot.order_id
                    else RiskOpStatus.CLEARED.value
                ),
                "order_id": trailing_snapshot.order_id,
            }
            if trailing_snapshot is not None
            else None
        )

        return RiskStateSnapshot(
            trade_id=trade_id,
            tp=tp_dict,
            sl=sl_dict,
            trailing=trailing_dict,
            risk_source=risk_source,
            last_synced_at=now,
        )

    async def on_exchange_event(self, event: dict) -> None:
        """Stub for Phase 2 WS push (#192). Currently logging-only."""
        logger.info(
            "risk_state.ws_event_received event=%s",
            event,
            extra={
                "event_type": "risk_state",
                "phase": "ws",
                "outcome": "stub",
            },
        )

    def note_strategy_exit(self, trade_id: int) -> None:
        """Record that ``trade_id`` was just closed by an internal strategy signal.

        Called by the position-monitor *before* it issues the close so that a
        subsequent :meth:`classify_close` can attribute the exit to the bot's
        own logic rather than to whatever native plan happened to fire at the
        same moment. Uses a monotonic clock so wall-clock changes don't poison
        the window.
        """
        self._strategy_exit_marks[trade_id] = time.monotonic()

    async def classify_close(
        self,
        trade_id: int,
        exit_price: float,
        exit_time: datetime,
    ) -> str:
        """Attribute a close to its true cause via exchange-side readback.

        Resolution order:

        1. Strategy-exit signal recorded within the last
           ``_STRATEGY_EXIT_WINDOW_SECONDS``: returns ``STRATEGY_EXIT``
           regardless of what the exchange thinks. Internal signals always
           win over external triggers because the bot deliberately initiated
           the close.
        2. Exchange ``orders-plan-history`` / ``orders-history`` probe (via
           :meth:`ExchangeClient.get_close_reason_from_history`): match the
           closing order id against ``trade.{trailing,tp,sl}_order_id``;
           failing that, fall back to the normalized ``closed_by_plan_type``.
        3. Software-trail: when the trade was opened with ``risk_source =
           software_bot`` and the trailing leg is confirmed, attribute to
           ``TRAILING_STOP_SOFTWARE``.
        4. Heuristic fallback (legacy behaviour) when the probe is
           unavailable (``NotImplementedError``) or fails (any other
           exception): use price proximity and ``native_trailing_stop``.

        Pattern B guard: the heuristic is *only* taken when the exchange
        probe could not deliver an answer. Never short-circuit a probe with
        a heuristic guess.
        """
        trade = await self._load_trade_for_classification(trade_id)
        if trade is None:
            logger.info(
                "risk_state.classify_close trade=%s reason=%s method=%s",
                trade_id, ExitReason.EXTERNAL_CLOSE_UNKNOWN.value, "no_trade",
                extra={
                    "event_type": "risk_state",
                    "trade_id": trade_id,
                    "method": "no_trade",
                    "reason": ExitReason.EXTERNAL_CLOSE_UNKNOWN.value,
                    "snap_plan_type": None,
                },
            )
            return ExitReason.EXTERNAL_CLOSE_UNKNOWN.value

        # 1) Strategy-exit signal beats everything — we initiated the close.
        if self._was_strategy_exit_recent(trade_id):
            logger.info(
                "risk_state.classify_close trade=%s reason=%s method=%s",
                trade_id, ExitReason.STRATEGY_EXIT.value, "strategy_signal",
                extra={
                    "event_type": "risk_state",
                    "trade_id": trade_id,
                    "method": "strategy_signal",
                    "reason": ExitReason.STRATEGY_EXIT.value,
                    "snap_plan_type": None,
                },
            )
            self._strategy_exit_marks.pop(trade_id, None)
            return ExitReason.STRATEGY_EXIT.value

        # 2) Probe the exchange for the actual close event.
        snap, probe_method = await self._probe_close_reason(trade)

        if probe_method == "heuristic_fallback":
            reason = self._classify_heuristic(trade, exit_price)
            logger.info(
                "risk_state.classify_close trade=%s reason=%s method=%s",
                trade_id, reason, probe_method,
                extra={
                    "event_type": "risk_state",
                    "trade_id": trade_id,
                    "method": probe_method,
                    "reason": reason,
                    "snap_plan_type": None,
                },
            )
            return reason

        if snap is None:
            # Probe ran fine but found no qualifying close event — this can
            # happen when the exchange's history is delayed. Fall back to the
            # heuristic so we still emit a sensible label.
            reason = self._classify_heuristic(trade, exit_price)
            logger.info(
                "risk_state.classify_close trade=%s reason=%s method=%s",
                trade_id, reason, "history_empty",
                extra={
                    "event_type": "risk_state",
                    "trade_id": trade_id,
                    "method": "history_empty",
                    "reason": reason,
                    "snap_plan_type": None,
                },
            )
            return reason

        reason = self._classify_from_snapshot(trade, snap)
        logger.info(
            "risk_state.classify_close trade=%s reason=%s method=%s",
            trade_id, reason, "history_match",
            extra={
                "event_type": "risk_state",
                "trade_id": trade_id,
                "method": "history_match",
                "reason": reason,
                "snap_plan_type": snap.closed_by_plan_type,
            },
        )
        return reason

    # ── classify_close helpers ─────────────────────────────────────

    def _was_strategy_exit_recent(self, trade_id: int) -> bool:
        """True if note_strategy_exit fired within the strategy-exit window.

        Uses a monotonic clock so that wall-clock skew (NTP jumps) does not
        accidentally extend or shrink the window.
        """
        marker = self._strategy_exit_marks.get(trade_id)
        if marker is None:
            return False
        elapsed = time.monotonic() - marker
        if elapsed > _STRATEGY_EXIT_WINDOW_SECONDS:
            # Stale — drop it so the cache stays bounded.
            self._strategy_exit_marks.pop(trade_id, None)
            return False
        return True

    async def _load_trade_for_classification(
        self, trade_id: int,
    ) -> Optional[dict]:
        """Snapshot the trade fields the classifier inspects.

        We deliberately copy into a plain dict so the SQLAlchemy session can
        be released before the (potentially slow) exchange probe runs.
        """
        async with self._session_factory() as session:
            trade = await session.get(TradeRecord, trade_id)
            if trade is None:
                return None
            entry_time = trade.entry_time
            if entry_time is not None and entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
            return {
                "id": trade.id,
                "user_id": trade.user_id,
                "exchange": trade.exchange,
                "demo_mode": bool(trade.demo_mode),
                "symbol": trade.symbol,
                "side": trade.side,
                "entry_time": entry_time,
                "entry_price": float(trade.entry_price or 0.0),
                "take_profit": trade.take_profit,
                "stop_loss": trade.stop_loss,
                "tp_order_id": trade.tp_order_id,
                "sl_order_id": trade.sl_order_id,
                "trailing_order_id": trade.trailing_order_id,
                "native_trailing_stop": bool(trade.native_trailing_stop),
                "risk_source": trade.risk_source or "unknown",
                "trailing_status": trade.trailing_status,
            }

    async def _probe_close_reason(
        self, trade: dict,
    ) -> Tuple[Optional[CloseReasonSnapshot], str]:
        """Ask the exchange for the most recent close event.

        Returns ``(snapshot, method)`` where ``method`` is one of:

        * ``"history_match"`` — probe ran and returned a (possibly None) snapshot.
        * ``"heuristic_fallback"`` — adapter doesn't implement the probe, or
          the probe raised an :class:`ExchangeError` / unexpected exception.
          Caller MUST then run :meth:`_classify_heuristic`.
        """
        client = None
        entry_time = trade.get("entry_time") or datetime.now(timezone.utc)
        # Pull a small window before entry to make sure we catch any close
        # event whose timestamp is slightly before entry_time + 1 cycle.
        since_ms = int(entry_time.timestamp() * 1000) - 1000
        try:
            client = await self._acquire_client(
                trade["user_id"], trade["exchange"], trade["demo_mode"],
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "risk_state.classify_close.client_error trade=%s exchange=%s error=%s",
                trade["id"], trade["exchange"], e,
            )
            return None, "heuristic_fallback"

        try:
            snap = await client.get_close_reason_from_history(
                trade["symbol"], since_ms,
            )
            return snap, "history_match"
        except NotImplementedError:
            logger.debug(
                "risk_state.classify_close.no_probe trade=%s exchange=%s",
                trade["id"], trade["exchange"],
            )
            return None, "heuristic_fallback"
        except ExchangeError as e:
            logger.warning(
                "risk_state.classify_close.exchange_error trade=%s exchange=%s error=%s",
                trade["id"], trade["exchange"], e,
            )
            return None, "heuristic_fallback"
        except Exception as e:  # noqa: BLE001 — defensive: any probe fault → fallback
            logger.warning(
                "risk_state.classify_close.unexpected_error trade=%s exchange=%s error=%s",
                trade["id"], trade["exchange"], e,
            )
            return None, "heuristic_fallback"
        finally:
            if client is not None:
                close_fn = getattr(client, "close", None)
                if close_fn is not None:
                    try:
                        result = close_fn()
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:  # noqa: BLE001 — never let cleanup hide the result
                        pass

    def _classify_from_snapshot(
        self, trade: dict, snap: CloseReasonSnapshot,
    ) -> str:
        """Resolve a snapshot to an ExitReason value.

        Order:
        1. Match ``closed_by_order_id`` against the per-leg order IDs in the
           trade — this is the most precise attribution available.
        2. Fall back to ``closed_by_plan_type`` (works even after a
           plan-id rotation caused by an edit).
        3. Software trailing detection when the trade was opened in
           ``software_bot`` mode and the trailing leg was confirmed.
        4. ``EXTERNAL_CLOSE_UNKNOWN`` as a last resort.
        """
        closing_oid = snap.closed_by_order_id
        if closing_oid:
            if trade["trailing_order_id"] and closing_oid == trade["trailing_order_id"]:
                return ExitReason.TRAILING_STOP_NATIVE.value
            if trade["tp_order_id"] and closing_oid == trade["tp_order_id"]:
                return ExitReason.TAKE_PROFIT_NATIVE.value
            if trade["sl_order_id"] and closing_oid == trade["sl_order_id"]:
                return ExitReason.STOP_LOSS_NATIVE.value

        plan_type = (snap.closed_by_plan_type or "").lower() or None
        if plan_type and plan_type in _PLAN_TYPE_TO_REASON:
            return _PLAN_TYPE_TO_REASON[plan_type]

        if (
            trade["risk_source"] == _RISK_SOURCE_SOFTWARE
            and trade["trailing_status"] == RiskOpStatus.CONFIRMED.value
        ):
            return ExitReason.TRAILING_STOP_SOFTWARE.value

        return ExitReason.EXTERNAL_CLOSE_UNKNOWN.value

    def _classify_heuristic(self, trade: dict, exit_price: float) -> str:
        """Legacy proximity heuristic — used only when the probe is unavailable.

        Pattern B guard: callers must only reach this when the exchange-side
        probe genuinely failed (``NotImplementedError`` or
        :class:`ExchangeError`). Never call this in lieu of probing.
        """
        if trade["native_trailing_stop"]:
            return ExitReason.TRAILING_STOP_NATIVE.value

        entry_price = trade["entry_price"]
        proximity = entry_price * 0.002 if entry_price > 0 else 0.0

        tp = trade["take_profit"]
        if tp is not None and entry_price > 0 and abs(exit_price - tp) < proximity:
            return ExitReason.TAKE_PROFIT_NATIVE.value

        sl = trade["stop_loss"]
        if sl is not None and entry_price > 0 and abs(exit_price - sl) < proximity:
            return ExitReason.STOP_LOSS_NATIVE.value

        return ExitReason.EXTERNAL_CLOSE_UNKNOWN.value

    # ── Phase A — DB intent write ──────────────────────────────────

    async def _write_intent_pending(
        self,
        trade_id: int,
        leg: RiskLeg,
        value: Any,
    ) -> Optional[dict]:
        """Persist the intent and return a snapshot of identifying fields.

        Returns None if the trade is not found. The returned dict is
        deliberately a plain dict so we do not leak a detached SQLAlchemy
        instance across session boundaries.
        """
        async with self._session_factory() as session:
            trade = await session.get(TradeRecord, trade_id)
            if trade is None:
                return None

            if leg is RiskLeg.TP:
                trade.tp_intent = value if value is not None else None
                trade.tp_status = RiskOpStatus.PENDING.value
            elif leg is RiskLeg.SL:
                trade.sl_intent = value if value is not None else None
                trade.sl_status = RiskOpStatus.PENDING.value
            elif leg is RiskLeg.TRAILING:
                callback = None
                if isinstance(value, dict):
                    callback = value.get("callback_rate")
                trade.trailing_intent_callback = callback
                trade.trailing_status = RiskOpStatus.PENDING.value
            else:  # pragma: no cover — defensive
                raise ValueError(f"Unknown RiskLeg {leg!r}")

            trade.last_synced_at = datetime.now(timezone.utc)
            await session.commit()

            return {
                "user_id": trade.user_id,
                "exchange": trade.exchange,
                "demo_mode": bool(trade.demo_mode),
                "symbol": trade.symbol,
                "side": trade.side,
                "size": float(trade.size),
                "tp_order_id": trade.tp_order_id,
                "sl_order_id": trade.sl_order_id,
                "trailing_order_id": trade.trailing_order_id,
            }

    # ── Phase B — Exchange apply (cancel-old → place-new) ──────────

    async def _exchange_apply(
        self,
        client: ExchangeClient,
        leg: RiskLeg,
        value: Any,
        symbol: str,
        side: str,
        size: float,
        existing_order_id: Optional[str],
    ) -> Optional[str]:
        """Cancel the existing leg (if any) then place a new one.

        Returns the new exchange order-id, or ``None`` if we only
        cleared (value is None) or the exchange didn't return one.
        Raises :class:`CancelFailed` if the cancel step fails, in which
        case the caller must NOT attempt the place. Raises
        :class:`ExchangeError` or subclasses on place failures.
        """
        # Cancel-old step — only if there was something there and
        # we're either clearing (value is None) or replacing.
        # CRITICAL: cancel ONLY the leg we're touching. Before Epic #188
        # follow-up, this called cancel_position_tpsl() which wipes TP+SL+
        # trailing simultaneously on Bitget, silently collapsing other
        # active legs. Each leg now has a dedicated cancel path.
        if existing_order_id is not None:
            try:
                if leg is RiskLeg.TP:
                    await client.cancel_tp_only(symbol=symbol, side=side)
                elif leg is RiskLeg.SL:
                    await client.cancel_sl_only(symbol=symbol, side=side)
                else:
                    # Trailing: prefer native dedicated cancel if adapter
                    # exposes it; otherwise fall back to cancel_order by id.
                    if hasattr(client, "cancel_native_trailing_stop"):
                        await client.cancel_native_trailing_stop(symbol=symbol, side=side)
                    else:
                        try:
                            await client.cancel_order(symbol, existing_order_id)
                        except NotImplementedError:
                            await client.cancel_position_tpsl(symbol=symbol, side=side)
            except (ExchangeError, Exception) as e:
                if isinstance(e, (ExchangeError, NotImplementedError)):
                    # NotImplementedError here means the exchange genuinely
                    # can't cancel — surface as CancelFailed so caller won't place.
                    raise CancelFailed(
                        getattr(client, "exchange_name", "unknown"),
                        f"cancel {leg.value} for {symbol} failed: {e}",
                        original_error=e,
                    ) from e
                # Any other Exception → treat as cancel failure too
                raise CancelFailed(
                    getattr(client, "exchange_name", "unknown"),
                    f"cancel {leg.value} for {symbol} failed: {e}",
                    original_error=e,
                ) from e

        # Pure clear: nothing more to do.
        if value is None:
            return None

        # Place-new step.
        if leg is RiskLeg.TP:
            result = await client.set_position_tpsl(
                symbol=symbol,
                take_profit=float(value),
                stop_loss=None,
                side=side,
                size=size,
            )
            return _extract_order_id(result)
        if leg is RiskLeg.SL:
            result = await client.set_position_tpsl(
                symbol=symbol,
                take_profit=None,
                stop_loss=float(value),
                side=side,
                size=size,
            )
            return _extract_order_id(result)
        if leg is RiskLeg.TRAILING:
            if not isinstance(value, dict):
                raise ValueError(
                    "Trailing intent value must be a dict with callback_rate / "
                    "activation_price / trigger_price"
                )
            trailing_result = await client.place_trailing_stop(
                symbol=symbol,
                hold_side=side,
                size=size,
                callback_ratio=float(value.get("callback_rate") or 0.0),
                trigger_price=float(value.get("trigger_price") or 0.0),
            )
            return _extract_order_id(trailing_result)
        raise ValueError(f"Unknown RiskLeg {leg!r}")  # pragma: no cover

    # ── Phase C — Readback (source of truth) ───────────────────────

    async def _readback(
        self,
        client: ExchangeClient,
        leg: RiskLeg,
        intended_value: Any,
        new_order_id: Optional[str],
        symbol: str,
        side: str,
    ) -> Tuple[Any, Optional[str]]:
        """Probe the exchange for the live state of ``leg``.

        Pattern A: the two values we return here MUST be written back to
        the DB by the caller — never drop them. If the adapter does not
        yet implement the probe (``NotImplementedError``), we fall back
        to ``(intended_value, new_order_id)`` so the caller still writes
        a sensible row.
        """
        try:
            if leg in (RiskLeg.TP, RiskLeg.SL):
                snap = await client.get_position_tpsl(symbol, side)
                if leg is RiskLeg.TP:
                    return snap.tp_price, snap.tp_order_id
                return snap.sl_price, snap.sl_order_id
            trailing_snap = await client.get_trailing_stop(symbol, side)
            confirmed_dict = {
                "callback_rate": trailing_snap.callback_rate,
                "activation_price": trailing_snap.activation_price,
                "trigger_price": trailing_snap.trigger_price,
            }
            return confirmed_dict, trailing_snap.order_id
        except NotImplementedError:
            # Best-effort fallback: trust the intended value + new_order_id.
            return intended_value, new_order_id

    # ── Phase D — DB confirmation write ─────────────────────────────

    async def _write_confirmation(
        self,
        trade_id: int,
        leg: RiskLeg,
        confirmed_value: Any,
        confirmed_order_id: Optional[str],
        status: RiskOpStatus,
    ) -> None:
        """Write the readback values back to the TradeRecord row.

        Pattern A guard: this is where the probe result becomes durable.
        """
        async with self._session_factory() as session:
            trade = await session.get(TradeRecord, trade_id)
            if trade is None:  # pragma: no cover — vanished mid-op
                return

            if leg is RiskLeg.TP:
                trade.take_profit = confirmed_value
                trade.tp_order_id = confirmed_order_id
                trade.tp_status = status.value
            elif leg is RiskLeg.SL:
                trade.stop_loss = confirmed_value
                trade.sl_order_id = confirmed_order_id
                trade.sl_status = status.value
            elif leg is RiskLeg.TRAILING:
                if isinstance(confirmed_value, dict):
                    trade.trailing_callback_rate = confirmed_value.get("callback_rate")
                    trade.trailing_activation_price = confirmed_value.get("activation_price")
                    trade.trailing_trigger_price = confirmed_value.get("trigger_price")
                else:
                    trade.trailing_callback_rate = None
                    trade.trailing_activation_price = None
                    trade.trailing_trigger_price = None
                trade.trailing_order_id = confirmed_order_id
                trade.trailing_status = status.value

            trade.risk_source = (
                _RISK_SOURCE_NATIVE if confirmed_order_id else _RISK_SOURCE_SOFTWARE
            )
            trade.last_synced_at = datetime.now(timezone.utc)
            await session.commit()

    # ── Failure-path DB writes ─────────────────────────────────────

    async def _write_status(
        self,
        trade_id: int,
        leg: RiskLeg,
        status: RiskOpStatus,
        error: Optional[str] = None,
    ) -> None:
        """Persist a non-success status on the correct *_status column."""
        async with self._session_factory() as session:
            trade = await session.get(TradeRecord, trade_id)
            if trade is None:  # pragma: no cover
                return
            if leg is RiskLeg.TP:
                trade.tp_status = status.value
            elif leg is RiskLeg.SL:
                trade.sl_status = status.value
            elif leg is RiskLeg.TRAILING:
                trade.trailing_status = status.value
            trade.last_synced_at = datetime.now(timezone.utc)
            await session.commit()
        if error is not None:
            logger.debug(
                "risk_state.status_written trade=%s leg=%s status=%s error=%s",
                trade_id, leg.value, status.value, error,
            )

    # ── Helpers ────────────────────────────────────────────────────

    async def _load_trade(self, trade_id: int) -> Optional[dict]:
        """Load minimal fields for reconcile."""
        async with self._session_factory() as session:
            trade = await session.get(TradeRecord, trade_id)
            if trade is None:
                return None
            return {
                "user_id": trade.user_id,
                "exchange": trade.exchange,
                "demo_mode": bool(trade.demo_mode),
                "symbol": trade.symbol,
                "side": trade.side,
            }

    async def _acquire_client(
        self,
        user_id: int,
        exchange: str,
        demo_mode: bool,
    ) -> ExchangeClient:
        """Resolve the exchange client, supporting both sync and async factories."""
        result = self._exchange_client_factory(user_id, exchange, demo_mode)
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _result(
        self,
        trade_id: int,
        leg: RiskLeg,
        status: RiskOpStatus,
        value: Any,
        order_id: Optional[str],
        error: Optional[str],
        started_at: float,
    ) -> RiskOpResult:
        """Build a :class:`RiskOpResult` with the elapsed latency filled in."""
        return RiskOpResult(
            trade_id=trade_id,
            leg=leg,
            status=status,
            value=value,
            order_id=order_id,
            error=error,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
        )


# ── Module-level helpers ────────────────────────────────────────────

def _extract_order_id(exchange_result: Any) -> Optional[str]:
    """Pull an order-id out of whatever an exchange's place call returned.

    Accepts dicts (common Bitget response), plain strings, objects with
    an ``order_id`` attribute, and ``None``. Exchanges whose
    ``set_position_tpsl`` returns ``None`` still count as native if we
    reached Phase D via a successful call — the reconciler /
    ``get_position_tpsl`` probe fills in the real id in a later step.
    """
    if exchange_result is None:
        return None
    if isinstance(exchange_result, str):
        return exchange_result
    if isinstance(exchange_result, dict):
        for key in ("orderId", "order_id", "clientOid", "planOrderId"):
            val = exchange_result.get(key)
            if val:
                return str(val)
        return None
    order_id_attr = getattr(exchange_result, "order_id", None)
    if order_id_attr:
        return str(order_id_attr)
    return None


__all__ = [
    "ExitReason",
    "RiskLeg",
    "RiskOpStatus",
    "RiskOpResult",
    "RiskStateSnapshot",
    "RiskStateManager",
]
