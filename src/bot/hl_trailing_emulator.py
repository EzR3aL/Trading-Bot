"""Hyperliquid Software Trailing Emulator (Issue #216, Section 3.1).

Hyperliquid has no native trailing-stop primitive (see
:meth:`src.exchanges.hyperliquid.client.HyperliquidClient.get_trailing_stop`
which unconditionally returns ``None``). To give HL positions feature-parity
with the Bitget/BingX native trailing legs, this module runs a single
process-wide asyncio watchdog that:

1. Every ``_TICK_SECONDS`` seconds, pulls the list of open HL trades from
   the DB whose ``trailing_intent_callback`` is set AND whose
   ``trailing_status='confirmed'``.
2. Fetches mark prices in a single ``all_mids()`` call per exchange-user,
   NEVER one call per trade — HL rate-limits reads per IP.
3. Updates ``trade.highest_price`` in the direction of the position
   (long: max, short: min) — this column already exists on TradeRecord
   and survives restarts so state reconstructs from the DB without any
   new schema.
4. Computes a new candidate SL from ``highest_price`` and the stored
   ``trailing_callback_rate`` (percent). If it is *tighter* than the
   current ``trade.stop_loss``, routes an SL update through
   :meth:`RiskStateManager.apply_intent` so the exchange write, the
   readback, and the DB confirmation use the same 2-Phase-Commit as
   every other risk-leg edit (Anti-Pattern A + C).
5. Stamps ``risk_source='software_bot'`` on every trade the emulator
   touches — this is what the existing close-classifier
   (``_classify_from_snapshot``) uses as the signal to attribute the
   eventual close to ``TRAILING_STOP_SOFTWARE`` rather than to an
   exchange-native trigger.

Feature flag
------------
Gated by ``Settings.risk.hl_software_trailing_enabled`` (env
``HL_SOFTWARE_TRAILING_ENABLED``, default off). ``start()`` is a no-op
when the flag is off, so the emulator is safe to wire into
``BotWorker.__init__`` unconditionally.

Why the emulator lives outside ``BotWorker``
--------------------------------------------
A single watchdog services every HL trade regardless of which bot
opened it: per-bot watchdogs would multiply exchange read traffic by
the number of running bots. The caller obtains the singleton via
:func:`src.api.dependencies.hl_trailing.get_hl_trailing_emulator`.
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.risk_state_manager import (
    RiskLeg,
    RiskOpStatus,
    RiskStateManager,
)
from src.models.database import TradeRecord
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ── Constants ───────────────────────────────────────────────────────

#: How often the watchdog wakes up. 5s is the sweet spot: tighter than
#: a typical HL mark-price drift on liquid perps, but slack enough to
#: avoid burning through the per-IP read rate limit when many trades
#: are open.
_TICK_SECONDS: float = 5.0

#: Risk-source marker stamped on any trade the emulator touches.
_RISK_SOURCE_SOFTWARE = "software_bot"

#: Exchange identifier the emulator is responsible for. Kept as a module
#: constant so tests can import it instead of hard-coding the literal.
_HL_EXCHANGE = "hyperliquid"


# ── Type aliases for DI ─────────────────────────────────────────────

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ExchangeClientFactory = Callable[
    [int, str, bool], Any  # user_id, exchange, demo_mode → awaitable ExchangeClient
]


# ── Emulator ────────────────────────────────────────────────────────


class HLTrailingEmulator:
    """Per-process watchdog that emulates trailing stops for HL trades.

    Shares the :class:`RiskStateManager` singleton for SL updates so all
    writes go through the same 2-Phase-Commit path. Each tick is
    scoped by a try/except so a transient HL error on one trade never
    kills the loop.
    """

    def __init__(
        self,
        exchange_client_factory: ExchangeClientFactory,
        session_factory: SessionFactory,
        risk_state_manager: RiskStateManager,
        tick_seconds: float = _TICK_SECONDS,
    ) -> None:
        self._exchange_client_factory = exchange_client_factory
        self._session_factory = session_factory
        self._risk_state_manager = risk_state_manager
        self._tick_seconds = tick_seconds
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self, *, enabled: bool) -> None:
        """Spawn the watchdog task when the feature flag is on.

        No-op when ``enabled`` is False so callers can wire this
        unconditionally. Safe to call repeatedly — duplicate starts
        are ignored.
        """
        if not enabled:
            logger.info(
                "hl_trailing_emulator.disabled reason=flag_off",
                extra={"event_type": "hl_trailing", "phase": "start"},
            )
            return
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run(), name="hl-trailing-emulator"
        )
        logger.info(
            "hl_trailing_emulator.started tick_seconds=%s",
            self._tick_seconds,
            extra={"event_type": "hl_trailing", "phase": "start"},
        )

    async def stop(self) -> None:
        """Signal the watchdog to exit and wait for it to finish."""
        self._stop_event.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=self._tick_seconds + 2)
            except asyncio.TimeoutError:
                task.cancel()
        self._task = None

    # ── Main loop ──────────────────────────────────────────────────

    async def _run(self) -> None:
        """Watchdog loop. Each iteration runs ``tick`` under try/except."""
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception as e:  # noqa: BLE001 — never let the loop die
                logger.warning(
                    "hl_trailing_emulator.tick_error error=%s",
                    e,
                    extra={"event_type": "hl_trailing", "phase": "tick"},
                )
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._tick_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def tick(self) -> None:
        """One watchdog iteration — public so tests can drive it directly."""
        trades = await self._load_active_trades()
        if not trades:
            return

        # One all_mids() per (user_id, demo_mode) so a user with many HL
        # trades pays one read per cycle, not N.
        mids_cache: Dict[tuple, Dict[str, float]] = {}
        for trade in trades:
            try:
                await self._process_trade(trade, mids_cache)
            except Exception as e:  # noqa: BLE001 — isolate per-trade faults
                logger.warning(
                    "hl_trailing_emulator.process_error trade=%s error=%s",
                    trade["id"], e,
                    extra={
                        "event_type": "hl_trailing",
                        "phase": "process",
                        "trade_id": trade["id"],
                    },
                )

    # ── Per-trade processing ──────────────────────────────────────

    async def _process_trade(
        self,
        trade: dict,
        mids_cache: Dict[tuple, Dict[str, float]],
    ) -> None:
        """Advance trailing state for a single trade and maybe emit SL."""
        mark_price = await self._resolve_mark_price(trade, mids_cache)
        if mark_price is None or mark_price <= 0:
            return

        side = (trade["side"] or "").lower()
        if side not in {"long", "short"}:
            return

        callback_rate = trade["trailing_callback_rate"]
        if callback_rate is None or callback_rate <= 0:
            return

        # Step 1: update highest_price in the direction of the position.
        previous_extreme = trade["highest_price"]
        new_extreme = _compute_new_extreme(side, previous_extreme, mark_price)

        # Step 2: compute the candidate SL from the extreme + callback.
        candidate_sl = _compute_candidate_sl(side, new_extreme, callback_rate)

        # Step 3: only emit when the candidate is strictly tighter than the
        # live SL. "Tighter" means closer to the current mark without
        # crossing it: higher SL for long, lower SL for short.
        current_sl = trade["stop_loss"]
        should_emit = _should_update_sl(side, current_sl, candidate_sl)

        # Persist the new highest_price regardless of whether we emit —
        # future ticks need the ratchet even when the candidate SL
        # already tracks the market.
        if new_extreme != previous_extreme or trade["risk_source"] != _RISK_SOURCE_SOFTWARE:
            await self._persist_extreme(trade["id"], new_extreme)

        if not should_emit:
            return

        logger.info(
            "risk_state.hl_trailing_trigger trade=%s new_sl=%s",
            trade["id"], candidate_sl,
            extra={
                "event_type": "risk_state",
                "trade_id": trade["id"],
                "phase": "hl_trailing",
                "outcome": "update_sl",
                "new_sl": candidate_sl,
                "previous_sl": current_sl,
                "highest_price": new_extreme,
                "mark_price": mark_price,
            },
        )

        # Route the SL update through RSM so the 2PC invariants hold.
        await self._risk_state_manager.apply_intent(
            trade["id"], RiskLeg.SL, float(candidate_sl),
        )

        # RSM's Phase-D rewrites ``risk_source='native_exchange'`` whenever a
        # confirmed order-id comes back from the readback (a reasonable
        # default for bot-driven TP/SL edits). For the software-trailing
        # emulator that is WRONG: the SL order is the *mechanism* we use to
        # emulate the trailing, but the *attribution* of the eventual close
        # must stay ``software_bot`` so ``classify_close`` returns
        # ``TRAILING_STOP_SOFTWARE``. Re-stamp after apply_intent.
        await self._persist_risk_source_software(trade["id"])

    # ── Helpers ────────────────────────────────────────────────────

    async def _load_active_trades(self) -> List[dict]:
        """Snapshot all HL trades the emulator is responsible for.

        Returns plain dicts so downstream processing can release the
        session before any potentially-slow exchange call. Filters on
        both ``trailing_intent_callback IS NOT NULL`` and
        ``trailing_status = 'confirmed'`` per the task spec.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(TradeRecord).where(
                    TradeRecord.exchange == _HL_EXCHANGE,
                    TradeRecord.status == "open",
                    TradeRecord.trailing_intent_callback.is_not(None),
                    TradeRecord.trailing_status == RiskOpStatus.CONFIRMED.value,
                )
            )
            trades = result.scalars().all()
            return [
                {
                    "id": t.id,
                    "user_id": t.user_id,
                    "demo_mode": bool(t.demo_mode),
                    "symbol": t.symbol,
                    "side": t.side,
                    "stop_loss": t.stop_loss,
                    "highest_price": t.highest_price,
                    "trailing_callback_rate": t.trailing_callback_rate,
                    "risk_source": t.risk_source,
                }
                for t in trades
            ]

    async def _resolve_mark_price(
        self,
        trade: dict,
        mids_cache: Dict[tuple, Dict[str, float]],
    ) -> Optional[float]:
        """Return the HL mark price for ``trade.symbol``.

        Caches the ``all_mids()`` response per (user_id, demo_mode) so
        a single tick does one HL read per distinct user-credential
        pair instead of one per trade. The cache is scoped to the
        tick, not persisted across calls.
        """
        cache_key = (trade["user_id"], trade["demo_mode"])
        mids = mids_cache.get(cache_key)
        if mids is None:
            client = await self._acquire_client(
                trade["user_id"], _HL_EXCHANGE, trade["demo_mode"],
            )
            info = getattr(client, "_info", None)
            if info is None:
                return None
            raw = await self._call_all_mids(client, info)
            if not isinstance(raw, dict):
                return None
            mids = {k: _safe_float(v) for k, v in raw.items() if v is not None}
            mids_cache[cache_key] = mids

        # Normalize the trade symbol to the HL coin key. HL stores plain
        # asset names ("BTC", "ETH") in ``all_mids``; the DB may carry a
        # ``BTCUSDT`` pair string.
        coin = _normalize_hl_symbol(trade["symbol"])
        return mids.get(coin)

    @staticmethod
    async def _call_all_mids(client: Any, info: Any) -> Any:
        """Call ``info.all_mids`` via the client's circuit breaker when available.

        Falls back to a direct call for test doubles that don't implement
        ``_cb_call`` — the tests stub ``_info.all_mids`` directly.
        """
        cb_call = getattr(client, "_cb_call", None)
        if cb_call is not None:
            try:
                return await cb_call(info.all_mids)
            except Exception as e:  # noqa: BLE001 — per-tick fault isolation
                logger.debug(
                    "hl_trailing_emulator.all_mids_failed error=%s", e,
                )
                return None
        result = info.all_mids()
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def _acquire_client(
        self,
        user_id: int,
        exchange: str,
        demo_mode: bool,
    ) -> Any:
        """Resolve the exchange client, supporting sync and async factories."""
        result = self._exchange_client_factory(user_id, exchange, demo_mode)
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def _persist_extreme(self, trade_id: int, new_extreme: float) -> None:
        """Persist ``highest_price`` + stamp risk_source=software_bot.

        Writing the extreme each tick is what lets state reconstruct
        after a bot restart: the emulator's next tick reads the same
        column and keeps ratcheting from there.
        """
        async with self._session_factory() as session:
            trade = await session.get(TradeRecord, trade_id)
            if trade is None:  # pragma: no cover — vanished mid-tick
                return
            trade.highest_price = new_extreme
            if trade.risk_source != _RISK_SOURCE_SOFTWARE:
                trade.risk_source = _RISK_SOURCE_SOFTWARE
            trade.last_synced_at = datetime.now(timezone.utc)
            await session.commit()

    async def _persist_risk_source_software(self, trade_id: int) -> None:
        """Stamp ``risk_source='software_bot'`` on a trade the emulator drives.

        RSM's Phase-D sets ``native_exchange`` whenever a confirmed SL
        order-id comes back. The emulator owns the attribution for HL
        trailing trades — without this re-stamp, ``classify_close`` would
        misclassify the eventual SL fire as ``STOP_LOSS_NATIVE``.
        """
        async with self._session_factory() as session:
            trade = await session.get(TradeRecord, trade_id)
            if trade is None:  # pragma: no cover — vanished between writes
                return
            if trade.risk_source != _RISK_SOURCE_SOFTWARE:
                trade.risk_source = _RISK_SOURCE_SOFTWARE
                trade.last_synced_at = datetime.now(timezone.utc)
                await session.commit()


