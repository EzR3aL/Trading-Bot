"""
Multibot management endpoints.

CRUD for bot configs + lifecycle (start/stop/restart).
Replaces the old bot_control router for the new multibot system.
"""

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.schemas.bots import (
    BotConfigCreate,
    BotConfigResponse,
    BotConfigUpdate,
    BotListResponse,
    BotRuntimeStatus,
    StrategiesListResponse,
    StrategyInfo,
)
from src.auth.dependencies import get_current_user
from src.exceptions import BotError, BotNotFoundError
from src.models.database import AffiliateLink, BotConfig, ConfigPreset, ExchangeConnection, TradeRecord, User
from src.models.session import get_db
from src.strategy import StrategyRegistry  # imports __init__.py → registers all strategies
from src.api.rate_limit import limiter
from src.utils.encryption import encrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/bots", tags=["bots"])

MAX_BOTS_PER_USER = 10


def set_orchestrator(orchestrator):
    """No-op kept for backward compatibility. Orchestrator is now read from app.state."""
    pass


def get_orchestrator(request: Request):
    """FastAPI dependency: retrieve orchestrator from app.state."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Bot orchestrator not initialized")
    return orchestrator


def _config_to_response(config: BotConfig) -> BotConfigResponse:
    """Convert a BotConfig ORM object to a response schema."""
    try:
        trading_pairs = json.loads(config.trading_pairs) if config.trading_pairs else []
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse trading_pairs for bot {config.id}: {e}")
        trading_pairs = []

    try:
        strategy_params = json.loads(config.strategy_params) if config.strategy_params else None
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse strategy_params for bot {config.id}: {e}")
        strategy_params = None

    try:
        schedule_config = json.loads(config.schedule_config) if config.schedule_config else None
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse schedule_config for bot {config.id}: {e}")
        schedule_config = None

    try:
        per_asset_config = json.loads(config.per_asset_config) if config.per_asset_config else None
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse per_asset_config for bot {config.id}: {e}")
        per_asset_config = None

    return BotConfigResponse(
        id=config.id,
        name=config.name,
        description=config.description,
        strategy_type=config.strategy_type,
        exchange_type=config.exchange_type,
        mode=config.mode,
        trading_pairs=trading_pairs,
        leverage=config.leverage,
        position_size_percent=config.position_size_percent,
        max_trades_per_day=config.max_trades_per_day,
        take_profit_percent=config.take_profit_percent,
        stop_loss_percent=config.stop_loss_percent,
        daily_loss_limit_percent=config.daily_loss_limit_percent,
        per_asset_config=per_asset_config,
        strategy_params=strategy_params,
        schedule_type=config.schedule_type,
        schedule_config=schedule_config,
        rotation_enabled=config.rotation_enabled or False,
        rotation_interval_minutes=config.rotation_interval_minutes,
        rotation_start_time=config.rotation_start_time,
        is_enabled=config.is_enabled,
        discord_webhook_configured=bool(config.discord_webhook_url),
        telegram_configured=bool(config.telegram_bot_token and config.telegram_chat_id),
        active_preset_id=config.active_preset_id,
        active_preset_name=getattr(config.active_preset, "name", None) if config.active_preset_id else None,
        created_at=config.created_at.isoformat() if config.created_at else None,
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


# ─── Strategies ───────────────────────────────────────────────

@router.get("/strategies", response_model=StrategiesListResponse)
async def list_strategies(user: User = Depends(get_current_user)):
    """List all available trading strategies with their parameter schemas."""
    strategies = StrategyRegistry.list_available()
    return StrategiesListResponse(
        strategies=[StrategyInfo(**s) for s in strategies]
    )


@router.get("/data-sources")
async def list_data_sources(user: User = Depends(get_current_user)):
    """Return the catalog of all available market data sources.

    Returns {sources: [...], defaults: [...]} where each source has
    id, name, description, category, provider, free, default fields.
    Used by the Bot Builder to render selectable data source cards.
    """
    from src.data.data_source_registry import DATA_SOURCES, DEFAULT_SOURCES

    return {
        "sources": [ds.to_dict() for ds in DATA_SOURCES],
        "defaults": DEFAULT_SOURCES,
    }


# ─── CRUD ─────────────────────────────────────────────────────

@router.post("", response_model=BotConfigResponse)
@limiter.limit("10/minute")
async def create_bot(
    request: Request,
    body: BotConfigCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new bot configuration."""
    # Validate strategy exists
    try:
        StrategyRegistry.get(body.strategy_type)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check bot limit
    count_result = await db.execute(
        select(func.count(BotConfig.id)).where(BotConfig.user_id == user.id)
    )
    if count_result.scalar() >= MAX_BOTS_PER_USER:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_BOTS_PER_USER} bots per user")

    # Encrypt discord webhook if provided
    encrypted_webhook = None
    if body.discord_webhook_url:
        encrypted_webhook = encrypt_value(body.discord_webhook_url)

    # Encrypt telegram bot token if provided
    encrypted_telegram_token = None
    if body.telegram_bot_token:
        encrypted_telegram_token = encrypt_value(body.telegram_bot_token)

    config = BotConfig(
        user_id=user.id,
        name=body.name,
        description=body.description,
        strategy_type=body.strategy_type,
        exchange_type=body.exchange_type,
        mode=body.mode,
        trading_pairs=json.dumps(body.trading_pairs),
        leverage=body.leverage,
        position_size_percent=body.position_size_percent,
        max_trades_per_day=body.max_trades_per_day,
        take_profit_percent=body.take_profit_percent,
        stop_loss_percent=body.stop_loss_percent,
        daily_loss_limit_percent=body.daily_loss_limit_percent,
        per_asset_config=json.dumps(body.per_asset_config) if body.per_asset_config else None,
        strategy_params=json.dumps(body.strategy_params) if body.strategy_params else None,
        schedule_type=body.schedule_type,
        schedule_config=json.dumps(body.schedule_config) if body.schedule_config else None,
        rotation_enabled=body.rotation_enabled,
        rotation_interval_minutes=body.rotation_interval_minutes,
        rotation_start_time=body.rotation_start_time,
        discord_webhook_url=encrypted_webhook,
        telegram_bot_token=encrypted_telegram_token,
        telegram_chat_id=body.telegram_chat_id,
        is_enabled=False,
    )
    db.add(config)
    await db.flush()
    await db.refresh(config)

    logger.info(f"Bot created: {config.name} (id={config.id}) by user {user.id}")
    return _config_to_response(config)


