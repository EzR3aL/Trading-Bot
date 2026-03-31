"""Config change audit trail endpoints."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.models.database import ConfigChangeLog, User
from src.models.session import get_db

router = APIRouter(prefix="/api/config-changes", tags=["config-audit"])


class ConfigChangeEntry(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    changes: Optional[dict] = None
    created_at: Optional[str] = None


class ConfigChangeListResponse(BaseModel):
    items: list[ConfigChangeEntry]
    total: int
    page: int
    page_size: int


@router.get("/", response_model=ConfigChangeListResponse)
async def list_config_changes(
    entity_type: Optional[str] = Query(None, pattern="^(bot_config|preset|exchange_connection)$"),
    entity_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None, pattern="^(create|update|delete)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List config changes for the current user (paginated, filterable)."""
    filters = [ConfigChangeLog.user_id == user.id]
    if entity_type:
        filters.append(ConfigChangeLog.entity_type == entity_type)
    if entity_id is not None:
        filters.append(ConfigChangeLog.entity_id == entity_id)
    if action:
        filters.append(ConfigChangeLog.action == action)

    # Total count
    count_result = await db.execute(
        select(func.count(ConfigChangeLog.id)).where(*filters)
    )
    total = count_result.scalar() or 0

    # Paginated results
    offset = (page - 1) * page_size
    result = await db.execute(
        select(ConfigChangeLog)
        .where(*filters)
        .order_by(ConfigChangeLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    logs = result.scalars().all()

    items = []
    for log in logs:
        changes = None
        if log.changes:
            try:
                changes = json.loads(log.changes)
            except (json.JSONDecodeError, TypeError):
                changes = None
        items.append(ConfigChangeEntry(
            id=log.id,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            action=log.action,
            changes=changes,
            created_at=log.created_at.isoformat() if log.created_at else None,
        ))

    return ConfigChangeListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
