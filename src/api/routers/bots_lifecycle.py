"""Bot lifecycle endpoints: start, stop, restart, close positions, test notifications, apply presets."""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.rate_limit import limiter
from src.api.routers.bots import _check_symbol_conflicts, _config_to_response, get_orchestrator
from src.api.schemas.bots import BotConfigResponse
from src.auth.dependencies import get_current_user
from src.exceptions import BotError
from src.models.database import AffiliateLink, BotConfig, ConfigPreset, ExchangeConnection, TradeRecord, User
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
        raise HTTPException(status_code=400, detail="Keine Hyperliquid-Verbindung konfiguriert.")

    hl_cfg = await get_hl_config()

    # Gate 1: Referral check
    referral_code = hl_cfg["referral_code"]
    if referral_code and not hl_conn.referral_verified:
        raise HTTPException(
            status_code=400,
            detail=f"Referral erforderlich. Bitte registriere dich ueber "
                   f"https://app.hyperliquid.xyz/join/{referral_code} "
                   f"bevor du Hyperliquid Bots nutzen kannst.",
        )

    # Gate 2: Builder fee check
    builder_address = hl_cfg["builder_address"]
    if builder_address and not hl_conn.builder_fee_approved:
        raise HTTPException(
            status_code=400,
            detail="Builder Fee nicht genehmigt. Bitte genehmige die Builder Fee auf der Website.",
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
                "message": "Registriere dich zuerst über unseren Affiliate-Link, trage dann deine UID unter Einstellungen → API Keys ein.",
                "affiliate_url": aff_link.affiliate_url,
                "type": "affiliate_required",
            },
        )
    if not conn.affiliate_verified:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Deine UID wurde eingereicht, ist aber noch nicht freigegeben. Bitte warte auf die Freigabe durch einen Admin.",
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
        raise HTTPException(status_code=404, detail="Bot nicht gefunden")

    # ── Pre-start gates (API level) — admins bypass all gates ──
    if user.role != "admin":
        if config.exchange_type == "hyperliquid":
            await _enforce_hl_gates(user, db)
        if config.exchange_type in ("bitget", "weex"):
            await _enforce_affiliate_gate(config.exchange_type, user, db)

    # Symbol conflict gate — one position per symbol per exchange
    from src.utils.json_helpers import parse_json_field
    trading_pairs = parse_json_field(config.trading_pairs, field_name="trading_pairs", context=f"bot {bot_id}", default=[])
    conflicts = await _check_symbol_conflicts(db, user.id, config.exchange_type, config.mode, trading_pairs, exclude_bot_id=bot_id)
    if conflicts:
        symbols = ", ".join(c.symbol for c in conflicts)
        raise HTTPException(status_code=400, detail=f"Symbol-Konflikt: {symbols} wird bereits von einem aktiven Bot auf dieser Exchange gehandelt")

    try:
        await orchestrator.start_bot(bot_id)
    except (ValueError, BotError) as e:
        raise HTTPException(status_code=400, detail=str(e))

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
        raise HTTPException(status_code=404, detail="Bot nicht gefunden")
    success = await orchestrator.stop_bot(bot_id)
    if not success:
        raise HTTPException(status_code=400, detail="Bot laeuft nicht")

    # Mark as disabled
    config.is_enabled = False
    await db.flush()

    from src.utils.event_logger import log_event
    await log_event("bot_stopped", f"Bot '{config.name}' stopped", user_id=user.id, bot_id=bot_id)

    return {"status": "ok", "message": f"Bot '{config.name}' stopped"}


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
        raise HTTPException(status_code=404, detail="Bot nicht gefunden")

    # ── Pre-start gates (API level) — admins bypass all gates ──
    if user.role != "admin":
        if config.exchange_type == "hyperliquid":
            await _enforce_hl_gates(user, db)
        if config.exchange_type in ("bitget", "weex"):
            await _enforce_affiliate_gate(config.exchange_type, user, db)

    # Symbol conflict gate — one position per symbol per exchange
    from src.utils.json_helpers import parse_json_field
    trading_pairs = parse_json_field(config.trading_pairs, field_name="trading_pairs", context=f"bot {bot_id}", default=[])
    conflicts = await _check_symbol_conflicts(db, user.id, config.exchange_type, config.mode, trading_pairs, exclude_bot_id=bot_id)
    if conflicts:
        symbols = ", ".join(c.symbol for c in conflicts)
        raise HTTPException(status_code=400, detail=f"Symbol-Konflikt: {symbols} wird bereits von einem aktiven Bot auf dieser Exchange gehandelt")

    try:
        await orchestrator.restart_bot(bot_id)
    except (ValueError, BotError) as e:
        raise HTTPException(status_code=400, detail=str(e))

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
        raise HTTPException(status_code=404, detail="Bot nicht gefunden")

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
        raise HTTPException(status_code=404, detail=f"Kein offener Trade fuer {symbol} gefunden")

    # Get exchange connection
    conn_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == config.exchange_type,
        )
    )
    conn = conn_result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=400, detail="Keine Exchange-Verbindung konfiguriert")

    is_demo = trade.demo_mode
    api_key_enc = conn.demo_api_key_encrypted if is_demo else conn.api_key_encrypted
    api_secret_enc = conn.demo_api_secret_encrypted if is_demo else conn.api_secret_encrypted
    passphrase_enc = conn.demo_passphrase_encrypted if is_demo else conn.passphrase_encrypted

    if not api_key_enc or not api_secret_enc:
        raise HTTPException(status_code=400, detail="Exchange-Zugangsdaten nicht konfiguriert")

    client = create_exchange_client(
        exchange_type=config.exchange_type,
        api_key=decrypt_value(api_key_enc),
        api_secret=decrypt_value(api_secret_enc),
        passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
        demo_mode=is_demo,
    )

    # Close position on exchange (may already be closed / not exist)
    try:
        order = await asyncio.wait_for(
            client.close_position(symbol, trade.side),
            timeout=15.0,
        )
    except Exception as e:
        # Log but don't fail — position may not exist on exchange anymore
        logger.warning(f"Exchange close_position failed for {symbol} bot {bot_id} (may already be closed): {e}")
        order = None

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
        raise HTTPException(status_code=404, detail="Bot nicht gefunden")
    if not config.telegram_bot_token or not config.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Telegram nicht konfiguriert")

    from src.notifications.telegram_notifier import TelegramNotifier
    from src.utils.encryption import decrypt_value

    notifier = TelegramNotifier(
        bot_token=decrypt_value(config.telegram_bot_token),
        chat_id=config.telegram_chat_id,
    )
    success = await notifier.send_test_message()
    if not success:
        raise HTTPException(status_code=502, detail="Telegram-Nachricht konnte nicht gesendet werden")
    return {"status": "ok", "message": "Test message sent"}


