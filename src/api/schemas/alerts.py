"""Pydantic schemas for alerts."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AlertCreate(BaseModel):
    bot_config_id: Optional[int] = None
    alert_type: Literal["price", "strategy", "portfolio"]
    category: str = Field(..., min_length=1, max_length=50)
    symbol: Optional[str] = None
    threshold: float = Field(..., gt=0)
    direction: Optional[Literal["above", "below"]] = None
    cooldown_minutes: int = Field(15, ge=1, le=1440)

    @model_validator(mode="after")
    def validate_alert_fields(self):
        if self.alert_type == "price":
            if not self.symbol:
                raise ValueError("symbol is required for price alerts")
            if not self.direction:
                raise ValueError("direction is required for price alerts")
        return self


class AlertUpdate(BaseModel):
    alert_type: Optional[Literal["price", "strategy", "portfolio"]] = None
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    symbol: Optional[str] = None
    threshold: Optional[float] = Field(None, gt=0)
    direction: Optional[Literal["above", "below"]] = None
    is_enabled: Optional[bool] = None
    cooldown_minutes: Optional[int] = Field(None, ge=1, le=1440)


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    bot_config_id: Optional[int] = None
    alert_type: str
    category: str
    symbol: Optional[str] = None
    threshold: float
    direction: Optional[str] = None
    is_enabled: bool
    cooldown_minutes: int
    last_triggered_at: Optional[datetime] = None
    trigger_count: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AlertHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_id: int
    triggered_at: datetime
    current_value: Optional[float] = None
    message: str
