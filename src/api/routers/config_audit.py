"""Config change audit trail endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.models.database import User
from src.models.session import get_db
from src.services import config_service

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
    payload = await config_service.list_config_changes(
        user,
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        page=page,
        page_size=page_size,
    )
    return ConfigChangeListResponse(
        items=[ConfigChangeEntry(**item) for item in payload["items"]],
        total=payload["total"],
        page=payload["page"],
        page_size=payload["page_size"],
    )
