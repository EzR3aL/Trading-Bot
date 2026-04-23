"""Shared trade closing logic for position monitor, rotation manager, and manual-close API.

Two entry points:

* ``close_and_record_trade`` — module-level helper used by the manual-close
  API route (#275). No BotWorker required; caller passes config, risk
  manager, and a notification dispatcher explicitly. Keeps the DB /
  WebSocket / SSE / notification side effects identical to the BotWorker
  path so manual closes are accounted the same way as automatic ones.

* ``TradeCloserMixin`` — thin proxy on BotWorker delegating to the
  composition-owned ``TradeCloser`` component
  (``src.bot.components.trade_closer.TradeCloser``). The mixin is kept
  for compatibility with existing call sites (``self._close_and_record_trade``)
  during the ARCH-H1 composition migration; it will be dropped in the
  Phase 1 finalize PR.
"""

from __future__ import annotations

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

    Used by the manual-close API path where no BotWorker is available.
    Returns ``(pnl, pnl_percent)`` — already written to ``trade``.
    """
    log_prefix = f"[Bot:{bot_config_id}]"

    pnl, pnl_percent = calculate_pnl(
        trade.side, trade.entry_price, exit_price, trade.size
    )

    now = datetime.now(timezone.utc)

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

    try:
        publish_trade_event(
            EVENT_TRADE_CLOSED,
            user_id=config.user_id,
            trade_id=trade.id,
            data=build_trade_snapshot(trade),
        )
    except Exception as e:
        logger.debug("SSE publish failed (trade_closed): %s", e)

    duration_minutes = None
    if trade.entry_time:
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
    """Proxies the close-and-record call to the composition-owned ``TradeCloser``."""

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
        await self._trade_closer.close_and_record(
            trade,
            exit_price,
            exit_reason,
            fees=fees,
            funding_paid=funding_paid,
            builder_fee=builder_fee,
            strategy_reason=strategy_reason,
        )
