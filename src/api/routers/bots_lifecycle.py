"""Bot lifecycle endpoints: start, stop, restart, close positions, test notifications."""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from src.api.dependencies.risk_state import get_risk_state_manager
from src.api.rate_limit import limiter
from src.api.routers.bots import _check_symbol_conflicts, get_orchestrator
from src.api.schemas.bots import _validate_webhook_url
from src.auth.dependencies import get_current_user
from src.errors import (
    ERR_AFFILIATE_PENDING,
    ERR_AFFILIATE_REQUIRED,
    ERR_BOT_NOT_FOUND,
    ERR_BOT_NOT_RUNNING,
    ERR_DISCORD_NOT_CONFIGURED,
    ERR_DISCORD_SEND_FAILED,
    ERR_EXCHANGE_CREDENTIALS_MISSING,
    ERR_HL_BUILDER_FEE_NOT_APPROVED,
    ERR_HL_REFERRAL_REQUIRED,
    ERR_NO_EXCHANGE_CONNECTION,
    ERR_NO_HL_CONNECTION,
    ERR_NO_OPEN_TRADE,
    ERR_PENDING_TRADE_NOT_FOUND,
    ERR_POSITION_CLOSE_FAILED,
    ERR_POSITION_VERIFY_FAILED,
    ERR_SYMBOL_CONFLICT,
    ERR_TELEGRAM_NOT_CONFIGURED,
    ERR_TELEGRAM_SEND_FAILED,
    ERR_TRADE_ALREADY_RESOLVED,
    translate_exchange_error,
)
from src.exceptions import BotError
from src.models.database import AffiliateLink, BotConfig, ExchangeConnection, TradeRecord, User
from src.models.enums import CEX_EXCHANGES
from src.models.session import get_db
from src.utils.logger import get_logger

logger = get_logger(__name__)

lifecycle_router = APIRouter(tags=["bots"])


async def _enforce_hl_gates(user: User, db: AsyncSession):
    """API-level hard gate for Hyperliquid: check builder fee + referral in DB.

    Raises HTTPException if any gate fails. Called from start_bot AND restart_bot.
    """
    from src.utils.settings import get_hl_config

    hl_conn_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == "hyperliquid",
        )
    )
    hl_conn = hl_conn_result.scalar_one_or_none()
    if not hl_conn:
        raise HTTPException(status_code=400, detail=ERR_NO_HL_CONNECTION)

    hl_cfg = await get_hl_config()

    # Gate 1: Referral check
    referral_code = hl_cfg["referral_code"]
    if referral_code and not hl_conn.referral_verified:
        raise HTTPException(
            status_code=400,
            detail=ERR_HL_REFERRAL_REQUIRED.format(referral_code=referral_code),
        )

    # Gate 2: Builder fee check
    builder_address = hl_cfg["builder_address"]
    if builder_address and not hl_conn.builder_fee_approved:
        raise HTTPException(
            status_code=400,
            detail=ERR_HL_BUILDER_FEE_NOT_APPROVED,
        )


async def _enforce_affiliate_gate(exchange_type: str, user: User, db: AsyncSession):
    """Check if user has verified affiliate UID for Bitget/Weex."""
    # Check if uid_required is active for this exchange
    link_result = await db.execute(
        select(AffiliateLink).where(
            AffiliateLink.exchange_type == exchange_type,
            AffiliateLink.is_active.is_(True),
            AffiliateLink.uid_required.is_(True),
        )
    )
    aff_link = link_result.scalar_one_or_none()
    if not aff_link:
        return  # No UID requirement active

    # Exchange display name for error messages
    exchange_display = exchange_type.capitalize()

    conn_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == exchange_type,
        )
    )
    conn = conn_result.scalar_one_or_none()

    if not conn or not conn.affiliate_uid:
        raise HTTPException(
            status_code=400,
            detail=ERR_AFFILIATE_REQUIRED.format(exchange=exchange_display),
        )
    if not conn.affiliate_verified:
        raise HTTPException(
            status_code=400,
            detail=ERR_AFFILIATE_PENDING.format(exchange=exchange_display),
        )


