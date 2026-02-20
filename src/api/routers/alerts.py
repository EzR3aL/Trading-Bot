"""Alert CRUD and management endpoints (user-scoped)."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.schemas.alerts import (
    AlertCreate,
    AlertHistoryResponse,
    AlertResponse,
    AlertUpdate,
)
from src.auth.dependencies import get_current_user
from src.models.database import Alert, AlertHistory, User
from src.models.session import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

MAX_ALERTS_PER_USER = 50


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    bot_id: int | None = Query(None),
    alert_type: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all alerts for the current user, with optional filters."""
    filters = [Alert.user_id == user.id]
    if bot_id is not None:
        filters.append(Alert.bot_config_id == bot_id)
    if alert_type:
        filters.append(Alert.alert_type == alert_type)

    result = await db.execute(
        select(Alert).where(*filters).order_by(Alert.created_at.desc())
    )
    return [AlertResponse.model_validate(a) for a in result.scalars().all()]


@router.post("", response_model=AlertResponse, status_code=201)
@limiter.limit("30/minute")
async def create_alert(
    request: Request,
    data: AlertCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new alert."""
    # Check alert limit
    count_result = await db.execute(
        select(func.count()).select_from(Alert).where(Alert.user_id == user.id)
    )
    if count_result.scalar() >= MAX_ALERTS_PER_USER:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_ALERTS_PER_USER} alerts reached")

    alert = Alert(
        user_id=user.id,
        bot_config_id=data.bot_config_id,
        alert_type=data.alert_type,
        category=data.category,
        symbol=data.symbol,
        threshold=data.threshold,
        direction=data.direction,
        cooldown_minutes=data.cooldown_minutes,
    )
    db.add(alert)
    await db.flush()
    return AlertResponse.model_validate(alert)


@router.get("/history", response_model=list[AlertHistoryResponse])
async def list_alert_history(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get global alert history for the user (latest triggered alerts)."""
    result = await db.execute(
        select(AlertHistory)
        .join(Alert, AlertHistory.alert_id == Alert.id)
        .where(Alert.user_id == user.id)
        .order_by(AlertHistory.triggered_at.desc())
        .limit(limit)
    )
    return [AlertHistoryResponse.model_validate(h) for h in result.scalars().all()]


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get alert details."""
    alert = await _get_user_alert(alert_id, user.id, db)
    return AlertResponse.model_validate(alert)


@router.put("/{alert_id}", response_model=AlertResponse)
@limiter.limit("30/minute")
async def update_alert(
    request: Request,
    alert_id: int,
    data: AlertUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing alert."""
    alert = await _get_user_alert(alert_id, user.id, db)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(alert, key, value)

    await db.flush()
    return AlertResponse.model_validate(alert)


@router.delete("/{alert_id}")
@limiter.limit("30/minute")
async def delete_alert(
    request: Request,
    alert_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an alert."""
    alert = await _get_user_alert(alert_id, user.id, db)
    await db.delete(alert)
    return {"detail": "deleted"}


@router.patch("/{alert_id}/toggle", response_model=AlertResponse)
@limiter.limit("30/minute")
async def toggle_alert(
    request: Request,
    alert_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle an alert on/off."""
    alert = await _get_user_alert(alert_id, user.id, db)
    alert.is_enabled = not alert.is_enabled
    await db.flush()
    return AlertResponse.model_validate(alert)


async def _get_user_alert(alert_id: int, user_id: int, db: AsyncSession) -> Alert:
    """Fetch an alert owned by the user or raise 404."""
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert
