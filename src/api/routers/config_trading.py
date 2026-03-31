"""Trading and strategy configuration endpoints."""

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.config import (
    ConfigResponse,
    StrategyConfigUpdate,
    TradingConfigUpdate,
)
from src.auth.dependencies import get_current_user
from src.models.database import User
from src.models.session import get_db
from src.services.config_service import (
    conn_to_response,
    get_or_create_config,
    get_user_connections,
)
from src.api.rate_limit import limiter

router = APIRouter()


@router.get("/", response_model=ConfigResponse)
async def get_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's configuration."""
    config = await get_or_create_config(user, db)
    connections = await get_user_connections(user.id, db)

    trading = None
    if config.trading_config:
        trading = TradingConfigUpdate(**json.loads(config.trading_config))

    strategy = None
    if config.strategy_config:
        strategy = StrategyConfigUpdate(**json.loads(config.strategy_config))

    conn_responses = [conn_to_response(c) for c in connections]

    # Deprecated fields for backward compat
    has_live_keys = bool(config.api_key_encrypted)
    has_demo_keys = bool(config.demo_api_key_encrypted)

    return ConfigResponse(
        trading=trading,
        strategy=strategy,
        connections=conn_responses,
        exchange_type=config.exchange_type,
        api_keys_configured=has_live_keys,
        demo_api_keys_configured=has_demo_keys,
    )


@router.put("/trading")
@limiter.limit("10/minute")
async def update_trading_config(
    request: Request,
    data: TradingConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update trading parameters."""
    config = await get_or_create_config(user, db)
    config.trading_config = json.dumps(data.model_dump())
    return {"status": "ok", "message": "Trading config updated"}


@router.put("/strategy")
@limiter.limit("10/minute")
async def update_strategy_config(
    request: Request,
    data: StrategyConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update strategy thresholds."""
    config = await get_or_create_config(user, db)
    config.strategy_config = json.dumps(data.model_dump())
    return {"status": "ok", "message": "Strategy config updated"}
