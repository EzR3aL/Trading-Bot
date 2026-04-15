"""Pydantic schemas for revenue endpoints."""

from typing import Optional

from pydantic import BaseModel


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


class SyncStatus(BaseModel):
    status: Optional[str]  # ok | error | unsupported | not_configured
    last_synced_at: Optional[str]
    error: Optional[str]


class RevenueOverview(BaseModel):
    summary: RevenueSummary
    by_exchange: list[ExchangeRevenue]
    daily: list[DailyRevenue]
    sync_status: dict[str, SyncStatus]
