"""Bot lifecycle endpoints: start, stop, restart, close positions, test notifications."""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.routers.bots import _check_symbol_conflicts, get_orchestrator
from src.auth.dependencies import get_current_user
from src.errors import (
    ERR_AFFILIATE_PENDING,
    ERR_AFFILIATE_REQUIRED,
    ERR_BOT_NOT_FOUND,
    ERR_BOT_NOT_RUNNING,
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
    ERR_WHATSAPP_NOT_CONFIGURED,
    ERR_WHATSAPP_SEND_FAILED,
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
            detail={
                "message": ERR_AFFILIATE_REQUIRED,
                "affiliate_url": aff_link.affiliate_url,
                "type": "affiliate_required",
            },
        )
    if not conn.affiliate_verified:
        raise HTTPException(
            status_code=400,
            detail={
                "message": ERR_AFFILIATE_PENDING,
                "type": "affiliate_pending",
            },
        )


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
):
    """Manually close an open position on the exchange and mark the trade record as closed."""
    from src.exchanges.factory import create_exchange_client
    from src.utils.encryption import decrypt_value

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
    try:
        await asyncio.wait_for(
            client.close_position(symbol, trade.side, margin_mode=getattr(config, "margin_mode", "cross")),
            timeout=15.0,
        )
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

    # Get current price for PnL
    try:
        ticker = await client.get_ticker(symbol)
        exit_price = ticker.last_price
    except Exception:
        exit_price = trade.entry_price  # fallback

    if trade.side == "long":
        pnl = (exit_price - trade.entry_price) * trade.size
    else:
        pnl = (trade.entry_price - exit_price) * trade.size
    pnl_percent = (pnl / (trade.entry_price * trade.size)) * 100 if trade.entry_price and trade.size else 0

    trade.status = "closed"
    trade.exit_price = exit_price
    trade.pnl = round(pnl, 4)
    trade.pnl_percent = round(pnl_percent, 2)
    trade.exit_time = datetime.now(timezone.utc)
    trade.exit_reason = "MANUAL_CLOSE"
    await db.flush()

    logger.info(f"Manual close: trade #{trade.id} {symbol} {trade.side} | PnL: ${pnl:.2f} ({pnl_percent:+.2f}%)")

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


@lifecycle_router.post("/{bot_id}/test-whatsapp")
@limiter.limit("5/minute")
async def test_whatsapp(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Send a test WhatsApp message."""
    result = await session.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)
    if not config.whatsapp_phone_number_id or not config.whatsapp_access_token or not config.whatsapp_recipient:
        raise HTTPException(status_code=400, detail=ERR_WHATSAPP_NOT_CONFIGURED)

    from src.notifications.whatsapp_notifier import WhatsAppNotifier
    from src.utils.encryption import decrypt_value

    notifier = WhatsAppNotifier(
        phone_number_id=decrypt_value(config.whatsapp_phone_number_id),
        access_token=decrypt_value(config.whatsapp_access_token),
        recipient_number=decrypt_value(config.whatsapp_recipient),
    )
    success = await notifier.send_test_message()
    if not success:
        raise HTTPException(status_code=502, detail=ERR_WHATSAPP_SEND_FAILED)
    return {"status": "ok", "message": "Test message sent"}


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
