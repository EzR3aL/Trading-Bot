"""Risk-state snapshot operations for :class:`TradesService`.

Houses ``get_risk_state_snapshot`` — the read-only path that reconciles
a trade's TP/SL/trailing legs against the exchange and returns a
FastAPI-free snapshot for the router to project onto its response model.
"""

from __future__ import annotations

from sqlalchemy import select

from src.bot.risk_state_manager import RiskOpStatus, RiskStateManager
from src.models.database import TradeRecord
from src.services._trades_helpers import _leg_dict_to_snapshot
from src.services.exceptions import TradeNotFound


class RiskSnapshotMixin:
    """Risk-state reconcile/readback for ``TradesService``."""

    async def get_risk_state_snapshot(
        self,
        trade_id: int,
        manager: RiskStateManager,
    ):
        """Return the post-readback risk-state snapshot for a trade.

        The caller (router) owns the feature-flag gate; this method runs
        under the assumption the flag is on. Ownership is enforced before
        :meth:`RiskStateManager.reconcile` is invoked so another user's
        trade is never leaked through a reconcile side-effect.

        Raises:
            TradeNotFound: when the trade does not exist, is not owned by
                ``self.user``, or when ``reconcile`` reports the row
                vanished mid-flight (``ValueError``).
        """
        from src.services.trades_service import RiskStateSnapshotResult

        user_id = self.user.id

        trade_result = await self.db.execute(
            select(TradeRecord).where(
                TradeRecord.id == trade_id,
                TradeRecord.user_id == user_id,
            )
        )
        trade = trade_result.scalar_one_or_none()
        if trade is None:
            raise TradeNotFound(trade_id)

        try:
            snapshot = await manager.reconcile(trade_id)
        except ValueError as exc:
            # reconcile() raises ValueError when the row vanishes mid-flight;
            # surface it to the router so the generic 404 mapping fires
            # with the exchange's error message preserved.
            raise TradeNotFound(str(exc)) from exc

        tp_snap = _leg_dict_to_snapshot(snapshot.tp)
        sl_snap = _leg_dict_to_snapshot(snapshot.sl)
        trailing_snap = _leg_dict_to_snapshot(snapshot.trailing)

        # A pure readback never writes, so overall is "all_confirmed"
        # (native orders are in place) or "no_change" (nothing attached).
        any_confirmed = any(
            s is not None and s.status == RiskOpStatus.CONFIRMED.value
            for s in (tp_snap, sl_snap, trailing_snap)
        )
        overall = "all_confirmed" if any_confirmed else "no_change"

        return RiskStateSnapshotResult(
            trade_id=trade_id,
            tp=tp_snap,
            sl=sl_snap,
            trailing=trailing_snap,
            applied_at=snapshot.last_synced_at,
            overall_status=overall,
        )
