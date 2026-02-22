"""Trade execution logic for BotWorker (mixin)."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from src.exceptions import ExchangeError, OrderError
from src.exchanges.base import ExchangeClient
from src.models.database import TradeRecord
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

        # Apply per-asset TP/SL overrides to signal
        asset_tp = asset_cfg.get("tp")
        asset_sl = asset_cfg.get("sl")
        if asset_tp is not None and signal.entry_price > 0:
            if signal.direction.value == "long":
                signal.target_price = round(signal.entry_price * (1 + asset_tp / 100), 2)
            else:
                signal.target_price = round(signal.entry_price * (1 - asset_tp / 100), 2)
        if asset_sl is not None and signal.entry_price > 0:
            if signal.direction.value == "long":
                signal.stop_loss = round(signal.entry_price * (1 - asset_sl / 100), 2)
            else:
                signal.stop_loss = round(signal.entry_price * (1 + asset_sl / 100), 2)

        try:
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

            # Calculate position size
            if asset_budget is not None:
                # Per-asset budget mode — use full budget directly
                position_usdt = available
                position_size = (available * leverage) / signal.entry_price
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

            # Set leverage
            await client.set_leverage(signal.symbol, leverage)

            # Place order
            side = "long" if signal.direction.value == "long" else "short"
            order = await client.place_market_order(
                symbol=signal.symbol,
                side=side,
                size=position_size,
                leverage=leverage,
                take_profit=signal.target_price,
                stop_loss=signal.stop_loss,
            )

            if not order:
                logger.error(f"{log_prefix} [{mode_str}] Failed to place order")
                return

            # Get fill price — prefer order.price (avgPx from exchange)
            fill_price = order.price if order.price > 0 else signal.entry_price
            if order.order_id:
                try:
                    actual = await client.get_fill_price(signal.symbol, order.order_id)
                    if actual:
                        fill_price = actual
                except Exception as e:
                    logger.debug(f"{log_prefix} [{mode_str}] Could not fetch fill price: {e}")

            # Record trade in database
            async with get_session() as session:
                trade = TradeRecord(
                    user_id=self._config.user_id,
                    bot_config_id=self.bot_config_id,
                    exchange=self._config.exchange_type,
                    symbol=signal.symbol,
                    side=signal.direction.value,
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
                )
                session.add(trade)

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

            # Warn if TP/SL placement failed — position is unprotected
            tpsl_warning = ""
            if getattr(order, "tpsl_failed", False):
                tpsl_warning = " [WARNING: TP/SL FAILED — position UNPROTECTED]"
                logger.error(
                    f"{log_prefix} [{mode_str}] TP/SL failed for {signal.symbol} — "
                    "position is open WITHOUT stop-loss protection"
                )

            logger.info(
                f"{log_prefix} [{mode_str}] Trade opened: {signal.direction.value.upper()} "
                f"{signal.symbol} @ ${fill_price:,.2f} (conf: {signal.confidence}%){tpsl_warning}"
            )

            # Broadcast via WebSocket
            try:
                from src.api.websocket.manager import ws_manager
                asyncio.create_task(ws_manager.broadcast_to_user(
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
            except Exception as e:
                logger.debug("WS broadcast failed: %s", e)

            # Send notifications (Discord + Telegram)
            trade_reason = f"[{self._config.name}] {signal.reason}"
            if getattr(order, "tpsl_failed", False):
                trade_reason += " | TP/SL FAILED — MANUAL INTERVENTION REQUIRED"
            await self._send_notification(lambda n, r=trade_reason: n.send_trade_entry(
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
            ))

            # Send dedicated risk alert if TP/SL failed
            if getattr(order, "tpsl_failed", False):
                await self._send_notification(lambda n: n.send_risk_alert(
                    alert_type="TPSL_FAILED",
                    message=(
                        f"{signal.symbol}: TP/SL placement failed after order fill. "
                        f"Position is UNPROTECTED. Manual TP/SL required."
                    ),
                ))

        except OrderError as e:
            err_msg = str(e).lower()
            if "minimum amount" in err_msg or "minimum order" in err_msg:
                logger.warning(f"{log_prefix} [{mode_str}] Order below exchange minimum: {e}")
            else:
                logger.error(f"{log_prefix} [{mode_str}] Order failed: {e}")
                await self._notify_trade_failure(signal, mode_str, str(e))
        except ExchangeError as e:
            logger.error(f"{log_prefix} [{mode_str}] Trade execution failed: {e}")
            await self._notify_trade_failure(signal, mode_str, str(e))
        except Exception as e:
            err_msg = str(e).lower()
            if "minimum amount" in err_msg or "minimum order" in err_msg:
                logger.warning(f"{log_prefix} [{mode_str}] Order below exchange minimum: {e}")
            else:
                logger.error(f"{log_prefix} [{mode_str}] Trade execution failed: {e}")
                await self._notify_trade_failure(signal, mode_str, str(e))

    async def _notify_trade_failure(self, signal: TradeSignal, mode_str: str, error: str):
        """Notify user of trade execution failure via WebSocket and notifications."""
        try:
            from src.api.websocket.manager import ws_manager
            asyncio.create_task(ws_manager.broadcast_to_user(
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
        except Exception:
            pass

        try:
            await self._send_notification(lambda n: n.send_risk_alert(
                alert_type="TRADE_FAILED",
                message=(
                    f"[{self._config.name}] {mode_str} order failed for "
                    f"{signal.symbol} ({signal.direction.value}): {error}"
                ),
            ))
        except Exception:
            pass
