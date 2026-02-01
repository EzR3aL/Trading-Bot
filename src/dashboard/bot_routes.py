"""
Bot Management API routes.

Provides REST endpoints for creating, managing, and monitoring
trading bot instances.
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.auth.dependencies import get_current_user_payload, TokenPayload
from src.models.bot_instance import BotInstanceRepository, BotConfig
from src.bot.orchestrator import get_orchestrator, BotStatus
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Router
router = APIRouter(prefix="/api/bots", tags=["bots"])


# ==================== REQUEST/RESPONSE MODELS ====================


class BotConfigModel(BaseModel):
    """Bot configuration model for API."""
    trading_pairs: List[str] = Field(default=["BTCUSDT", "ETHUSDT"])
    leverage: int = Field(default=3, ge=1, le=20)
    position_size_percent: float = Field(default=7.5, ge=1, le=100)
    max_trades_per_day: int = Field(default=2, ge=1, le=20)
    daily_loss_limit_percent: float = Field(default=5.0, ge=1, le=50)
    take_profit_percent: float = Field(default=4.0, ge=0.5, le=50)
    stop_loss_percent: float = Field(default=1.5, ge=0.5, le=20)
    min_confidence: int = Field(default=60, ge=0, le=100)


class BotCreateRequest(BaseModel):
    """Request to create a new bot instance."""
    name: str = Field(..., min_length=1, max_length=100)
    credential_id: int = Field(..., gt=0)
    config: Optional[BotConfigModel] = None


class BotUpdateRequest(BaseModel):
    """Request to update bot configuration."""
    config: BotConfigModel


class BotResponse(BaseModel):
    """Bot instance response."""
    id: int
    name: str
    credential_id: int
    config: dict
    is_running: bool
    runtime_status: str
    uptime_seconds: int
    last_heartbeat: Optional[datetime]
    created_at: Optional[datetime]


class BotListResponse(BaseModel):
    """List of bot instances."""
    bots: List[BotResponse]
    count: int


class BotHealthResponse(BaseModel):
    """Bot health response."""
    status: str
    last_heartbeat: Optional[datetime]
    uptime_seconds: int
    trades_today: int
    daily_pnl: float
    open_positions: int
    error_message: Optional[str]


class MessageResponse(BaseModel):
    """Simple message response."""
    message: str
    success: bool = True


# ==================== BOT ENDPOINTS ====================


@router.get("", response_model=BotListResponse)
@limiter.limit("30/minute")
async def list_bots(
    request: Request,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    List all bot instances for the current user.
    """
    orchestrator = await get_orchestrator()
    instances = await orchestrator.get_user_instances(payload.user_id)

    bots = []
    for inst in instances:
        bots.append(BotResponse(
            id=inst["id"],
            name=inst["name"],
            credential_id=inst["credential_id"],
            config=inst["config"],
            is_running=inst["is_running"],
            runtime_status=inst.get("runtime_status", "stopped"),
            uptime_seconds=inst.get("uptime_seconds", 0),
            last_heartbeat=inst.get("last_heartbeat"),
            created_at=inst.get("created_at"),
        ))

    return BotListResponse(bots=bots, count=len(bots))


