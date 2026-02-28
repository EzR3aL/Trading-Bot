"""
Multibot management endpoints.

CRUD for bot configs, strategies, data sources.
Lifecycle (start/stop) and statistics live in sub-modules
(bots_lifecycle, bots_statistics) and are included via sub-routers.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.schemas.bots import (
    BotBudgetInfo,
    BotBudgetListResponse,
    BotConfigCreate,
    BotConfigResponse,
    BotConfigUpdate,
    BotListResponse,
    BotRuntimeStatus,
    ExchangeBalanceOverview,
    ExchangeBalancePreview,
    StrategiesListResponse,
    StrategyInfo,
    SymbolConflict,
    SymbolConflictResponse,
)
from src.auth.dependencies import get_current_user
from src.errors import ERR_BOT_NOT_FOUND, ERR_MAX_BOTS_REACHED, ERR_STOP_BOT_BEFORE_EDIT
from src.models.database import BotConfig, ConfigPreset, ExchangeConnection, TradeRecord, User
from src.models.session import get_db
from src.strategy import StrategyRegistry  # imports __init__.py → registers all strategies
from src.api.rate_limit import limiter
from src.utils.encryption import encrypt_value
from src.utils.json_helpers import parse_json_field
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/bots", tags=["bots"])

MAX_BOTS_PER_USER = 10


def get_orchestrator(request: Request):
    """FastAPI dependency: retrieve orchestrator from app.state."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Bot-Orchestrator nicht initialisiert")
    return orchestrator


