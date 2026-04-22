"""Trade-execution orchestration (ARCH-H1 Phase 1 PR-5, #72).

Extracted from ``TradeExecutorMixin`` so the order-placement and
pending-trade-resolution flow is composition-owned and independently
testable. The mixin is kept as a thin proxy until the Phase 1 finalize
PR removes all mixin shims.

The component exposes the five public entry points that the rest of the
``BotWorker`` stack calls into:

* ``execute(signal, client, demo_mode, asset_budget)`` — the main
  market-order + TP/SL + native-trailing pipeline.
* ``resolve_pending_trade(pending_id, status, error)`` — flips a row in
  ``PendingTrade`` to its terminal state.
* ``notify_trade_failure(signal, mode, error)`` — WS broadcast + risk
  alert + optional fatal-pause.
* ``get_open_trades_count(bot_config_id)`` / ``get_open_trades_for_bot``
  — simple DB helpers reused by self-managed strategies.
* ``execute_wrapper(...)`` / ``close_by_strategy(...)`` — the
  public-facing wrappers the copy-trading strategy depends on.

Dependencies (``_config``, ``_risk_manager``, ``_close_and_record_trade``,
``_send_notification``, the live exchange ``client``) are injected via
getter callables because they are attached to ``BotWorker`` at different
lifecycle points. The worker-level side effects that the mixin used to
mutate directly (``self.trades_today += 1`` and the fatal-error status
flip) are delivered through ``on_trade_opened`` / ``on_fatal_error``
callbacks so the component stays free of worker-state knowledge.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from src.bot.event_bus import (
    EVENT_TRADE_OPENED,
    build_trade_snapshot,
    publish_trade_event,
)
from src.exceptions import ExchangeError, OrderError
from src.exchanges.base import ExchangeClient
from src.models.database import PendingTrade, TradeRecord
from src.models.session import get_session
from src.strategy import TradeSignal
from src.utils.json_helpers import parse_json_field
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Patterns that indicate a fatal configuration error (bot should pause).
_FATAL_ERROR_PATTERNS = [
    "does not exist",
    "invalid api key",
    "invalid api-key",
    "api key expired",
    "key is disabled",
    "invalid signature",
    "not whitelisted",
    "not allowed",
    "wallet not found",
    "account not found",
    "account suspended",
    "account frozen",
    "account disabled",
    "account locked",
    "sub-account not found",
    "unauthorized",
    "permission denied",
    "forbidden",
]

# User-friendly error messages mapped from raw exchange errors.
_USER_FRIENDLY_ERRORS = [
    (r"User or API Wallet (0x[a-fA-F0-9]+) does not exist",
     lambda m: (
         f"Dein Hyperliquid-Wallet ({m.group(1)[:8]}...{m.group(1)[-4:]}) wurde nicht gefunden. "
         "Bitte stelle sicher, dass du auf Hyperliquid mindestens eine Einzahlung gemacht hast, "
         "damit dein Wallet aktiviert ist. Falls du ein API-Wallet nutzt, erstelle es zuerst "
         "unter app.hyperliquid.xyz > API Wallet."
     )),
    (r"(?i)(insufficient|not enough).*(balance|margin|fund)",
     lambda m: "Nicht genügend Guthaben auf deinem Exchange-Konto. Bitte zahle Guthaben ein oder reduziere die Positionsgröße."),
    (r"(?i)(rate.?limit|too many requests|429)",
     lambda m: "Zu viele Anfragen an die Exchange-API. Der Bot wird es beim nächsten Zyklus erneut versuchen."),
    (r"(?i)API temporarily unavailable",
     lambda m: "Die Exchange-API ist vorübergehend nicht erreichbar. Der Bot versucht es automatisch erneut."),
    (r"(?i)(invalid api.?key|api.?key.*expired|key is disabled|invalid signature)",
     lambda m: "Dein API-Key ist ungültig oder abgelaufen. Bitte prüfe deine API-Zugangsdaten in den Einstellungen."),
    (r"(?i)ip.*(not|isn).*(whitelist|allowed)",
     lambda m: "Die Server-IP ist nicht in deiner API-Key Whitelist. Bitte füge sie in deinen Exchange-Einstellungen hinzu."),
    (r"(?i)(position.*already|leverage.*conflict|cannot change leverage)",
     lambda m: "Es existiert bereits eine offene Position mit anderer Konfiguration. Schließe die bestehende Position zuerst."),
    (r"(?i)(minimum.*(amount|order|size)|order.*too small)",
     lambda m: "Die Ordergröße ist unter dem Mindestbetrag der Exchange. Erhöhe dein Budget oder reduziere die Anzahl der Trading-Paare."),
    (r"(?i)liquidation.?prevention",
     lambda m: "Die Order wurde abgelehnt, da sie zu einer Liquidation führen könnte. Reduziere den Hebel oder die Positionsgröße."),
    (r"(?i)(account.*(suspend|frozen|disabled|locked))",
     lambda m: "Dein Exchange-Konto ist gesperrt oder eingeschränkt. Bitte prüfe deinen Account direkt bei der Exchange."),
]


def _make_user_friendly(raw_error: str) -> str:
    """Convert raw exchange error to a user-friendly message."""
    for pattern, formatter in _USER_FRIENDLY_ERRORS:
        match = re.search(pattern, raw_error)
        if match:
            return formatter(match)
    return raw_error


def _is_fatal_error(error_msg: str) -> bool:
    """True if the error indicates a configuration problem that won't self-resolve."""
    lower = error_msg.lower()
    return any(p in lower for p in _FATAL_ERROR_PATTERNS)


