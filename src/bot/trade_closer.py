"""Shared trade closing logic for position monitor and rotation manager."""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from src.bot.pnl import calculate_pnl
from src.models.database import TradeRecord
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeCloserMixin:
    """Mixin providing shared trade close/record logic.

    Used by both PositionMonitorMixin and RotationManagerMixin to avoid
    duplicating the trade record update, risk manager recording,
    WebSocket broadcast, and notification dispatch.
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
        """Close a trade and record the result.

        Updates the TradeRecord in-place (caller must hold the DB session),
        records the exit in the risk manager, broadcasts via WebSocket,
        and sends notifications (Discord/Telegram).

        Args:
            trade: The open TradeRecord to close.
            exit_price: The price at which the trade was closed.
            exit_reason: Why the trade was closed (e.g. TAKE_PROFIT, ROTATION).
            fees: Trading fees (default: keep existing trade.fees).
            funding_paid: Funding fees (default: keep existing trade.funding_paid).
            builder_fee: Builder fee for Hyperliquid (default: keep existing).
            strategy_reason: Human-readable reason for notifications.
        """
        log_prefix = f"[Bot:{self.bot_config_id}]"

        pnl, pnl_percent = calculate_pnl(
            trade.side, trade.entry_price, exit_price, trade.size
        )

        # Update trade record fields
        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.pnl_percent = pnl_percent
        trade.exit_time = datetime.now(timezone.utc)
        trade.exit_reason = exit_reason
        trade.status = "closed"

        if fees is not None:
            trade.fees = fees
        if funding_paid is not None:
            trade.funding_paid = funding_paid
        if builder_fee is not None:
            trade.builder_fee = builder_fee

        # Record in risk manager
        self._risk_manager.record_trade_exit(
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

        # Broadcast via WebSocket
        try:
            from src.api.websocket.manager import ws_manager
            asyncio.create_task(ws_manager.broadcast_to_user(
                self._config.user_id,
                "trade_closed",
                {
                    "bot_id": self.bot_config_id,
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
        except Exception as e:
            logger.debug("WS broadcast failed: %s", e)

        # Send notifications (Discord + Telegram)
        duration_minutes = None
        if trade.entry_time:
            duration_minutes = int(
                (datetime.now(timezone.utc) - trade.entry_time).total_seconds() / 60
            )

        reason_text = strategy_reason or f"[{self._config.name}]"
        await self._send_notification(lambda n: n.send_trade_exit(
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
        ))