def _config_to_response(config: BotConfig) -> BotConfigResponse:
    """Convert a BotConfig ORM object to a response schema."""
    ctx = f"bot {config.id}"
    trading_pairs = parse_json_field(config.trading_pairs, field_name="trading_pairs", context=ctx, default=[])
    strategy_params = parse_json_field(config.strategy_params, field_name="strategy_params", context=ctx)
    schedule_config = parse_json_field(config.schedule_config, field_name="schedule_config", context=ctx)
    per_asset_config = parse_json_field(config.per_asset_config, field_name="per_asset_config", context=ctx)

    return BotConfigResponse(
        id=config.id,
        name=config.name,
        description=config.description,
        strategy_type=config.strategy_type,
        exchange_type=config.exchange_type,
        mode=config.mode,
        margin_mode=getattr(config, "margin_mode", None) or "cross",
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


# Mode overlap: which existing modes conflict with a new bot's mode
_MODE_CONFLICTS: dict[str, set[str]] = {
    "demo": {"demo", "both"},
    "live": {"live", "both"},
    "both": {"demo", "live", "both"},
}


async def _check_symbol_conflicts(
    db: AsyncSession,
    user_id: int,
    exchange_type: str,
    mode: str,
    trading_pairs: list[str],
    exclude_bot_id: int | None = None,
) -> list[SymbolConflict]:
    """Find enabled bots that already trade the same symbols on the same exchange/mode."""
    conflicting_modes = _MODE_CONFLICTS.get(mode, set())
    query = (
        select(BotConfig)
        .where(
            BotConfig.user_id == user_id,
            BotConfig.exchange_type == exchange_type,
            BotConfig.is_enabled.is_(True),
            BotConfig.mode.in_(conflicting_modes),
        )
    )
    if exclude_bot_id is not None:
        query = query.where(BotConfig.id != exclude_bot_id)

    result = await db.execute(query)
    existing_bots = result.scalars().all()

    requested_set = set(trading_pairs)
    conflicts: list[SymbolConflict] = []
    for bot in existing_bots:
        existing_pairs = set(parse_json_field(bot.trading_pairs, field_name="trading_pairs", context=f"bot {bot.id}", default=[]))
        overlap = requested_set & existing_pairs
        for symbol in sorted(overlap):
            conflicts.append(SymbolConflict(
                symbol=symbol,
                existing_bot_id=bot.id,
                existing_bot_name=bot.name,
                existing_bot_mode=bot.mode,
            ))
    return conflicts


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


# ─── Balance Preview (for BotBuilder) ────────────────────────

@router.get("/balance-preview", response_model=ExchangeBalancePreview)
@limiter.limit("15/minute")
async def get_balance_preview(
    request: Request,
    exchange_type: str = Query(..., pattern="^(bitget|weex|hyperliquid)$"),
    mode: str = Query(..., pattern="^(demo|live|both)$"),
    exclude_bot_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Balance preview for the BotBuilder — shows equity, allocated %, and remaining."""
    import asyncio
    from src.exchanges.factory import create_exchange_client
    from src.utils.encryption import decrypt_value

    # For "both" mode, live balance is the limiting factor
    effective_mode = "live" if mode == "both" else mode

    # Check exchange connection
    conn_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == exchange_type,
        )
    )
    conn = conn_result.scalar_one_or_none()
    if not conn:
        return ExchangeBalancePreview(
            exchange_type=exchange_type, mode=mode, has_connection=False,
            error="no_connection",
        )

    is_demo = effective_mode == "demo"
    api_key_enc = conn.demo_api_key_encrypted if is_demo else conn.api_key_encrypted
    api_secret_enc = conn.demo_api_secret_encrypted if is_demo else conn.api_secret_encrypted
    passphrase_enc = conn.demo_passphrase_encrypted if is_demo else conn.passphrase_encrypted

    if not api_key_enc or not api_secret_enc:
        return ExchangeBalancePreview(
            exchange_type=exchange_type, mode=mode, has_connection=False,
            error="no_credentials",
        )

    # Fetch balance (reuse budget cache)
    cache_key = f"budget:{user.id}:{exchange_type}:{effective_mode}"
    cached = _budget_cache_get(cache_key)
    if cached:
        available, equity, currency = cached
    else:
        try:
            client = create_exchange_client(
                exchange_type=exchange_type,
                api_key=decrypt_value(api_key_enc),
                api_secret=decrypt_value(api_secret_enc),
                passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
                demo_mode=is_demo,
            )
            balance = await asyncio.wait_for(client.get_account_balance(), timeout=10.0)
            available = balance.available
            equity = balance.total
            currency = balance.currency
            _budget_cache_set(cache_key, (available, equity, currency))
        except Exception as e:
            logger.warning("Balance preview fetch failed for %s/%s: %s", exchange_type, effective_mode, e)
            return ExchangeBalancePreview(
                exchange_type=exchange_type, mode=mode, has_connection=True,
                error=f"fetch_failed: {e}",
            )

    # Calculate already-allocated % from existing bots on this exchange/mode
    bot_filter = [
        BotConfig.user_id == user.id,
        BotConfig.exchange_type == exchange_type,
    ]
    if mode == "both":
        bot_filter.append(BotConfig.mode.in_(["live", "both"]))
    else:
        bot_filter.append(BotConfig.mode.in_([mode, "both"]))

    if exclude_bot_id:
        bot_filter.append(BotConfig.id != exclude_bot_id)

    bots_result = await db.execute(select(BotConfig).where(*bot_filter))
    existing_bots = bots_result.scalars().all()

    total_allocated_pct = 0.0
    for bot in existing_bots:
        pac = parse_json_field(bot.per_asset_config, field_name="per_asset_config", context=f"bot {bot.id}", default={})
        try:
            pairs = json.loads(bot.trading_pairs) if isinstance(bot.trading_pairs, str) else (bot.trading_pairs or [])
        except (json.JSONDecodeError, TypeError):
            pairs = []
        for symbol in pairs:
            pct = (pac.get(symbol) or {}).get("position_pct")
            if pct and pct > 0:
                total_allocated_pct += pct

    allocated_amount = equity * total_allocated_pct / 100 if equity > 0 else 0.0
    remaining = max(0.0, equity - allocated_amount)

    return ExchangeBalancePreview(
        exchange_type=exchange_type,
        mode=mode,
        currency=currency,
        exchange_balance=round(available, 2),
        exchange_equity=round(equity, 2),
        existing_allocated_pct=round(total_allocated_pct, 1),
        existing_allocated_amount=round(allocated_amount, 2),
        remaining_balance=round(remaining, 2),
        has_connection=True,
    )


@router.get("/balance-overview", response_model=ExchangeBalanceOverview)
@limiter.limit("10/minute")
async def get_balance_overview(
    request: Request,
    exclude_bot_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Balance overview across ALL connected exchanges (demo + live)."""
    import asyncio
    from src.exchanges.factory import create_exchange_client
    from src.utils.encryption import decrypt_value

    # Load all exchange connections
    conn_result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user.id)
    )
    connections = {c.exchange_type: c for c in conn_result.scalars().all()}

    # Load all bots for allocation calculation
    bot_filter = [BotConfig.user_id == user.id]
    if exclude_bot_id:
        bot_filter.append(BotConfig.id != exclude_bot_id)
    bots_result = await db.execute(select(BotConfig).where(*bot_filter))
    all_bots = bots_result.scalars().all()

    # Build (exchange, mode) pairs to query
    exchange_modes: list[tuple[str, str]] = []
    for ex_type in ["bitget", "weex", "hyperliquid"]:
        conn = connections.get(ex_type)
        if not conn:
            continue
        if conn.demo_api_key_encrypted and conn.demo_api_secret_encrypted:
            exchange_modes.append((ex_type, "demo"))
        if conn.api_key_encrypted and conn.api_secret_encrypted:
            exchange_modes.append((ex_type, "live"))

    if not exchange_modes:
        return ExchangeBalanceOverview(exchanges=[])

    # Fetch balances in parallel
    results: list[ExchangeBalancePreview] = []

    async def _fetch(ex_type: str, mode: str):
        conn = connections[ex_type]
        is_demo = mode == "demo"
        api_key_enc = conn.demo_api_key_encrypted if is_demo else conn.api_key_encrypted
        api_secret_enc = conn.demo_api_secret_encrypted if is_demo else conn.api_secret_encrypted
        passphrase_enc = conn.demo_passphrase_encrypted if is_demo else conn.passphrase_encrypted

        # Fetch balance with cache
        cache_key = f"budget:{user.id}:{ex_type}:{mode}"
        cached = _budget_cache_get(cache_key)
        if cached:
            available, equity, currency = cached
        else:
            try:
                client = create_exchange_client(
                    exchange_type=ex_type,
                    api_key=decrypt_value(api_key_enc),
                    api_secret=decrypt_value(api_secret_enc),
                    passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
                    demo_mode=is_demo,
                )
                balance = await asyncio.wait_for(client.get_account_balance(), timeout=10.0)
                available, equity, currency = balance.available, balance.total, balance.currency
                _budget_cache_set(cache_key, (available, equity, currency))
            except Exception as e:
                logger.warning("Balance overview fetch failed for %s/%s: %s", ex_type, mode, e)
                results.append(ExchangeBalancePreview(
                    exchange_type=ex_type, mode=mode, has_connection=True,
                    error=f"fetch_failed",
                ))
                return

        # Calculate allocated % from existing bots on this exchange/mode
        total_pct = 0.0
        for bot in all_bots:
            if bot.exchange_type != ex_type:
                continue
            if mode not in (["demo", "both"] if bot.mode == "both" else [bot.mode]):
                if not (bot.mode == "both" or bot.mode == mode):
                    continue
            pac = parse_json_field(bot.per_asset_config, field_name="per_asset_config", context=f"bot {bot.id}", default={})
            try:
                pairs = json.loads(bot.trading_pairs) if isinstance(bot.trading_pairs, str) else (bot.trading_pairs or [])
            except (json.JSONDecodeError, TypeError):
                pairs = []
            for symbol in pairs:
                pct = (pac.get(symbol) or {}).get("position_pct")
                if pct and pct > 0:
                    total_pct += pct

        allocated_amount = equity * total_pct / 100 if equity > 0 else 0.0
        results.append(ExchangeBalancePreview(
            exchange_type=ex_type,
            mode=mode,
            currency=currency,
            exchange_balance=round(available, 2),
            exchange_equity=round(equity, 2),
            existing_allocated_pct=round(total_pct, 1),
            existing_allocated_amount=round(allocated_amount, 2),
            remaining_balance=round(max(0.0, equity - allocated_amount), 2),
            has_connection=True,
        ))

    await asyncio.gather(*(_fetch(ex, m) for ex, m in exchange_modes), return_exceptions=True)

    return ExchangeBalanceOverview(exchanges=results)


