"""Admin-only endpoints for the Broadcast Notification System."""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.schemas.broadcast import (
    BroadcastCreate,
    BroadcastListResponse,
    BroadcastPreviewResponse,
    BroadcastProgressResponse,
    BroadcastResponse,
    BroadcastTargetListResponse,
    BroadcastTargetResponse,
)
from src.auth.dependencies import get_current_admin
from src.models.broadcast import Broadcast, BroadcastTarget
from src.models.database import User
from src.models.session import get_db
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/admin/broadcasts", tags=["admin-broadcasts"])

MAX_CONCURRENT_SENDING = 2


# ── Helpers ────────────────────────────────────────────────────


def _broadcast_to_response(broadcast: Broadcast) -> BroadcastResponse:
    """Map an ORM Broadcast to the API response schema."""
    return BroadcastResponse.model_validate(broadcast)


async def _get_broadcast_or_404(
    broadcast_id: int, db: AsyncSession
) -> Broadcast:
    """Fetch a broadcast by ID or raise 404."""
    result = await db.execute(
        select(Broadcast).where(Broadcast.id == broadcast_id)
    )
    broadcast = result.scalar_one_or_none()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    return broadcast


# ── Endpoints ──────────────────────────────────────────────────


@router.post("/", response_model=BroadcastResponse, status_code=201)
@limiter.limit("10/minute")
async def create_broadcast(
    request: Request,
    body: BroadcastCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new broadcast notification."""
    from src.services.broadcast_service import render_messages

    rendered = render_messages(body.title, body.message, body.image_url)

    status = "draft"
    scheduler_job_id = None

    # If scheduled, register APScheduler job
    if body.scheduled_at:
        status = "scheduled"
        scheduler_job_id = f"broadcast_scheduled_{int(datetime.now(timezone.utc).timestamp())}"

    broadcast = Broadcast(
        admin_user_id=admin.id,
        title=body.title,
        message_markdown=body.message,
        message_discord=rendered.get("discord"),
        message_telegram=rendered.get("telegram"),
        message_whatsapp=rendered.get("whatsapp"),
        image_url=body.image_url,
        exchange_filter=body.exchange_filter,
        status=status,
        scheduled_at=body.scheduled_at,
        scheduler_job_id=scheduler_job_id,
    )
    db.add(broadcast)
    await db.flush()

    # Register scheduler job for scheduled broadcasts
    if body.scheduled_at and scheduler_job_id:
        try:
            scheduler = request.app.state.orchestrator._scheduler
            from src.services.broadcast_sender import send_broadcast

            scheduler.add_job(
                send_broadcast,
                "date",
                run_date=body.scheduled_at,
                id=scheduler_job_id,
                args=[broadcast.id],
                replace_existing=True,
            )
        except Exception as exc:
            logger.error("Failed to register scheduler job: %s", exc)

    logger.info(
        "Broadcast #%d created by admin %s (status=%s)",
        broadcast.id, admin.username, status,
    )
    return _broadcast_to_response(broadcast)


@router.get("/", response_model=BroadcastListResponse)
@limiter.limit("60/minute")
async def list_broadcasts(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, pattern="^(draft|scheduled|sending|completed|failed|cancelled)$"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List broadcasts with optional status filter and pagination."""
    query = select(Broadcast)
    count_query = select(func.count(Broadcast.id))

    if status:
        query = query.where(Broadcast.status == status)
        count_query = count_query.where(Broadcast.status == status)

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(Broadcast.created_at.desc()).offset(offset).limit(per_page)
    )
    broadcasts = result.scalars().all()

    return BroadcastListResponse(
        items=[_broadcast_to_response(b) for b in broadcasts],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{broadcast_id}", response_model=BroadcastResponse)
@limiter.limit("60/minute")
async def get_broadcast(
    request: Request,
    broadcast_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single broadcast by ID."""
    broadcast = await _get_broadcast_or_404(broadcast_id, db)
    return _broadcast_to_response(broadcast)


@router.get("/{broadcast_id}/targets", response_model=BroadcastTargetListResponse)
@limiter.limit("60/minute")
async def list_broadcast_targets(
    request: Request,
    broadcast_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None, pattern="^(pending|sending|sent|failed)$"),
    channel: Optional[str] = Query(None, pattern="^(discord|telegram|whatsapp)$"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List delivery targets for a broadcast with filters and pagination."""
    # Verify broadcast exists
    await _get_broadcast_or_404(broadcast_id, db)

    query = select(BroadcastTarget).where(BroadcastTarget.broadcast_id == broadcast_id)
    count_query = select(func.count(BroadcastTarget.id)).where(
        BroadcastTarget.broadcast_id == broadcast_id
    )

    if status:
        query = query.where(BroadcastTarget.status == status)
        count_query = count_query.where(BroadcastTarget.status == status)
    if channel:
        query = query.where(BroadcastTarget.channel == channel)
        count_query = count_query.where(BroadcastTarget.channel == channel)

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(BroadcastTarget.id).offset(offset).limit(per_page)
    )
    targets = result.scalars().all()

    return BroadcastTargetListResponse(
        items=[BroadcastTargetResponse.model_validate(t) for t in targets],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/{broadcast_id}/preview", response_model=BroadcastPreviewResponse)
@limiter.limit("10/minute")
async def preview_broadcast(
    request: Request,
    broadcast_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Preview the broadcast: resolve targets and estimate delivery."""
    broadcast = await _get_broadcast_or_404(broadcast_id, db)

    from src.services.broadcast_service import (
        estimate_duration,
        get_target_summary,
        resolve_targets,
    )

    targets = await resolve_targets(broadcast, db)
    summary = get_target_summary(targets)
    duration = estimate_duration(len(targets))

    preview = {}
    if broadcast.message_discord:
        preview["discord"] = broadcast.message_discord
    if broadcast.message_telegram:
        preview["telegram"] = broadcast.message_telegram
    if broadcast.message_whatsapp:
        preview["whatsapp"] = broadcast.message_whatsapp

    return BroadcastPreviewResponse(
        total_targets=len(targets),
        by_channel=summary,
        estimated_duration_seconds=duration,
        preview=preview,
    )


@router.post("/{broadcast_id}/send", status_code=202)
@limiter.limit("5/minute")
async def send_broadcast_endpoint(
    request: Request,
    broadcast_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Start sending a broadcast. Launches delivery as a background task."""
    broadcast = await _get_broadcast_or_404(broadcast_id, db)

    if broadcast.status not in ("draft", "scheduled"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot send broadcast with status '{broadcast.status}'. "
                   f"Only 'draft' or 'scheduled' broadcasts can be sent.",
        )

    # Enforce max concurrent sending broadcasts
    sending_count_result = await db.execute(
        select(func.count(Broadcast.id)).where(Broadcast.status == "sending")
    )
    sending_count = sending_count_result.scalar() or 0
    if sending_count >= MAX_CONCURRENT_SENDING:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum {MAX_CONCURRENT_SENDING} concurrent broadcasts allowed. "
                   f"Wait for current broadcasts to finish.",
        )

    broadcast.status = "sending"
    broadcast.started_at = datetime.now(timezone.utc)
    await db.flush()

    # Launch background send task
    from src.services.broadcast_sender import send_broadcast

    asyncio.create_task(send_broadcast(broadcast.id))

    logger.info(
        "Broadcast #%d send initiated by admin %s",
        broadcast.id, admin.username,
    )
    return {"status": "sending", "broadcast_id": broadcast.id}


@router.post("/{broadcast_id}/cancel", response_model=BroadcastResponse)
@limiter.limit("10/minute")
async def cancel_broadcast(
    request: Request,
    broadcast_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a broadcast. Removes any scheduled APScheduler job."""
    broadcast = await _get_broadcast_or_404(broadcast_id, db)

    if broadcast.status in ("completed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel broadcast with status '{broadcast.status}'.",
        )

    broadcast.status = "cancelled"

    # Remove APScheduler job if scheduled
    if broadcast.scheduler_job_id:
        try:
            scheduler = request.app.state.orchestrator._scheduler
            scheduler.remove_job(broadcast.scheduler_job_id)
        except Exception as exc:
            logger.warning(
                "Could not remove scheduler job %s: %s",
                broadcast.scheduler_job_id, exc,
            )
        broadcast.scheduler_job_id = None

    logger.info(
        "Broadcast #%d cancelled by admin %s",
        broadcast.id, admin.username,
    )
    return _broadcast_to_response(broadcast)


@router.delete("/{broadcast_id}", status_code=204)
@limiter.limit("10/minute")
async def delete_broadcast(
    request: Request,
    broadcast_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a broadcast. Only allowed for terminal or draft statuses."""
    broadcast = await _get_broadcast_or_404(broadcast_id, db)

    allowed_statuses = {"completed", "failed", "cancelled", "draft"}
    if broadcast.status not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete broadcast with status '{broadcast.status}'. "
                   f"Allowed: {', '.join(sorted(allowed_statuses))}.",
        )

    await db.execute(
        delete(Broadcast).where(Broadcast.id == broadcast_id)
    )

    logger.info(
        "Broadcast #%d deleted by admin %s",
        broadcast.id, admin.username,
    )
    return None


@router.get("/{broadcast_id}/progress", response_model=BroadcastProgressResponse)
@limiter.limit("60/minute")
async def get_broadcast_progress(
    request: Request,
    broadcast_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get real-time progress of a broadcast."""
    broadcast = await _get_broadcast_or_404(broadcast_id, db)
    return BroadcastProgressResponse(
        broadcast_id=broadcast.id,
        sent=broadcast.sent_count,
        failed=broadcast.failed_count,
        total=broadcast.total_targets,
        status=broadcast.status,
    )