@router.get("", response_model=BotListResponse)
async def list_bots(
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """List all bots for the current user with runtime status."""
    # Preload preset names for active presets
    preset_names: dict[int, str] = {}
    preset_result = await db.execute(
        select(ConfigPreset.id, ConfigPreset.name).where(ConfigPreset.user_id == user.id)
    )
    for pid, pname in preset_result.all():
        preset_names[pid] = pname

    # Preload HL gate status (builder fee + referral)
    hl_approved = False
    hl_referral_verified = False
    hl_conn_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == "hyperliquid",
        )
    )
    hl_conn = hl_conn_result.scalar_one_or_none()
    if hl_conn:
        hl_approved = getattr(hl_conn, "builder_fee_approved", False)
        hl_referral_verified = getattr(hl_conn, "referral_verified", False)

    # Preload affiliate UID status (Bitget / Weex) — single query
    affiliate_data: dict[str, dict] = {}
    aff_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type.in_(["bitget", "weex"]),
        )
    )
    for aff_conn in aff_result.scalars().all():
        affiliate_data[aff_conn.exchange_type] = {
            "uid": getattr(aff_conn, "affiliate_uid", None),
            "verified": getattr(aff_conn, "affiliate_verified", False),
        }

    # Filter bots by mode when demo_mode is set
    bot_query = select(BotConfig).where(BotConfig.user_id == user.id)
    if demo_mode is True:
        bot_query = bot_query.where(BotConfig.mode.in_(["demo", "both"]))
    elif demo_mode is False:
        bot_query = bot_query.where(BotConfig.mode.in_(["live", "both"]))
    bot_query = bot_query.order_by(BotConfig.created_at.desc())

    result = await db.execute(bot_query)
    configs = result.scalars().all()

    bot_ids = [c.id for c in configs]
    llm_bot_ids = [c.id for c in configs if c.strategy_type == "llm_signal"]

    # ── Batch queries (replace N+1 per-bot queries) ──────────────

    # Maps: bot_config_id → (count, pnl, fees, funding)
    trade_stats: dict[int, tuple] = {}
    open_counts: dict[int, int] = {}
    closed_stats: dict[int, tuple] = {}
    last_trades: dict[int, TradeRecord] = {}
    bot_snapshots: dict[int, list[str]] = {}

    if bot_ids:
        # Batch 1: Trade stats per bot
        stats_filters = [TradeRecord.bot_config_id.in_(bot_ids)]
        if demo_mode is not None:
            stats_filters.append(TradeRecord.demo_mode == demo_mode)

        stats_result = await db.execute(
            select(
                TradeRecord.bot_config_id,
                func.count(TradeRecord.id),
                func.coalesce(func.sum(TradeRecord.pnl), 0),
                func.coalesce(func.sum(TradeRecord.fees), 0),
                func.coalesce(func.sum(TradeRecord.funding_paid), 0),
            ).where(*stats_filters)
            .group_by(TradeRecord.bot_config_id)
        )
        for bid, cnt, pnl, fees, funding in stats_result.all():
            trade_stats[bid] = (cnt, pnl, fees, funding)

        # Batch 2: Open trade counts per bot
        open_filters = [
            TradeRecord.bot_config_id.in_(bot_ids),
            TradeRecord.status == "open",
        ]
        if demo_mode is not None:
            open_filters.append(TradeRecord.demo_mode == demo_mode)

        open_result = await db.execute(
            select(
                TradeRecord.bot_config_id,
                func.count(TradeRecord.id),
            ).where(*open_filters)
            .group_by(TradeRecord.bot_config_id)
        )
        open_counts = dict(open_result.all())

    if llm_bot_ids:
        # Batch 3: Closed trade stats for LLM accuracy
        closed_filters = [
            TradeRecord.bot_config_id.in_(llm_bot_ids),
            TradeRecord.status == "closed",
        ]
        if demo_mode is not None:
            closed_filters.append(TradeRecord.demo_mode == demo_mode)

        closed_result = await db.execute(
            select(
                TradeRecord.bot_config_id,
                func.count(TradeRecord.id),
                func.sum(case((TradeRecord.pnl > 0, 1), else_=0)),
            ).where(*closed_filters)
            .group_by(TradeRecord.bot_config_id)
        )
        for bid, total, wins in closed_result.all():
            closed_stats[bid] = (total, wins)

        # Batch 4: Last trade per LLM bot (max id per bot → single query)
        last_trade_filters = [TradeRecord.bot_config_id.in_(llm_bot_ids)]
        if demo_mode is not None:
            last_trade_filters.append(TradeRecord.demo_mode == demo_mode)

        max_id_subq = (
            select(func.max(TradeRecord.id).label("max_id"))
            .where(*last_trade_filters)
            .group_by(TradeRecord.bot_config_id)
            .subquery()
        )
        last_trades_result = await db.execute(
            select(TradeRecord).where(TradeRecord.id.in_(select(max_id_subq.c.max_id)))
        )
        last_trades = {t.bot_config_id: t for t in last_trades_result.scalars().all()}

        # Batch 5: Metrics snapshots for token aggregation
        snapshot_filters = [
            TradeRecord.bot_config_id.in_(llm_bot_ids),
            TradeRecord.metrics_snapshot.isnot(None),
        ]
        if demo_mode is not None:
            snapshot_filters.append(TradeRecord.demo_mode == demo_mode)

        snapshots_result = await db.execute(
            select(TradeRecord.bot_config_id, TradeRecord.metrics_snapshot)
            .where(*snapshot_filters)
        )
        for bid, snapshot_json in snapshots_result.all():
            bot_snapshots.setdefault(bid, []).append(snapshot_json)

    # ── Build response from preloaded data ───────────────────────

    bots = []

    for config in configs:
        runtime = orchestrator.get_bot_status(config.id)
        trading_pairs = json.loads(config.trading_pairs) if config.trading_pairs else []

        total_trades, total_pnl, total_fees, total_funding = trade_stats.get(
            config.id, (0, 0, 0, 0)
        )
        open_trades = open_counts.get(config.id, 0)

        # LLM-specific metrics
        llm_data = {}
        if config.strategy_type == "llm_signal":
            last_trade = last_trades.get(config.id)

            if last_trade:
                llm_data["llm_last_direction"] = last_trade.side.upper() if last_trade.side else None
                llm_data["llm_last_confidence"] = last_trade.confidence
                if last_trade.metrics_snapshot:
                    try:
                        metrics = json.loads(last_trade.metrics_snapshot)
                        llm_data["llm_last_reasoning"] = metrics.get("llm_reasoning", "")[:200]
                        llm_data["llm_provider"] = metrics.get("llm_provider")
                        llm_data["llm_model"] = metrics.get("llm_model")
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse metrics_snapshot for trade #{last_trade.id}: {e}")

            # Accuracy from batched closed stats
            closed_total, winners = closed_stats.get(config.id, (0, 0))
            if closed_total and closed_total > 0:
                llm_data["llm_accuracy"] = round(
                    (float(winners or 0) / closed_total) * 100, 1
                )
            llm_data["llm_total_predictions"] = total_trades

            # Token aggregation from batched snapshots
            snapshots = bot_snapshots.get(config.id, [])
            if snapshots:
                total_tokens = 0
                token_count = 0
                for snapshot_json in snapshots:
                    try:
                        snapshot = json.loads(snapshot_json)
                        tokens = snapshot.get("llm_tokens_used", 0)
                        if tokens and tokens > 0:
                            total_tokens += tokens
                            token_count += 1
                    except (json.JSONDecodeError, TypeError):
                        pass
                if token_count > 0:
                    llm_data["llm_total_tokens_used"] = total_tokens
                    llm_data["llm_avg_tokens_per_call"] = round(
                        total_tokens / token_count, 1
                    )

            # Get provider/model from strategy_params as fallback
            if (not llm_data.get("llm_provider") or not llm_data.get("llm_model")) and config.strategy_params:
                try:
                    sp = json.loads(config.strategy_params)
                    if not llm_data.get("llm_provider"):
                        llm_data["llm_provider"] = sp.get("llm_provider")
                    if not llm_data.get("llm_model"):
                        llm_data["llm_model"] = sp.get("llm_model")
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Failed to parse strategy_params for bot {config.id}: {e}")

            # Fallback for legacy bots: detect provider from last trade reason text
            if not llm_data.get("llm_provider") and last_trade and last_trade.reason:
                reason = last_trade.reason
                if reason.startswith("["):
                    bracket_end = reason.find("]")
                    if bracket_end > 0:
                        model_tag = reason[1:bracket_end]
                        from src.ai.providers import MODEL_CATALOG
                        for ptype, cat in MODEL_CATALOG.items():
                            if cat["family_name"] in model_tag:
                                llm_data["llm_provider"] = ptype
                                for m in cat["models"]:
                                    if m["name"] in model_tag:
                                        llm_data["llm_model"] = m["id"]
                                        break
                                break

        bots.append(BotRuntimeStatus(
            bot_config_id=config.id,
            name=config.name,
            strategy_type=config.strategy_type,
            exchange_type=config.exchange_type,
            mode=config.mode,
            trading_pairs=trading_pairs,
            status=runtime["status"] if runtime else ("idle" if not config.is_enabled else "stopped"),
            error_message=runtime.get("error_message") if runtime else None,
            started_at=runtime.get("started_at") if runtime else None,
            last_analysis=runtime.get("last_analysis") if runtime else None,
            trades_today=runtime.get("trades_today", 0) if runtime else 0,
            is_enabled=config.is_enabled,
            total_trades=total_trades,
            total_pnl=round(float(total_pnl), 2),
            total_fees=round(float(total_fees), 2),
            total_funding=round(float(total_funding), 2),
            open_trades=open_trades,
            discord_webhook_configured=bool(config.discord_webhook_url),
            telegram_configured=bool(config.telegram_bot_token and config.telegram_chat_id),
            active_preset_id=config.active_preset_id,
            active_preset_name=preset_names.get(config.active_preset_id) if config.active_preset_id else None,
            builder_fee_approved=hl_approved if config.exchange_type == "hyperliquid" else None,
            referral_verified=hl_referral_verified if config.exchange_type == "hyperliquid" else None,
            affiliate_uid=affiliate_data.get(config.exchange_type, {}).get("uid") if config.exchange_type in ("bitget", "weex") else None,
            affiliate_verified=affiliate_data.get(config.exchange_type, {}).get("verified") if config.exchange_type in ("bitget", "weex") else None,
            **llm_data,
        ))

    return BotListResponse(bots=bots)


