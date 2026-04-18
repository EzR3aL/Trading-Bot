"""Trade history endpoints (user-scoped)."""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from src.api.dependencies.risk_state import (
    get_idempotency_cache,
    get_risk_state_manager,
)
from src.api.schemas.trade import TradeListResponse, TradeResponse
from src.auth.dependencies import get_current_user
from src.bot.risk_state_manager import RiskLeg, RiskOpResult, RiskOpStatus
from src.data.market_data import MarketDataFetcher
from src.exchanges.factory import create_exchange_client
from src.models.database import BotConfig, ExchangeConnection, TradeRecord, User, UserConfig
from src.models.session import get_db
from src.strategy.base import resolve_strategy_params
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


#: Strategies that compute an ATR-based trailing stop for the dashboard display.
TRAILING_STOP_STRATEGIES = ("edge_indicator", "liquidation_hunter")


async def _compute_trailing_stop(
    trade: TradeRecord,
    strategy_type: Optional[str],
    strategy_params_json: Optional[str],
    klines_cache: Optional[dict] = None,
) -> dict:
    """Compute live trailing stop fields for an open trade.

    Returns a dict with keys matching TradeResponse trailing stop fields.
    Uses ``resolve_strategy_params`` so the dashboard's view of the trailing
    stop matches the live strategy exactly (same DEFAULTS → RISK_PROFILE →
    user_params merge, same ``kline_interval``).

    Args:
        klines_cache: Optional pre-fetched klines keyed by ``(symbol, interval)``.
            Must match the resolved strategy interval; otherwise the per-call
            Binance fetch is used instead.
    """
    if trade.status != "open":
        return {}

    # Manual override takes precedence — works without a bot strategy
    has_manual_override = trade.trailing_atr_override is not None
    has_strategy = strategy_type in TRAILING_STOP_STRATEGIES

    if not has_manual_override and not has_strategy:
        return {}

    # Resolve params identically to how the live strategy merges them.
    # This is the parity guarantee: dashboard calc === strategy calc.
    params = resolve_strategy_params(strategy_type, strategy_params_json)

    if not has_manual_override and not params.get("trailing_stop_enabled", True):
        return {}

    highest_price = trade.highest_price
    if highest_price is None:
        return {"trailing_stop_active": False, "can_close_at_loss": True}

    # Fetch klines for ATR calculation (use cache if available, keyed by interval)
    atr_period = params.get("atr_period", 14)
    interval = params.get("kline_interval", "1h")
    cache_key = (trade.symbol, interval)
    if klines_cache is not None and cache_key in klines_cache:
        klines = klines_cache[cache_key]
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

    # Pre-fetch klines for all unique (symbol, interval) pairs with open trades
    # (avoids N+1 API calls). Interval comes from the resolved strategy params
    # so each bot's kline_interval (1h / 4h / ...) is honored correctly.
    klines_cache: dict[tuple[str, str], list] = {}
    prefetch_keys: set[tuple[str, str]] = set()
    for t, _, _, strat_type, strat_params in rows:
        if t.status != "open":
            continue
        if strat_type not in TRAILING_STOP_STRATEGIES and t.trailing_atr_override is None:
            continue
        resolved = resolve_strategy_params(strat_type, strat_params)
        interval = resolved.get("kline_interval", "1h")
        prefetch_keys.add((t.symbol, interval))

    if prefetch_keys:
        fetcher = MarketDataFetcher()
        try:
            for sym, interval in prefetch_keys:
                try:
                    klines_cache[(sym, interval)] = await fetcher.get_binance_klines(sym, interval, 14 + 15)
                except Exception as exc:
                    logger.debug("Batch kline fetch failed for %s %s: %s", sym, interval, exc)
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
                    # Prefer the actual close-order fill price (matches exchange exactly).
                    exit_price = None
                    try:
                        exit_price = await client.get_close_fill_price(trade.symbol)
                    except Exception:
                        pass
                    if not exit_price:
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
    remove_trailing: bool = False


# ── Response schemas (RiskStateManager path, #192) ─────────────────


class RiskLegStatus(PydanticBaseModel):
    """Per-leg outcome surfaced from a RiskStateManager apply_intent call."""

    value: Optional[Any] = None
    status: str  # pending | confirmed | rejected | cleared | cancel_failed
    order_id: Optional[str] = None
    error: Optional[str] = None
    latency_ms: int = 0


class TpSlResponse(PydanticBaseModel):
    """Aggregate response for the new RiskStateManager-backed endpoint."""

    trade_id: int
    tp: Optional[RiskLegStatus] = None
    sl: Optional[RiskLegStatus] = None
    trailing: Optional[RiskLegStatus] = None
    applied_at: datetime
    overall_status: str  # all_confirmed | partial_success | all_rejected | no_change


