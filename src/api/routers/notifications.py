"""Notification history endpoints."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.schemas.notifications import (
    NotificationListResponse,
    NotificationLogResponse,
)
from src.auth.dependencies import get_current_user
from src.models.database import NotificationLog, User
from src.models.session import get_db

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
@limiter.limit("60/minute")
async def list_notifications(
    request: Request,
    channel: Optional[str] = Query(None, pattern="^(discord|telegram)$"),
    status: Optional[str] = Query(None, pattern="^(sent|failed)$"),
    bot_id: Optional[int] = None,
    event_type: Optional[str] = None,
    date_from: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List notification history for the authenticated user.

    Returns notifications from the last 7 days by default (newest first).
    Supports filtering by channel, status, bot_id, event_type, and date range.
    """
    query = select(NotificationLog).where(NotificationLog.user_id == user.id)
    count_query = select(func.count(NotificationLog.id)).where(NotificationLog.user_id == user.id)

    # Default to last 7 days if no date range specified
    if not date_from and not date_to:
        default_from = datetime.now(timezone.utc) - timedelta(days=7)
        query = query.where(NotificationLog.created_at >= default_from)
        count_query = count_query.where(NotificationLog.created_at >= default_from)

    if channel:
        query = query.where(NotificationLog.channel == channel)
        count_query = count_query.where(NotificationLog.channel == channel)
    if status:
        query = query.where(NotificationLog.status == status)
        count_query = count_query.where(NotificationLog.status == status)
    if bot_id is not None:
        query = query.where(NotificationLog.bot_config_id == bot_id)
        count_query = count_query.where(NotificationLog.bot_config_id == bot_id)
    if event_type:
        query = query.where(NotificationLog.event_type == event_type)
        count_query = count_query.where(NotificationLog.event_type == event_type)
    if date_from:
        dt_from = datetime.fromisoformat(date_from)
        query = query.where(NotificationLog.created_at >= dt_from)
        count_query = count_query.where(NotificationLog.created_at >= dt_from)
    if date_to:
        dt_to = datetime.fromisoformat(date_to + "T23:59:59")
        query = query.where(NotificationLog.created_at <= dt_to)
        count_query = count_query.where(NotificationLog.created_at <= dt_to)

    total = (await db.execute(count_query)).scalar() or 0

    result = await db.execute(
        query.order_by(NotificationLog.created_at.desc()).offset(offset).limit(limit)
    )
    logs = result.scalars().all()

    return NotificationListResponse(
        notifications=[
            NotificationLogResponse(
                id=log.id,
                bot_config_id=log.bot_config_id,
                channel=log.channel,
                event_type=log.event_type,
                status=log.status,
                error_message=log.error_message,
                retry_count=log.retry_count,
                payload_summary=log.payload_summary,
                created_at=log.created_at.isoformat() if log.created_at else None,
            )
            for log in logs
        ],
        total=total,
    )
