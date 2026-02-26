"""Position monitoring logic for BotWorker (mixin)."""

import json
from datetime import datetime, timezone

from src.exchanges.base import ExchangeClient
from src.models.database import TradeRecord
from src.models.session import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PositionMonitorMixin:
    """Mixin providing position monitoring methods for BotWorker."""

    async def _monitor_positions_safe(self):
        """Wrapper with error handling for position monitoring."""
        try:
            await self._monitor_positions()
        except Exception as e:
            logger.error(f"[Bot:{self.bot_config_id}] Monitor error: {e}")

    async def _monitor_positions(self):
        """Check open positions for this bot."""
        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TradeRecord).where(
                    TradeRecord.bot_config_id == self.bot_config_id,
                    TradeRecord.status == "open",
                )
            )
            open_trades = result.scalars().all()

            if not open_trades:
                return

            for trade in open_trades:
                await self._check_position(trade, session)

    async def _check_position(self, trade: TradeRecord, session):
        """Check a single open position — exchange status + strategy exit signals."""
        client = self._get_client(trade.demo_mode)
        if not client:
            return

        try:
            position = await client.get_position(trade.symbol)

            if not position:
                await self._handle_closed_position(trade, client, session)
                return

            if hasattr(position, 'side') and position.side != trade.side:
                await self._handle_closed_position(trade, client, session)
                return

            # Update highest price tracking for trailing stop
            current_price = None
            try:
                ticker = await client.get_ticker(trade.symbol)
                if ticker:
                    current_price = ticker.last_price
            except Exception:
                pass

            if current_price and trade.entry_price:
                if trade.side == "long":
                    new_highest = max(trade.highest_price or trade.entry_price, current_price)
                else:
                    # For short: track lowest price (stored in highest_price field)
                    new_highest = min(trade.highest_price or trade.entry_price, current_price)

                if new_highest != trade.highest_price:
                    trade.highest_price = new_highest
                    await session.commit()

            # Skip strategy exit when exchange handles TP/SL
            has_exchange_tpsl = trade.take_profit is not None or trade.stop_loss is not None
            if has_exchange_tpsl:
                logger.debug(
                    "[Bot:%s] Skipping should_exit for %s — exchange TP/SL active (TP=%s SL=%s)",
                    self.bot_config_id, trade.symbol, trade.take_profit, trade.stop_loss,
                )
                return

            # Strategy-based exit check
            if self._strategy and hasattr(self._strategy, 'should_exit'):
                try:
                    metrics_at_entry = None
                    if trade.metrics_snapshot:
                        try:
                            metrics_at_entry = json.loads(trade.metrics_snapshot) if isinstance(trade.metrics_snapshot, str) else trade.metrics_snapshot
                        except (json.JSONDecodeError, TypeError):
                            pass

                    should_close, exit_reason = await self._strategy.should_exit(
                        symbol=trade.symbol,
                        side=trade.side,
                        entry_price=trade.entry_price,
                        metrics_at_entry=metrics_at_entry,
                        current_price=current_price,
                        highest_price=trade.highest_price,
                        entry_time=trade.entry_time,
                    )

                    if should_close:
                        logger.info(
                            "[Bot:%s] Strategy exit for %s (%s): %s",
                            self.bot_config_id, trade.symbol, trade.side, exit_reason,
                        )
                        try:
                            await client.close_position(trade.symbol, trade.side)
                        except Exception as close_err:
                            logger.error("[Bot:%s] Failed to close position: %s", self.bot_config_id, close_err)
                            return

                        ticker = await client.get_ticker(trade.symbol)
                        exit_price = ticker.last_price if ticker else trade.entry_price

                        fees = trade.fees or 0
                        try:
                            if trade.order_id:
                                fees = await client.get_trade_total_fees(
                                    symbol=trade.symbol,
                                    entry_order_id=trade.order_id,
                                    close_order_id=trade.close_order_id,
                                )
                        except Exception:
                            pass

                        funding_paid = trade.funding_paid or 0
                        try:
                            if trade.entry_time:
                                entry_ms = int(trade.entry_time.timestamp() * 1000)
                                exit_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                                funding_paid = await client.get_funding_fees(
                                    symbol=trade.symbol,
                                    start_time_ms=entry_ms,
                                    end_time_ms=exit_ms,
                                )
                        except Exception:
                            pass

                        await self._close_and_record_trade(
                            trade,
                            exit_price,
                            "STRATEGY_EXIT",
                            fees=fees,
                            funding_paid=funding_paid,
                            strategy_reason="[%s] %s" % (self._config.name, exit_reason),
                        )
                except Exception as e:
                    logger.error("[Bot:%s] Strategy exit check error: %s", self.bot_config_id, e)

        except Exception as e:
            logger.error("[Bot:%s] Position check error: %s", self.bot_config_id, e)

    async def _handle_closed_position(self, trade: TradeRecord, client: ExchangeClient, session):
        """Handle a position that was closed externally (TP/SL/manual)."""
        log_prefix = f"[Bot:{self.bot_config_id}]"

        try:
            # Get current price as exit price estimate
            ticker = await client.get_ticker(trade.symbol)
            exit_price = ticker.last_price if ticker else trade.entry_price

            # Determine exit reason
            exit_reason = "EXTERNAL_CLOSE"
            if trade.take_profit is not None and trade.entry_price > 0:
                if abs(exit_price - trade.take_profit) < trade.entry_price * 0.002:
                    exit_reason = "TAKE_PROFIT"
            if trade.stop_loss is not None and trade.entry_price > 0:
                if abs(exit_price - trade.stop_loss) < trade.entry_price * 0.002:
                    exit_reason = "STOP_LOSS"

            # Fetch trading fees from exchange (entry + exit via orders-history)
            fees = trade.fees
            try:
                if trade.order_id:
                    fees = await client.get_trade_total_fees(
                        symbol=trade.symbol,
                        entry_order_id=trade.order_id,
                        close_order_id=trade.close_order_id,
                    )
            except Exception as e:
                logger.debug(f"{log_prefix} Could not fetch fees for trade #{trade.id}: {e}")
                fees = 0

            # Fetch funding fees (charged every 8h while position was open)
            funding_paid = trade.funding_paid
            try:
                if trade.entry_time:
                    entry_ms = int(trade.entry_time.timestamp() * 1000)
                    exit_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                    funding_paid = await client.get_funding_fees(
                        symbol=trade.symbol,
                        start_time_ms=entry_ms,
                        end_time_ms=exit_ms,
                    )
            except Exception as e:
                logger.debug(f"{log_prefix} Could not fetch funding fees for trade #{trade.id}: {e}")
                funding_paid = 0

            # Calculate builder fee revenue (Hyperliquid only)
            builder_fee = 0
            try:
                if hasattr(client, 'calculate_builder_fee'):
                    builder_fee = client.calculate_builder_fee(
                        entry_price=trade.entry_price,
                        exit_price=exit_price,
                        size=trade.size,
                    )
            except Exception as e:  # pragma: no cover -- defensive fee calc fallback
                logger.debug(f"{log_prefix} Could not calculate builder fee for trade #{trade.id}: {e}")

            # Use shared close-and-record logic
            await self._close_and_record_trade(
                trade,
                exit_price,
                exit_reason,
                fees=fees,
                funding_paid=funding_paid,
                builder_fee=builder_fee,
                strategy_reason=f"[{self._config.name}]",
            )

        except Exception as e:
            logger.error(f"{log_prefix} Handle closed position error: {e}")
