"""Pydantic schemas for revenue endpoints."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RevenueEntryCreate(BaseModel):
    date: date
    exchange: str = Field(..., min_length=1, max_length=50)
    revenue_type: str = Field(None, min_length=1, max_length=50)
    amount_usd: float = Field(..., gt=0)
    notes: Optional[str] = None

    # Frontend sendet "type" statt "revenue_type"
    type: Optional[str] = Field(None, exclude=True)

    def model_post_init(self, __context):
        # Accept "type" from frontend as alias for "revenue_type"
        if self.type and not self.revenue_type:
            self.revenue_type = self.type


class RevenueEntryUpdate(BaseModel):
    date: Optional[date] = None
    exchange: Optional[str] = Field(None, min_length=1, max_length=50)
    revenue_type: Optional[str] = Field(None, min_length=1, max_length=50)
    amount_usd: Optional[float] = Field(None, gt=0)
    notes: Optional[str] = None

    type: Optional[str] = Field(None, exclude=True)

    def model_post_init(self, __context):
        if self.type and not self.revenue_type:
            self.revenue_type = self.type


class RevenueEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    exchange: str
    type: str  # mapped from revenue_type
    amount: float  # mapped from amount_usd
    source: str  # "auto" | "manual"
    notes: Optional[str] = None
    created_at: Optional[str] = None


class ExchangeRevenue(BaseModel):
    exchange: str
    type: str
    total: float
    count: int = 0


class DailyRevenue(BaseModel):
    date: str
    total: float = 0
    by_exchange: dict[str, float]


class RevenueSummary(BaseModel):
    today: float
    last_7d: float
    last_30d: float
    total: float


class RevenueOverview(BaseModel):
    summary: RevenueSummary
    by_exchange: list[ExchangeRevenue]
    daily: list[DailyRevenue]
    entries: list[RevenueEntryResponse]