# ─── Symbol Conflict Check ────────────────────────────────────

@router.get("/symbol-conflicts", response_model=SymbolConflictResponse)
@limiter.limit("30/minute")
async def check_symbol_conflicts(
    request: Request,
    exchange_type: str = Query(..., pattern="^(bitget|weex|hyperliquid)$"),
    mode: str = Query(..., pattern="^(demo|live|both)$"),
    trading_pairs: str = Query(..., description="Comma-separated list of trading pairs"),
    exclude_bot_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if trading pairs conflict with existing enabled bots."""
    pairs = [p.strip() for p in trading_pairs.split(",") if p.strip()]
    if not pairs:
        return SymbolConflictResponse()
    conflicts = await _check_symbol_conflicts(db, user.id, exchange_type, mode, pairs, exclude_bot_id)
    return SymbolConflictResponse(has_conflicts=len(conflicts) > 0, conflicts=conflicts)


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
        raise HTTPException(status_code=400, detail=ERR_MAX_BOTS_REACHED.format(max_bots=MAX_BOTS_PER_USER))

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
        margin_mode=body.margin_mode,
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

    from src.utils.event_logger import log_event
    await log_event("bot_created", f"Bot '{config.name}' created", user_id=user.id, bot_id=config.id)

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
            margin_mode=getattr(config, "margin_mode", None) or "cross",
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
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)
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
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    # Check if running
    if orchestrator.is_running(bot_id):
        raise HTTPException(status_code=400, detail=ERR_STOP_BOT_BEFORE_EDIT)

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
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    # Stop if running
    if orchestrator.is_running(bot_id):
        await orchestrator.stop_bot(bot_id)

    bot_name = config.name
    await db.delete(config)
    logger.info(f"Bot deleted: {bot_name} (id={bot_id})")

    from src.utils.event_logger import log_event
    await log_event("bot_deleted", f"Bot '{bot_name}' deleted", user_id=user.id, bot_id=bot_id)

    return {"status": "ok", "message": f"Bot '{bot_name}' deleted"}


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
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    # Check bot limit
    count_result = await db.execute(
        select(func.count(BotConfig.id)).where(BotConfig.user_id == user.id)
    )
    if count_result.scalar() >= MAX_BOTS_PER_USER:
        raise HTTPException(status_code=400, detail=ERR_MAX_BOTS_REACHED.format(max_bots=MAX_BOTS_PER_USER))

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

    from src.utils.event_logger import log_event
    await log_event("bot_duplicated", f"Bot '{original.name}' duplicated as '{copy.name}'", user_id=user.id, bot_id=copy.id)

    return _config_to_response(copy)


# ─── Budget / Balance Info ────────────────────────────────────

import asyncio
import time as _time

_budget_cache: dict[str, tuple[float, any]] = {}
_BUDGET_CACHE_TTL = 30  # seconds


def _budget_cache_get(key: str):
    entry = _budget_cache.get(key)
    if entry and (_time.monotonic() - entry[0]) < _BUDGET_CACHE_TTL:
        return entry[1]
    return None


def _budget_cache_set(key: str, value):
    _budget_cache[key] = (_time.monotonic(), value)


@router.get("/budget-info", response_model=BotBudgetListResponse)
@limiter.limit("10/minute")
async def get_budget_info(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Budget allocation info per bot with overallocation warnings."""
    from src.exchanges.factory import create_exchange_client
    from src.utils.encryption import decrypt_value

    # Load all bot configs for this user
    result = await db.execute(
        select(BotConfig).where(
            BotConfig.user_id == user.id,
            BotConfig.is_enabled == True,  # noqa: E712
        )
    )
    bot_configs = result.scalars().all()
    if not bot_configs:
        return BotBudgetListResponse(budgets=[])

    # Load exchange connections
    conn_result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user.id)
    )
    connections = {c.exchange_type: c for c in conn_result.scalars().all()}

    # Group bots by (exchange_type, effective_mode)
    # "both" mode counts as two groups: demo + live
    groups: dict[tuple[str, str], list[BotConfig]] = {}
    for bot in bot_configs:
        modes = ["demo", "live"] if bot.mode == "both" else [bot.mode]
        for m in modes:
            key = (bot.exchange_type, m)
            groups.setdefault(key, []).append(bot)

    # Fetch balance per (exchange, mode) with caching
    balances: dict[tuple[str, str], tuple[float, float, str]] = {}  # (available, equity, currency)

    async def _fetch_balance(exchange_type: str, mode: str):
        cache_key = f"budget:{user.id}:{exchange_type}:{mode}"
        cached = _budget_cache_get(cache_key)
        if cached is not None:
            balances[(exchange_type, mode)] = cached
            return

        conn = connections.get(exchange_type)
        if not conn:
            return

        is_demo = mode == "demo"
        if is_demo:
            api_key_enc = conn.demo_api_key_encrypted
            api_secret_enc = conn.demo_api_secret_encrypted
            passphrase_enc = conn.demo_passphrase_encrypted
        else:
            api_key_enc = conn.api_key_encrypted
            api_secret_enc = conn.api_secret_encrypted
            passphrase_enc = conn.passphrase_encrypted

        if not api_key_enc or not api_secret_enc:
            return

        try:
            client = create_exchange_client(
                exchange_type=exchange_type,
                api_key=decrypt_value(api_key_enc),
                api_secret=decrypt_value(api_secret_enc),
                passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
                demo_mode=is_demo,
            )
            balance = await asyncio.wait_for(client.get_account_balance(), timeout=10.0)
            val = (balance.available, balance.total, balance.currency)
            balances[(exchange_type, mode)] = val
            _budget_cache_set(cache_key, val)
        except Exception as e:
            logger.warning(f"Budget balance fetch failed for {exchange_type}/{mode}: {e}")

    await asyncio.gather(
        *(_fetch_balance(ex, m) for ex, m in groups.keys()),
        return_exceptions=True,
    )

    # Calculate per-bot budget info
    # First: compute total_allocated_pct per (exchange, mode)
    group_total_pct: dict[tuple[str, str], float] = {}
    bot_pct_map: dict[tuple[int, str], float] = {}  # (bot_id, mode) -> pct

    for (exchange_type, mode), bots in groups.items():
        total_pct = 0.0
        for bot in bots:
            pac = parse_json_field(
                bot.per_asset_config,
                field_name="per_asset_config",
                context=f"bot {bot.id}",
                default={},
            )
            # Sum position_pct across all trading pairs for this bot
            bot_pct = 0.0
            try:
                pairs = json.loads(bot.trading_pairs) if isinstance(bot.trading_pairs, str) else bot.trading_pairs
            except (json.JSONDecodeError, TypeError):
                pairs = []

            has_fixed = False
            for symbol in pairs:
                asset_cfg = pac.get(symbol, {})
                pct = asset_cfg.get("position_pct")
                if pct is not None and pct > 0:
                    bot_pct += pct
                    has_fixed = True

            # If no per-asset config, this bot uses equal split of remaining
            if not has_fixed:
                bot_pct = 100.0 / max(len(bots), 1) if not any(
                    parse_json_field(b.per_asset_config, default={}).get(s, {}).get("position_pct")
                    for b in bots
                    for s in (json.loads(b.trading_pairs) if isinstance(b.trading_pairs, str) else [])
                ) else 0.0

            bot_pct_map[(bot.id, mode)] = bot_pct
            total_pct += bot_pct

        group_total_pct[(exchange_type, mode)] = total_pct

    # Build response
    budgets: list[BotBudgetInfo] = []
    seen = set()

    for (exchange_type, mode), bots in groups.items():
        bal = balances.get((exchange_type, mode))
        available = bal[0] if bal else 0.0
        equity = bal[1] if bal else 0.0
        currency = bal[2] if bal else "USDT"
        total_pct = group_total_pct.get((exchange_type, mode), 0.0)

        for bot in bots:
            # Avoid duplicate entries for "both" mode bots
            entry_key = (bot.id, mode)
            if entry_key in seen:
                continue
            seen.add(entry_key)

            pct = bot_pct_map.get((bot.id, mode), 0.0)
            allocated_budget = equity * pct / 100 if pct > 0 else 0.0
            has_funds = allocated_budget <= available and total_pct <= 100.0

            warning = None
            if total_pct > 100.0:
                warning = f"Overallocated: {total_pct:.0f}% of 100% used on {exchange_type} ({mode})"
            elif allocated_budget > available:
                warning = f"Insufficient balance: ${allocated_budget:,.2f} needed, ${available:,.2f} available"

            budgets.append(BotBudgetInfo(
                bot_config_id=bot.id,
                bot_name=bot.name,
                exchange_type=exchange_type,
                mode=mode,
                currency=currency,
                exchange_balance=available,
                exchange_equity=equity,
                allocated_budget=allocated_budget,
                allocated_pct=pct,
                total_allocated_pct=total_pct,
                has_sufficient_funds=has_funds,
                warning_message=warning,
            ))

    return BotBudgetListResponse(budgets=budgets)


# ─── Include sub-routers ─────────────────────────────────────

from src.api.routers.bots_lifecycle import lifecycle_router  # noqa: E402
from src.api.routers.bots_statistics import statistics_router  # noqa: E402

router.include_router(lifecycle_router)
router.include_router(statistics_router)

# ─── Re-exports for backward compatibility (tests import from here) ──

from src.api.routers.bots_lifecycle import (  # noqa: E402, F401
    _enforce_affiliate_gate,
    _enforce_hl_gates,
    apply_preset_to_bot,
    reset_preset,
    restart_bot,
    start_bot,
    stop_all_bots,
    stop_bot,
    test_telegram,
)
from src.api.routers.bots_statistics import (  # noqa: E402, F401
    compare_bots_performance,
    get_bot_statistics,
)
