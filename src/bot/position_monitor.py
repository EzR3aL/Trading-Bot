"""Position monitoring logic for BotWorker (mixin)."""

import asyncio
import json
from datetime import datetime, timezone

from src.bot.pnl import calculate_pnl
from src.data.market_data import MarketDataFetcher
from src.exchanges.base import ExchangeClient
from src.models.database import TradeRecord
from src.models.session import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Constants (safe to share — immutable)
_TRAILING_STOP_RETRY_MINUTES = 10
_POSITION_GONE_THRESHOLD = 3
_POSITION_GONE_DELAY_S = 2.0
_GLITCH_WARN_THRESHOLD = 3  # warn after N glitches in a row
_GLITCH_ALERT_THRESHOLD = 10  # send notification after N glitches


class PositionMonitorMixin:
    """Mixin providing position monitoring methods for BotWorker."""

    def _init_monitor_state(self) -> None:
        """Initialize per-instance monitor state.

        Must be called from BotWorker.__init__ so each bot has its own
        trailing-stop backoff tracker, lock, and glitch counter instead
        of sharing module-level globals across all bots.
        """
        # Track failed native trailing stop attempts: {trade_id: last_attempt_time}
        self._trailing_stop_backoff: dict[int, datetime] = {}
        self._trailing_stop_lock = asyncio.Lock()
        # Track API glitch frequency per symbol: {symbol: count}
        self._glitch_counter: dict[str, int] = {}
        # Track PnL alert notifications sent per trade: {trade_id: set("profit_5.0","loss_10.0")}
        self._pnl_alerts_sent: dict[int, set[str]] = {}
        # Cached parsed PnL alert settings (refreshed each monitor cycle)
        self._pnl_alert_parsed: dict | None = None

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
                # No open trades — clear all tracking caches
                self._trailing_stop_backoff.clear()
                self._glitch_counter.clear()
                return

            # Clean up backoff/glitch entries for trades no longer open
            open_trade_ids = {t.id for t in open_trades}
            stale_backoff = [tid for tid in self._trailing_stop_backoff if tid not in open_trade_ids]
            for tid in stale_backoff:
                del self._trailing_stop_backoff[tid]

            open_glitch_keys = {f"{self.bot_config_id}:{t.symbol}" for t in open_trades}
            stale_glitch = [k for k in self._glitch_counter if k not in open_glitch_keys]
            for k in stale_glitch:
                del self._glitch_counter[k]

            stale_alerts = [tid for tid in self._pnl_alerts_sent if tid not in open_trade_ids]
            for tid in stale_alerts:
                del self._pnl_alerts_sent[tid]

            # Parse PnL alert settings once per cycle (not per trade)
            self._pnl_alert_parsed = None
            if self._config and self._config.pnl_alert_settings:
                try:
                    parsed = json.loads(self._config.pnl_alert_settings)
                    if parsed.get("enabled") and parsed.get("thresholds"):
                        self._pnl_alert_parsed = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

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
                # Position appears gone — confirm with retries to avoid
                # false closures from transient API glitches.
                confirmed = await self._confirm_position_closed(
                    trade, client,
                )
                if confirmed:
                    await self._handle_closed_position(trade, client, session)
                return

            # Fix stale side: if trade has wrong side (e.g. "neutral"), adopt
            # the actual exchange side so future checks match correctly.
            if hasattr(position, 'side') and trade.side != position.side:
                if trade.side not in ("long", "short"):
                    logger.info(
                        "[Bot:%s] Correcting trade #%s side: %s -> %s",
                        self.bot_config_id, trade.id, trade.side, position.side,
                    )
                    trade.side = position.side
                    await session.commit()

            # Update highest price tracking for trailing stop
            current_price = None
            try:
                ticker = await client.get_ticker(trade.symbol)
                if ticker:
                    current_price = ticker.last_price
            except Exception:
                pass

            if current_price and trade.entry_price:
                # PnL threshold alert check
                await self._check_pnl_alert(trade, current_price)

                if trade.side == "long":
                    new_highest = max(trade.highest_price or trade.entry_price, current_price)
                else:
                    # For short: track lowest price (stored in highest_price field)
                    new_highest = min(trade.highest_price or trade.entry_price, current_price)

                if new_highest != trade.highest_price:
                    trade.highest_price = new_highest
                    await session.commit()

            # Auto-place native trailing stop for existing positions (with backoff).
            # Only retry on exchanges that actually support native trailing; for
            # Weex/Bitunix/Hyperliquid we rely entirely on the software trailing
            # in strategy.should_exit so there's no point hitting the Binance
            # klines API + exchange API every 10 minutes for a guaranteed no-op.
            supports_native_trailing = getattr(
                type(client), "SUPPORTS_NATIVE_TRAILING_STOP", False,
            )
            supports_trailing_probe = getattr(
                type(client), "SUPPORTS_NATIVE_TRAILING_PROBE", False,
            )

            # Bidirectional drift check: DB flag may disagree with the
            # exchange in either direction. A cheap probe per cycle catches
            # both "DB=False but plan is live" (cancel no-op after edit) and
            # "DB=True but plan is gone" (exchange cancelled it for reasons
            # we did not record). The probe is cached inside the client's
            # HTTP layer for the current cycle so this stays sub-10ms.
            if supports_native_trailing and supports_trailing_probe:
                try:
                    exch_has_trail = await client.has_native_trailing_stop(
                        trade.symbol, trade.side,
                    )
                    if exch_has_trail != bool(trade.native_trailing_stop):
                        logger.info(
                            "[Bot:%s] Trailing drift reconciled for %s %s: "
                            "DB=%s exchange=%s",
                            self.bot_config_id, trade.symbol, trade.side,
                            trade.native_trailing_stop, exch_has_trail,
                        )
                        trade.native_trailing_stop = exch_has_trail
                        await session.commit()
                        if exch_has_trail:
                            async with self._trailing_stop_lock:
                                self._trailing_stop_backoff.pop(trade.id, None)
                except Exception as e:
                    logger.debug(
                        "[Bot:%s] Trailing probe failed for %s: %s",
                        self.bot_config_id, trade.symbol, e,
                    )

            if (
                supports_native_trailing
                and not trade.native_trailing_stop
                and self._strategy
                and hasattr(self._strategy, '_p')
            ):
                async with self._trailing_stop_lock:
                    last_attempt = self._trailing_stop_backoff.get(trade.id)
                    should_retry = (
                        last_attempt is None
                        or (datetime.now(timezone.utc) - last_attempt).total_seconds() > _TRAILING_STOP_RETRY_MINUTES * 60
                    )
                    # Update backoff timestamp inside the lock to prevent
                    # concurrent re-entry (Bug 3 fix: race condition)
                    if should_retry:
                        self._trailing_stop_backoff[trade.id] = datetime.now(timezone.utc)
                if should_retry:
                    await self._try_place_native_trailing_stop(trade, client, position, current_price, session)

            # Skip strategy exit when exchange handles TP/SL
            # BUT: still run should_exit if strategy has trailing stop enabled
            # (software trailing stop may trigger before exchange SL)
            has_exchange_tpsl = trade.take_profit is not None or trade.stop_loss is not None
            has_trailing = (
                trade.trailing_atr_override is not None
                or (
                    self._strategy
                    and hasattr(self._strategy, '_p')
                    and self._strategy._p.get("trailing_stop_enabled")
                )
            )
            if has_exchange_tpsl and not has_trailing:
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
                        trailing_atr_override=trade.trailing_atr_override,
                    )

                    if should_close:
                        logger.info(
                            "[Bot:%s] Strategy exit for %s (%s): %s",
                            self.bot_config_id, trade.symbol, trade.side, exit_reason,
                        )
                        try:
                            margin_mode = getattr(self._config, "margin_mode", "cross")
                            close_order = await client.close_position(trade.symbol, trade.side, margin_mode=margin_mode)
                        except Exception as close_err:
                            logger.error("[Bot:%s] Failed to close position: %s", self.bot_config_id, close_err)
                            return

                        if close_order is None:
                            # Position already closed (native TS/TP/SL beat us)
                            logger.info(
                                "[Bot:%s] Strategy exit for %s — position already closed on exchange, "
                                "deferring to _handle_closed_position on next cycle",
                                self.bot_config_id, trade.symbol,
                            )
                            return

                        # Verify close order was actually placed (non-empty order_id)
                        if not close_order.order_id:
                            logger.error(
                                "[Bot:%s] Close order for %s returned empty order_id — "
                                "exchange may not have executed the close. "
                                "NOT marking trade as closed, will retry next cycle.",
                                self.bot_config_id, trade.symbol,
                            )
                            return

                        # Persist close order ID for fee lookup
                        trade.close_order_id = close_order.order_id

                        # Prefer the actual close-order fill price (matches exchange exactly).
                        # Ticker can drift from the real fill, which corrupts PnL and tax reports.
                        exit_price = None
                        try:
                            exit_price = await client.get_close_fill_price(trade.symbol)
                        except Exception:
                            pass
                        if not exit_price:
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

                        # Use TRAILING_STOP label when the strategy's trailing stop triggered the exit
                        close_label = "TRAILING_STOP" if "Trailing Stop" in exit_reason else "STRATEGY_EXIT"
                        await self._close_and_record_trade(
                            trade,
                            exit_price,
                            close_label,
                            fees=fees,
                            funding_paid=funding_paid,
                            strategy_reason="[%s] %s" % (self._config.name, exit_reason),
                        )
                except Exception as e:
                    logger.error("[Bot:%s] Strategy exit check error: %s", self.bot_config_id, e)

        except Exception as e:
            logger.error("[Bot:%s] Position check error: %s", self.bot_config_id, e)

    async def _try_place_native_trailing_stop(self, trade, client, position, current_price, session):
        """Auto-place a native trailing stop on the exchange for an existing position."""
        log_prefix = f"[Bot:{self.bot_config_id}]"
        try:
            # Drift is already reconciled by the outer probe in _check_position
            # before this method is invoked; we only land here when the probe
            # confirmed "no live plan" (or no probe exists).
            params = self._strategy._p
            if not params.get("trailing_stop_enabled"):
                return

            entry_price = trade.entry_price
            if not entry_price or entry_price <= 0:
                return

            # Fetch ATR from Binance klines
            fetcher = MarketDataFetcher()
            try:
                klines = await fetcher.get_binance_klines(
                    trade.symbol,
                    params.get("kline_interval", "1h"),
                    params.get("kline_count", 200),
                )
            finally:
                await fetcher.close()

            if not klines:
                return

            atr_series = MarketDataFetcher.calculate_atr(klines, params.get("atr_period", 14))
            if not atr_series:
                return

            atr_val = atr_series[-1]
            trail_atr = params.get("trailing_trail_atr", 2.5)
            breakeven_atr = params.get("trailing_breakeven_atr", 1.5)

            callback_pct = round((atr_val * trail_atr) / entry_price * 100, 2)
            if trade.side == "long":
                trigger_price = round(entry_price + atr_val * breakeven_atr, 2)
            else:
                trigger_price = round(entry_price - atr_val * breakeven_atr, 2)

            margin_mode = getattr(self._config, "margin_mode", "cross")
            result = await client.place_trailing_stop(
                symbol=trade.symbol,
                hold_side=trade.side,
                size=trade.size,
                callback_ratio=callback_pct,
                trigger_price=trigger_price,
                margin_mode=margin_mode,
            )

            if result is not None:
                trade.native_trailing_stop = True
                await session.commit()
                async with self._trailing_stop_lock:
                    self._trailing_stop_backoff.pop(trade.id, None)
                logger.info(
                    "%s Native trailing stop placed for existing %s %s position: "
                    "callback=%.2f%% trigger=$%.2f",
                    log_prefix, trade.symbol, trade.side, callback_pct, trigger_price,
                )
            else:
                logger.debug(
                    "%s Exchange does not support native trailing stop for %s",
                    log_prefix, trade.symbol,
                )
        except Exception as e:
            async with self._trailing_stop_lock:
                self._trailing_stop_backoff[trade.id] = datetime.now(timezone.utc)
            logger.warning(
                "%s Failed to place native trailing stop for %s (software backup active, retry in %dm): %s",
                log_prefix, trade.symbol, _TRAILING_STOP_RETRY_MINUTES, e,
            )

    async def _confirm_position_closed(
        self, trade: TradeRecord, client: ExchangeClient,
    ) -> bool:
        """Re-check the exchange multiple times before confirming a position is gone.

        Returns True only if the position is absent on all retry attempts.
        This guards against transient API errors / empty responses that would
        otherwise cause a live position to be prematurely marked as closed.
        """
        log_prefix = f"[Bot:{self.bot_config_id}]"
        glitch_key = f"{self.bot_config_id}:{trade.symbol}"

        # Track whether all retries threw exceptions (Bug 1 fix)
        any_exception = False
        for attempt in range(1, _POSITION_GONE_THRESHOLD + 1):  # Bug 6 fix: +1 for correct retry count
            await asyncio.sleep(_POSITION_GONE_DELAY_S)
            try:
                pos = await client.get_position(trade.symbol)
                if pos:
                    # Track glitch frequency
                    self._glitch_counter[glitch_key] = self._glitch_counter.get(glitch_key, 0) + 1
                    count = self._glitch_counter[glitch_key]

                    logger.info(
                        "%s Position %s reappeared on attempt %d/%d — API glitch #%d, "
                        "skipping closure",
                        log_prefix, trade.symbol, attempt, _POSITION_GONE_THRESHOLD, count,
                    )

                    if count == _GLITCH_WARN_THRESHOLD:
                        logger.warning(
                            "%s Repeated API glitches for %s (%d occurrences) — "
                            "exchange API may be unstable",
                            log_prefix, trade.symbol, count,
                        )
                    if count >= _GLITCH_ALERT_THRESHOLD and count % _GLITCH_ALERT_THRESHOLD == 0:
                        logger.error(
                            "%s CRITICAL: %d API glitches for %s — "
                            "position monitoring unreliable, manual check recommended",
                            log_prefix, count, trade.symbol,
                        )
                        await self._send_notification(
                            lambda n, s=trade.symbol, c=count: n.send_risk_alert(
                                alert_type="API_GLITCH",
                                message=f"{s}: {c} API-Glitches erkannt — Position wird weiter überwacht, "
                                        f"aber die Exchange-API ist instabil. Bitte manuell prüfen.",
                            ),
                            event_type="risk_alert",
                            summary=f"API_GLITCH: {trade.symbol} ({count}x)",
                        )
                    return False
            except Exception as e:
                any_exception = True
                logger.warning(
                    "%s Retry %d/%d for %s failed: %s",
                    log_prefix, attempt, _POSITION_GONE_THRESHOLD, trade.symbol, e,
                )

        # If all retries threw exceptions, do not falsely confirm closure (Bug 1 fix)
        if any_exception:
            logger.warning(
                "%s Cannot confirm %s closed — all retries raised exceptions, assuming still open",
                log_prefix, trade.symbol,
            )
            return False

        # Position genuinely closed — reset glitch counter
        self._glitch_counter.pop(glitch_key, None)
        logger.info(
            "%s Position %s confirmed closed after %d checks",
            log_prefix, trade.symbol, _POSITION_GONE_THRESHOLD,
        )
        return True

    async def _check_pnl_alert(self, trade: TradeRecord, current_price: float) -> None:
        """Send a one-time notification when a trade's PnL crosses configured thresholds."""
        settings = self._pnl_alert_parsed
        if not settings:
            return

        pnl_abs, pnl_pct = calculate_pnl(trade.side, trade.entry_price, current_price, trade.size)
        direction = settings.get("direction", "both")
        sent = self._pnl_alerts_sent.get(trade.id, set())

        for t in settings.get("thresholds", []):
            # Each threshold has its own mode (dollar or percent)
            if isinstance(t, dict):
                threshold = float(t.get("value", 0))
                mode = t.get("mode", "percent")
            else:
                # Backwards compat: plain float = percent
                threshold = float(t)
                mode = "percent"

            value = pnl_pct if mode == "percent" else pnl_abs
            unit = "%" if mode == "percent" else "$"
            key_base = f"{mode}_{threshold}"

            # Check profit direction
            if value >= threshold and direction in ("profit", "both"):
                key = f"profit_{key_base}"
                if key not in sent:
                    msg = (
                        f"{trade.symbol} ({trade.side}): PnL-Schwelle erreicht! "
                        f"Aktuell: {value:+.2f}{unit} (Schwelle: +{threshold}{unit})"
                    )
                    await self._send_notification(
                        lambda n, m=msg, v=value, th=threshold: n.send_risk_alert(
                            alert_type="PNL_THRESHOLD", message=m, current_value=v, threshold=th,
                        ),
                        event_type="pnl_alert",
                        summary=f"PNL_PROFIT: {trade.symbol} {value:+.2f}{unit}",
                    )
                    sent.add(key)

            # Check loss direction
            if value <= -threshold and direction in ("loss", "both"):
                key = f"loss_{key_base}"
                if key not in sent:
                    msg = (
                        f"{trade.symbol} ({trade.side}): PnL-Schwelle erreicht! "
                        f"Aktuell: {value:+.2f}{unit} (Schwelle: -{threshold}{unit})"
                    )
                    await self._send_notification(
                        lambda n, m=msg, v=value, th=threshold: n.send_risk_alert(
                            alert_type="PNL_THRESHOLD", message=m, current_value=v, threshold=th,
                        ),
                        event_type="pnl_alert",
                        summary=f"PNL_LOSS: {trade.symbol} {value:+.2f}{unit}",
                    )
                    sent.add(key)

        if sent:
            self._pnl_alerts_sent[trade.id] = sent

    async def _handle_closed_position(self, trade: TradeRecord, client: ExchangeClient, session):
        """Handle a position that was closed externally (TP/SL/manual)."""
        log_prefix = f"[Bot:{self.bot_config_id}]"

        # Clean up backoff tracking for closed trade
        self._trailing_stop_backoff.pop(trade.id, None)

        try:
            # Get actual fill price from the close order (TP/SL/trailing/manual)
            exit_price = None
            try:
                exit_price = await client.get_close_fill_price(trade.symbol)
                if exit_price:
                    logger.info(
                        "%s Actual close fill price for %s: $%.2f",
                        log_prefix, trade.symbol, exit_price,
                    )
                # Persist close_order_id if the exchange client discovered it
                close_oid = getattr(client, "_last_close_order_id", None)
                if close_oid and not trade.close_order_id:
                    trade.close_order_id = close_oid
            except Exception:
                pass
            # Fallback to current ticker if fill price unavailable
            if not exit_price:
                ticker = await client.get_ticker(trade.symbol)
                exit_price = ticker.last_price if ticker else trade.entry_price

            # Determine exit reason
            exit_reason = "EXTERNAL_CLOSE"
            if trade.native_trailing_stop:
                exit_reason = "TRAILING_STOP"
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