# ─── Notification Test (without bot_id, for new bots) ────────


class TelegramTestRequest(BaseModel):
    """Body model for /test-telegram-direct."""
    bot_token: str = Field(..., min_length=1, max_length=200)
    chat_id: str = Field(..., min_length=1, max_length=64)


class DiscordTestRequest(BaseModel):
    """Body model for /test-discord-direct (SSRF-protected)."""
    webhook_url: str = Field(..., min_length=1, max_length=500)

    @field_validator("webhook_url")
    @classmethod
    def _check_webhook(cls, v: str) -> str:
        # Reuses the shared SSRF-prevention validator
        return _validate_webhook_url(v) or ""


@lifecycle_router.post("/test-telegram-direct")
@limiter.limit("5/minute")
async def test_telegram_direct(
    request: Request,
    body: TelegramTestRequest,
    user: User = Depends(get_current_user),
):
    """Send a test Telegram message with provided credentials (no bot required)."""
    bot_token = body.bot_token.strip()
    chat_id = body.chat_id.strip()
    if not bot_token or not chat_id:
        raise HTTPException(status_code=400, detail=ERR_TELEGRAM_NOT_CONFIGURED)

    from src.notifications.telegram_notifier import TelegramNotifier

    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
    try:
        await notifier.send_test_message()
    except Exception as e:
        logger.warning(f"Telegram direct test failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "ok", "message": "Test message sent"}


@lifecycle_router.post("/test-discord-direct")
@limiter.limit("5/minute")
async def test_discord_direct(
    request: Request,
    body: DiscordTestRequest,
    user: User = Depends(get_current_user),
):
    """Send a test Discord message with provided webhook URL (no bot required)."""
    webhook_url = body.webhook_url.strip()
    if not webhook_url:
        raise HTTPException(status_code=400, detail=ERR_DISCORD_NOT_CONFIGURED)

    import aiohttp

    try:
        async with aiohttp.ClientSession() as http_session:
            payload = {
                "embeds": [{
                    "title": "\ud83d\udd14 Verbindungstest",
                    "description": "Discord-Benachrichtigungen sind korrekt eingerichtet!",
                    "color": 0x00D166,
                }]
            }
            async with http_session.post(webhook_url, json=payload) as resp:
                if resp.status not in (200, 204):
                    error_text = await resp.text()
                    raise HTTPException(status_code=502, detail=f"Discord error {resp.status}: {error_text}")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Discord direct webhook test failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))

    return {"status": "ok", "message": "Discord test message sent"}


# ─── Bot Lifecycle ───────────────────────────────────────────


@lifecycle_router.post("/{bot_id}/start")
@limiter.limit("20/minute")
async def start_bot(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """Start a bot."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    # ── Pre-start gates (API level) — admins bypass all gates ──
    if user.role != "admin":
        if config.exchange_type == "hyperliquid":
            await _enforce_hl_gates(user, db)
        if config.exchange_type in CEX_EXCHANGES:
            await _enforce_affiliate_gate(config.exchange_type, user, db)

    # Symbol conflict gate — one position per symbol per exchange
    from src.utils.json_helpers import parse_json_field
    trading_pairs = parse_json_field(config.trading_pairs, field_name="trading_pairs", context=f"bot {bot_id}", default=[])
    conflicts = await _check_symbol_conflicts(db, user.id, config.exchange_type, config.mode, trading_pairs, exclude_bot_id=bot_id)
    if conflicts:
        symbols = ", ".join(c.symbol for c in conflicts)
        raise HTTPException(status_code=400, detail=ERR_SYMBOL_CONFLICT.format(symbols=symbols))

    try:
        await orchestrator.start_bot(bot_id)
    except (ValueError, BotError) as e:
        raise HTTPException(status_code=400, detail=translate_exchange_error(str(e)))

    # Mark as enabled
    config.is_enabled = True
    await db.flush()

    from src.utils.event_logger import log_event
    await log_event("bot_started", f"Bot '{config.name}' started", user_id=user.id, bot_id=bot_id)

    return {"status": "ok", "message": f"Bot '{config.name}' started"}


@lifecycle_router.post("/{bot_id}/stop")
@limiter.limit("20/minute")
async def stop_bot(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """Stop a running bot."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)
    # Check for open trades before stopping
    open_result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.bot_config_id == bot_id,
            TradeRecord.status == "open",
        )
    )
    open_trades = list(open_result.scalars().all())

    success = await orchestrator.stop_bot(bot_id)
    if not success:
        raise HTTPException(status_code=400, detail=ERR_BOT_NOT_RUNNING)

    # Mark as disabled
    config.is_enabled = False
    await db.flush()

    from src.utils.event_logger import log_event
    await log_event("bot_stopped", f"Bot '{config.name}' stopped", user_id=user.id, bot_id=bot_id)

    warning = None
    if open_trades:
        symbols = ", ".join(t.symbol for t in open_trades)
        warning = (
            f"{len(open_trades)} offene Position(en) auf der Exchange: {symbols}. "
            f"Diese werden NICHT automatisch geschlossen und nicht mehr überwacht."
        )

    return {"status": "ok", "message": f"Bot '{config.name}' stopped", "warning": warning}