@router.post("", response_model=BotResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
async def create_bot(
    request: Request,
    data: BotCreateRequest,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Create a new bot instance.
    """
    # Verify credential belongs to user
    from src.security.credential_manager import CredentialManager
    cred_manager = CredentialManager()
    credential = await cred_manager.get_credential(data.credential_id, payload.user_id)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found"
        )

    # Create config
    config = None
    if data.config:
        config = BotConfig(
            trading_pairs=data.config.trading_pairs,
            leverage=data.config.leverage,
            position_size_percent=data.config.position_size_percent,
            max_trades_per_day=data.config.max_trades_per_day,
            daily_loss_limit_percent=data.config.daily_loss_limit_percent,
            take_profit_percent=data.config.take_profit_percent,
            stop_loss_percent=data.config.stop_loss_percent,
            min_confidence=data.config.min_confidence,
        )

    # Create bot instance
    repo = BotInstanceRepository()
    try:
        instance = await repo.create(
            user_id=payload.user_id,
            credential_id=data.credential_id,
            name=data.name,
            config=config
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )

    logger.info(f"User {payload.user_id} created bot '{data.name}'")

    return BotResponse(
        id=instance.id,
        name=instance.name,
        credential_id=instance.credential_id,
        config=instance.config.to_dict(),
        is_running=instance.is_running,
        runtime_status=BotStatus.STOPPED.value,
        uptime_seconds=0,
        last_heartbeat=instance.last_heartbeat,
        created_at=instance.created_at,
    )


@router.get("/{bot_id}", response_model=BotResponse)
@limiter.limit("30/minute")
async def get_bot(
    request: Request,
    bot_id: int,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Get a specific bot instance.
    """
    repo = BotInstanceRepository()
    instance = await repo.get_by_id(bot_id, payload.user_id)

    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot not found"
        )

    # Get runtime status
    orchestrator = await get_orchestrator()
    instances = await orchestrator.get_user_instances(payload.user_id)
    runtime_info = next((i for i in instances if i["id"] == bot_id), {})

    return BotResponse(
        id=instance.id,
        name=instance.name,
        credential_id=instance.credential_id,
        config=instance.config.to_dict(),
        is_running=instance.is_running,
        runtime_status=runtime_info.get("runtime_status", BotStatus.STOPPED.value),
        uptime_seconds=runtime_info.get("uptime_seconds", 0),
        last_heartbeat=instance.last_heartbeat,
        created_at=instance.created_at,
    )


@router.put("/{bot_id}", response_model=MessageResponse)
@limiter.limit("10/hour")
async def update_bot_config(
    request: Request,
    bot_id: int,
    data: BotUpdateRequest,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Update bot configuration.

    Note: Changes take effect on next bot restart.
    """
    repo = BotInstanceRepository()

    # Verify bot exists and belongs to user
    instance = await repo.get_by_id(bot_id, payload.user_id)
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot not found"
        )

    # Create new config
    config = BotConfig(
        trading_pairs=data.config.trading_pairs,
        leverage=data.config.leverage,
        position_size_percent=data.config.position_size_percent,
        max_trades_per_day=data.config.max_trades_per_day,
        daily_loss_limit_percent=data.config.daily_loss_limit_percent,
        take_profit_percent=data.config.take_profit_percent,
        stop_loss_percent=data.config.stop_loss_percent,
        min_confidence=data.config.min_confidence,
    )

    # Update
    success = await repo.update_config(bot_id, payload.user_id, config)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update configuration"
        )

    logger.info(f"User {payload.user_id} updated bot {bot_id} config")

    # Check if running
    if instance.is_running:
        return MessageResponse(
            message="Configuration updated. Restart bot for changes to take effect.",
            success=True
        )

    return MessageResponse(message="Configuration updated")


@router.delete("/{bot_id}", response_model=MessageResponse)
@limiter.limit("10/hour")
async def delete_bot(
    request: Request,
    bot_id: int,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Delete a bot instance.

    The bot must be stopped before deletion.
    """
    repo = BotInstanceRepository()

    # Verify bot exists and belongs to user
    instance = await repo.get_by_id(bot_id, payload.user_id)
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot not found"
        )

    # Check if running
    if instance.is_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete running bot. Stop it first."
        )

    # Delete
    success = await repo.delete(bot_id, payload.user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete bot"
        )

    logger.info(f"User {payload.user_id} deleted bot {bot_id}")

    return MessageResponse(message="Bot deleted")


