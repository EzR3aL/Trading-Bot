"""Trade rotation logic for BotWorker (mixin)."""

import json
from datetime import datetime, timedelta, timezone

from src.exchanges.base import ExchangeClient
from src.models.database import TradeRecord
from src.models.session import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RotationManagerMixin:
    """Mixin providing trade rotation methods for BotWorker."""

    async def _check_rotation_safe(self):
        """Wrapper with error handling for rotation check."""
        try:
            await self._check_rotation()
        except Exception as e:
            logger.error(f"[Bot:{self.bot_config_id}] Rotation check error: {e}")

    async def _check_rotation(self):
        """Check if any open trades have exceeded their rotation interval and need closing.

        If rotation_start_time is set (e.g. "08:00"), rotation windows are anchored
        to that UTC time. Otherwise, elapsed time since entry_time is used.
        In rotation_only mode with no open trades, triggers a new analysis.
        """
        rotation_minutes = getattr(self._config, "rotation_interval_minutes", None)
        if not rotation_minutes:
            return

        log_prefix = f"[Bot:{self.bot_config_id}]"
        now = datetime.now(timezone.utc)

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
                # In rotation_only mode, if no open trades exist, open one now
                if self._config.schedule_type == "rotation_only":
                    logger.info(f"{log_prefix} ROTATION: No open trades -- triggering analysis")
                    pairs = json.loads(self._config.trading_pairs) if isinstance(self._config.trading_pairs, str) else self._config.trading_pairs
                    rot_balance = await self._client.get_account_balance()
                    rot_budgets = self._calculate_asset_budgets(rot_balance.available, pairs)
                    for symbol in pairs:
                        can_trade_sym, sym_reason = self._risk_manager.can_trade(symbol)
                        if not can_trade_sym:  # pragma: no cover -- rotation risk skip
                            logger.info(f"{log_prefix} ROTATION: Skipping {symbol} -- {sym_reason}")
                            continue
                        try:
                            await self._analyze_symbol(symbol, force=True, asset_budget=rot_budgets.get(symbol))
                        except Exception as e:  # pragma: no cover -- rotation analysis error
                            logger.error(f"{log_prefix} ROTATION: Analysis failed for {symbol}: {e}")
                return

            # Determine if we use anchored rotation (start_time) or elapsed-based
            start_time_str = getattr(self._config, "rotation_start_time", None)

            for trade in open_trades:
                if not trade.entry_time:
                    continue

                should_rotate = False
                if start_time_str:
                    # Anchored rotation: calculate next rotation boundary from start_time
                    try:
                        sh, sm = int(start_time_str[:2]), int(start_time_str[3:5])
                        # Build today's anchor at start_time UTC
                        anchor = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                        # If anchor is in the future, go back one day
                        if anchor > now:  # pragma: no cover -- time-dependent edge
                            anchor = anchor - timedelta(days=1)
                        # How many intervals since anchor?
                        elapsed_since_anchor = (now - anchor).total_seconds() / 60
                        # Find the last rotation boundary
                        intervals_passed = int(elapsed_since_anchor // rotation_minutes)
                        last_boundary = anchor + timedelta(minutes=intervals_passed * rotation_minutes)
                        # Trade should rotate if it was opened before the last boundary
                        if trade.entry_time < last_boundary:
                            should_rotate = True
                            elapsed = (now - trade.entry_time).total_seconds() / 60
                    except (ValueError, IndexError):  # pragma: no cover -- rotation parse fallback
                        # Fall back to elapsed-based
                        elapsed = (now - trade.entry_time).total_seconds() / 60
                        should_rotate = elapsed >= rotation_minutes
                else:
                    # Simple elapsed-based rotation
                    elapsed = (now - trade.entry_time).total_seconds() / 60
                    should_rotate = elapsed >= rotation_minutes

                if not should_rotate:  # pragma: no cover -- rotation timing skip
                    continue

                elapsed = (now - trade.entry_time).total_seconds() / 60
                logger.info(
                    f"{log_prefix} ROTATION: Trade #{trade.id} {trade.symbol} "
                    f"open for {elapsed:.0f}min (limit: {rotation_minutes}min) -- closing"
                )

                # Force-close the trade
                client = self._get_client(trade.demo_mode)
                if not client:  # pragma: no cover -- no client available
                    continue

                closed = await self._force_close_trade(trade, client, session)

                if closed:
                    # Check risk limits before re-opening
                    can_reopen, reopen_reason = self._risk_manager.can_trade(trade.symbol)
                    if not can_reopen:  # pragma: no cover -- rotation re-open blocked
                        logger.info(f"{log_prefix} ROTATION: Trade closed but no re-open -- {reopen_reason}")
                        continue

                    # Re-analyze and open a new trade for this symbol
                    logger.info(f"{log_prefix} ROTATION: Re-analyzing {trade.symbol}...")
                    try:
                        pairs = json.loads(self._config.trading_pairs) if isinstance(self._config.trading_pairs, str) else self._config.trading_pairs
                        reopen_balance = await client.get_account_balance()
                        reopen_budgets = self._calculate_asset_budgets(reopen_balance.available, pairs)
                        await self._analyze_symbol(trade.symbol, force=True, asset_budget=reopen_budgets.get(trade.symbol))
                    except Exception as e:
                        logger.error(f"{log_prefix} ROTATION: Re-analysis failed for {trade.symbol}: {e}")

    async def _force_close_trade(
        self, trade: TradeRecord, client: ExchangeClient, session
    ) -> bool:
        """Force-close an open trade via the exchange. Returns True on success.

        Handles the case where the position was already closed (TP/SL hit)
        by marking the trade as ROTATION_ALREADY_CLOSED instead of retrying.
        """
        log_prefix = f"[Bot:{self.bot_config_id}]"
        mode_str = "DEMO" if trade.demo_mode else "LIVE"
        rotation_reason = f"[{self._config.name}] Auto-rotation ({self._config.rotation_interval_minutes}min)"

        try:
            # Close position via exchange client
            order = await client.close_position(trade.symbol, trade.side)

            if order is None:
                # Position already closed (TP/SL triggered before rotation)
                logger.info(
                    f"{log_prefix} [{mode_str}] ROTATION: Trade #{trade.id} {trade.symbol} "
                    f"already closed on exchange (TP/SL hit). Marking as ROTATION_ALREADY_CLOSED."
                )
                # Get current price for approximate PnL
                exit_price = trade.entry_price
                try:
                    ticker = await client.get_ticker(trade.symbol)
                    if ticker:
                        exit_price = ticker.last_price
                except Exception as e:
                    logger.warning("%s Failed to get ticker for %s during rotation: %s", log_prefix, trade.symbol, e)

                await self._close_and_record_trade(
                    trade, exit_price, "ROTATION_ALREADY_CLOSED",
                    strategy_reason=rotation_reason,
                )
                return True

            # Get exit price from the close order
            exit_price = trade.entry_price
            if order.price and order.price > 0:
                exit_price = order.price
            else:
                try:
                    ticker = await client.get_ticker(trade.symbol)
                    if ticker:
                        exit_price = ticker.last_price
                except Exception as e:
                    logger.warning("Failed to get exit price ticker for %s: %s", trade.symbol, e)

            await self._close_and_record_trade(
                trade, exit_price, "ROTATION",
                strategy_reason=rotation_reason,
            )

            return True

        except Exception as e:
            err_msg = str(e).lower()
            # Handle "no position" errors from exchange API explicitly
            if any(phrase in err_msg for phrase in ("no position", "position not exist", "does not exist")):
                logger.info(
                    f"{log_prefix} [{mode_str}] ROTATION: Trade #{trade.id} {trade.symbol} "
                    f"position not found on exchange. Marking as ROTATION_ALREADY_CLOSED."
                )
                await self._close_and_record_trade(
                    trade, trade.entry_price, "ROTATION_ALREADY_CLOSED",
                    strategy_reason=rotation_reason,
                )
                return True

            logger.error(f"{log_prefix} [{mode_str}] ROTATION close failed for trade #{trade.id}: {e}")
            return False