# ── Helpers for the new endpoint ───────────────────────────────────


# Status codes returned by the RiskStateManager — used to derive the
# aggregate ``overall_status`` and the HTTP response code.
_RISK_OK_STATUSES = {RiskOpStatus.CONFIRMED.value, RiskOpStatus.CLEARED.value}
_RISK_FAIL_STATUSES = {
    RiskOpStatus.REJECTED.value,
    RiskOpStatus.CANCEL_FAILED.value,
}


def _risk_result_to_status(result: RiskOpResult) -> RiskLegStatus:
    """Convert a :class:`RiskOpResult` into the API response shape."""
    return RiskLegStatus(
        value=result.value,
        status=result.status.value,
        order_id=result.order_id,
        error=result.error,
        latency_ms=result.latency_ms,
    )


def _derive_overall_status(legs: list[RiskLegStatus]) -> str:
    """Aggregate per-leg statuses into a single overall outcome label."""
    if not legs:
        return "no_change"
    statuses = [leg.status for leg in legs]
    has_ok = any(s in _RISK_OK_STATUSES for s in statuses)
    has_fail = any(s in _RISK_FAIL_STATUSES for s in statuses)
    if has_ok and not has_fail:
        return "all_confirmed"
    if has_fail and not has_ok:
        return "all_rejected"
    if has_ok and has_fail:
        return "partial_success"
    return "no_change"


async def _compute_atr_for_trailing(
    symbol: str, entry_price: float
) -> float:
    """Fetch ATR for the trailing-stop endpoint.

    Returns the live 1h/14-period ATR if available, otherwise a 1.5%
    fallback based on the trade's entry price. The computation lives in
    the endpoint (not the manager) because ATR depends on a strategy-
    specific kline interval that the manager has no business knowing.
    """
    fetcher = MarketDataFetcher()
    try:
        klines = await fetcher.get_binance_klines(symbol, "1h", 30)
        atr_series = MarketDataFetcher.calculate_atr(klines, 14)
        if atr_series:
            return atr_series[-1]
    except Exception as atr_err:  # noqa: BLE001 — fallback to estimate
        logger.warning(
            "ATR fetch failed for %s, using 1.5%% estimate: %s", symbol, atr_err,
        )
    finally:
        await fetcher.close()
    return entry_price * 0.015


async def _build_trailing_intent(
    trade: TradeRecord, params: TrailingStopParams,
) -> dict:
    """Translate a UI ``TrailingStopParams`` into the manager's payload.

    The manager expects a dict with ``callback_rate``,
    ``activation_price`` and ``trigger_price`` keys (plus an
    ``atr_override`` so we can persist the user's chosen multiplier on
    the trade row through Phase D).
    """
    atr_val = await _compute_atr_for_trailing(trade.symbol, trade.entry_price)
    atr_mult = params.callback_pct
    trail_distance = atr_val * atr_mult
    callback_rate = (trail_distance / trade.entry_price) * 100
    breakeven_atr = 1.5
    if trade.side == "long":
        trigger = trade.entry_price + atr_val * breakeven_atr
    else:
        trigger = trade.entry_price - atr_val * breakeven_atr
    return {
        "callback_rate": round(callback_rate, 2),
        "activation_price": None,
        "trigger_price": round(trigger, 2),
        "atr_override": atr_mult,
    }


def _validate_tp_sl_values(body: UpdateTpSlRequest, trade: TradeRecord) -> None:
    """Run the side/entry-price validation that's shared by both paths.

    Raises :class:`HTTPException` (400/422) on a violation. The legacy
    endpoint runs the same checks inline; we extract them so the new
    path can reuse them without duplicating the validation logic.
    """
    if body.remove_tp and body.take_profit is not None:
        raise HTTPException(status_code=422, detail=ERR_TP_SL_CONFLICT_TP)
    if body.remove_sl and body.stop_loss is not None:
        raise HTTPException(status_code=422, detail=ERR_TP_SL_CONFLICT_SL)
    if trade.entry_price <= 0:
        raise HTTPException(status_code=400, detail="Trade has invalid entry price")
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


# ---------------------------------------------------------------------------
# Read-only risk-state snapshot (Issue #195)
# ---------------------------------------------------------------------------


