"""Take-profit / stop-loss / trailing update flows for :class:`TradesService`.

Houses both ``update_tp_sl_via_manager`` (the RSM-routed path used when
the feature flag is on) and ``update_tp_sl_legacy`` (the direct
exchange-call path used when RSM is off). Behavior of each method is
preserved verbatim from the pre-extract router handlers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select

from src.bot.risk_state_manager import RiskLeg, RiskOpStatus
from src.models.database import BotConfig, ExchangeConnection, TradeRecord
from src.services._trades_helpers import (
    _build_trailing_intent,
    _derive_overall_status,
    _risk_result_to_outcome,
    _validate_tp_sl_against_trade,
)
from src.services.exceptions import (
    ExchangeConnectionMissing,
    InvalidTpSlIntent,
    TpSlExchangeNotSupported,
    TpSlUpdateFailed,
    TradeNotFound,
    TradeNotOpen,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TpSlMixin:
    """TP/SL/trailing update flows for ``TradesService``."""

    async def update_tp_sl_via_manager(
        self,
        trade_id: int,
        intent,
        *,
        idempotency_key: Optional[str],
        get_risk_state_manager: Callable[[], Any],
        get_idempotency_cache: Callable[[], Any],
        market_data_fetcher_cls: type,
    ):
        """Route a TP/SL/trailing update through :class:`RiskStateManager`.

        The caller (router) owns the feature-flag gate; this method runs
        under the assumption the flag is on. Per-leg try/except is
        load-bearing — a single leg failure must not block the others.

        Raises:
            TradeNotFound: when the trade does not exist or is owned by
                a different user.
            TradeNotOpen: when the trade is not in the ``open`` state.
            InvalidTpSlIntent: when the intent violates a side/entry or
                mutex check (router maps this to 422 on this path).
        """
        from src.services.trades_service import (
            RiskLegOutcome,
            TpSlManagerResult,
        )

        # Mutex checks (remove_X and set_X at the same time)
        if intent.remove_tp and intent.take_profit is not None:
            raise InvalidTpSlIntent("tp_conflict")
        if intent.remove_sl and intent.stop_loss is not None:
            raise InvalidTpSlIntent("sl_conflict")
        if intent.remove_trailing and intent.trailing_callback_pct is not None:
            raise InvalidTpSlIntent("trailing_conflict")

        user_id = self.user.id
        trade_result = await self.db.execute(
            select(TradeRecord).where(
                TradeRecord.id == trade_id,
                TradeRecord.user_id == user_id,
            )
        )
        trade = trade_result.scalar_one_or_none()
        if not trade:
            raise TradeNotFound(trade_id)
        if trade.status != "open":
            raise TradeNotOpen(trade_id)

        _validate_tp_sl_against_trade(intent, trade)

        cache = get_idempotency_cache()
        cache_key: Optional[str] = None
        if idempotency_key:
            cache_key = f"tp_sl:{trade_id}:{idempotency_key}"
            cached = await cache.get(cache_key)
            if cached is not None:
                return cached

        manager = get_risk_state_manager()
        legs: list[tuple[RiskLeg, RiskLegOutcome]] = []

        async def _apply(leg: RiskLeg, value: Any) -> RiskLegOutcome:
            try:
                result = await manager.apply_intent(trade_id, leg, value)
                outcome = _risk_result_to_outcome(result)
            except Exception as exc:  # noqa: BLE001 — surface as REJECTED
                logger.exception(
                    "tp_sl_endpoint manager.apply_intent crashed",
                    extra={
                        "event_type": "tp_sl_endpoint",
                        "trade_id": trade_id,
                        "leg": leg.value,
                        "status": "rejected",
                    },
                )
                outcome = RiskLegOutcome(
                    value=value,
                    status=RiskOpStatus.REJECTED.value,
                    order_id=None,
                    error=str(exc),
                    latency_ms=0,
                )
            logger.info(
                "tp_sl_endpoint leg=%s status=%s latency_ms=%s",
                leg.value, outcome.status, outcome.latency_ms,
                extra={
                    "event_type": "tp_sl_endpoint",
                    "trade_id": trade_id,
                    "leg": leg.value,
                    "status": outcome.status,
                    "latency_ms": outcome.latency_ms,
                },
            )
            return outcome

        # ── TP leg ───────────────────────────────────────────────────
        if intent.remove_tp:
            legs.append((RiskLeg.TP, await _apply(RiskLeg.TP, None)))
        elif intent.take_profit is not None:
            legs.append((RiskLeg.TP, await _apply(RiskLeg.TP, intent.take_profit)))

        # ── SL leg ───────────────────────────────────────────────────
        if intent.remove_sl:
            legs.append((RiskLeg.SL, await _apply(RiskLeg.SL, None)))
        elif intent.stop_loss is not None:
            legs.append((RiskLeg.SL, await _apply(RiskLeg.SL, intent.stop_loss)))

        # ── Trailing leg ─────────────────────────────────────────────
        if intent.remove_trailing:
            legs.append((RiskLeg.TRAILING, await _apply(RiskLeg.TRAILING, None)))
        elif intent.trailing_callback_pct is not None:
            trailing_value = await _build_trailing_intent(
                trade=trade,
                callback_pct=intent.trailing_callback_pct,
                market_data_fetcher_cls=market_data_fetcher_cls,
            )
            legs.append(
                (RiskLeg.TRAILING, await _apply(RiskLeg.TRAILING, trailing_value))
            )

        leg_dict: dict[RiskLeg, RiskLegOutcome] = dict(legs)
        overall = _derive_overall_status(list(leg_dict.values()))

        if overall == "partial_success":
            logger.warning(
                "tp_sl_endpoint partial_success trade=%s legs=%s",
                trade_id,
                {leg.value: status.status for leg, status in legs},
                extra={
                    "event_type": "tp_sl_endpoint",
                    "trade_id": trade_id,
                    "status": overall,
                },
            )

        response = TpSlManagerResult(
            trade_id=trade_id,
            tp=leg_dict.get(RiskLeg.TP),
            sl=leg_dict.get(RiskLeg.SL),
            trailing=leg_dict.get(RiskLeg.TRAILING),
            applied_at=datetime.now(timezone.utc),
            overall_status=overall,
        )

        if cache_key is not None:
            await cache.set(cache_key, response)

        return response

    async def update_tp_sl_legacy(
        self,
        trade_id: int,
        intent,
        *,
        decrypt_value: Callable[[str], str],
        create_exchange_client: Callable[..., Any],
        market_data_fetcher_cls: type,
    ):
        """Update TP/SL on an open position via direct exchange calls.

        The legacy code path that runs when ``risk_state_manager_enabled``
        is off. Behavior is preserved verbatim, including the order of
        operations (cancel then set), the native-trailing-probe branch,
        and the 400/502 split for exchange errors.

        Raises:
            TradeNotFound: unknown trade id or owned by a different user.
            TradeNotOpen: the trade is not open.
            InvalidTpSlIntent: mutex conflict or price/side violation.
            ExchangeConnectionMissing: no connection row, or no API keys.
            TpSlExchangeNotSupported: the client raised ``NotImplementedError``.
            TpSlUpdateFailed: any other exchange-side failure (carries the
                raw error message for router-side 400/502 disambiguation).
        """
        from src.services.trades_service import TpSlLegacyResult

        # Mutex checks — legacy raises 400 (so `InvalidTpSlIntent`
        # short-circuits before DB work).
        if intent.remove_tp and intent.take_profit is not None:
            raise InvalidTpSlIntent("tp_conflict")
        if intent.remove_sl and intent.stop_loss is not None:
            raise InvalidTpSlIntent("sl_conflict")

        user_id = self.user.id
        trade_result = await self.db.execute(
            select(TradeRecord).where(
                TradeRecord.id == trade_id,
                TradeRecord.user_id == user_id,
            ).with_for_update()
        )
        trade = trade_result.scalar_one_or_none()
        if not trade:
            raise TradeNotFound(trade_id)
        if trade.status != "open":
            raise TradeNotOpen(trade_id)
        if trade.entry_price <= 0:
            raise InvalidTpSlIntent("invalid_entry_price")

        _validate_tp_sl_against_trade(intent, trade)

        # Load exchange connection
        conn_result = await self.db.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user_id,
                ExchangeConnection.exchange_type == trade.exchange,
            )
        )
        conn = conn_result.scalar_one_or_none()
        if not conn:
            raise ExchangeConnectionMissing("No exchange connection found")

        api_key_enc = (
            conn.demo_api_key_encrypted if trade.demo_mode else conn.api_key_encrypted
        )
        api_secret_enc = (
            conn.demo_api_secret_encrypted if trade.demo_mode else conn.api_secret_encrypted
        )
        passphrase_enc = (
            conn.demo_passphrase_encrypted if trade.demo_mode else conn.passphrase_encrypted
        )

        if not api_key_enc or not api_secret_enc:
            raise ExchangeConnectionMissing("API keys not configured for this mode")

        client = create_exchange_client(
            exchange_type=trade.exchange,
            api_key=decrypt_value(api_key_enc),
            api_secret=decrypt_value(api_secret_enc),
            passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
            demo_mode=trade.demo_mode,
        )

        # Resolve margin_mode from bot config (defaults to "cross")
        margin_mode = "cross"
        if trade.bot_config_id:
            bot_result = await self.db.execute(
                select(BotConfig.margin_mode).where(
                    BotConfig.id == trade.bot_config_id,
                )
            )
            bot_margin = bot_result.scalar_one_or_none()
            if bot_margin:
                margin_mode = bot_margin

        # Effective TP/SL values (after remove flags)
        effective_tp = (
            None if intent.remove_tp
            else (intent.take_profit if intent.take_profit is not None else trade.take_profit)
        )
        effective_sl = (
            None if intent.remove_sl
            else (intent.stop_loss if intent.stop_loss is not None else trade.stop_loss)
        )

        trailing_placed = False
        exchange_has_trailing: Optional[bool] = None
        fetcher = None
        try:
            has_tp_change = intent.take_profit is not None or intent.remove_tp
            has_sl_change = intent.stop_loss is not None or intent.remove_sl
            if has_tp_change or has_sl_change:
                final_tp = effective_tp
                final_sl = effective_sl

                # Step 1: Cancel ALL old TP/SL on exchange (clean slate)
                await client.cancel_position_tpsl(
                    symbol=trade.symbol,
                    side=trade.side,
                )

                # Step 2: Set new values if any remain
                if final_tp is not None or final_sl is not None:
                    await client.set_position_tpsl(
                        symbol=trade.symbol,
                        take_profit=final_tp,
                        stop_loss=final_sl,
                        side=trade.side,
                        size=trade.size,
                    )

            # Trailing Stop — compute trigger_price and callback from ATR
            if intent.trailing_callback_pct is not None:
                # Always cancel the existing native trailing before placing
                # a new one; otherwise Bitget reports "Insufficient position"
                # because the live moving_plan already reserves the full
                # position size.
                if hasattr(client, "cancel_native_trailing_stop"):
                    try:
                        await client.cancel_native_trailing_stop(
                            trade.symbol, trade.side,
                        )
                    except Exception as cancel_err:
                        logger.debug(
                            "cancel_native_trailing_stop for trade %s failed: %s",
                            trade_id, cancel_err,
                        )

                atr_mult = intent.trailing_callback_pct
                try:
                    fetcher = market_data_fetcher_cls()
                    klines = await fetcher.get_binance_klines(
                        trade.symbol, "1h", 30,
                    )
                    atr_series = market_data_fetcher_cls.calculate_atr(klines, 14)
                    atr_val = (
                        atr_series[-1] if atr_series
                        else trade.entry_price * 0.015
                    )
                except Exception as atr_err:
                    logger.warning(
                        "ATR fetch failed for %s, using 1.5%% estimate: %s",
                        trade.symbol, atr_err,
                    )
                    atr_val = trade.entry_price * 0.015

                trail_distance = atr_val * atr_mult
                callback_pct = (trail_distance / trade.entry_price) * 100
                breakeven_atr = 1.5
                trigger = (
                    trade.entry_price + atr_val * breakeven_atr
                    if trade.side == "long"
                    else trade.entry_price - atr_val * breakeven_atr
                )

                try:
                    trail_order = await client.place_trailing_stop(
                        symbol=trade.symbol,
                        hold_side=trade.side,
                        size=trade.size,
                        callback_ratio=round(callback_pct, 2),
                        trigger_price=round(trigger, 2),
                        margin_mode=margin_mode,
                    )
                    if trail_order is not None:
                        trailing_placed = True
                    else:
                        logger.info(
                            "Native trailing not supported by %s — using software "
                            "trailing for trade %s (ATR override=%sx)",
                            trade.exchange, trade_id, atr_mult,
                        )
                except Exception as trail_err:
                    logger.warning(
                        "Native trailing stop failed for trade %s on %s: %s — "
                        "falling back to software trailing",
                        trade_id, trade.exchange, trail_err,
                    )

            # Authoritative probe before closing the client.
            if getattr(type(client), "SUPPORTS_NATIVE_TRAILING_PROBE", False):
                try:
                    exchange_has_trailing = await client.has_native_trailing_stop(
                        trade.symbol, trade.side,
                    )
                except Exception as probe_err:
                    logger.debug(
                        "has_native_trailing_stop probe failed: %s", probe_err,
                    )
                    exchange_has_trailing = None
        except NotImplementedError:
            raise TpSlExchangeNotSupported(trade.exchange)
        except Exception as e:
            error_msg = str(e)
            logger.error(
                "Failed to set TP/SL on exchange for trade %s: %s",
                trade_id, error_msg,
            )
            raise TpSlUpdateFailed(error_msg)
        finally:
            await client.close()
            if fetcher is not None:
                await fetcher.close()

        # Resolve the authoritative native_trailing_stop state.
        if exchange_has_trailing is None:
            native_state = trailing_placed
        else:
            native_state = exchange_has_trailing
            if exchange_has_trailing and not trailing_placed:
                logger.info(
                    "TP/SL sync: trade %s flagged trailing_placed=False but "
                    "exchange still reports a live moving_plan — keeping "
                    "native_trailing_stop=True",
                    trade_id,
                )
            elif not exchange_has_trailing and trailing_placed:
                logger.warning(
                    "TP/SL sync: place_trailing_stop returned success for trade "
                    "%s but the exchange shows no live moving_plan — "
                    "persisting False",
                    trade_id,
                )

        trade.take_profit = effective_tp
        trade.stop_loss = effective_sl
        if intent.trailing_callback_pct is not None:
            trade.native_trailing_stop = native_state
            trade.trailing_atr_override = intent.trailing_callback_pct
        else:
            # User submitted the form but trailing was off — reflect real
            # exchange state.
            trade.trailing_atr_override = None
            trade.native_trailing_stop = native_state
        await self.db.commit()

        logger.info(
            "TP/SL updated for trade %s: TP=%s, SL=%s, trailing=%s (native=%s)",
            trade_id, effective_tp, effective_sl,
            intent.trailing_callback_pct is not None, trailing_placed,
        )
        return TpSlLegacyResult(
            take_profit=intent.take_profit,
            stop_loss=intent.stop_loss,
            trailing_stop_placed=trailing_placed,
            trailing_stop_software=(
                intent.trailing_callback_pct is not None and not trailing_placed
            ),
        )
