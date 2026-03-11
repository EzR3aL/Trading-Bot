"""Pydantic schemas for notification history endpoints."""

from typing import List, Optional

from pydantic import BaseModel


class NotificationLogResponse(BaseModel):
    id: int
    bot_config_id: Optional[int] = None
    channel: str
    event_type: str
    status: str
    error_message: Optional[str] = None
    retry_count: int = 0
    payload_summary: Optional[str] = None
    created_at: Optional[str] = None


class NotificationListResponse(BaseModel):
    notifications: List[NotificationLogResponse]
    total: int
