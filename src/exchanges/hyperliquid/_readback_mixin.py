"""Risk-state readback (#191) for the Hyperliquid client.

Source-of-truth probes used by ``RiskStateManager`` to reconcile DB state
against what is actually live on Hyperliquid:

* :meth:`get_position_tpsl` — position-level TP/SL triggers
* :meth:`get_trailing_stop` — always ``None``; HL has no native trailing
* :meth:`get_close_reason_from_history` — derives close reason from fills

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.exchanges.base import (
    CloseReasonSnapshot,
    PositionTpSlSnapshot,
    TrailingStopSnapshot,
)
from src.exchanges.hyperliquid._helpers import _hl_float, _hl_int, _hl_ts_to_datetime
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HyperliquidReadbackMixin:
    """Risk-state readback API (#191) used by :class:`HyperliquidClient`.

    HL exposes position-level TP/SL as ``isPositionTpsl`` triggers on
    ``frontendOpenOrders``. There is NO native trailing-stop primitive on
    HL, so :meth:`get_trailing_stop` always returns ``None`` — callers
    should rely on software trailing instead.
    """

    async def get_position_tpsl(
        self, symbol: str, side: str
    ) -> PositionTpSlSnapshot:
        """Read live position-level TP/SL triggers from Hyperliquid.

        Queries frontendOpenOrders for the user, filters entries where
        ``isTrigger=true`` (or ``isPositionTpsl=true``) and the coin
        matches. Classifies into TP vs SL by ``orderType`` string.
        """
        coin = self._normalize_symbol(symbol)
        empty = PositionTpSlSnapshot(
            symbol=coin,
            side=side,
            tp_price=None,
            tp_order_id=None,
            tp_trigger_type=None,
            sl_price=None,
            sl_order_id=None,
            sl_trigger_type=None,
        )

        address = (self.wallet_address or self._wallet.address).lower()
        raw = await self._cb_call(self._info_exec.frontend_open_orders, address)
        if not isinstance(raw, list):
            return empty

        # Closing direction is opposite of position side.
        # long position → close via sell (is_buy=False on HL)
        close_is_buy = side.lower() != "long"

        tp_order: Optional[Dict[str, Any]] = None
        sl_order: Optional[Dict[str, Any]] = None
        for order in raw:
            if not isinstance(order, dict):
                continue
            if order.get("coin") != coin:
                continue
            is_trigger = bool(order.get("isTrigger") or order.get("isPositionTpsl"))
            if not is_trigger:
                continue
            # Side filter: TP/SL for a LONG position are SELL orders on HL.
            side_field = str(order.get("side", "")).upper()
            if side_field == "B":
                order_is_buy = True
            elif side_field == "A":
                order_is_buy = False
            else:
                # Unknown side format — don't filter it out, accept all.
                order_is_buy = close_is_buy

            if order_is_buy != close_is_buy:
                continue

            order_type = str(order.get("orderType") or "").lower()
            if ("tp" in order_type or "take" in order_type) and tp_order is None:
                tp_order = order
            elif ("sl" in order_type or "stop" in order_type) and sl_order is None:
                sl_order = order

        trigger_type = "mark_price"  # HL trigger prices are mark-price based
        return PositionTpSlSnapshot(
            symbol=coin,
            side=side,
            tp_price=_hl_float(tp_order.get("triggerPx") or tp_order.get("limitPx")) if tp_order else None,
            tp_order_id=str(tp_order.get("oid")) if tp_order and tp_order.get("oid") is not None else None,
            tp_trigger_type=trigger_type if tp_order else None,
            sl_price=_hl_float(sl_order.get("triggerPx") or sl_order.get("limitPx")) if sl_order else None,
            sl_order_id=str(sl_order.get("oid")) if sl_order and sl_order.get("oid") is not None else None,
            sl_trigger_type=trigger_type if sl_order else None,
        )

    async def get_trailing_stop(
        self, symbol: str, side: str
    ) -> Optional[TrailingStopSnapshot]:
        """Hyperliquid has no native trailing-stop primitive.

        Returns ``None`` unconditionally. Callers fall back to the
        software trailing loop in ``strategy.should_exit``.
        """
        logger.debug(
            "Hyperliquid has no native trailing stop — get_trailing_stop returns None"
        )
        return None

    async def get_close_reason_from_history(
        self,
        symbol: str,
        since_ts_ms: int,
        until_ts_ms: Optional[int] = None,
    ) -> Optional[CloseReasonSnapshot]:
        """Find the most recent close fill for ``symbol`` in the time window.

        Inspects ``user_fills`` and picks the newest reduce-only close fill.
        Hyperliquid encodes the close reason in the fill's ``dir`` field
        (e.g. "Close Long", "Close Short") plus a ``liquidation`` flag.

        A transient SDK failure in ``user_fills`` is isolated so the outer
        ``get_close_reason_from_history`` surface still returns ``None``
        rather than bubbling — caller's heuristic fallback then runs
        (Pattern C mitigation per #224).

        ``until_ts_ms`` bounds the right end of the window for backfill
        use; HL's ``user_fills`` has no server-side time filter, so the
        bound is enforced client-side (per #221 pattern).
        """
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        try:
            fills = await self._cb_call(self._info_exec.user_fills, address)
        except Exception as e:  # noqa: BLE001 — isolate probe failures per anti-pattern C
            logger.warning(
                "hyperliquid.close_reason_probe_failed coin=%s error=%s",
                coin, e,
            )
            return None
        if not isinstance(fills, list):
            return None

        qualifying: List[Dict[str, Any]] = []
        for fill in fills:
            if not isinstance(fill, dict):
                continue
            if fill.get("coin") != coin:
                continue
            ts = _hl_int(fill.get("time"))
            if ts is not None and ts < since_ts_ms:
                continue
            if ts is not None and until_ts_ms is not None and ts > until_ts_ms:
                continue
            direction = str(fill.get("dir") or "")
            # Close fills: "Close Long", "Close Short", "Liquidated Long", etc.
            if direction.startswith("Close") or "Liquidat" in direction:
                qualifying.append(fill)

        if not qualifying:
            return None

        qualifying.sort(key=lambda f: _hl_int(f.get("time")) or 0, reverse=True)
        fill = qualifying[0]

        if fill.get("liquidation") or "Liquidat" in str(fill.get("dir", "")):
            plan_type = "liquidation"
        elif fill.get("isTpsl") or fill.get("isPositionTpsl"):
            # HL marks TP/SL fills but doesn't distinguish TP vs SL at the
            # fill level. ``tpsl_ambiguous`` is a sentinel plan_type that
            # tells RiskStateManager._classify_from_snapshot to try order-id
            # matching (authoritative) first, then price-crossover against
            # trade.take_profit / trade.stop_loss as a tiebreaker. See
            # _PLAN_TYPE_TO_REASON for the mapping.
            plan_type = "tpsl_ambiguous"
        else:
            plan_type = "manual"

        ts_ms = _hl_int(fill.get("time"))
        return CloseReasonSnapshot(
            symbol=coin,
            closed_by_order_id=str(fill.get("oid")) if fill.get("oid") is not None else None,
            closed_by_plan_type=plan_type,
            closed_by_trigger_type="mark_price" if plan_type in ("pos_profit", "pos_loss", "tpsl_ambiguous") else None,
            closed_at=_hl_ts_to_datetime(ts_ms),
            fill_price=_hl_float(fill.get("px")),
        )
