"""Shared trade closing logic for position monitor, rotation manager, and manual-close API.

Exposes both a standalone ``close_and_record_trade`` helper and a
``TradeCloserMixin`` for BotWorker. Both go through the same code path so
the manual-close endpoint produces the same fee/notification/WS/SSE side
effects as an automated exit (Issue #275).
"""

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from src.bot.event_bus import (
    EVENT_TRADE_CLOSED,
    build_trade_snapshot,
    publish_trade_event,
)
from src.bot.pnl import calculate_pnl
from src.models.database import BotConfig, TradeRecord
from src.models.session import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Callback signature for notification dispatch. Receives a notifier instance
# and must send the trade_exit message. Matches BotWorker._send_notification.
NotificationDispatcher = Callable[
    [Callable[[object], Awaitable[bool]], str, Optional[str]],
    Awaitable[None],
]


async def close_and_record_trade(
    trade: TradeRecord,
    exit_price: float,
    exit_reason: str,
    *,
    bot_config_id: int,
    config: BotConfig,
    risk_manager,
    send_notification: NotificationDispatcher,
    fees: Optional[float] = None,
    funding_paid: Optional[float] = None,
    builder_fee: Optional[float] = None,
    strategy_reason: Optional[str] = None,
) -> tuple[float, float]:
    """Close a trade and trigger all side effects (DB, risk, WS, SSE, notifications).

    This is the single source of truth for trade-close accounting. Both the
    BotWorker mixin path and the manual-close API route call it so they stay
    in sync for fee capture, Discord/Telegram dispatch, WebSocket broadcast
    and SSE publish.

    Returns:
        (pnl, pnl_percent) — already written to ``trade`` but returned for
        convenience so callers don't have to re-read the attribute.
    """
    log_prefix = f"[Bot:{bot_config_id}]"

    pnl, pnl_percent = calculate_pnl(
        trade.side, trade.entry_price, exit_price, trade.size
    )

    now = datetime.now(timezone.utc)

    # Update the in-memory trade object (always works, including tests)
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

    # Persist via a dedicated session to guarantee DB commit even if
    # the caller's session is stale or detached.  Falls back to the
    # in-memory update above if the DB round-trip fails (e.g. in tests).
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
        # In-memory object is already updated; the caller's session
        # commit will persist the changes if it's still active.
        logger.debug(
            "%s DB round-trip for trade #%s close failed (in-memory updated): %s",
            log_prefix, trade.id, db_err,
        )

    # Record in risk manager (may be None for manual-close when bot is stopped)
    if risk_manager is not None:
        try:
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
        except Exception as rm_err:
            logger.warning(
                "%s record_trade_exit failed for #%s: %s",
                log_prefix, trade.id, rm_err,
            )

    logger.info(
        f"{log_prefix} Trade #{trade.id} closed: {exit_reason} | "
        f"PnL: ${pnl:.2f} ({pnl_percent:+.2f}%)"
    )

    # Broadcast via WebSocket (keep reference to prevent GC)
    try:
        from src.api.websocket.manager import ws_manager
        task = asyncio.create_task(ws_manager.broadcast_to_user(
            config.user_id,
            "trade_closed",
            {
                "bot_id": bot_config_id,
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
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)
    except Exception as e:
        logger.debug("WS broadcast failed: %s", e)

    # Publish trade_closed on the SSE event bus (Issue #216 §2.2).
    # Kept distinct from the WS broadcast so the SSE trades stream stays
    # the single source of truth for the real-time trades-list view.
    try:
        publish_trade_event(
            EVENT_TRADE_CLOSED,
            user_id=config.user_id,
            trade_id=trade.id,
            data=build_trade_snapshot(trade),
        )
    except Exception as e:
        logger.debug("SSE publish failed (trade_closed): %s", e)

    # Send notifications (Discord + Telegram) via the provided dispatcher
    duration_minutes = None
    if trade.entry_time:
        # SQLite drops tzinfo on read — normalize to UTC so the subtraction
        # doesn't raise "can't subtract offset-naive and offset-aware datetimes".
        entry_dt = trade.entry_time
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        duration_minutes = int(
            (datetime.now(timezone.utc) - entry_dt).total_seconds() / 60
        )

    reason_text = strategy_reason or f"[{getattr(config, 'name', 'bot')}]"
    try:
        await send_notification(
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
            "trade_exit",
            f"{trade.side} {trade.symbol} PnL={pnl:+.2f}",
        )
    except Exception as notif_err:
        logger.warning("%s notification dispatch failed: %s", log_prefix, notif_err)

    return pnl, pnl_percent


class TradeCloserMixin:
    """Mixin providing shared trade close/record logic for BotWorker.

    Used by PositionMonitorMixin, RotationManagerMixin, and TradeExecutorMixin
    to avoid duplicating the trade record update, risk manager recording,
    WebSocket broadcast, and notification dispatch. Delegates to the
    standalone :func:`close_and_record_trade` helper so the manual-close API
    path can share the same logic without pulling in BotWorker.
    """

    async def _close_and_record_trade(
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
        """Close a trade and record the result via the shared helper."""
        await close_and_record_trade(
            trade,
            exit_price,
            exit_reason,
            bot_config_id=self.bot_config_id,
            config=self._config,
            risk_manager=self._risk_manager,
            send_notification=self._send_notification,
            fees=fees,
            funding_paid=funding_paid,
            builder_fee=builder_fee,
            strategy_reason=strategy_reason,
        )