@lifecycle_router.post("/{bot_id}/restart")
@limiter.limit("20/minute")
async def restart_bot(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """Restart a bot (stop + start)."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    # ── Pre-start gates (API level) — admins bypass all gates ──
    if user.role != "admin":
        if config.exchange_type == "hyperliquid":
            await _enforce_hl_gates(user, db)
        if config.exchange_type in CEX_EXCHANGES:
            await _enforce_affiliate_gate(config.exchange_type, user, db)

    # Symbol conflict gate — one position per symbol per exchange
    from src.utils.json_helpers import parse_json_field
    trading_pairs = parse_json_field(config.trading_pairs, field_name="trading_pairs", context=f"bot {bot_id}", default=[])
    conflicts = await _check_symbol_conflicts(db, user.id, config.exchange_type, config.mode, trading_pairs, exclude_bot_id=bot_id)
    if conflicts:
        symbols = ", ".join(c.symbol for c in conflicts)
        raise HTTPException(status_code=400, detail=ERR_SYMBOL_CONFLICT.format(symbols=symbols))

    try:
        await orchestrator.restart_bot(bot_id)
    except (ValueError, BotError) as e:
        raise HTTPException(status_code=400, detail=translate_exchange_error(str(e)))

    config.is_enabled = True
    await db.flush()

    from src.utils.event_logger import log_event
    await log_event("bot_restarted", f"Bot '{config.name}' restarted", user_id=user.id, bot_id=bot_id)

    return {"status": "ok", "message": f"Bot '{config.name}' restarted"}


@lifecycle_router.post("/{bot_id}/close-position/{symbol}")
@limiter.limit("10/minute")
async def close_position(
    request: Request,
    bot_id: int,
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """Manually close an open position on the exchange and mark the trade record as closed.

    Routes through the shared :func:`close_and_record_trade` helper so the
    manual-close path emits the same side effects as an automated exit:
    fee/funding/builder-fee capture, Discord/Telegram notification,
    WebSocket broadcast, SSE ``trade_closed`` event, and RiskManager
    daily-stats update (Issue #275).
    """
    from src.exchanges.factory import create_exchange_client
    from src.utils.encryption import decrypt_value
    from src.bot.notifications import build_standalone_dispatcher
    from src.bot.trade_closer import close_and_record_trade

    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    # Find the open trade record for this bot + symbol
    trade_result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.bot_config_id == bot_id,
            TradeRecord.symbol == symbol,
            TradeRecord.status == "open",
        )
    )
    trade = trade_result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail=ERR_NO_OPEN_TRADE.format(symbol=symbol))

    # Get exchange connection
    conn_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == config.exchange_type,
        )
    )
    conn = conn_result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=400, detail=ERR_NO_EXCHANGE_CONNECTION)

    is_demo = trade.demo_mode
    api_key_enc = conn.demo_api_key_encrypted if is_demo else conn.api_key_encrypted
    api_secret_enc = conn.demo_api_secret_encrypted if is_demo else conn.api_secret_encrypted
    passphrase_enc = conn.demo_passphrase_encrypted if is_demo else conn.passphrase_encrypted

    if not api_key_enc or not api_secret_enc:
        raise HTTPException(status_code=400, detail=ERR_EXCHANGE_CREDENTIALS_MISSING)

    client = create_exchange_client(
        exchange_type=config.exchange_type,
        api_key=decrypt_value(api_key_enc),
        api_secret=decrypt_value(api_secret_enc),
        passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
        demo_mode=is_demo,
    )

    # Close position on exchange
    close_order_id: str | None = None
    try:
        close_order = await asyncio.wait_for(
            client.close_position(symbol, trade.side, margin_mode=getattr(config, "margin_mode", "cross")),
            timeout=15.0,
        )
        if close_order is not None:
            close_order_id = getattr(close_order, "order_id", None)
    except Exception as e:
        logger.warning(f"Exchange close_position call failed for {symbol} bot {bot_id}: {e}")

    # Verify position is actually closed on exchange
    try:
        remaining_pos = await asyncio.wait_for(client.get_position(symbol), timeout=10.0)
        if remaining_pos and remaining_pos.size > 0:
            raise HTTPException(
                status_code=502,
                detail=ERR_POSITION_CLOSE_FAILED.format(symbol=symbol),
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Could not verify position status for {symbol} bot {bot_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail=ERR_POSITION_VERIFY_FAILED.format(symbol=symbol),
        )

    # Get exit price — prefer the actual fill price of the close order,
    # fall back to ticker last_price, then entry_price as last resort.
    # Using ticker.last_price alone caused incorrect PnL when the ticker
    # diverged from the real fill (especially in demo mode).
    exit_price = None
    try:
        exit_price = await client.get_close_fill_price(symbol)
    except Exception as e:
        logger.debug(f"get_close_fill_price failed for {symbol}: {e}")
    if not exit_price:
        try:
            ticker = await client.get_ticker(symbol)
            exit_price = ticker.last_price
        except Exception:
            exit_price = trade.entry_price  # fallback

    # Persist the close order id so fee lookups can include exit fills
    if close_order_id:
        trade.close_order_id = close_order_id

    # ── Fee capture (matches PositionMonitorMixin._handle_closed_position) ──
    fees = trade.fees or 0
    try:
        if trade.order_id:
            fees = await client.get_trade_total_fees(
                symbol=trade.symbol,
                entry_order_id=trade.order_id,
                close_order_id=trade.close_order_id,
            )
    except Exception as e:
        logger.debug(f"Manual close: fee fetch failed for trade #{trade.id}: {e}")

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
    except Exception as e:
        logger.debug(f"Manual close: funding fetch failed for trade #{trade.id}: {e}")

    builder_fee = 0
    try:
        if hasattr(client, "calculate_builder_fee"):
            builder_fee = client.calculate_builder_fee(
                entry_price=trade.entry_price,
                exit_price=exit_price,
                size=trade.size,
            )
    except Exception as e:
        logger.debug(f"Manual close: builder-fee calc failed for trade #{trade.id}: {e}")

    # Determine exit reason. When the RiskStateManager feature flag is on,
    # defer to ``classify_close`` — it probes the exchange order history
    # and attributes the close precisely (MANUAL_CLOSE_UI, MANUAL_CLOSE_EXCHANGE,
    # TAKE_PROFIT_NATIVE, etc.). When the flag is off OR classify_close
    # fails, fall back to the legacy ``MANUAL_CLOSE`` literal so historical
    # behaviour is preserved.
    exit_time_now = datetime.now(timezone.utc)
    exit_reason = "MANUAL_CLOSE"
    if settings.risk.risk_state_manager_enabled:
        try:
            manager = get_risk_state_manager()
            exit_reason = await manager.classify_close(
                trade.id, exit_price, exit_time_now,
            )
        except Exception as classify_err:  # noqa: BLE001
            logger.warning(
                "Manual close: classify_close failed for trade %s, "
                "falling back to MANUAL_CLOSE: %s",
                trade.id, classify_err,
            )
            exit_reason = "MANUAL_CLOSE"

    # Prefer the live worker's RiskManager + notification dispatcher so daily
    # stats update the same in-memory object the bot is using. Fall back to
    # a DB-backed RiskManager + standalone dispatcher when the bot is stopped.
    worker = None
    workers_map = getattr(orchestrator, "_workers", None)
    if isinstance(workers_map, dict):
        worker = workers_map.get(bot_id)
    risk_manager = getattr(worker, "_risk_manager", None) if worker else None
    if worker is not None and hasattr(worker, "_send_notification"):
        send_notification = worker._send_notification
    else:
        send_notification = build_standalone_dispatcher(config, bot_id)

    # If the bot is stopped there's no live RiskManager — build one from DB
    # so daily-stats still get updated and persisted.
    if risk_manager is None:
        try:
            from src.risk.risk_manager import RiskManager
            risk_manager = RiskManager(
                max_trades_per_day=getattr(config, "max_trades_per_day", None),
                daily_loss_limit_percent=getattr(config, "daily_loss_limit_percent", None),
                position_size_percent=getattr(config, "position_size_percent", None),
                bot_config_id=bot_id,
            )
            # Load today's stats; if none exist we seed with the trade's
            # entry balance so record_trade_exit has a valid DailyStats.
            await risk_manager.load_stats_from_db()
            if risk_manager._daily_stats is None:
                risk_manager.initialize_day(starting_balance=0.0)
        except Exception as rm_err:
            logger.warning(f"Manual close: could not build RiskManager: {rm_err}")
            risk_manager = None

    pnl, pnl_percent = await close_and_record_trade(
        trade,
        exit_price,
        exit_reason,
        bot_config_id=bot_id,
        config=config,
        risk_manager=risk_manager,
        send_notification=send_notification,
        fees=fees,
        funding_paid=funding_paid,
        builder_fee=builder_fee,
        strategy_reason=f"[{config.name}] Manual close",
    )

    # Round numeric fields for the response and downstream consumers
    trade.pnl = round(pnl, 4)
    trade.pnl_percent = round(pnl_percent, 2)
    await db.flush()

    # Persist updated RiskManager daily stats if we built a fresh one.
    # When a live worker was reused, record_trade_exit already scheduled the
    # autosave via its own background task.
    if risk_manager is not None and worker is None:
        try:
            await risk_manager._save_stats_to_db()
        except Exception as save_err:
            logger.debug(f"Manual close: save_stats_to_db failed: {save_err}")

    from src.utils.event_logger import log_event
    await log_event("position_closed", f"Position {symbol} manually closed | PnL: ${pnl:.2f}", user_id=user.id, bot_id=bot_id)

    return {
        "status": "ok",
        "message": f"Position {symbol} closed",
        "pnl": round(pnl, 2),
        "exit_price": exit_price,
    }


@lifecycle_router.post("/stop-all")
@limiter.limit("5/minute")
async def stop_all_bots(
    request: Request,
    user: User = Depends(get_current_user),
    orchestrator=Depends(get_orchestrator),
):
    """Stop all running bots for the current user."""
    stopped = await orchestrator.stop_all_for_user(user.id)
    return {"status": "ok", "message": f"{stopped} bot(s) stopped"}


@lifecycle_router.post("/{bot_id}/test-telegram")
@limiter.limit("5/minute")
async def test_telegram(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Send a test Telegram message."""
    result = await session.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)
    if not config.telegram_bot_token or not config.telegram_chat_id:
        raise HTTPException(status_code=400, detail=ERR_TELEGRAM_NOT_CONFIGURED)

    from src.notifications.telegram_notifier import TelegramNotifier
    from src.utils.encryption import decrypt_value

    notifier = TelegramNotifier(
        bot_token=decrypt_value(config.telegram_bot_token),
        chat_id=decrypt_value(config.telegram_chat_id),
    )
    success = await notifier.send_test_message()
    if not success:
        raise HTTPException(status_code=502, detail=ERR_TELEGRAM_SEND_FAILED)
    return {"status": "ok", "message": "Test message sent"}


@lifecycle_router.post("/{bot_id}/test-discord")
@limiter.limit("5/minute")
async def test_discord(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Send a test Discord message via webhook."""
    result = await session.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)
    if not config.discord_webhook_url:
        raise HTTPException(status_code=400, detail=ERR_DISCORD_NOT_CONFIGURED)

    from src.utils.encryption import decrypt_value

    import aiohttp

    webhook_url = decrypt_value(config.discord_webhook_url)
    try:
        async with aiohttp.ClientSession() as http_session:
            payload = {
                "embeds": [{
                    "title": "\ud83d\udd14 Verbindungstest",
                    "description": "Discord-Benachrichtigungen sind korrekt eingerichtet!",
                    "color": 0x00D166,
                }]
            }
            async with http_session.post(webhook_url, json=payload) as resp:
                if resp.status not in (200, 204):
                    raise HTTPException(status_code=502, detail=ERR_DISCORD_SEND_FAILED)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Discord webhook test failed for bot {bot_id}: {e}")
        raise HTTPException(status_code=502, detail=ERR_DISCORD_SEND_FAILED)

    return {"status": "ok", "message": "Discord test message sent"}


# ─── Pending Trades (Crash Recovery) ─────────────────────────

@lifecycle_router.get("/{bot_id}/pending-trades")
@limiter.limit("30/minute")
async def list_pending_trades(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List pending and orphaned trades for a bot (crash recovery visibility)."""
    from src.api.schemas.bots import PendingTradeListResponse, PendingTradeResponse
    from src.models.database import PendingTrade

    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    trades_result = await db.execute(
        select(PendingTrade)
        .where(
            PendingTrade.bot_config_id == bot_id,
            PendingTrade.status.in_(["pending", "orphaned", "failed"]),
        )
        .order_by(PendingTrade.created_at.desc())
    )
    trades = trades_result.scalars().all()

    items = []
    for t in trades:
        order_data = None
        if t.order_data:
            try:
                order_data = json.loads(t.order_data)
            except (json.JSONDecodeError, TypeError):
                pass
        items.append(PendingTradeResponse(
            id=t.id,
            bot_config_id=t.bot_config_id,
            symbol=t.symbol,
            side=t.side,
            action=t.action,
            order_data=order_data,
            status=t.status,
            error_message=t.error_message,
            created_at=t.created_at.isoformat() if t.created_at else None,
            resolved_at=t.resolved_at.isoformat() if t.resolved_at else None,
        ))

    return PendingTradeListResponse(pending_trades=items)


@lifecycle_router.post("/{bot_id}/pending-trades/{trade_id}/resolve")
@limiter.limit("20/minute")
async def resolve_pending_trade(
    request: Request,
    bot_id: int,
    trade_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually mark a pending/orphaned trade as resolved."""
    from src.models.database import PendingTrade

    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    trade_result = await db.execute(
        select(PendingTrade).where(
            PendingTrade.id == trade_id,
            PendingTrade.bot_config_id == bot_id,
        )
    )
    trade = trade_result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail=ERR_PENDING_TRADE_NOT_FOUND)

    if trade.status not in ("pending", "orphaned", "failed"):
        raise HTTPException(status_code=400, detail=ERR_TRADE_ALREADY_RESOLVED)

    trade.status = "completed"
    trade.resolved_at = datetime.now(timezone.utc)
    trade.error_message = "Manually resolved by user"
    await db.flush()

    from src.utils.event_logger import log_event
    await log_event(
        "pending_trade_resolved",
        f"Pending trade #{trade_id} ({trade.symbol} {trade.side}) manually resolved",
        user_id=user.id,
        bot_id=bot_id,
    )

    return {"status": "ok", "message": f"Pending trade #{trade_id} resolved"}
