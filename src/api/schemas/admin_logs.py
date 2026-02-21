"""Pydantic schemas for admin log endpoints."""

from typing import Dict, List, Optional

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    method: str
    path: str
    status_code: int
    response_time_ms: float
    client_ip: str
    created_at: Optional[str] = None


class AuditLogListResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int
    page: int
    per_page: int
    pages: int


class EventLogResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    bot_id: Optional[int] = None
    event_type: str
    severity: str
    message: str
    details: Optional[str] = None
    created_at: Optional[str] = None


class EventLogListResponse(BaseModel):
    items: List[EventLogResponse]
    total: int
    page: int
    per_page: int
    pages: int


class EventStatsResponse(BaseModel):
    period: str
    by_type: Dict[str, int]
    by_severity: Dict[str, int]
    total: int


class EventStatsListResponse(BaseModel):
    stats: List[EventStatsResponse]


class PurgeResponse(BaseModel):
    deleted: int
    message: str