# ─── Preset Application ──────────────────────────────────────

@lifecycle_router.post("/{bot_id}/apply-preset/{preset_id}", response_model=BotConfigResponse)
@limiter.limit("10/minute")
async def apply_preset_to_bot(
    request: Request,
    bot_id: int,
    preset_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """Apply a preset to an existing bot. Bot must be stopped."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot nicht gefunden")

    # Check if running
    if orchestrator.is_running(bot_id):
        raise HTTPException(status_code=400, detail="Stoppe den Bot bevor du ein Preset anwendest")

    # Load preset
    preset_result = await db.execute(
        select(ConfigPreset).where(ConfigPreset.id == preset_id, ConfigPreset.user_id == user.id)
    )
    preset = preset_result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset nicht gefunden")

    # Apply trading config from preset
    if preset.trading_config:
        trading = json.loads(preset.trading_config)
        if "leverage" in trading:
            config.leverage = trading["leverage"]
        if "position_size_percent" in trading:
            config.position_size_percent = trading["position_size_percent"]
        if "max_trades_per_day" in trading:
            config.max_trades_per_day = trading["max_trades_per_day"]
        if "take_profit_percent" in trading:
            config.take_profit_percent = trading["take_profit_percent"]
        if "stop_loss_percent" in trading:
            config.stop_loss_percent = trading["stop_loss_percent"]
        if "daily_loss_limit_percent" in trading:
            config.daily_loss_limit_percent = trading["daily_loss_limit_percent"]

    # Apply strategy config from preset (merge, preserve data_sources)
    if preset.strategy_config:
        existing = json.loads(config.strategy_params) if config.strategy_params else {}
        preset_params = json.loads(preset.strategy_config) if isinstance(preset.strategy_config, str) else preset.strategy_config
        preserved_data_sources = existing.get("data_sources")
        existing.update(preset_params)
        if preserved_data_sources is not None:
            existing["data_sources"] = preserved_data_sources
        config.strategy_params = json.dumps(existing)

    # Apply trading pairs (convert if needed for exchange compatibility)
    if preset.trading_pairs:
        pairs = json.loads(preset.trading_pairs)
        if config.exchange_type == "hyperliquid":
            # Strip USDT suffix for Hyperliquid
            pairs = [p.replace("USDT", "") if p.endswith("USDT") else p for p in pairs]
        else:
            # Add USDT suffix for CEX exchanges if missing
            pairs = [p if p.endswith("USDT") else f"{p}USDT" for p in pairs]
        config.trading_pairs = json.dumps(pairs)

    # Track which preset is active
    config.active_preset_id = preset_id

    await db.flush()

    # Re-fetch with preset relationship loaded
    refreshed = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id)
        .options(selectinload(BotConfig.active_preset))
    )
    config = refreshed.scalar_one()

    logger.info(f"Preset '{preset.name}' applied to bot {config.name} (id={bot_id})")
    return _config_to_response(config)