@router.post("/{bot_id}/start", response_model=MessageResponse)
@limiter.limit("10/minute")
async def start_bot(
    request: Request,
    bot_id: int,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Start a bot instance.
    """
    orchestrator = await get_orchestrator()

    try:
        await orchestrator.start_instance(bot_id, payload.user_id)
        logger.info(f"User {payload.user_id} started bot {bot_id}")
        return MessageResponse(message="Bot started")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to start bot {bot_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start bot: {str(e)}"
        )


@router.post("/{bot_id}/stop", response_model=MessageResponse)
@limiter.limit("10/minute")
async def stop_bot(
    request: Request,
    bot_id: int,
    force: bool = False,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Stop a bot instance.

    Args:
        force: If True, forcefully stop without graceful shutdown
    """
    orchestrator = await get_orchestrator()

    try:
        await orchestrator.stop_instance(bot_id, payload.user_id, force=force)
        logger.info(f"User {payload.user_id} stopped bot {bot_id}")
        return MessageResponse(message="Bot stopped")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to stop bot {bot_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop bot: {str(e)}"
        )


@router.get("/{bot_id}/status", response_model=BotHealthResponse)
@limiter.limit("60/minute")
async def get_bot_status(
    request: Request,
    bot_id: int,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Get detailed status/health for a bot instance.
    """
    orchestrator = await get_orchestrator()

    try:
        health = await orchestrator.get_instance_health(bot_id, payload.user_id)
        return BotHealthResponse(
            status=health.status.value,
            last_heartbeat=health.last_heartbeat,
            uptime_seconds=health.uptime_seconds,
            trades_today=health.trades_today,
            daily_pnl=health.daily_pnl,
            open_positions=health.open_positions,
            error_message=health.error_message,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/{bot_id}/restart", response_model=MessageResponse)
@limiter.limit("5/minute")
async def restart_bot(
    request: Request,
    bot_id: int,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Restart a bot instance.

    Stops the bot gracefully, then starts it again.
    """
    orchestrator = await get_orchestrator()

    try:
        # Stop
        await orchestrator.stop_instance(bot_id, payload.user_id)

        # Wait a moment
        import asyncio
        await asyncio.sleep(2)

        # Start
        await orchestrator.start_instance(bot_id, payload.user_id)

        logger.info(f"User {payload.user_id} restarted bot {bot_id}")
        return MessageResponse(message="Bot restarted")

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to restart bot {bot_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restart bot: {str(e)}"
        )


class RiskStatsResponse(BaseModel):
    """Risk statistics response."""
    can_trade: bool
    reason: str
    config: dict
    daily_stats: Optional[dict]
    remaining_trades: int
    remaining_risk_budget_percent: float
    dynamic_loss_limit_percent: float


@router.get("/{bot_id}/risk", response_model=RiskStatsResponse)
@limiter.limit("30/minute")
async def get_bot_risk_stats(
    request: Request,
    bot_id: int,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Get risk management stats for a bot instance.

    Returns current risk limits, daily stats, and trading status.
    Only available for running bots.
    """
    orchestrator = await get_orchestrator()

    # Get running instance to access risk manager
    running = orchestrator._instances.get(bot_id)

    if not running or running.bot_instance.user_id != payload.user_id:
        # Bot not running or doesn't belong to user
        # Return default stats from config
        repo = BotInstanceRepository()
        instance = await repo.get_by_id(bot_id, payload.user_id)
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bot not found"
            )

        # Return offline risk config
        return RiskStatsResponse(
            can_trade=False,
            reason="Bot is not running",
            config={
                "user_id": payload.user_id,
                "bot_instance_id": bot_id,
                "max_trades_per_day": instance.config.max_trades_per_day,
                "daily_loss_limit_percent": instance.config.daily_loss_limit_percent,
                "position_size_percent": instance.config.position_size_percent,
            },
            daily_stats=None,
            remaining_trades=instance.config.max_trades_per_day,
            remaining_risk_budget_percent=instance.config.daily_loss_limit_percent,
            dynamic_loss_limit_percent=instance.config.daily_loss_limit_percent,
        )

    # Bot is running, get real risk stats
    risk_status = running.risk_manager.get_risk_status()

    return RiskStatsResponse(
        can_trade=risk_status["can_trade"],
        reason=risk_status["reason"],
        config=risk_status["config"],
        daily_stats=risk_status["daily_stats"],
        remaining_trades=risk_status["remaining_trades"],
        remaining_risk_budget_percent=risk_status["remaining_risk_budget_percent"],
        dynamic_loss_limit_percent=risk_status["dynamic_loss_limit_percent"],
    )


class PerformanceResponse(BaseModel):
    """Performance summary response."""
    period_days: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_fees: float
    average_daily_return: float
    max_drawdown: float
    sharpe_estimate: float


@router.get("/{bot_id}/performance", response_model=PerformanceResponse)
@limiter.limit("10/minute")
async def get_bot_performance(
    request: Request,
    bot_id: int,
    days: int = 30,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Get performance summary for a bot instance.

    Args:
        days: Number of days to analyze (default: 30)
    """
    from src.risk.risk_manager import RiskManager

    # Verify bot belongs to user
    repo = BotInstanceRepository()
    instance = await repo.get_by_id(bot_id, payload.user_id)
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot not found"
        )

    # Create temp risk manager to read historical stats
    risk_manager = RiskManager(
        user_id=payload.user_id,
        bot_instance_id=bot_id,
    )

    summary = risk_manager.get_performance_summary(days=days)

    return PerformanceResponse(**summary)