async def _noop_async(*_args, **_kwargs) -> None:  # pragma: no cover - defensive default
    return None


class TradeExecutor:
    """Orchestrates order placement, pending-trade bookkeeping, and failure notifications."""

    def __init__(
        self,
        bot_config_id: int,
        config_getter: Callable[[], Optional[Any]],
        risk_manager_getter: Callable[[], Any],
        close_trade: Callable[..., Awaitable[None]],
        notification_sender: Callable[..., Awaitable[None]],
        client_getter: Callable[[], Optional[ExchangeClient]],
        on_trade_opened: Callable[[], None],
        on_fatal_error: Callable[[str], None],
    ) -> None:
        self._bot_config_id = bot_config_id
        self._get_config = config_getter
        self._get_risk_manager = risk_manager_getter
        self._close_trade = close_trade
        self._send_notification = notification_sender
        self._get_client = client_getter
        self._on_trade_opened = on_trade_opened
        self._on_fatal_error = on_fatal_error

    # ----- main executor -------------------------------------------------

    async def execute(
        self,
        signal: TradeSignal,
        client: ExchangeClient,
        demo_mode: bool,
        asset_budget: Optional[float] = None,
    ) -> None:
        """Place a market order for ``signal``, persist the trade, and broadcast."""
        config = self._get_config()
        log_prefix = f"[Bot:{self._bot_config_id}]"
        mode_str = "DEMO" if demo_mode else "LIVE"

        per_asset_cfg = parse_json_field(
            config.per_asset_config,
            field_name="per_asset_config",
            context=f"bot {self._bot_config_id}",
            default={},
        )
        asset_cfg = per_asset_cfg.get(signal.symbol, {})

        leverage = asset_cfg.get("leverage") or config.leverage or 1

        tp_pct = (
            asset_cfg.get("tp")
            or asset_cfg.get("take_profit_percent")
            or getattr(config, "take_profit_percent", None)
        )
        sl_pct = (
            asset_cfg.get("sl")
            or asset_cfg.get("stop_loss_percent")
            or getattr(config, "stop_loss_percent", None)
        )

        is_long = signal.direction.value == "long"
        caller_tp = signal.target_price
        caller_sl = signal.stop_loss
        if caller_tp is not None:
            pass
        elif tp_pct and signal.entry_price and signal.entry_price > 0:
            signal.target_price = (
                signal.entry_price * (1 + tp_pct / 100)
                if is_long
                else signal.entry_price * (1 - tp_pct / 100)
            )
        else:
            signal.target_price = None

        if caller_sl is not None:
            pass
        elif sl_pct and signal.entry_price and signal.entry_price > 0:
            signal.stop_loss = (
                signal.entry_price * (1 - sl_pct / 100)
                if is_long
                else signal.entry_price * (1 + sl_pct / 100)
            )

        pending_trade_id: Optional[int] = None
        try:
            if not signal.entry_price or signal.entry_price <= 0:
                logger.warning(f"{log_prefix} [{mode_str}] Invalid entry price: {signal.entry_price}")
                return

            risk_manager = self._get_risk_manager()
            can_trade, deny_reason = risk_manager.can_trade(signal.symbol)
            if not can_trade:
                logger.warning(f"{log_prefix} [{mode_str}] Trade denied at execution: {deny_reason}")
                return

            if asset_budget is not None:
                available = asset_budget
            else:
                balance = await client.get_account_balance()
                available = balance.available

            if asset_budget is not None:
                usable = available * 0.95
                position_usdt = usable
                position_size = (usable * leverage) / signal.entry_price
            else:
                position_usdt, position_size = risk_manager.calculate_position_size(
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

            margin_mode = getattr(config, "margin_mode", "cross")
            leverage_ok = await client.set_leverage(signal.symbol, leverage, margin_mode=margin_mode)
            if not leverage_ok:
                logger.warning(
                    "%s Cannot set %dx leverage for %s — position may be open with different leverage. Skipping trade.",
                    log_prefix, leverage, signal.symbol,
                )
                return

            if signal.direction.value == "neutral":
                logger.info(f"{log_prefix} [{mode_str}] Skipping NEUTRAL signal for {signal.symbol}")
                return

            side = signal.direction.value
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
                        bot_config_id=self._bot_config_id,
                        user_id=config.user_id,
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
                await self.resolve_pending_trade(pending_trade_id, "failed", "Order returned None")
                return

            if getattr(order, "tpsl_failed", False):
                if hasattr(client, "set_position_tpsl"):
                    try:
                        await asyncio.sleep(0.3)
                        pos = await client.get_position(signal.symbol)
                        if pos:
                            kwargs: dict[str, Any] = {
                                "symbol": signal.symbol,
                                "take_profit": signal.target_price,
                                "stop_loss": signal.stop_loss,
                            }
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

            fill_price = order.price if order.price > 0 else signal.entry_price
            if order.order_id:
                try:
                    actual = await client.get_fill_price(signal.symbol, order.order_id)
                    if actual:
                        fill_price = actual
                except Exception as e:
                    logger.debug(f"{log_prefix} [{mode_str}] Could not fetch fill price: {e}")

            async with get_session() as session:
                trade = TradeRecord(
                    user_id=config.user_id,
                    bot_config_id=self._bot_config_id,
                    exchange=config.exchange_type,
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

                if pending_trade_id is not None:
                    from sqlalchemy import select as sa_select
                    pt_result = await session.execute(
                        sa_select(PendingTrade).where(PendingTrade.id == pending_trade_id)
                    )
                    pending = pt_result.scalar_one_or_none()
                    if pending:
                        pending.status = "completed"
                        pending.resolved_at = datetime.now(timezone.utc)
                    pending_trade_id = None

            risk_manager.record_trade_entry(
                symbol=signal.symbol,
                side=signal.direction.value,
                size=position_size,
                entry_price=fill_price,
                leverage=leverage,
                confidence=signal.confidence,
                reason=signal.reason,
                order_id=order.order_id,
            )

            try:
                self._on_trade_opened()
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("on_trade_opened callback raised: %s", e)

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

            try:
                from src.api.websocket.manager import ws_manager
                task = asyncio.create_task(ws_manager.broadcast_to_user(
                    config.user_id,
                    "trade_opened",
                    {
                        "bot_id": self._bot_config_id,
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

            try:
                publish_trade_event(
                    EVENT_TRADE_OPENED,
                    user_id=config.user_id,
                    trade_id=getattr(trade, "id", None),
                    data=build_trade_snapshot(trade),
                )
            except Exception as e:
                logger.debug("SSE publish failed (trade_opened): %s", e)

            trade_reason = f"[{config.name}] {signal.reason}"
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
                await self.notify_trade_failure(signal, mode_str, str(e))
            await self.resolve_pending_trade(pending_trade_id, "failed", str(e))
        except ExchangeError as e:
            logger.error(f"{log_prefix} [{mode_str}] Trade execution failed: {e}")
            await self.notify_trade_failure(signal, mode_str, str(e))
            await self.resolve_pending_trade(pending_trade_id, "failed", str(e))
        except Exception as e:
            err_msg = str(e).lower()
            if "minimum amount" in err_msg or "minimum order" in err_msg:
                logger.warning(f"{log_prefix} [{mode_str}] Order below exchange minimum: {e}")
            else:
                logger.error(f"{log_prefix} [{mode_str}] Trade execution failed: {e}")
                await self.notify_trade_failure(signal, mode_str, str(e))
            await self.resolve_pending_trade(pending_trade_id, "failed", str(e))

    # ----- pending / failure helpers ------------------------------------

    async def resolve_pending_trade(
        self, pending_trade_id: Optional[int], status: str, error_message: Optional[str] = None,
    ) -> None:
        """Update a ``PendingTrade`` row to its final status."""
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
                self._bot_config_id, pending_trade_id, e,
            )

    async def notify_trade_failure(
        self, signal: TradeSignal, mode_str: str, error: str,
    ) -> None:
        """Notify the user of a trade-execution failure (WS + risk alert + optional fatal pause)."""
        config = self._get_config()
        friendly_error = _make_user_friendly(error)
        is_fatal = _is_fatal_error(error)

        try:
            from src.api.websocket.manager import ws_manager
            task = asyncio.create_task(ws_manager.broadcast_to_user(
                config.user_id,
                "trade_failed",
                {
                    "bot_id": self._bot_config_id,
                    "bot_name": config.name,
                    "symbol": signal.symbol,
                    "side": signal.direction.value,
                    "error": friendly_error,
                    "fatal": is_fatal,
                    "demo_mode": mode_str == "DEMO",
                },
            ))
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)
        except Exception:
            pass

        try:
            alert_type = "TRADE_FAILED_FATAL" if is_fatal else "TRADE_FAILED"
            await self._send_notification(
                lambda n: n.send_risk_alert(
                    alert_type=alert_type,
                    message=(
                        f"[{config.name}] {mode_str} order failed for "
                        f"{signal.symbol} ({signal.direction.value}):\n\n{friendly_error}"
                    ),
                    is_fatal=is_fatal,
                ),
                event_type="error",
                summary=f"TRADE_FAILED {signal.symbol}",
            )
        except Exception:
            pass

        if is_fatal:
            logger.warning(
                "[Bot:%s] Fatal configuration error detected — pausing bot. "
                "User action required: %s",
                self._bot_config_id, friendly_error,
            )
            try:
                self._on_fatal_error(friendly_error)
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("on_fatal_error callback raised: %s", e)

    # ----- public wrappers used by self-managed strategies --------------

    async def get_open_trades_count(self, bot_config_id: int) -> int:
        from sqlalchemy import select, func
        async with get_session() as session:
            result = await session.execute(
                select(func.count(TradeRecord.id)).where(
                    TradeRecord.bot_config_id == bot_config_id,
                    TradeRecord.status == "open",
                )
            )
            return int(result.scalar_one() or 0)

    async def get_open_trades_for_bot(self, bot_config_id: int) -> list:
        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(
                select(TradeRecord).where(
                    TradeRecord.bot_config_id == bot_config_id,
                    TradeRecord.status == "open",
                )
            )
            return list(result.scalars().all())

    async def execute_wrapper(
        self,
        *,
        symbol: str,
        side: str,
        notional_usdt: float,
        leverage: int,
        reason: str,
        bot_config_id: int,
        take_profit_pct: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
    ) -> None:
        """Thin wrapper for self-managed strategies: build a ``TradeSignal`` and run ``execute``."""
        from src.strategy.base import SignalDirection, TradeSignal as _TradeSignal

        client = self._get_client()
        if client is None:
            logger.warning(
                "[Bot:%s] execute_trade: no exchange client available", bot_config_id
            )
            return

        try:
            ticker = await client.get_ticker(symbol)
            price = float(getattr(ticker, "last_price", 0) or 0)
        except Exception as e:
            logger.warning(
                "[Bot:%s] execute_trade: ticker lookup failed for %s: %s",
                bot_config_id, symbol, e,
            )
            return
        if price <= 0:
            return

        direction = (
            SignalDirection.LONG if side.lower() == "long" else SignalDirection.SHORT
        )
        is_long = direction == SignalDirection.LONG
        target_price: Optional[float] = None
        stop_loss: Optional[float] = None
        if take_profit_pct and price > 0:
            target_price = (
                price * (1 + float(take_profit_pct) / 100)
                if is_long
                else price * (1 - float(take_profit_pct) / 100)
            )
        if stop_loss_pct and price > 0:
            stop_loss = (
                price * (1 - float(stop_loss_pct) / 100)
                if is_long
                else price * (1 + float(stop_loss_pct) / 100)
            )
        signal = _TradeSignal(
            direction=direction,
            confidence=100,
            symbol=symbol,
            entry_price=price,
            target_price=target_price,
            stop_loss=stop_loss,
            reason=reason,
            metrics_snapshot={},
            timestamp=datetime.now(timezone.utc),
        )
        config = self._get_config()
        demo_mode = bool(getattr(config, "demo_mode", False)) if config is not None else False
        await self.execute(signal, client, demo_mode, asset_budget=notional_usdt)

    async def close_by_strategy(self, trade: Any, *, reason: str) -> None:
        """Thin wrapper so self-managed strategies can close trades via the injected closer."""
        client = self._get_client()
        exit_price = float(getattr(trade, "entry_price", 0) or 0)
        if client is not None:
            try:
                ticker = await client.get_ticker(trade.symbol)
                px = float(getattr(ticker, "last_price", 0) or 0)
                if px > 0:
                    exit_price = px
            except Exception:
                pass

        await self._close_trade(
            trade, exit_price=exit_price, exit_reason=reason, strategy_reason=reason,
        )
