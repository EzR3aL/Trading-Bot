"""Exchange-position sync flow for :class:`TradesService`.

Houses ``sync_exchange_positions`` — reconciles open trades against
the exchange's open positions and closes any trade that vanished
locally so the dashboard reflects reality.

Behavior is preserved verbatim from the pre-extract router handler
(including the exception-swallowing semantics and the Discord webhook
side-effect).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select

from src.models.database import ExchangeConnection, TradeRecord
from src.services._trades_helpers import (
    _resolve_exit_reason,
    _send_sync_discord_notifications,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SyncMixin:
    """Exchange position-sync for ``TradesService``."""

    async def sync_exchange_positions(
        self,
        *,
        rsm_enabled: bool,
        decrypt_value: Callable[[str], str],
        create_exchange_client: Callable[..., Any],
        get_risk_state_manager: Callable[[], Any],
        discord_notifier_cls: Callable[..., Any],
    ):
        """Sync open trades with the exchange and close any that vanished.

        Behavior is preserved verbatim from the pre-extract handler,
        including the exception-swallowing semantics and the Discord
        webhook side-effect. All external dependencies are supplied by
        the router so its patched symbols (used by the characterization
        tests) remain the effective call targets.
        """
        from src.services.trades_service import SyncClosedTrade, SyncResult

        user_id = self.user.id

        result = await self.db.execute(
            select(TradeRecord).where(
                TradeRecord.user_id == user_id,
                TradeRecord.status == "open",
            )
        )
        open_trades = list(result.scalars().all())

        if not open_trades:
            return SyncResult(synced=0, closed_trades=[])

        trades_by_exchange: dict[str, list[TradeRecord]] = defaultdict(list)
        for trade in open_trades:
            trades_by_exchange[trade.exchange].append(trade)

        closed_trades: list[SyncClosedTrade] = []

        for exchange_type, trades in trades_by_exchange.items():
            conn_result = await self.db.execute(
                select(ExchangeConnection).where(
                    ExchangeConnection.user_id == user_id,
                    ExchangeConnection.exchange_type == exchange_type,
                )
            )
            conn = conn_result.scalar_one_or_none()
            if not conn:
                logger.warning(
                    "Sync: no connection for %s, skipping %d trades",
                    exchange_type, len(trades),
                )
                continue

            # Create exchange client (prefer demo keys, then live)
            if conn.demo_api_key_encrypted:
                api_key = decrypt_value(conn.demo_api_key_encrypted)
                api_secret = decrypt_value(conn.demo_api_secret_encrypted)
                passphrase = (
                    decrypt_value(conn.demo_passphrase_encrypted)
                    if conn.demo_passphrase_encrypted else ""
                )
                demo_mode = True
            elif conn.api_key_encrypted:
                api_key = decrypt_value(conn.api_key_encrypted)
                api_secret = decrypt_value(conn.api_secret_encrypted)
                passphrase = (
                    decrypt_value(conn.passphrase_encrypted)
                    if conn.passphrase_encrypted else ""
                )
                demo_mode = False
            else:
                continue

            client = create_exchange_client(
                exchange_type=exchange_type,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase,
                demo_mode=demo_mode,
            )

            try:
                exchange_positions = await client.get_open_positions()
                open_on_exchange = {
                    (pos.symbol, pos.side) for pos in exchange_positions
                }

                for trade in trades:
                    if (trade.symbol, trade.side) in open_on_exchange:
                        continue  # Still open on exchange

                    try:
                        # Prefer the actual close-order fill price (matches
                        # exchange exactly).
                        exit_price = None
                        try:
                            exit_price = await client.get_close_fill_price(trade.symbol)
                        except Exception:
                            pass
                        if not exit_price:
                            ticker = await client.get_ticker(trade.symbol)
                            exit_price = ticker.last_price

                        exit_time_now = datetime.now(timezone.utc)
                        exit_reason = await _resolve_exit_reason(
                            trade=trade,
                            exit_price=exit_price,
                            exit_time_now=exit_time_now,
                            rsm_enabled=rsm_enabled,
                            get_risk_state_manager=get_risk_state_manager,
                        )

                        # Calculate PnL (late import preserves the router's
                        # current side-effect ordering).
                        from src.bot.pnl import calculate_pnl
                        pnl, pnl_percent = calculate_pnl(
                            trade.side, trade.entry_price, exit_price, trade.size,
                        )

                        # Fetch trading + funding fees; non-fatal on failure.
                        try:
                            if trade.order_id:
                                trade.fees = await client.get_trade_total_fees(
                                    symbol=trade.symbol,
                                    entry_order_id=trade.order_id,
                                    close_order_id=trade.close_order_id,
                                )
                        except Exception as e:
                            logger.warning(
                                "Failed to fetch trading fees for trade %s: %s",
                                trade.id, e,
                            )

                        try:
                            if trade.entry_time:
                                entry_ms = int(trade.entry_time.timestamp() * 1000)
                                exit_ms = int(
                                    datetime.now(timezone.utc).timestamp() * 1000
                                )
                                trade.funding_paid = await client.get_funding_fees(
                                    symbol=trade.symbol,
                                    start_time_ms=entry_ms,
                                    end_time_ms=exit_ms,
                                )
                        except Exception as e:
                            logger.warning(
                                "Failed to fetch funding fees for trade %s: %s",
                                trade.id, e,
                            )

                        # Apply the close to the ORM row
                        trade.status = "closed"
                        trade.exit_price = exit_price
                        trade.pnl = round(pnl, 4)
                        trade.pnl_percent = round(pnl_percent, 2)
                        trade.exit_time = exit_time_now
                        trade.exit_reason = exit_reason

                        # When RSM is active, reconcile the trade so per-leg
                        # status columns reflect the post-close exchange state.
                        # Failure is non-fatal — the close is already staged.
                        if rsm_enabled:
                            try:
                                await self.db.flush()
                                await get_risk_state_manager().reconcile(trade.id)
                            except Exception as rec_err:  # noqa: BLE001
                                logger.warning(
                                    "Sync: reconcile failed for trade %s: %s",
                                    trade.id, rec_err,
                                )

                        closed_trades.append(SyncClosedTrade(
                            id=trade.id,
                            symbol=trade.symbol,
                            side=trade.side,
                            exit_price=exit_price,
                            pnl=round(pnl, 2),
                            exit_reason=exit_reason,
                        ))

                        logger.info(
                            "Sync: closed trade #%s %s %s | %s | PnL: $%.2f (%+.2f%%)",
                            trade.id, trade.symbol, trade.side,
                            exit_reason, pnl, pnl_percent,
                        )
                    except Exception as e:
                        logger.error(
                            "Sync: failed to close trade #%s: %s", trade.id, e,
                        )

            except Exception as e:
                logger.error(
                    "Sync: failed to query %s positions: %s", exchange_type, e,
                )
            finally:
                await client.close()

        await self.db.flush()

        if closed_trades:
            await _send_sync_discord_notifications(
                db=self.db,
                user_id=user_id,
                open_trades=open_trades,
                closed_trades=closed_trades,
                decrypt_value=decrypt_value,
                discord_notifier_cls=discord_notifier_cls,
            )

        return SyncResult(synced=len(closed_trades), closed_trades=closed_trades)
