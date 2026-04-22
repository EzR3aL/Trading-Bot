"""Trade-close orchestration (ARCH-H1 Phase 1 PR-3, #279).

Extracted from ``TradeCloserMixin`` so the close-and-record flow is
composition-owned and independently testable. The mixin is kept as a
thin proxy until the Phase 1 finalize PR removes all mixin shims.

A single method ``close_and_record`` does the full end-to-end close:
1. Update the in-memory ``TradeRecord`` fields (pnl, exit_price, …).
2. Persist via a dedicated session (idempotent guard: only close if
   the DB row is still ``open``).
3. Record the exit on the injected ``RiskManager``.
4. Broadcast ``trade_closed`` on the WebSocket manager.
5. Publish the same event on the SSE event bus.
6. Send exit notifications via the injected notification sender.

The component does NOT own the risk manager or the notification
sender — those are injected via getters/callables because they are
attached to ``BotWorker`` at different lifecycle points (``_risk_manager``
is set during ``initialize()``; ``_send_notification`` is a bound method
from the notification mixin/component).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from src.bot.event_bus import (
    EVENT_TRADE_CLOSED,
    build_trade_snapshot,
    publish_trade_event,
)
from src.bot.pnl import calculate_pnl
from src.models.database import TradeRecord
from src.models.session import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeCloser:
    """Closes a trade, persists the result, and fires out-of-band side effects.

    Dependencies are supplied as callables so the component tolerates the
    deferred lifecycle of ``BotWorker`` (config and risk-manager are only
    attached after ``initialize()`` runs, long after ``__init__``).
    """

    def __init__(
        self,
        bot_config_id: int,
        config_getter: Callable[[], Optional[Any]],
        risk_manager_getter: Callable[[], Any],
        notification_sender: Callable[..., Awaitable[None]],
    ) -> None:
        self._bot_config_id = bot_config_id
        self._get_config = config_getter
        self._get_risk_manager = risk_manager_getter
        self._send_notification = notification_sender

    async def close_and_record(
        self,
        trade: TradeRecord,
        exit_price: float,
        exit_reason: str,
        *,
        fees: Optional[float] = None,
        funding_paid: Optional[float] = None,
        builder_fee: Optional[float] = None,
        strategy_reason: Optional[str] = None,
    ) -> None:
        log_prefix = f"[Bot:{self._bot_config_id}]"

        pnl, pnl_percent = calculate_pnl(
            trade.side, trade.entry_price, exit_price, trade.size
        )
        now = datetime.now(timezone.utc)

        # Update in-memory trade (always works, including tests).
        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.pnl_percent = pnl_percent
        trade.exit_time = now
        trade.exit_reason = exit_reason
        trade.status = "closed"
        if fees is not None:
            trade.fees = fees
        if funding_paid is not None:
            trade.funding_paid = funding_paid
        if builder_fee is not None:
            trade.builder_fee = builder_fee

        # Persist via dedicated session — guarantees commit even if the
        # caller's session is stale/detached.
        try:
            async with get_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(TradeRecord).where(TradeRecord.id == trade.id)
                )
                db_trade = result.scalar_one_or_none()
                if db_trade is not None and db_trade.status != "closed":
                    db_trade.exit_price = exit_price
                    db_trade.pnl = pnl
                    db_trade.pnl_percent = pnl_percent
                    db_trade.exit_time = now
                    db_trade.exit_reason = exit_reason
                    db_trade.status = "closed"
                    if fees is not None:
                        db_trade.fees = fees
                    if funding_paid is not None:
                        db_trade.funding_paid = funding_paid
                    if builder_fee is not None:
                        db_trade.builder_fee = builder_fee
        except Exception as db_err:
            logger.debug(
                "%s DB round-trip for trade #%s close failed (in-memory updated): %s",
                log_prefix, trade.id, db_err,
            )

        # Record in risk manager.
        risk_manager = self._get_risk_manager()
        risk_manager.record_trade_exit(
            symbol=trade.symbol,
            side=trade.side,
            size=trade.size,
            entry_price=trade.entry_price,
            exit_price=exit_price,
            fees=trade.fees or 0,
            funding_paid=trade.funding_paid or 0,
            reason=exit_reason,
            order_id=trade.order_id,
        )

        logger.info(
            f"{log_prefix} Trade #{trade.id} closed: {exit_reason} | "
            f"PnL: ${pnl:.2f} ({pnl_percent:+.2f}%)"
        )

        config = self._get_config()
        user_id = getattr(config, "user_id", None) if config else None

        # WebSocket broadcast (keep reference to prevent GC).
        if user_id is not None:
            try:
                from src.api.websocket.manager import ws_manager
                task = asyncio.create_task(ws_manager.broadcast_to_user(
                    user_id,
                    "trade_closed",
                    {
                        "bot_id": self._bot_config_id,
                        "trade_id": trade.id,
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "entry_price": trade.entry_price,
                        "exit_price": exit_price,
                        "pnl": pnl,
                        "pnl_percent": pnl_percent,
                        "exit_reason": exit_reason,
                        "demo_mode": trade.demo_mode,
                    },
                ))
                task.add_done_callback(
                    lambda t: t.exception() if not t.cancelled() and t.exception() else None
                )
            except Exception as e:
                logger.debug("WS broadcast failed: %s", e)

        # SSE event (distinct from the WS broadcast — single source of truth
        # for the real-time trades-list view).
        if user_id is not None:
            try:
                publish_trade_event(
                    EVENT_TRADE_CLOSED,
                    user_id=user_id,
                    trade_id=trade.id,
                    data=build_trade_snapshot(trade),
                )
            except Exception as e:
                logger.debug("SSE publish failed (trade_closed): %s", e)

        # Notifications (Discord + Telegram) via the injected sender.
        duration_minutes: Optional[int] = None
        if trade.entry_time:
            duration_minutes = int(
                (datetime.now(timezone.utc) - trade.entry_time).total_seconds() / 60
            )

        config_name = getattr(config, "name", "") if config else ""
        reason_text = strategy_reason or f"[{config_name}]"
        await self._send_notification(
            lambda n: n.send_trade_exit(
                symbol=trade.symbol,
                side=trade.side,
                size=trade.size,
                entry_price=trade.entry_price,
                exit_price=exit_price,
                pnl=pnl,
                pnl_percent=pnl_percent,
                fees=trade.fees or 0,
                funding_paid=trade.funding_paid or 0,
                reason=exit_reason,
                order_id=trade.order_id or "",
                duration_minutes=duration_minutes,
                demo_mode=trade.demo_mode,
                strategy_reason=reason_text,
            ),
            event_type="trade_exit",
            summary=f"{trade.side} {trade.symbol} PnL={pnl:+.2f}",
        )
