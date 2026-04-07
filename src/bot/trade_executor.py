"""Trade execution logic for BotWorker (mixin)."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from src.exceptions import ExchangeError, OrderError
from src.exchanges.base import ExchangeClient
from src.models.database import PendingTrade, TradeRecord
from src.models.session import get_session
from src.strategy import TradeSignal
from src.utils.json_helpers import parse_json_field
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeExecutorMixin:
    """Mixin providing trade execution methods for BotWorker."""

    async def _execute_trade(
        self, signal: TradeSignal, client: ExchangeClient, demo_mode: bool,
        asset_budget: Optional[float] = None,
    ):
        """Execute a trade on a specific exchange client."""
        log_prefix = f"[Bot:{self.bot_config_id}]"
        mode_str = "DEMO" if demo_mode else "LIVE"

        # Resolve per-asset config overrides
        per_asset_cfg = parse_json_field(
            self._config.per_asset_config,
            field_name="per_asset_config",
            context=f"bot {self.bot_config_id}",
            default={},
        )
        asset_cfg = per_asset_cfg.get(signal.symbol, {})

        # Resolve leverage: per-asset > global > 1x
        leverage = asset_cfg.get("leverage") or self._config.leverage or 1

        # TP/SL: Use user-configured values from per-asset or bot-level config.
        # Per-asset config takes priority, then bot-level, then None (strategy exit).
        tp_pct = asset_cfg.get("take_profit_percent") or getattr(self._config, "take_profit_percent", None)
        sl_pct = asset_cfg.get("stop_loss_percent") or getattr(self._config, "stop_loss_percent", None)

        is_long = signal.direction.value == "long"
        if tp_pct and signal.entry_price and signal.entry_price > 0:
            signal.target_price = (
                signal.entry_price * (1 + tp_pct / 100)
                if is_long
                else signal.entry_price * (1 - tp_pct / 100)
            )
        else:
            signal.target_price = None

        if sl_pct and signal.entry_price and signal.entry_price > 0:
            signal.stop_loss = (
                signal.entry_price * (1 - sl_pct / 100)
                if is_long
                else signal.entry_price * (1 + sl_pct / 100)
            )
        # else: preserve strategy-computed SL (e.g. default ATR SL)

        pending_trade_id = None
        try:
            # Validate entry price before any calculations
            if not signal.entry_price or signal.entry_price <= 0:
                logger.warning(f"{log_prefix} [{mode_str}] Invalid entry price: {signal.entry_price}")
                return

            # Pre-execution risk check — ensures daily loss limit is enforced
            # even if conditions changed between analysis and execution
            can_trade, deny_reason = self._risk_manager.can_trade(signal.symbol)
            if not can_trade:
                logger.warning(f"{log_prefix} [{mode_str}] Trade denied at execution: {deny_reason}")
                return

            # Use pre-calculated asset budget or fall back to full available balance
            if asset_budget is not None:
                available = asset_budget
            else:
                balance = await client.get_account_balance()
                available = balance.available

            # Calculate position size (use margin, not leveraged notional)
            if asset_budget is not None:
                # Per-asset budget mode — budget is the margin amount
                # Use 95% of budget to leave margin for fees and funding
                usable = available * 0.95
                position_usdt = usable
                position_size = (usable * leverage) / signal.entry_price
            else:
                # Legacy fallback via RiskManager
                position_usdt, position_size = self._risk_manager.calculate_position_size(
                    balance=available,
                    entry_price=signal.entry_price,
                    confidence=signal.confidence,
                    leverage=leverage,
                )

            if position_usdt < 5:
                logger.warning(f"{log_prefix} [{mode_str}] Position too small: ${position_usdt:.2f} (min 5 USDT)")
                return

            logger.info(
                f"{log_prefix} [{mode_str}] Order prep: {signal.symbol} "
                f"available=${available:,.2f} leverage={leverage}x "
                f"position_usdt=${position_usdt:,.2f} size={position_size:.6f} "
                f"entry=${signal.entry_price:,.2f}"
            )

            # Set leverage — abort trade if leverage cannot be set (e.g. open position with different leverage)
            margin_mode = getattr(self._config, "margin_mode", "cross")
            leverage_ok = await client.set_leverage(signal.symbol, leverage, margin_mode=margin_mode)
            if not leverage_ok:
                logger.warning(
                    "%s Cannot set %dx leverage for %s — position may be open with different leverage. Skipping trade.",
                    log_prefix, leverage, signal.symbol,
                )
                return

            # Reject NEUTRAL signals — no clear direction to trade
            if signal.direction.value == "neutral":
                logger.info(f"{log_prefix} [{mode_str}] Skipping NEUTRAL signal for {signal.symbol}")
                return

            # Record pending trade BEFORE placing the order (crash recovery)
            side = signal.direction.value  # "long" or "short"
            try:
                order_params = json.dumps({
                    "symbol": str(signal.symbol),
                    "side": side,
                    "size": float(position_size),
                    "leverage": int(leverage),
                    "take_profit": float(signal.target_price) if signal.target_price else None,
                    "stop_loss": float(signal.stop_loss) if signal.stop_loss else None,
                    "margin_mode": margin_mode,
                    "demo_mode": demo_mode,
                    "entry_price": float(signal.entry_price),
                })
            except (TypeError, ValueError):
                order_params = None
            try:
                async with get_session() as session:
                    pending = PendingTrade(
                        bot_config_id=self.bot_config_id,
                        user_id=self._config.user_id,
                        symbol=signal.symbol,
                        side=side.upper(),
                        action="open",
                        order_data=order_params,
                        status="pending",
                    )
                    session.add(pending)
                    await session.flush()
                    pending_trade_id = pending.id
            except Exception as pt_err:
                logger.warning("%s [%s] Could not record pending trade: %s", log_prefix, mode_str, pt_err)

            # Place order
            order = await client.place_market_order(
                symbol=signal.symbol,
                side=side,
                size=position_size,
                leverage=leverage,
                take_profit=signal.target_price,
                stop_loss=signal.stop_loss,
                margin_mode=margin_mode,
            )

            if not order:
                logger.error(f"{log_prefix} [{mode_str}] Failed to place order")
                await self._resolve_pending_trade(pending_trade_id, "failed", "Order returned None")
                return

            # Safety: if exchange couldn't set TP/SL, try dedicated endpoint as fallback
            if getattr(order, "tpsl_failed", False):
                if hasattr(client, "set_position_tpsl"):
                    try:
                        await asyncio.sleep(0.3)
                        pos = await client.get_position(signal.symbol)
                        if pos:
                            kwargs = {
                                "symbol": signal.symbol,
                                "take_profit": signal.target_price,
                                "stop_loss": signal.stop_loss,
                            }
                            # Bitunix needs position_id, Weex needs side+size
                            if getattr(pos, "position_id", None):
                                kwargs["position_id"] = pos.position_id
                            if "side" in client.set_position_tpsl.__code__.co_varnames:
                                kwargs["side"] = side
                                kwargs["size"] = position_size
                            await client.set_position_tpsl(**kwargs)
                            logger.info(
                                "%s [%s] TP/SL set via fallback endpoint for %s",
                                log_prefix, mode_str, signal.symbol,
                            )
                        else:
                            signal.target_price = None
                            signal.stop_loss = None
                    except Exception as tpsl_err:
                        logger.warning(
                            "%s [%s] TP/SL fallback also failed for %s: %s",
                            log_prefix, mode_str, signal.symbol, tpsl_err,
                        )
                        signal.target_price = None
                        signal.stop_loss = None
                else:
                    signal.target_price = None
                    signal.stop_loss = None

            # Place native trailing stop on exchange (if strategy provided params
            # and the exchange advertises native support). Exchanges without
            # native trailing (Weex, Bitunix, Hyperliquid) are skipped entirely
            # — the software trailing fallback in strategy.should_exit handles
            # exits for those. The capability flag avoids both wasted API calls
            # and misleading "placed" log lines for no-op attempts.
            trailing_placed = False
            supports_native = getattr(type(client), "SUPPORTS_NATIVE_TRAILING_STOP", False)
            if (
                supports_native
                and signal.trailing_callback_pct
                and signal.trailing_trigger_price
            ):
                try:
                    await asyncio.sleep(0.3)
                    trailing_result = await client.place_trailing_stop(
                        symbol=signal.symbol,
                        hold_side=side,
                        size=position_size,
                        callback_ratio=signal.trailing_callback_pct,
                        trigger_price=signal.trailing_trigger_price,
                        margin_mode=margin_mode,
                    )
                    if trailing_result is not None:
                        trailing_placed = True
                        logger.info(
                            "%s [%s] Native trailing stop placed: %s callback=%.2f%% trigger=$%.2f",
                            log_prefix, mode_str, signal.symbol,
                            signal.trailing_callback_pct, signal.trailing_trigger_price,
                        )
                    else:
                        logger.debug(
                            "%s [%s] Native trailing stop returned None for %s — "
                            "software trailing will handle exit",
                            log_prefix, mode_str, signal.symbol,
                        )
                except Exception as e:
                    logger.warning(
                        "%s [%s] Native trailing stop failed (software backup active): %s",
                        log_prefix, mode_str, e,
                    )

            # Get fill price — prefer order.price (avgPx from exchange)
            fill_price = order.price if order.price > 0 else signal.entry_price
            if order.order_id:
                try:
                    actual = await client.get_fill_price(signal.symbol, order.order_id)
                    if actual:
                        fill_price = actual
                except Exception as e:
                    logger.debug(f"{log_prefix} [{mode_str}] Could not fetch fill price: {e}")

            # Record trade in database AND resolve pending trade atomically
            async with get_session() as session:
                trade = TradeRecord(
                    user_id=self._config.user_id,
                    bot_config_id=self.bot_config_id,
                    exchange=self._config.exchange_type,
                    symbol=signal.symbol,
                    side=side,
                    size=position_size,
                    entry_price=fill_price,
                    take_profit=signal.target_price,
                    stop_loss=signal.stop_loss,
                    leverage=leverage,
                    confidence=signal.confidence,
                    reason=signal.reason,
                    order_id=order.order_id,
                    status="open",
                    entry_time=datetime.now(timezone.utc),
                    demo_mode=demo_mode,
                    metrics_snapshot=json.dumps(signal.metrics_snapshot),
                    native_trailing_stop=trailing_placed,
                )
                session.add(trade)

                # Resolve pending trade in the SAME session (atomic)
                if pending_trade_id is not None:
                    from sqlalchemy import select as sa_select
                    pt_result = await session.execute(
                        sa_select(PendingTrade).where(PendingTrade.id == pending_trade_id)
                    )
                    pending = pt_result.scalar_one_or_none()
                    if pending:
                        pending.status = "completed"
                        pending.resolved_at = datetime.now(timezone.utc)
                    pending_trade_id = None  # already resolved

            # Record in risk manager
            self._risk_manager.record_trade_entry(
                symbol=signal.symbol,
                side=signal.direction.value,
                size=position_size,
                entry_price=fill_price,
                leverage=leverage,
                confidence=signal.confidence,
                reason=signal.reason,
                order_id=order.order_id,
            )

            self.trades_today += 1

            # Log TP/SL status
            tpsl_warning = ""
            if signal.target_price is not None or signal.stop_loss is not None:
                tp_str = f"${signal.target_price:,.2f}" if signal.target_price else "—"
                sl_str = f"${signal.stop_loss:,.2f}" if signal.stop_loss else "—"
                tpsl_warning = f" [TP={tp_str} SL={sl_str}]"
                logger.info(
                    "%s [%s] %s: TP/SL an Exchange gesendet — TP=%s SL=%s, "
                    "should_exit() deaktiviert",
                    log_prefix, mode_str, signal.symbol, tp_str, sl_str,
                )
            elif signal.target_price is None and signal.stop_loss is None:
                tpsl_warning = " [Kein TP/SL - Strategie-Exit aktiv]"
                logger.info(
                    "%s [%s] %s: kein TP/SL gesetzt - "
                    "Position wird durch Strategie-Exit-Signale verwaltet",
                    log_prefix, mode_str, signal.symbol,
                )
            elif getattr(order, "tpsl_failed", False):
                tpsl_warning = " [WARNING: TP/SL FAILED — position UNPROTECTED]"
                logger.error(
                    f"{log_prefix} [{mode_str}] TP/SL failed for {signal.symbol} — "
                    "position is open WITHOUT stop-loss protection"
                )

            trailing_info = ""
            if trailing_placed:
                trailing_info = (
                    f" [Trailing: {signal.trailing_callback_pct:.2f}% "
                    f"trigger=${signal.trailing_trigger_price:,.2f}]"
                )
            logger.info(
                f"{log_prefix} [{mode_str}] Trade opened: {signal.direction.value.upper()} "
                f"{signal.symbol} @ ${fill_price:,.2f} (conf: {signal.confidence}%)"
                f"{tpsl_warning}{trailing_info}"
            )

            # Broadcast via WebSocket (keep reference to prevent GC)
            try:
                from src.api.websocket.manager import ws_manager
                task = asyncio.create_task(ws_manager.broadcast_to_user(
                    self._config.user_id,
                    "trade_opened",
                    {
                        "bot_id": self.bot_config_id,
                        "symbol": signal.symbol,
                        "side": signal.direction.value,
                        "entry_price": fill_price,
                        "size": position_size,
                        "leverage": leverage,
                        "demo_mode": demo_mode,
                        "tpsl_failed": getattr(order, "tpsl_failed", False),
                    },
                ))
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)
            except Exception as e:
                logger.debug("WS broadcast failed: %s", e)

            # Send notifications (Discord + Telegram)
            trade_reason = f"[{self._config.name}] {signal.reason}"
            if getattr(order, "tpsl_failed", False):
                trade_reason += " | TP/SL FAILED — MANUAL INTERVENTION REQUIRED"
            await self._send_notification(
                lambda n, r=trade_reason: n.send_trade_entry(
                    symbol=signal.symbol,
                    side=signal.direction.value,
                    size=position_size,
                    entry_price=fill_price,
                    leverage=leverage,
                    take_profit=signal.target_price,
                    stop_loss=signal.stop_loss,
                    confidence=signal.confidence,
                    reason=r,
                    order_id=order.order_id or "",
                    demo_mode=demo_mode,
                ),
                event_type="trade_entry",
                summary=f"{signal.direction.value} {signal.symbol} @ {fill_price}",
            )

            # Send dedicated risk alert if TP/SL failed
            if getattr(order, "tpsl_failed", False):
                await self._send_notification(
                    lambda n: n.send_risk_alert(
                        alert_type="TPSL_FAILED",
                        message=(
                            f"{signal.symbol}: TP/SL placement failed after order fill. "
                            f"Position is UNPROTECTED. Manual TP/SL required."
                        ),
                    ),
                    event_type="risk_alert",
                    summary=f"TPSL_FAILED {signal.symbol}",
                )

        except OrderError as e:
            err_msg = str(e).lower()
            if "minimum amount" in err_msg or "minimum order" in err_msg:
                logger.warning(f"{log_prefix} [{mode_str}] Order below exchange minimum: {e}")
            else:
                logger.error(f"{log_prefix} [{mode_str}] Order failed: {e}")
                await self._notify_trade_failure(signal, mode_str, str(e))
            await self._resolve_pending_trade(pending_trade_id, "failed", str(e))
        except ExchangeError as e:
            logger.error(f"{log_prefix} [{mode_str}] Trade execution failed: {e}")
            await self._notify_trade_failure(signal, mode_str, str(e))
            await self._resolve_pending_trade(pending_trade_id, "failed", str(e))
        except Exception as e:
            err_msg = str(e).lower()
            if "minimum amount" in err_msg or "minimum order" in err_msg:
                logger.warning(f"{log_prefix} [{mode_str}] Order below exchange minimum: {e}")
            else:
                logger.error(f"{log_prefix} [{mode_str}] Trade execution failed: {e}")
                await self._notify_trade_failure(signal, mode_str, str(e))
            await self._resolve_pending_trade(pending_trade_id, "failed", str(e))

    async def _resolve_pending_trade(
        self, pending_trade_id: int | None, status: str, error_message: str | None = None
    ):
        """Update a pending trade record to its final status."""
        if pending_trade_id is None:
            return
        try:
            async with get_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(PendingTrade).where(PendingTrade.id == pending_trade_id)
                )
                pending = result.scalar_one_or_none()
                if pending:
                    pending.status = status
                    pending.error_message = error_message
                    pending.resolved_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning(
                "[Bot:%s] Could not resolve pending trade #%s: %s",
                self.bot_config_id, pending_trade_id, e,
            )

    async def _notify_trade_failure(self, signal: TradeSignal, mode_str: str, error: str):
        """Notify user of trade execution failure via WebSocket and notifications."""
        try:
            from src.api.websocket.manager import ws_manager
            task = asyncio.create_task(ws_manager.broadcast_to_user(
                self._config.user_id,
                "trade_failed",
                {
                    "bot_id": self.bot_config_id,
                    "bot_name": self._config.name,
                    "symbol": signal.symbol,
                    "side": signal.direction.value,
                    "error": error,
                    "demo_mode": mode_str == "DEMO",
                },
            ))
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)
        except Exception:
            pass

        try:
            await self._send_notification(
                lambda n: n.send_risk_alert(
                    alert_type="TRADE_FAILED",
                    message=(
                        f"[{self._config.name}] {mode_str} order failed for "
                        f"{signal.symbol} ({signal.direction.value}): {error}"
                    ),
                ),
                event_type="error",
                summary=f"TRADE_FAILED {signal.symbol}",
            )
        except Exception:
            pass