@router.get("/{trade_id}/risk-state", response_model=TpSlResponse)
@limiter.limit("60/minute")
async def get_trade_risk_state(
    trade_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current post-readback risk-state snapshot for a trade.

    The response shape matches ``PUT /trades/{trade_id}/tp-sl`` so the
    frontend ``useRiskState`` hook and ``useUpdateTpSl`` mutation share one
    TypeScript type. Only active while ``risk_state_manager_enabled`` is on;
    the legacy path has no concept of a per-leg snapshot and returns 404.

    Delegates to :meth:`RiskStateManager.reconcile` which probes the
    exchange and heals DB drift in one call — same primitive the periodic
    reconciler uses.
    """

    if not settings.risk.risk_state_manager_enabled:
        raise HTTPException(
            status_code=404,
            detail="Risk-state endpoint is disabled (feature flag off)",
        )

    # Ownership check — never leak another user's trade through reconcile
    trade_result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.id == trade_id,
            TradeRecord.user_id == user.id,
        )
    )
    trade = trade_result.scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail=ERR_TRADE_NOT_FOUND)

    manager = get_risk_state_manager()
    try:
        snapshot = await manager.reconcile(trade_id)
    except ValueError as exc:
        # reconcile() raises ValueError when the row vanishes mid-flight;
        # the ownership check above already covers "not yours", so this is
        # a genuine 404.
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _leg_dict_to_status(leg: Optional[dict]) -> Optional[RiskLegStatus]:
        if leg is None:
            return None
        return RiskLegStatus(
            value=leg.get("value"),
            status=leg.get("status", RiskOpStatus.CLEARED.value),
            order_id=leg.get("order_id"),
            error=leg.get("error"),
            latency_ms=int(leg.get("latency_ms", 0)),
        )

    tp_status = _leg_dict_to_status(snapshot.tp)
    sl_status = _leg_dict_to_status(snapshot.sl)
    trailing_status = _leg_dict_to_status(snapshot.trailing)

    # A pure readback never writes, so overall is "all_confirmed" (native
    # orders are in place) or "no_change" (exchange has nothing attached).
    any_confirmed = any(
        s is not None and s.status == RiskOpStatus.CONFIRMED.value
        for s in (tp_status, sl_status, trailing_status)
    )
    overall = "all_confirmed" if any_confirmed else "no_change"

    return TpSlResponse(
        trade_id=trade_id,
        tp=tp_status,
        sl=sl_status,
        trailing=trailing_status,
        applied_at=snapshot.last_synced_at,
        overall_status=overall,
    )


async def _handle_tp_sl_via_manager(
    trade_id: int,
    body: UpdateTpSlRequest,
    trade: TradeRecord,
    idempotency_key: Optional[str],
) -> TpSlResponse:
    """Dispatch the request through :class:`RiskStateManager`.

    Each leg is applied independently — a rejection on one leg does not
    block the others. Per-leg results are collected and the response
    aggregates them. No direct exchange calls happen here (Pattern A
    guard) — everything goes through the manager.
    """
    cache = get_idempotency_cache()
    cache_key: Optional[str] = None
    if idempotency_key:
        cache_key = f"tp_sl:{trade_id}:{idempotency_key}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached

    manager = get_risk_state_manager()
    legs: list[tuple[RiskLeg, RiskLegStatus]] = []

    async def _apply(leg: RiskLeg, value: Any) -> RiskLegStatus:
        # Per-leg try/except: a single leg failure must not break the others
        try:
            result = await manager.apply_intent(trade_id, leg, value)
            status = _risk_result_to_status(result)
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
            status = RiskLegStatus(
                value=value,
                status=RiskOpStatus.REJECTED.value,
                order_id=None,
                error=str(exc),
                latency_ms=0,
            )
        logger.info(
            "tp_sl_endpoint leg=%s status=%s latency_ms=%s",
            leg.value, status.status, status.latency_ms,
            extra={
                "event_type": "tp_sl_endpoint",
                "trade_id": trade_id,
                "leg": leg.value,
                "status": status.status,
                "latency_ms": status.latency_ms,
            },
        )
        return status

    # ── TP leg ─────────────────────────────────────────────────────
    if body.remove_tp:
        legs.append((RiskLeg.TP, await _apply(RiskLeg.TP, None)))
    elif body.take_profit is not None:
        legs.append((RiskLeg.TP, await _apply(RiskLeg.TP, body.take_profit)))

    # ── SL leg ─────────────────────────────────────────────────────
    if body.remove_sl:
        legs.append((RiskLeg.SL, await _apply(RiskLeg.SL, None)))
    elif body.stop_loss is not None:
        legs.append((RiskLeg.SL, await _apply(RiskLeg.SL, body.stop_loss)))

    # ── Trailing leg ───────────────────────────────────────────────
    # Without an explicit ``remove_trailing`` flag the endpoint has no way to
    # communicate "toggle trailing off" — a naked ``trailing_stop: None`` body
    # is indistinguishable from "leave trailing alone". The flag lets the UI
    # clear a trailing leg without touching TP/SL, matching the remove_tp /
    # remove_sl semantics.
    if body.remove_trailing:
        legs.append((RiskLeg.TRAILING, await _apply(RiskLeg.TRAILING, None)))
    elif body.trailing_stop is not None:
        trailing_value = await _build_trailing_intent(trade, body.trailing_stop)
        legs.append((RiskLeg.TRAILING, await _apply(RiskLeg.TRAILING, trailing_value)))

    leg_dict: dict[RiskLeg, RiskLegStatus] = dict(legs)
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

    response = TpSlResponse(
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


@router.put("/{trade_id}/tp-sl")
@limiter.limit("10/minute")
async def update_trade_tpsl(
    trade_id: int,
    body: UpdateTpSlRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Update TP/SL on an open position — sets on exchange + updates DB.

    When ``Settings.risk.risk_state_manager_enabled`` is True the request
    is delegated to :class:`RiskStateManager` which guarantees
    2-Phase-Commit per leg. The legacy direct-exchange path runs
    unchanged when the flag is off.
    """

    # ── Feature flag: route through RiskStateManager (#192) ─────────
    if settings.risk.risk_state_manager_enabled:
        # Reject contradictory flags before doing any DB work
        if body.remove_tp and body.take_profit is not None:
            raise HTTPException(status_code=422, detail=ERR_TP_SL_CONFLICT_TP)
        if body.remove_sl and body.stop_loss is not None:
            raise HTTPException(status_code=422, detail=ERR_TP_SL_CONFLICT_SL)
        if body.remove_trailing and body.trailing_stop is not None:
            raise HTTPException(
                status_code=422,
                detail="Cannot both set and remove trailing stop",
            )

        trade_result = await db.execute(
            select(TradeRecord).where(
                TradeRecord.id == trade_id,
                TradeRecord.user_id == user.id,
            )
        )
        trade = trade_result.scalar_one_or_none()
        if not trade:
            raise HTTPException(status_code=404, detail=ERR_TRADE_NOT_FOUND)
        if trade.status != "open":
            raise HTTPException(status_code=400, detail="Trade is not open")
        _validate_tp_sl_values(body, trade)

        return await _handle_tp_sl_via_manager(
            trade_id=trade_id,
            body=body,
            trade=trade,
            idempotency_key=idempotency_key,
        )

    # ── Legacy path (flag off) — UNTOUCHED below ───────────────────

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
    exchange_has_trailing: Optional[bool] = None
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
            # Always cancel the existing native trailing before placing a new
            # one; otherwise Bitget reports "Insufficient position" because
            # the live moving_plan already reserves the full position size.
            # The earlier TP/SL cancel block only runs on TP/SL changes, so
            # a trailing-only edit would leave the old plan alive.
            if hasattr(client, "cancel_native_trailing_stop"):
                try:
                    await client.cancel_native_trailing_stop(trade.symbol, trade.side)
                except Exception as cancel_err:
                    logger.debug(
                        "cancel_native_trailing_stop for trade %s failed: %s",
                        trade_id, cancel_err,
                    )

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

        # Authoritative probe before closing the client: what does the
        # exchange really say about the trailing plan right now? This covers
        # silent cancel-no-ops and partial failures where trailing_placed
        # disagrees with reality. Skip on exchanges without a meaningful probe
        # — their default ``False`` return is not authoritative.
        if getattr(type(client), "SUPPORTS_NATIVE_TRAILING_PROBE", False):
            try:
                exchange_has_trailing = await client.has_native_trailing_stop(
                    trade.symbol, trade.side,
                )
            except Exception as probe_err:
                logger.debug("has_native_trailing_stop probe failed: %s", probe_err)
                exchange_has_trailing = None
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

    # Resolve true native_trailing_stop state from the probe taken before the
    # client was closed. If the probe failed, fall back to local bookkeeping.
    if exchange_has_trailing is None:
        native_state = trailing_placed
    else:
        native_state = exchange_has_trailing
        if exchange_has_trailing and not trailing_placed:
            logger.info(
                "TP/SL sync: trade %s flagged trailing_placed=False but exchange still "
                "reports a live moving_plan — keeping native_trailing_stop=True",
                trade_id,
            )
        elif not exchange_has_trailing and trailing_placed:
            logger.warning(
                "TP/SL sync: place_trailing_stop returned success for trade %s but the "
                "exchange shows no live moving_plan — persisting False",
                trade_id,
            )

    trade.take_profit = effective_tp
    trade.stop_loss = effective_sl
    if body.trailing_stop is not None:
        trade.native_trailing_stop = native_state
        trade.trailing_atr_override = body.trailing_stop.callback_pct
    else:
        # User submitted the form but trailing was off — reflect real exchange state
        trade.trailing_atr_override = None
        trade.native_trailing_stop = native_state
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
