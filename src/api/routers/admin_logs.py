"""Admin-only endpoints for querying audit logs and event logs."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.admin_logs import (
    AuditLogListResponse,
    AuditLogResponse,
    EventLogListResponse,
    EventLogResponse,
    EventStatsListResponse,
    EventStatsResponse,
    PurgeResponse,
)
from src.auth.dependencies import get_current_admin
from src.models.database import AuditLog, EventLog, User
from src.models.session import get_db

router = APIRouter(prefix="/api/admin", tags=["admin-logs"])


# ── Audit Logs ──────────────────────────────────────────────────


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    user_id: Optional[int] = None,
    method: Optional[str] = Query(None, pattern="^(GET|POST|PUT|DELETE|PATCH|OPTIONS)$"),
    path: Optional[str] = None,
    status_code: Optional[int] = None,
    date_from: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List audit logs with filters and pagination."""
    query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))

    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
        count_query = count_query.where(AuditLog.user_id == user_id)
    if method:
        query = query.where(AuditLog.method == method)
        count_query = count_query.where(AuditLog.method == method)
    if path:
        safe_path = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(AuditLog.path.ilike(f"%{safe_path}%", escape="\\"))
        count_query = count_query.where(AuditLog.path.ilike(f"%{safe_path}%", escape="\\"))
    if status_code is not None:
        query = query.where(AuditLog.status_code == status_code)
        count_query = count_query.where(AuditLog.status_code == status_code)
    if date_from:
        dt_from = datetime.fromisoformat(date_from)
        query = query.where(AuditLog.created_at >= dt_from)
        count_query = count_query.where(AuditLog.created_at >= dt_from)
    if date_to:
        dt_to = datetime.fromisoformat(date_to + "T23:59:59")
        query = query.where(AuditLog.created_at <= dt_to)
        count_query = count_query.where(AuditLog.created_at <= dt_to)

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(AuditLog.created_at.desc()).offset(offset).limit(per_page)
    )
    logs = result.scalars().all()

    return AuditLogListResponse(
        items=[
            AuditLogResponse(
                id=log.id,
                user_id=log.user_id,
                method=log.method,
                path=log.path,
                status_code=log.status_code,
                response_time_ms=log.response_time_ms,
                client_ip=log.client_ip,
                created_at=log.created_at.isoformat() if log.created_at else None,
            )
            for log in logs
        ],
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, -(-total // per_page)),
    )


@router.delete("/audit-logs", response_model=PurgeResponse)
async def purge_audit_logs(
    days: int = Query(30, ge=1, le=365, description="Delete logs older than N days"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Purge audit logs older than N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        delete(AuditLog).where(AuditLog.created_at < cutoff)
    )
    deleted = result.rowcount
    return PurgeResponse(deleted=deleted, message=f"Deleted {deleted} audit logs older than {days} days")


# ── Event Logs ──────────────────────────────────────────────────


@router.get("/events", response_model=EventLogListResponse)
async def list_events(
    event_type: Optional[str] = None,
    severity: Optional[str] = Query(None, pattern="^(info|warning|error)$"),
    bot_id: Optional[int] = None,
    user_id: Optional[int] = None,
    date_from: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List event logs with filters and pagination."""
    query = select(EventLog)
    count_query = select(func.count(EventLog.id))

    if event_type:
        query = query.where(EventLog.event_type == event_type)
        count_query = count_query.where(EventLog.event_type == event_type)
    if severity:
        query = query.where(EventLog.severity == severity)
        count_query = count_query.where(EventLog.severity == severity)
    if bot_id is not None:
        query = query.where(EventLog.bot_id == bot_id)
        count_query = count_query.where(EventLog.bot_id == bot_id)
    if user_id is not None:
        query = query.where(EventLog.user_id == user_id)
        count_query = count_query.where(EventLog.user_id == user_id)
    if date_from:
        dt_from = datetime.fromisoformat(date_from)
        query = query.where(EventLog.created_at >= dt_from)
        count_query = count_query.where(EventLog.created_at >= dt_from)
    if date_to:
        dt_to = datetime.fromisoformat(date_to + "T23:59:59")
        query = query.where(EventLog.created_at <= dt_to)
        count_query = count_query.where(EventLog.created_at <= dt_to)

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(EventLog.created_at.desc()).offset(offset).limit(per_page)
    )
    events = result.scalars().all()

    return EventLogListResponse(
        items=[
            EventLogResponse(
                id=ev.id,
                user_id=ev.user_id,
                bot_id=ev.bot_id,
                event_type=ev.event_type,
                severity=ev.severity,
                message=ev.message,
                details=ev.details,
                created_at=ev.created_at.isoformat() if ev.created_at else None,
            )
            for ev in events
        ],
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, -(-total // per_page)),
    )


@router.get("/events/stats", response_model=EventStatsListResponse)
async def event_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Event counts by type and severity for last 24h, 7d, 30d."""
    now = datetime.now(timezone.utc)
    periods = [
        ("24h", now - timedelta(hours=24)),
        ("7d", now - timedelta(days=7)),
        ("30d", now - timedelta(days=30)),
    ]

    stats = []
    for label, since in periods:
        # By type
        type_result = await db.execute(
            select(EventLog.event_type, func.count(EventLog.id))
            .where(EventLog.created_at >= since)
            .group_by(EventLog.event_type)
        )
        by_type = dict(type_result.all())

        # By severity
        sev_result = await db.execute(
            select(EventLog.severity, func.count(EventLog.id))
            .where(EventLog.created_at >= since)
            .group_by(EventLog.severity)
        )
        by_severity = dict(sev_result.all())

        total = sum(by_severity.values())
        stats.append(EventStatsResponse(
            period=label,
            by_type=by_type,
            by_severity=by_severity,
            total=total,
        ))

    return EventStatsListResponse(stats=stats)


@router.delete("/events", response_model=PurgeResponse)
async def purge_events(
    days: int = Query(30, ge=1, le=365, description="Delete events older than N days"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Purge event logs older than N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        delete(EventLog).where(EventLog.created_at < cutoff)
    )
    deleted = result.rowcount
    return PurgeResponse(deleted=deleted, message=f"Deleted {deleted} event logs older than {days} days")
