"""Pydantic schemas for the Broadcast Notification System."""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

VALID_EXCHANGES = {"hyperliquid", "bitget", "weex", "bitunix", "bingx"}


class BroadcastCreate(BaseModel):
    """Request to create a new broadcast notification."""

    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=4000)
    image_url: Optional[str] = Field(None, max_length=500)
    exchange_filter: Optional[str] = None
    scheduled_at: Optional[datetime] = None

    @field_validator("exchange_filter", mode="before")
    @classmethod
    def validate_exchange_filter(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if v not in VALID_EXCHANGES:
            raise ValueError(
                f"Invalid exchange filter '{v}'. "
                f"Allowed: {', '.join(sorted(VALID_EXCHANGES))}"
            )
        return v

    @field_validator("scheduled_at", mode="before")
    @classmethod
    def validate_scheduled_at(cls, v: datetime | str | None) -> datetime | str | None:
        if v is None:
            return v
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        # Ensure timezone-aware comparison
        now = datetime.now(timezone.utc)
        compare_v = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if compare_v <= now:
            raise ValueError("scheduled_at must be in the future")
        return v

    @field_validator("image_url", mode="before")
    @classmethod
    def validate_image_url(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("image_url must start with http:// or https://")
        return v


class BroadcastResponse(BaseModel):
    """Single broadcast response."""

    id: int
    admin_user_id: Optional[int] = None
    title: str
    message_markdown: str
    image_url: Optional[str] = None
    exchange_filter: Optional[str] = None
    status: str
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    total_targets: int = 0
    sent_count: int = 0
    failed_count: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BroadcastListResponse(BaseModel):
    """Paginated list of broadcasts."""

    items: List[BroadcastResponse]
    total: int
    page: int
    per_page: int


class BroadcastPreviewResponse(BaseModel):
    """Preview of broadcast targets and rendered messages."""

    total_targets: int
    by_channel: Dict[str, int]
    estimated_duration_seconds: int
    preview: Dict[str, str]


class BroadcastTargetResponse(BaseModel):
    """Single broadcast target (delivery record)."""

    id: int
    channel: str
    status: str
    error_message: Optional[str] = None
    retry_count: int = 0
    sent_at: Optional[datetime] = None
    user_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class BroadcastTargetListResponse(BaseModel):
    """Paginated list of broadcast targets."""

    items: List[BroadcastTargetResponse]
    total: int
    page: int
    per_page: int


class BroadcastProgressResponse(BaseModel):
    """Real-time progress of a sending broadcast."""

    broadcast_id: int
    sent: int
    failed: int
    total: int
    status: str
