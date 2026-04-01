"""Trade history endpoints (user-scoped)."""

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.trade import TradeListResponse, TradeResponse
from src.auth.dependencies import get_current_user
from src.data.market_data import MarketDataFetcher
from src.exchanges.factory import create_exchange_client
from src.models.database import BotConfig, ExchangeConnection, TradeRecord, User, UserConfig
from src.models.session import get_db
from src.strategy.edge_indicator import DEFAULTS as EDGE_DEFAULTS
from src.utils.encryption import decrypt_value
from src.api.rate_limit import limiter
from src.errors import (
    ERR_SL_ABOVE_ENTRY_SHORT,
    ERR_SL_BELOW_ENTRY_LONG,
    ERR_SL_POSITIVE,
    ERR_TP_ABOVE_ENTRY_LONG,
    ERR_TP_BELOW_ENTRY_SHORT,
    ERR_TP_POSITIVE,
    ERR_TP_SL_CONFLICT_SL,
    ERR_TP_SL_CONFLICT_TP,
    ERR_TPSL_EXCHANGE_NOT_SUPPORTED,
    ERR_TPSL_UPDATE_FAILED,
    ERR_TRADE_NOT_FOUND,
    translate_exchange_error,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def _compute_trailing_stop(
    trade: TradeRecord,
    strategy_type: Optional[str],
    strategy_params_json: Optional[str],
    klines_cache: Optional[dict] = None,
) -> dict:
    """Compute live trailing stop fields for an open trade.

    Returns a dict with keys matching TradeResponse trailing stop fields.
    Only computes for edge_indicator strategy with trailing_stop_enabled.

    Args:
        klines_cache: Optional pre-fetched klines keyed by symbol.
            When provided, avoids per-trade Binance API calls.
    """
    if trade.status != "open":
        return {}

    # Manual override takes precedence — works without a bot strategy
    has_manual_override = trade.trailing_atr_override is not None
    has_strategy = strategy_type == "edge_indicator"

    if not has_manual_override and not has_strategy:
        return {}

    # Merge strategy defaults with custom params
    params = dict(EDGE_DEFAULTS)
    if strategy_params_json:
        try:
            params.update(json.loads(strategy_params_json))
        except (json.JSONDecodeError, TypeError):
            pass

    if not has_manual_override and not params.get("trailing_stop_enabled", True):
        return {}

    highest_price = trade.highest_price
    if highest_price is None:
        return {"trailing_stop_active": False, "can_close_at_loss": True}

    # Fetch klines for ATR calculation (use cache if available)
    atr_period = params.get("atr_period", 14)
    interval = params.get("kline_interval", "1h")
    if klines_cache is not None and trade.symbol in klines_cache:
        klines = klines_cache[trade.symbol]
    else:
        try:
            fetcher = MarketDataFetcher()
            klines = await fetcher.get_binance_klines(
                trade.symbol, interval, atr_period + 15,
            )
            await fetcher.close()
        except Exception as exc:
            logger.debug("Trailing stop kline fetch failed for %s: %s", trade.symbol, exc)
            return {"trailing_stop_active": False}

    if not klines:
        return {"trailing_stop_active": False}

    atr_series = MarketDataFetcher.calculate_atr(klines, atr_period)
    atr_val = atr_series[-1] if atr_series else trade.entry_price * 0.015

    breakeven_atr = params.get("trailing_breakeven_atr", 1.5)
    # Manual ATR override takes precedence over strategy default
    trail_atr = trade.trailing_atr_override if trade.trailing_atr_override is not None else params.get("trailing_trail_atr", 2.5)
    breakeven_threshold = atr_val * breakeven_atr
    trail_distance = atr_val * trail_atr

    side = trade.side
    entry = trade.entry_price

    if side == "long":
        was_profitable = (highest_price - entry) >= breakeven_threshold
        if was_profitable:
            trailing_stop = max(highest_price - trail_distance, entry)
            distance = highest_price - trailing_stop
            distance_pct = (distance / highest_price) * 100 if highest_price else 0
            return {
                "trailing_stop_active": True,
                "trailing_stop_price": round(trailing_stop, 2),
                "trailing_stop_distance": round(distance, 2),
                "trailing_stop_distance_pct": round(distance_pct, 2),
                "can_close_at_loss": False,
            }
        return {"trailing_stop_active": False, "trailing_stop_distance_pct": round(trail_atr, 1), "can_close_at_loss": True}
    else:
        # SHORT: highest_price tracks the lowest price since entry
        was_profitable = (entry - highest_price) >= breakeven_threshold
        if was_profitable:
            trailing_stop = min(highest_price + trail_distance, entry)
            distance = trailing_stop - highest_price
            distance_pct = (distance / highest_price) * 100 if highest_price else 0
            return {
                "trailing_stop_active": True,
                "trailing_stop_price": round(trailing_stop, 2),
                "trailing_stop_distance": round(distance, 2),
                "trailing_stop_distance_pct": round(distance_pct, 2),
                "can_close_at_loss": False,
            }
        return {"trailing_stop_active": False, "trailing_stop_distance_pct": round(trail_atr, 1), "can_close_at_loss": True}

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=TradeListResponse)
@limiter.limit("60/minute")
async def list_trades(
    request: Request,
    status: Optional[str] = Query(None, pattern="^(open|closed|cancelled)$"),
    symbol: Optional[str] = None,
    exchange: Optional[str] = None,
    bot_name: Optional[str] = None,
    date_from: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    demo_mode: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List trades for the current user with filters."""
    query = (
        select(
            TradeRecord,
            BotConfig.name.label("bot_name"),
            BotConfig.exchange_type.label("bot_exchange"),
            BotConfig.strategy_type.label("strategy_type"),
            BotConfig.strategy_params.label("strategy_params"),
        )
        .outerjoin(BotConfig, TradeRecord.bot_config_id == BotConfig.id)
        .where(TradeRecord.user_id == user.id)
    )

    if status:
        query = query.where(TradeRecord.status == status)
    if symbol:
        safe_symbol = symbol.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(TradeRecord.symbol.ilike(f"%{safe_symbol}%", escape="\\"))
    if exchange:
        query = query.where(BotConfig.exchange_type == exchange)
    if bot_name:
        query = query.where(BotConfig.name == bot_name)
    if date_from:
        query = query.where(TradeRecord.entry_time >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.where(TradeRecord.entry_time < datetime.fromisoformat(date_to + "T23:59:59"))
    if demo_mode is not None:
        query = query.where(TradeRecord.demo_mode == demo_mode)

    # Count total
    count_base = (
        select(TradeRecord.id)
        .outerjoin(BotConfig, TradeRecord.bot_config_id == BotConfig.id)
        .where(TradeRecord.user_id == user.id)
    )
    if status:
        count_base = count_base.where(TradeRecord.status == status)
    if symbol:
        count_base = count_base.where(TradeRecord.symbol.ilike(f"%{safe_symbol}%", escape="\\"))
    if exchange:
        count_base = count_base.where(BotConfig.exchange_type == exchange)
    if bot_name:
        count_base = count_base.where(BotConfig.name == bot_name)
    if date_from:
        count_base = count_base.where(TradeRecord.entry_time >= datetime.fromisoformat(date_from))
    if date_to:
        count_base = count_base.where(TradeRecord.entry_time < datetime.fromisoformat(date_to + "T23:59:59"))
    if demo_mode is not None:
        count_base = count_base.where(TradeRecord.demo_mode == demo_mode)
    count_query = select(func.count()).select_from(count_base.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(TradeRecord.entry_time.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    rows = result.all()

    # Pre-fetch klines for all unique symbols with open trades (avoids N+1 API calls)
    klines_cache: dict = {}
    open_symbols = {t.symbol for t, _, _, strat_type, _ in rows if t.status == "open" and strat_type == "edge_indicator"}
    if open_symbols:
        fetcher = MarketDataFetcher()
        try:
            for sym in open_symbols:
                try:
                    klines = await fetcher.get_binance_klines(sym, "1h", 14 + 15)
                    klines_cache[sym] = klines
                except Exception as exc:
                    logger.debug("Batch kline fetch failed for %s: %s", sym, exc)
        finally:
            await fetcher.close()

    # Build responses and enrich open trades with trailing stop info
    trades_out: list[TradeResponse] = []
    for t, bot_name_val, bot_exchange_val, strat_type, strat_params in rows:
        ts_info: dict = {}
        if t.status == "open":
            try:
                ts_info = await _compute_trailing_stop(t, strat_type, strat_params, klines_cache)
            except Exception as exc:
                logger.debug("Trailing stop enrichment failed for trade %s: %s", t.id, exc)

        trades_out.append(TradeResponse(
            id=t.id,
            symbol=t.symbol,
            side=t.side,
            size=t.size,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            take_profit=t.take_profit,
            stop_loss=t.stop_loss,
            leverage=t.leverage,
            confidence=t.confidence,
            reason=t.reason,
            status=t.status,
            pnl=t.pnl,
            pnl_percent=t.pnl_percent,
            fees=t.fees or 0,
            funding_paid=t.funding_paid or 0,
            entry_time=t.entry_time.isoformat() if t.entry_time else "",
            exit_time=t.exit_time.isoformat() if t.exit_time else None,
            exit_reason=t.exit_reason,
            exchange=t.exchange,
            demo_mode=t.demo_mode,
            bot_name=bot_name_val,
            bot_exchange=bot_exchange_val,
            **ts_info,
        ))

    return TradeListResponse(
        trades=trades_out,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/sync")
@limiter.limit("5/minute")
async def sync_trades(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync open trades with the exchange — close any that no longer exist on the exchange."""
    # 1. Get all open trades
    result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.user_id == user.id,
            TradeRecord.status == "open",
        )
    )
    open_trades = list(result.scalars().all())

    if not open_trades:
        return {"synced": 0, "closed_trades": []}

    # 2. Group trades by exchange
    trades_by_exchange: dict[str, list[TradeRecord]] = defaultdict(list)
    for trade in open_trades:
        trades_by_exchange[trade.exchange].append(trade)

    closed_trades = []

    # 3. Per exchange: check positions
    for exchange_type, trades in trades_by_exchange.items():
        # Get exchange connection
        conn_result = await db.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user.id,
                ExchangeConnection.exchange_type == exchange_type,
            )
        )
        conn = conn_result.scalar_one_or_none()
        if not conn:
            logger.warning(f"Sync: no connection for {exchange_type}, skipping {len(trades)} trades")
            continue

        # Create exchange client (prefer demo keys, then live)
        if conn.demo_api_key_encrypted:
            api_key = decrypt_value(conn.demo_api_key_encrypted)
            api_secret = decrypt_value(conn.demo_api_secret_encrypted)
            passphrase = decrypt_value(conn.demo_passphrase_encrypted) if conn.demo_passphrase_encrypted else ""
            demo_mode = True
        elif conn.api_key_encrypted:
            api_key = decrypt_value(conn.api_key_encrypted)
            api_secret = decrypt_value(conn.api_secret_encrypted)
            passphrase = decrypt_value(conn.passphrase_encrypted) if conn.passphrase_encrypted else ""
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
            # Get all open positions from exchange
            exchange_positions = await client.get_open_positions()

            # Build set of (symbol, side) tuples for quick lookup
            open_on_exchange = {
                (pos.symbol, pos.side) for pos in exchange_positions
            }

            # Check each trade
            for trade in trades:
                if (trade.symbol, trade.side) in open_on_exchange:
                    continue  # Still open on exchange

                # Position no longer exists — close the trade
                try:
                    # Try to get current price for PnL calculation
                    ticker = await client.get_ticker(trade.symbol)
                    exit_price = ticker.last_price

                    # Determine exit reason from price proximity
                    if trade.take_profit and abs(exit_price - trade.take_profit) < trade.entry_price * 0.005:
                        exit_reason = "TAKE_PROFIT"
                    elif trade.stop_loss and abs(exit_price - trade.stop_loss) < trade.entry_price * 0.005:
                        exit_reason = "STOP_LOSS"
                    else:
                        exit_reason = "MANUAL_CLOSE"

                    # Calculate PnL
                    from src.bot.pnl import calculate_pnl
                    pnl, pnl_percent = calculate_pnl(trade.side, trade.entry_price, exit_price, trade.size)

                    # Fetch trading fees from exchange (entry + exit via orders-history)
                    try:
                        if trade.order_id:
                            trade.fees = await client.get_trade_total_fees(
                                symbol=trade.symbol,
                                entry_order_id=trade.order_id,
                                close_order_id=trade.close_order_id,
                            )
                    except Exception as e:
                        logger.warning("Failed to fetch trading fees for trade %s: %s", trade.id, e)

                    # Fetch funding fees (charged every 8h while position was open)
                    try:
                        if trade.entry_time:
                            entry_ms = int(trade.entry_time.timestamp() * 1000)
                            exit_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                            trade.funding_paid = await client.get_funding_fees(
                                symbol=trade.symbol,
                                start_time_ms=entry_ms,
                                end_time_ms=exit_ms,
                            )
                    except Exception as e:
                        logger.warning("Failed to fetch funding fees for trade %s: %s", trade.id, e)

                    # Update trade record
                    trade.status = "closed"
                    trade.exit_price = exit_price
                    trade.pnl = round(pnl, 4)
                    trade.pnl_percent = round(pnl_percent, 2)
                    trade.exit_time = datetime.now(timezone.utc)
                    trade.exit_reason = exit_reason

                    closed_trades.append({
                        "id": trade.id,
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "exit_price": exit_price,
                        "pnl": round(pnl, 2),
                        "exit_reason": exit_reason,
                    })

                    logger.info(
                        f"Sync: closed trade #{trade.id} {trade.symbol} {trade.side} "
                        f"| {exit_reason} | PnL: ${pnl:.2f} ({pnl_percent:+.2f}%)"
                    )
                except Exception as e:
                    logger.error(f"Sync: failed to close trade #{trade.id}: {e}")

        except Exception as e:
            logger.error(f"Sync: failed to query {exchange_type} positions: {e}")
        finally:
            await client.close()

    await db.flush()

    # Send Discord notifications for closed trades
    if closed_trades:
        cfg_result = await db.execute(
            select(UserConfig).where(UserConfig.user_id == user.id)
        )
        config = cfg_result.scalar_one_or_none()

        if config and config.discord_webhook_url:
            try:
                webhook_url = decrypt_value(config.discord_webhook_url)
            except (ValueError, Exception):
                webhook_url = None

            if webhook_url:
                from src.notifications.discord_notifier import DiscordNotifier
                notifier = DiscordNotifier(webhook_url=webhook_url)
                try:
                    for ct in closed_trades:
                        matching = [t for t in open_trades if t.id == ct["id"]]
                        if not matching:  # pragma: no cover — notify loop skip
                            continue
                        trade = matching[0]

                        duration_minutes = None
                        if trade.entry_time:
                            entry = trade.entry_time
                            if entry.tzinfo is None:
                                entry = entry.replace(tzinfo=timezone.utc)
                            duration = datetime.now(timezone.utc) - entry
                            duration_minutes = int(duration.total_seconds() / 60)

                        await notifier.send_trade_exit(
                            symbol=trade.symbol,
                            side=trade.side,
                            size=trade.size,
                            entry_price=trade.entry_price,
                            exit_price=trade.exit_price,
                            pnl=trade.pnl,
                            pnl_percent=trade.pnl_percent,
                            fees=trade.fees or 0,
                            funding_paid=trade.funding_paid or 0,
                            reason=trade.exit_reason,
                            order_id=trade.order_id,
                            duration_minutes=duration_minutes,
                            demo_mode=trade.demo_mode,
                            strategy_reason=trade.reason,
                        )
                except Exception as e:
                    logger.warning(f"Discord sync notification failed: {e}")
                finally:
                    await notifier.close()

    return {"synced": len(closed_trades), "closed_trades": closed_trades}


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(
    trade_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific trade."""

    result = await db.execute(
        select(
            TradeRecord,
            BotConfig.name.label("bot_name"),
            BotConfig.exchange_type.label("bot_exchange"),
            BotConfig.strategy_type.label("strategy_type"),
            BotConfig.strategy_params.label("strategy_params"),
        )
        .outerjoin(BotConfig, TradeRecord.bot_config_id == BotConfig.id)
        .where(TradeRecord.id == trade_id, TradeRecord.user_id == user.id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=ERR_TRADE_NOT_FOUND)

    trade, bot_name, bot_exchange, strat_type, strat_params = row

    ts_info: dict = {}
    if trade.status == "open":
        try:
            ts_info = await _compute_trailing_stop(trade, strat_type, strat_params)
        except Exception as exc:
            logger.debug("Trailing stop enrichment failed for trade %s: %s", trade.id, exc)

    return TradeResponse(
        id=trade.id,
        symbol=trade.symbol,
        side=trade.side,
        size=trade.size,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        take_profit=trade.take_profit,
        stop_loss=trade.stop_loss,
        leverage=trade.leverage,
        confidence=trade.confidence,
        reason=trade.reason,
        status=trade.status,
        pnl=trade.pnl,
        pnl_percent=trade.pnl_percent,
        fees=trade.fees or 0,
        funding_paid=trade.funding_paid or 0,
        entry_time=trade.entry_time.isoformat() if trade.entry_time else "",
        exit_time=trade.exit_time.isoformat() if trade.exit_time else None,
        exit_reason=trade.exit_reason,
        exchange=trade.exchange,
        demo_mode=trade.demo_mode,
        bot_name=bot_name,
        bot_exchange=bot_exchange,
        **ts_info,
    )


# ---------------------------------------------------------------------------
# Update TP/SL on an open position
# ---------------------------------------------------------------------------

from pydantic import BaseModel as PydanticBaseModel, field_validator


class TrailingStopParams(PydanticBaseModel):
    callback_pct: float  # ATR multiplier (e.g., 2.5 = 2.5x ATR)

    @field_validator("callback_pct")
    @classmethod
    def validate_atr_range(cls, v: float) -> float:
        if v < 1.0 or v > 5.0:
            raise ValueError("ATR multiplier must be between 1.0 and 5.0")
        return v


class UpdateTpSlRequest(PydanticBaseModel):
    model_config = {"extra": "forbid"}

    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    remove_tp: bool = False
    remove_sl: bool = False
    trailing_stop: Optional[TrailingStopParams] = None


@router.put("/{trade_id}/tp-sl")
@limiter.limit("10/minute")
async def update_trade_tpsl(
    trade_id: int,
    body: UpdateTpSlRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update TP/SL on an open position — sets on exchange + updates DB."""

    # Reject contradictory flags
    if body.remove_tp and body.take_profit is not None:
        raise HTTPException(status_code=400, detail=ERR_TP_SL_CONFLICT_TP)
    if body.remove_sl and body.stop_loss is not None:
        raise HTTPException(status_code=400, detail=ERR_TP_SL_CONFLICT_SL)

    # Load trade with row-level lock to prevent race conditions
    trade_result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.id == trade_id,
            TradeRecord.user_id == user.id,
        ).with_for_update()
    )
    trade = trade_result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail=ERR_TRADE_NOT_FOUND)
    if trade.status != "open":
        raise HTTPException(status_code=400, detail="Trade is not open")
    if trade.entry_price <= 0:
        raise HTTPException(status_code=400, detail="Trade has invalid entry price")

    # Validate TP/SL values
    is_long = trade.side == "long"
    if body.take_profit is not None:
        if body.take_profit <= 0:
            raise HTTPException(status_code=400, detail=ERR_TP_POSITIVE)
        if is_long and body.take_profit <= trade.entry_price:
            raise HTTPException(status_code=400, detail=ERR_TP_ABOVE_ENTRY_LONG)
        if not is_long and body.take_profit >= trade.entry_price:
            raise HTTPException(status_code=400, detail=ERR_TP_BELOW_ENTRY_SHORT)
    if body.stop_loss is not None:
        if body.stop_loss <= 0:
            raise HTTPException(status_code=400, detail=ERR_SL_POSITIVE)
        if is_long and body.stop_loss >= trade.entry_price:
            raise HTTPException(status_code=400, detail=ERR_SL_BELOW_ENTRY_LONG)
        if not is_long and body.stop_loss <= trade.entry_price:
            raise HTTPException(status_code=400, detail=ERR_SL_ABOVE_ENTRY_SHORT)

    # Load exchange connection
    conn_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == trade.exchange,
        )
    )
    conn = conn_result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=400, detail="No exchange connection found")

    # Create exchange client
    api_key_enc = conn.demo_api_key_encrypted if trade.demo_mode else conn.api_key_encrypted
    api_secret_enc = conn.demo_api_secret_encrypted if trade.demo_mode else conn.api_secret_encrypted
    passphrase_enc = conn.demo_passphrase_encrypted if trade.demo_mode else conn.passphrase_encrypted

    if not api_key_enc or not api_secret_enc:
        raise HTTPException(status_code=400, detail="API keys not configured for this mode")

    client = create_exchange_client(
        exchange_type=trade.exchange,
        api_key=decrypt_value(api_key_enc),
        api_secret=decrypt_value(api_secret_enc),
        passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
        demo_mode=trade.demo_mode,
    )

    # Resolve margin_mode from bot config
    margin_mode = "cross"
    if trade.bot_config_id:
        bot_result = await db.execute(
            select(BotConfig.margin_mode).where(BotConfig.id == trade.bot_config_id)
        )
        bot_margin = bot_result.scalar_one_or_none()
        if bot_margin:
            margin_mode = bot_margin

    # For DB: resolve final TP/SL values
    effective_tp = None if body.remove_tp else (body.take_profit if body.take_profit is not None else trade.take_profit)
    effective_sl = None if body.remove_sl else (body.stop_loss if body.stop_loss is not None else trade.stop_loss)

    # Set TP/SL on exchange
    trailing_placed = False
    fetcher = None
    try:
        has_tp_change = body.take_profit is not None or body.remove_tp
        has_sl_change = body.stop_loss is not None or body.remove_sl
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
        if body.trailing_stop is not None:
            atr_mult = body.trailing_stop.callback_pct
            try:
                fetcher = MarketDataFetcher()
                klines = await fetcher.get_binance_klines(trade.symbol, "1h", 30)
                atr_series = MarketDataFetcher.calculate_atr(klines, 14)
                atr_val = atr_series[-1] if atr_series else trade.entry_price * 0.015
            except Exception as atr_err:
                logger.warning("ATR fetch failed for %s, using 1.5%% estimate: %s", trade.symbol, atr_err)
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
                        "Native trailing not supported by %s — using software trailing for trade %s (ATR override=%sx)",
                        trade.exchange, trade_id, atr_mult,
                    )
            except Exception as trail_err:
                logger.warning(
                    "Native trailing stop failed for trade %s on %s: %s — falling back to software trailing",
                    trade_id, trade.exchange, trail_err,
                )
    except NotImplementedError:
        raise HTTPException(
            status_code=400,
            detail=ERR_TPSL_EXCHANGE_NOT_SUPPORTED.format(exchange=trade.exchange),
        )
    except Exception as e:
        error_msg = str(e)
        logger.error("Failed to set TP/SL on exchange for trade %s: %s", trade_id, error_msg)
        # Surface exchange validation errors as 400 (user can fix), not 502
        exchange_hints = ["price", "less than", "greater than", "invalid", "must be", "should be"]
        if any(hint in error_msg.lower() for hint in exchange_hints):
            raise HTTPException(status_code=400, detail=translate_exchange_error(error_msg))
        raise HTTPException(status_code=502, detail=ERR_TPSL_UPDATE_FAILED)
    finally:
        await client.close()
        if fetcher:
            await fetcher.close()

    # Update DB
    trade.take_profit = effective_tp
    trade.stop_loss = effective_sl
    if body.trailing_stop is not None:
        trade.native_trailing_stop = trailing_placed
        trade.trailing_atr_override = body.trailing_stop.callback_pct
    else:
        # User submitted the form but trailing was off — clear any previous override
        trade.trailing_atr_override = None
        trade.native_trailing_stop = False
    await db.commit()

    logger.info(
        "TP/SL updated for trade %s: TP=%s, SL=%s, trailing=%s (native=%s)",
        trade_id, effective_tp, effective_sl,
        body.trailing_stop is not None, trailing_placed,
    )
    return {
        "status": "ok",
        "take_profit": body.take_profit,
        "stop_loss": body.stop_loss,
        "trailing_stop_placed": trailing_placed,
        "trailing_stop_software": body.trailing_stop is not None and not trailing_placed,
    }
