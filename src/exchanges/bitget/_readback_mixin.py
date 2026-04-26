"""Risk-state readback probes for the Bitget client (#191).

These methods are the source-of-truth probes used by ``RiskStateManager``
to reconcile DB state against the exchange. They return either a typed
snapshot (``PositionTpSlSnapshot``, ``TrailingStopSnapshot``,
``CloseReasonSnapshot``) or ``None`` when nothing matches. Genuine API
errors propagate as :class:`ExchangeError`; "no plan found" is NOT an
error.

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.exceptions import ExchangeError
from src.exchanges.base import (
    CloseReasonSnapshot,
    PositionTpSlSnapshot,
    TrailingStopSnapshot,
)
from src.exchanges.bitget._helpers import (
    _bitget_order_source_to_plan_type,
    _parse_float,
    _parse_int,
    _ts_to_datetime,
)
from src.exchanges.bitget.constants import ENDPOINTS, PRODUCT_TYPE_USDT
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BitgetReadbackMixin:
    """Risk-state readback probes (#191) used by :class:`BitgetExchangeClient`."""

    @staticmethod
    def _bitget_plans(payload: Any) -> List[Dict[str, Any]]:
        """Extract the list of plan dicts from a Bitget plan-order response."""
        if isinstance(payload, dict):
            entries = payload.get("entrustedList")
            if isinstance(entries, list):
                return entries
            return []
        if isinstance(payload, list):
            return payload
        return []

    async def get_position_tpsl(
        self, symbol: str, side: str
    ) -> PositionTpSlSnapshot:
        """Read live position-level TP/SL from Bitget plan orders.

        Queries plan-orders with ``planType=profit_loss`` (returns both
        ``pos_profit`` and ``pos_loss`` plans), then filters by ``holdSide``.
        Empty snapshot when no plans match the position.
        """
        empty = PositionTpSlSnapshot(
            symbol=symbol,
            side=side,
            tp_price=None,
            tp_order_id=None,
            tp_trigger_type=None,
            sl_price=None,
            sl_order_id=None,
            sl_trigger_type=None,
        )

        payload = await self._request(
            "GET",
            "/api/v2/mix/order/orders-plan-pending",
            params={
                "productType": PRODUCT_TYPE_USDT,
                "symbol": symbol,
                "planType": "profit_loss",
            },
            auth=True,
        )

        plans = self._bitget_plans(payload)
        if not plans:
            return empty

        side_norm = side.lower()
        tp_plan: Optional[Dict[str, Any]] = None
        sl_plan: Optional[Dict[str, Any]] = None
        for plan in plans:
            hold_side = (plan.get("holdSide") or plan.get("posSide") or "").lower()
            if hold_side and hold_side != side_norm:
                continue
            plan_type = (plan.get("planType") or "").lower()
            if plan_type == "pos_profit" and tp_plan is None:
                tp_plan = plan
            elif plan_type == "pos_loss" and sl_plan is None:
                sl_plan = plan

        return PositionTpSlSnapshot(
            symbol=symbol,
            side=side,
            tp_price=_parse_float(tp_plan.get("executePrice") or tp_plan.get("triggerPrice")) if tp_plan else None,
            tp_order_id=str(tp_plan.get("orderId")) if tp_plan and tp_plan.get("orderId") else None,
            tp_trigger_type=tp_plan.get("triggerType") if tp_plan else None,
            sl_price=_parse_float(sl_plan.get("executePrice") or sl_plan.get("triggerPrice")) if sl_plan else None,
            sl_order_id=str(sl_plan.get("orderId")) if sl_plan and sl_plan.get("orderId") else None,
            sl_trigger_type=sl_plan.get("triggerType") if sl_plan else None,
        )

    async def get_trailing_stop(
        self, symbol: str, side: str
    ) -> Optional[TrailingStopSnapshot]:
        """Read the live ``moving_plan`` (trailing stop) from Bitget plan orders.

        Bitget groups position-level trailing stops under ``planType=moving_plan``
        and exposes them via the TPSL plan list (``planType=profit_loss``).
        Querying ``planType=moving_plan`` directly returns HTTP 400 ``planType
        is not met``, so we fetch the umbrella ``profit_loss`` list and filter
        locally — same pattern as :meth:`has_native_trailing_stop`.

        Returns ``None`` if no trailing plan exists. If multiple plans exist
        (should not happen in practice), warns and returns the newest by
        creation time.
        """
        payload = await self._request(
            "GET",
            "/api/v2/mix/order/orders-plan-pending",
            params={
                "productType": PRODUCT_TYPE_USDT,
                "symbol": symbol,
                "planType": "profit_loss",
            },
            auth=True,
        )

        side_norm = side.lower()
        plans = [
            p for p in self._bitget_plans(payload)
            if (p.get("planType") or "").lower() == "moving_plan"
            and (
                (p.get("holdSide") or p.get("posSide") or "").lower() in ("", side_norm)
            )
        ]
        if not plans:
            return None

        if len(plans) > 1:
            logger.warning(
                "Bitget %s %s has %d active track_plan entries; using newest",
                symbol, side, len(plans),
            )
            plans.sort(key=lambda p: int(p.get("cTime") or p.get("createTime") or 0), reverse=True)

        plan = plans[0]
        callback_ratio = _parse_float(plan.get("callbackRatio"))
        # Bitget returns ``callbackRatio`` as an already-percent string
        # ("2.5" = 2.5 %). A previous comment claimed it was a decimal
        # and the code multiplied by 100 — verified live against Bitget
        # demo it returns the same percent value that we sent in via
        # ``rangeRate``, so no scaling is needed.
        callback_rate = round(callback_ratio, 4) if callback_ratio is not None else None

        # Bitget exposes activation via ``triggerPrice``. The running trail
        # level is not reliably surfaced in the plan endpoint, so
        # trigger_price stays None unless the plan dict explicitly carries
        # a ``presetStopPrice`` / ``executePrice`` field (rare).
        return TrailingStopSnapshot(
            symbol=symbol,
            side=side,
            callback_rate=callback_rate,
            activation_price=_parse_float(plan.get("triggerPrice")),
            trigger_price=_parse_float(plan.get("presetStopPrice") or plan.get("executePrice")),
            order_id=str(plan.get("orderId")) if plan.get("orderId") else None,
        )

    async def get_close_reason_from_history(
        self,
        symbol: str,
        since_ts_ms: int,
        until_ts_ms: Optional[int] = None,
    ) -> Optional[CloseReasonSnapshot]:
        """Find the most recent close event for ``symbol`` in the time window.

        Searches:
          1. orders-plan-history for triggered TP/SL/trailing plans
             (planType in pos_profit/pos_loss/track_plan).
          2. orders-history for reduce-only manual market closes.

        Returns the newest event across both sources, or ``None`` when nothing
        qualifies. A failure on one source does not suppress the other — a
        triggered SL found via plan-history must not be hidden because the
        manual-close endpoint returned an error (or vice versa).

        ``until_ts_ms`` bounds the window on the right; when absent we look
        up to "now". Bounding is essential for backfilling historical trades
        so that a newer close on the same symbol does not leak into an older
        trade's lookup.
        """
        plan_event: Optional[CloseReasonSnapshot] = None
        manual_event: Optional[CloseReasonSnapshot] = None

        try:
            plan_event = await self._fetch_bitget_plan_close(
                symbol, since_ts_ms, until_ts_ms,
            )
        except ExchangeError as e:
            logger.warning(
                "bitget.plan_close_probe_failed symbol=%s error=%s",
                symbol, e,
            )

        try:
            manual_event = await self._fetch_bitget_manual_close(
                symbol, since_ts_ms, until_ts_ms,
            )
        except ExchangeError as e:
            logger.warning(
                "bitget.manual_close_probe_failed symbol=%s error=%s",
                symbol, e,
            )

        candidates = [e for e in (plan_event, manual_event) if e is not None]
        if not candidates:
            return None

        # Pick newest by closed_at (fall back to None-as-oldest)
        candidates.sort(
            key=lambda e: e.closed_at or datetime.fromtimestamp(0, tz=timezone.utc),
            reverse=True,
        )
        return candidates[0]

    async def _fetch_bitget_plan_close(
        self,
        symbol: str,
        since_ts_ms: int,
        until_ts_ms: Optional[int] = None,
    ) -> Optional[CloseReasonSnapshot]:
        """Find the newest triggered TP/SL/trailing plan in the time window.

        Bitget v2 ``/api/v2/mix/order/orders-plan-history`` requires both
        ``planType`` and a closed ``startTime``/``endTime`` range. We use
        ``planType=profit_loss`` — the umbrella that returns plans whose
        concrete type is ``pos_profit`` (TP), ``pos_loss`` (SL) or
        ``track_plan`` (trailing) in the response. Triggered plans come
        back with ``planStatus=executed``; cancelled ones with
        ``cancelled``. The legacy ``triggered`` string is kept as a fallback
        in case Bitget re-labels a subset of plan types later.
        """
        end_ts_ms = until_ts_ms if until_ts_ms is not None else int(time.time() * 1000)
        payload = await self._request(
            "GET",
            "/api/v2/mix/order/orders-plan-history",
            params={
                "productType": PRODUCT_TYPE_USDT,
                "symbol": symbol,
                "planType": "profit_loss",
                "startTime": str(since_ts_ms),
                "endTime": str(end_ts_ms),
            },
            auth=True,
        )
        plans = self._bitget_plans(payload)
        # Bitget v2 orders-plan-history honors startTime for filtering but
        # not endTime — rows with uTime > endTime still appear in the
        # response. Filter client-side so backfilling an old trade does not
        # pick up a newer close on the same symbol.
        executed = [
            p for p in plans
            if (p.get("planStatus") or p.get("state") or "").lower()
            in {"executed", "triggered"}
            and int(p.get("uTime") or p.get("updateTime") or p.get("cTime") or 0) <= end_ts_ms
        ]
        if not executed:
            return None

        executed.sort(
            key=lambda p: int(p.get("uTime") or p.get("updateTime") or p.get("cTime") or 0),
            reverse=True,
        )
        plan = executed[0]
        plan_type = (plan.get("planType") or "").lower() or None
        ts_ms = _parse_int(plan.get("uTime") or plan.get("updateTime") or plan.get("cTime"))
        # Triggered plans produce a child execute order — that id is the
        # one that appears as the fill in orders-history and is what
        # TradeRecord.close_order_id should end up storing. Prefer it over
        # the plan's own orderId (which is the plan definition, not the fill).
        execute_oid = plan.get("executeOrderId") or plan.get("orderId")
        return CloseReasonSnapshot(
            symbol=symbol,
            closed_by_order_id=str(execute_oid) if execute_oid else None,
            closed_by_plan_type=plan_type,
            closed_by_trigger_type=plan.get("triggerType"),
            closed_at=_ts_to_datetime(ts_ms),
            fill_price=_parse_float(plan.get("executePrice") or plan.get("priceAvg")),
        )

    async def _fetch_bitget_manual_close(
        self,
        symbol: str,
        since_ts_ms: int,
        until_ts_ms: Optional[int] = None,
    ) -> Optional[CloseReasonSnapshot]:
        """Find the newest filled reduce-only market close in the time window.

        Bitget's ``orders-history`` response encodes the trigger source in
        ``orderSource`` — e.g. ``pos_loss_market``, ``pos_profit_market``,
        ``track_plan_market`` for plan-triggered closes, or bare ``market``
        for a plain reduce-only market close. We use this to distinguish
        user-driven manual closes from plan-triggered ones when
        ``orders-plan-history`` missed the row (edge cases such as
        plans that execute but get GC'd from the plan-history before we probe).
        """
        end_ts_ms = until_ts_ms if until_ts_ms is not None else int(time.time() * 1000)
        payload = await self._request(
            "GET",
            ENDPOINTS["orders_history"],
            params={
                "productType": PRODUCT_TYPE_USDT,
                "symbol": symbol,
                "startTime": str(since_ts_ms),
                "endTime": str(end_ts_ms),
            },
            auth=True,
        )
        orders = (
            payload.get("entrustedList") or payload.get("orderList") or payload
            if isinstance(payload, dict) else payload
        )
        if not isinstance(orders, list):
            return None

        # Order history is returned newest-first, but be explicit: sort by
        # uTime descending so the first match wins regardless of upstream order.
        # Also enforce end-of-window client-side — Bitget's endTime param is
        # advisory and the response may include rows past it.
        sorted_orders = sorted(
            (
                o for o in orders
                if isinstance(o, dict)
                and int(o.get("uTime") or o.get("cTime") or 0) <= end_ts_ms
            ),
            key=lambda o: int(o.get("uTime") or o.get("cTime") or 0),
            reverse=True,
        )

        for order in sorted_orders:
            trade_side = (order.get("tradeSide") or "").lower()
            order_type = (order.get("orderType") or "").lower()
            status = (order.get("state") or order.get("status") or "").lower()
            if "close" not in trade_side:
                continue
            if status != "filled":
                continue
            if order_type and order_type != "market":
                continue
            ts_ms = _parse_int(order.get("uTime") or order.get("cTime"))
            # Bitget encodes the trigger origin in ``orderSource``. A close
            # originating from a triggered TP/SL/trailing plan comes back as
            # ``pos_profit_market`` / ``pos_loss_market`` / ``track_plan_market``
            # — even if plan-history has already rotated the plan row out. A
            # bare ``market`` source means a user- or bot-driven reduce-only
            # market close. Mapping this back to the canonical plan_type keys
            # lets the classifier route to the correct ExitReason without a
            # second round-trip.
            order_source = (order.get("orderSource") or "").lower()
            plan_type = _bitget_order_source_to_plan_type(order_source)
            return CloseReasonSnapshot(
                symbol=symbol,
                closed_by_order_id=str(order.get("orderId")) if order.get("orderId") else None,
                closed_by_plan_type=plan_type,
                closed_by_trigger_type=None,
                closed_at=_ts_to_datetime(ts_ms),
                fill_price=_parse_float(order.get("priceAvg") or order.get("fillPrice")),
            )
        return None