@router.get("/{bot_id}", response_model=BotConfigResponse)
async def get_bot(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific bot configuration."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
        .options(selectinload(BotConfig.active_preset))
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")
    return _config_to_response(config)


@router.put("/{bot_id}", response_model=BotConfigResponse)
@limiter.limit("10/minute")
async def update_bot(
    request: Request,
    bot_id: int,
    body: BotConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """Update a bot configuration. Bot must be stopped to update."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Check if running
    if orchestrator.is_running(bot_id):
        raise HTTPException(status_code=400, detail="Stop the bot before editing its configuration")

    # Validate strategy if changed
    if body.strategy_type:
        try:
            StrategyRegistry.get(body.strategy_type)
        except KeyError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Apply updates
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "trading_pairs" and value is not None:
            setattr(config, field, json.dumps(value))
        elif field == "strategy_params" and value is not None:
            setattr(config, field, json.dumps(value))
        elif field == "schedule_config" and value is not None:
            setattr(config, field, json.dumps(value))
        elif field == "per_asset_config" and value is not None:
            setattr(config, field, json.dumps(value))
        elif field == "discord_webhook_url":
            # Empty string = clear, non-empty = encrypt
            if value:
                setattr(config, field, encrypt_value(value))
            else:
                setattr(config, field, None)
        elif field == "telegram_bot_token":
            # Empty string = clear, non-empty = encrypt
            if value:
                setattr(config, field, encrypt_value(value))
            else:
                setattr(config, field, None)
        elif field == "telegram_chat_id":
            # Empty string = clear, non-empty = set
            if value:
                setattr(config, field, value)
            else:
                setattr(config, field, None)
        elif value is not None:
            setattr(config, field, value)

    await db.flush()
    await db.refresh(config)

    logger.info(f"Bot updated: {config.name} (id={bot_id})")
    return _config_to_response(config)


@router.delete("/{bot_id}")
@limiter.limit("10/minute")
async def delete_bot(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """Delete a bot configuration. Bot must be stopped first."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Stop if running
    if orchestrator.is_running(bot_id):
        await orchestrator.stop_bot(bot_id)

    await db.delete(config)
    logger.info(f"Bot deleted: {config.name} (id={bot_id})")
    return {"status": "ok", "message": f"Bot '{config.name}' deleted"}


@router.post("/{bot_id}/duplicate", response_model=BotConfigResponse)
@limiter.limit("10/minute")
async def duplicate_bot(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Duplicate an existing bot configuration (stopped, disabled copy)."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Check bot limit
    count_result = await db.execute(
        select(func.count(BotConfig.id)).where(BotConfig.user_id == user.id)
    )
    if count_result.scalar() >= MAX_BOTS_PER_USER:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_BOTS_PER_USER} bots per user")

    copy = BotConfig(
        user_id=user.id,
        name=f"{original.name} (Copy)",
        description=original.description,
        strategy_type=original.strategy_type,
        exchange_type=original.exchange_type,
        mode=original.mode,
        trading_pairs=original.trading_pairs,
        leverage=original.leverage,
        position_size_percent=original.position_size_percent,
        max_trades_per_day=original.max_trades_per_day,
        take_profit_percent=original.take_profit_percent,
        stop_loss_percent=original.stop_loss_percent,
        daily_loss_limit_percent=original.daily_loss_limit_percent,
        per_asset_config=original.per_asset_config,
        strategy_params=original.strategy_params,
        schedule_type=original.schedule_type,
        schedule_config=original.schedule_config,
        rotation_enabled=original.rotation_enabled,
        rotation_interval_minutes=original.rotation_interval_minutes,
        rotation_start_time=original.rotation_start_time,
        discord_webhook_url=original.discord_webhook_url,
        telegram_bot_token=original.telegram_bot_token,
        telegram_chat_id=original.telegram_chat_id,
        is_enabled=False,
    )
    db.add(copy)
    await db.flush()
    await db.refresh(copy)

    logger.info(f"Bot duplicated: {original.name} -> {copy.name} (id={copy.id}) by user {user.id}")
    return _config_to_response(copy)


# ─── Lifecycle ────────────────────────────────────────────────


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
            AffiliateLink.is_active == True,
            AffiliateLink.uid_required == True,
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


@router.post("/{bot_id}/start")
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
        raise HTTPException(status_code=404, detail="Bot not found")

    # ── Pre-start gates (API level) — admins bypass all gates ──
    if user.role != "admin":
        if config.exchange_type == "hyperliquid":
            await _enforce_hl_gates(user, db)
        if config.exchange_type in ("bitget", "weex"):
            await _enforce_affiliate_gate(config.exchange_type, user, db)

    try:
        await orchestrator.start_bot(bot_id)
    except (ValueError, BotError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Mark as enabled
    config.is_enabled = True
    await db.flush()

    return {"status": "ok", "message": f"Bot '{config.name}' started"}


@router.post("/{bot_id}/stop")
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
        raise HTTPException(status_code=404, detail="Bot not found")
    success = await orchestrator.stop_bot(bot_id)
    if not success:
        raise HTTPException(status_code=400, detail="Bot is not running")

    # Mark as disabled
    config.is_enabled = False
    await db.flush()

    return {"status": "ok", "message": f"Bot '{config.name}' stopped"}


@router.post("/{bot_id}/restart")
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
        raise HTTPException(status_code=404, detail="Bot not found")

    # ── Pre-start gates (API level) — admins bypass all gates ──
    if user.role != "admin":
        if config.exchange_type == "hyperliquid":
            await _enforce_hl_gates(user, db)
        if config.exchange_type in ("bitget", "weex"):
            await _enforce_affiliate_gate(config.exchange_type, user, db)

    try:
        await orchestrator.restart_bot(bot_id)
    except (ValueError, BotError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    config.is_enabled = True
    await db.flush()

    return {"status": "ok", "message": f"Bot '{config.name}' restarted"}


@router.post("/stop-all")
@limiter.limit("5/minute")
async def stop_all_bots(
    request: Request,
    user: User = Depends(get_current_user),
    orchestrator=Depends(get_orchestrator),
):
    """Stop all running bots for the current user."""
    stopped = await orchestrator.stop_all_for_user(user.id)
    return {"status": "ok", "message": f"{stopped} bot(s) stopped"}


@router.post("/{bot_id}/test-telegram")
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
        raise HTTPException(status_code=404, detail="Bot not found")
    if not config.telegram_bot_token or not config.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Telegram not configured")

    from src.notifications.telegram_notifier import TelegramNotifier
    from src.utils.encryption import decrypt_value

    notifier = TelegramNotifier(
        bot_token=decrypt_value(config.telegram_bot_token),
        chat_id=config.telegram_chat_id,
    )
    success = await notifier.send_test_message()
    if not success:
        raise HTTPException(status_code=502, detail="Failed to send Telegram message")
    return {"status": "ok", "message": "Test message sent"}


# ─── Preset Application ──────────────────────────────────────

@router.post("/{bot_id}/apply-preset/{preset_id}", response_model=BotConfigResponse)
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
        raise HTTPException(status_code=404, detail="Bot not found")

    # Check if running
    if orchestrator.is_running(bot_id):
        raise HTTPException(status_code=400, detail="Stop the bot before applying a preset")

    # Load preset
    preset_result = await db.execute(
        select(ConfigPreset).where(ConfigPreset.id == preset_id, ConfigPreset.user_id == user.id)
    )
    preset = preset_result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

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


# ─── Per-Bot Statistics ──────────────────────────────────────

@router.get("/{bot_id}/statistics")
async def get_bot_statistics(
    bot_id: int,
    days: int = Query(default=30, ge=1, le=365),
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed statistics for a specific bot including daily PnL series."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")

    since = datetime.utcnow() - timedelta(days=days)

    # Daily PnL series (cumulative)
    daily_filters = [
        TradeRecord.bot_config_id == bot_id,
        TradeRecord.status == "closed",
        TradeRecord.exit_time >= since,
    ]
    if demo_mode is not None:
        daily_filters.append(TradeRecord.demo_mode == demo_mode)

    daily_result = await db.execute(
        select(
            func.date(TradeRecord.exit_time).label("date"),
            func.sum(TradeRecord.pnl).label("pnl"),
            func.count(TradeRecord.id).label("trades"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
            func.coalesce(func.sum(TradeRecord.fees), 0).label("fees"),
            func.coalesce(func.sum(TradeRecord.funding_paid), 0).label("funding"),
        ).where(
            *daily_filters
        ).group_by(
            func.date(TradeRecord.exit_time)
        ).order_by(
            func.date(TradeRecord.exit_time)
        )
    )
    daily_rows = daily_result.all()

    cumulative = 0.0
    daily_series = []
    for row in daily_rows:
        cumulative += float(row.pnl or 0)
        daily_series.append({
            "date": str(row.date) if row.date else None,
            "pnl": round(float(row.pnl or 0), 2),
            "cumulative_pnl": round(cumulative, 2),
            "trades": row.trades,
            "wins": int(row.wins or 0),
            "fees": round(float(row.fees or 0), 4),
            "funding": round(float(row.funding or 0), 4),
        })

    # Overall stats
    overall_filters = [
        TradeRecord.bot_config_id == bot_id,
        TradeRecord.status == "closed",
    ]
    if demo_mode is not None:
        overall_filters.append(TradeRecord.demo_mode == demo_mode)

    overall_result = await db.execute(
        select(
            func.count(TradeRecord.id).label("total"),
            func.coalesce(func.sum(TradeRecord.pnl), 0).label("total_pnl"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
            func.sum(case((TradeRecord.pnl <= 0, 1), else_=0)).label("losses"),
            func.coalesce(func.sum(TradeRecord.fees), 0).label("total_fees"),
            func.coalesce(func.sum(TradeRecord.funding_paid), 0).label("total_funding"),
            func.avg(TradeRecord.pnl).label("avg_pnl"),
            func.max(TradeRecord.pnl).label("best_trade"),
            func.min(TradeRecord.pnl).label("worst_trade"),
        ).where(*overall_filters)
    )
    stats = overall_result.one()

    total = stats.total or 0
    wins = int(stats.wins or 0)
    win_rate = round((wins / total) * 100, 1) if total > 0 else 0.0

    # Recent trades
    recent_filters = [TradeRecord.bot_config_id == bot_id]
    if demo_mode is not None:
        recent_filters.append(TradeRecord.demo_mode == demo_mode)

    recent_result = await db.execute(
        select(TradeRecord).where(
            *recent_filters
        ).order_by(TradeRecord.entry_time.desc()).limit(20)
    )
    recent_trades = []
    for trade in recent_result.scalars().all():
        recent_trades.append({
            "id": trade.id,
            "symbol": trade.symbol,
            "side": trade.side,
            "size": trade.size,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "pnl": round(float(trade.pnl or 0), 2),
            "pnl_percent": round(float(trade.pnl_percent or 0), 2),
            "confidence": trade.confidence,
            "reason": trade.reason,
            "status": trade.status,
            "demo_mode": trade.demo_mode,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "exit_reason": trade.exit_reason,
            "fees": round(float(trade.fees or 0), 4),
            "funding_paid": round(float(trade.funding_paid or 0), 4),
        })

    return {
        "bot_id": bot_id,
        "bot_name": config.name,
        "strategy_type": config.strategy_type,
        "exchange_type": config.exchange_type,
        "mode": config.mode,
        "days": days,
        "summary": {
            "total_trades": total,
            "wins": wins,
            "losses": int(stats.losses or 0),
            "win_rate": win_rate,
            "total_pnl": round(float(stats.total_pnl or 0), 2),
            "total_fees": round(float(stats.total_fees or 0), 2),
            "total_funding": round(float(stats.total_funding or 0), 2),
            "avg_pnl": round(float(stats.avg_pnl or 0), 2),
            "best_trade": round(float(stats.best_trade or 0), 2),
            "worst_trade": round(float(stats.worst_trade or 0), 2),
        },
        "daily_series": daily_series,
        "recent_trades": recent_trades,
    }


@router.get("/compare/performance")
async def compare_bots_performance(
    days: int = Query(default=30, ge=1, le=365),
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get comparative performance data for all bots (for multi-line chart)."""
    bot_query = select(BotConfig).where(BotConfig.user_id == user.id)
    if demo_mode is True:
        bot_query = bot_query.where(BotConfig.mode.in_(["demo", "both"]))
    elif demo_mode is False:
        bot_query = bot_query.where(BotConfig.mode.in_(["live", "both"]))
    bot_query = bot_query.order_by(BotConfig.created_at)

    configs_result = await db.execute(bot_query)
    configs = configs_result.scalars().all()

    since = datetime.utcnow() - timedelta(days=days)
    bot_ids = [c.id for c in configs]
    if not bot_ids:
        return {"days": days, "bots": []}

    # ── Batch 1: Daily PnL per bot (single query) ────────────────────
    daily_filters = [
        TradeRecord.bot_config_id.in_(bot_ids),
        TradeRecord.status == "closed",
        TradeRecord.exit_time >= since,
    ]
    if demo_mode is not None:
        daily_filters.append(TradeRecord.demo_mode == demo_mode)

    daily_result = await db.execute(
        select(
            TradeRecord.bot_config_id,
            func.date(TradeRecord.exit_time).label("date"),
            func.sum(TradeRecord.pnl).label("pnl"),
        ).where(*daily_filters).group_by(
            TradeRecord.bot_config_id, func.date(TradeRecord.exit_time)
        ).order_by(
            TradeRecord.bot_config_id, func.date(TradeRecord.exit_time)
        )
    )
    # Build per-bot daily series
    daily_by_bot: dict[int, list] = {bid: [] for bid in bot_ids}
    for row in daily_result.all():
        daily_by_bot[row.bot_config_id].append({
            "date": str(row.date) if row.date else None,
            "pnl": float(row.pnl or 0),
        })

    # ── Batch 2: Overall stats per bot (single query) ────────────────
    stats_filters = [
        TradeRecord.bot_config_id.in_(bot_ids),
        TradeRecord.status == "closed",
    ]
    if demo_mode is not None:
        stats_filters.append(TradeRecord.demo_mode == demo_mode)

    stats_result = await db.execute(
        select(
            TradeRecord.bot_config_id,
            func.count(TradeRecord.id).label("total"),
            func.coalesce(func.sum(TradeRecord.pnl), 0).label("pnl"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
            func.coalesce(func.sum(TradeRecord.fees), 0).label("total_fees"),
            func.coalesce(func.sum(TradeRecord.funding_paid), 0).label("total_funding"),
        ).where(*stats_filters).group_by(TradeRecord.bot_config_id)
    )
    stats_by_bot: dict[int, Any] = {}
    for row in stats_result.all():
        stats_by_bot[row.bot_config_id] = row

    # ── Batch 3: Last trade per bot (subquery + join) ────────────────
    last_trade_filters = [TradeRecord.bot_config_id.in_(bot_ids)]
    if demo_mode is not None:
        last_trade_filters.append(TradeRecord.demo_mode == demo_mode)

    max_id_subq = (
        select(func.max(TradeRecord.id).label("max_id"))
        .where(*last_trade_filters)
        .group_by(TradeRecord.bot_config_id)
        .subquery()
    )
    last_trades_result = await db.execute(
        select(TradeRecord).where(TradeRecord.id.in_(select(max_id_subq.c.max_id)))
    )
    last_trade_by_bot: dict[int, TradeRecord] = {}
    for trade in last_trades_result.scalars().all():
        last_trade_by_bot[trade.bot_config_id] = trade

    # ── Assemble response ────────────────────────────────────────────
    bots_data = []
    for config in configs:
        # Build cumulative series from daily data
        cumulative = 0.0
        series = []
        for day in daily_by_bot.get(config.id, []):
            cumulative += day["pnl"]
            series.append({
                "date": day["date"],
                "cumulative_pnl": round(cumulative, 2),
            })

        stats = stats_by_bot.get(config.id)
        total = int(stats.total) if stats else 0
        wins = int(stats.wins or 0) if stats else 0
        pnl = float(stats.pnl or 0) if stats else 0.0
        total_fees = float(stats.total_fees or 0) if stats else 0.0
        total_funding = float(stats.total_funding or 0) if stats else 0.0

        last_trade = last_trade_by_bot.get(config.id)

        # Extract LLM provider/model from strategy_params
        llm_provider = None
        llm_model = None
        if config.strategy_type == "llm_signal":
            if config.strategy_params:
                try:
                    sp = json.loads(config.strategy_params)
                    llm_provider = sp.get("llm_provider")
                    llm_model = sp.get("llm_model")
                except (json.JSONDecodeError, TypeError):
                    pass
            # Fallback for legacy bots: detect provider from last trade reason
            if not llm_provider and last_trade and last_trade.reason:
                reason = last_trade.reason
                if reason.startswith("["):
                    bracket_end = reason.find("]")
                    if bracket_end > 0:
                        model_tag = reason[1:bracket_end]
                        from src.ai.providers import MODEL_CATALOG
                        for ptype, cat in MODEL_CATALOG.items():
                            if cat["family_name"] in model_tag:
                                llm_provider = ptype
                                for m in cat["models"]:
                                    if m["name"] in model_tag:
                                        llm_model = m["id"]
                                        break
                                break

        bots_data.append({
            "bot_id": config.id,
            "name": config.name,
            "strategy_type": config.strategy_type,
            "exchange_type": config.exchange_type,
            "mode": config.mode,
            "total_trades": total,
            "total_pnl": round(pnl, 2),
            "total_fees": round(total_fees, 2),
            "total_funding": round(total_funding, 2),
            "win_rate": round((wins / total) * 100, 1) if total > 0 else 0.0,
            "wins": wins,
            "last_direction": last_trade.side.upper() if last_trade and last_trade.side else None,
            "last_confidence": last_trade.confidence if last_trade else None,
            "llm_provider": llm_provider,
            "llm_model": llm_model,
            "series": series,
        })

    return {"days": days, "bots": bots_data}
