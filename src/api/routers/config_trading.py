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
from src.services import config_service
from src.services.config_service import get_or_create_config
from src.api.rate_limit import limiter

router = APIRouter()


@router.get("/", response_model=ConfigResponse)
async def get_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's configuration."""
    payload = await config_service.get_user_config_response(user, db)

    trading = (
        TradingConfigUpdate(**payload["trading"])
        if payload["trading"] is not None
        else None
    )
    strategy = (
        StrategyConfigUpdate(**payload["strategy"])
        if payload["strategy"] is not None
        else None
    )

    return ConfigResponse(
        trading=trading,
        strategy=strategy,
        connections=payload["connections"],
        exchange_type=payload["exchange_type"],
        api_keys_configured=payload["api_keys_configured"],
        demo_api_keys_configured=payload["demo_api_keys_configured"],
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