# ── Pure-function helpers ───────────────────────────────────────────


def _compute_new_extreme(
    side: str,
    previous_extreme: Optional[float],
    mark_price: float,
) -> float:
    """Ratchet the running extreme in the direction of the position.

    Long: take the maximum of previous and mark. Short: take the minimum.
    When no previous extreme exists (first tick for this trade), seed it
    from the current mark.
    """
    if previous_extreme is None:
        return mark_price
    if side == "long":
        return max(previous_extreme, mark_price)
    return min(previous_extreme, mark_price)


def _compute_candidate_sl(
    side: str,
    extreme: float,
    callback_rate_pct: float,
) -> float:
    """Compute the trailing SL from the extreme and the callback percent.

    callback_rate_pct is expressed in percent (e.g. 1.4 means 1.4%),
    matching the :class:`TrailingStopSnapshot` convention.
    """
    fraction = float(callback_rate_pct) / 100.0
    if side == "long":
        return extreme * (1.0 - fraction)
    return extreme * (1.0 + fraction)


def _should_update_sl(
    side: str,
    current_sl: Optional[float],
    candidate_sl: float,
) -> bool:
    """True when ``candidate_sl`` is strictly tighter than ``current_sl``.

    "Tighter" for a long means *higher* (closer below the current mark);
    for a short it means *lower* (closer above the current mark). No SL
    configured yet is treated as looser than any candidate.
    """
    if current_sl is None:
        return True
    if side == "long":
        return candidate_sl > current_sl
    return candidate_sl < current_sl


def _normalize_hl_symbol(symbol: str) -> str:
    """Strip USDT/USDC/USD/PERP suffixes so ``BTCUSDT`` → ``BTC``.

    Mirrors :meth:`HyperliquidClient._normalize_symbol` without importing
    the client module (keeps the emulator import-light and test-friendly).
    """
    upper = (symbol or "").upper()
    for suffix in ("USDT", "USDC", "USD", "PERP"):
        if upper.endswith(suffix) and len(upper) > len(suffix):
            return upper[: -len(suffix)]
    return upper


def _safe_float(value: Any) -> Optional[float]:
    """Parse a possibly-stringified HL price to float; None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "HLTrailingEmulator",
    "SessionFactory",
    "ExchangeClientFactory",
]
