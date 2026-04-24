"""Trade schemas."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TradeFilterBotOption(BaseModel):
    """A bot option exposed via ``GET /api/trades/filter-options``."""

    id: int
    name: str


class TradeFilterOptionsResponse(BaseModel):
    """Distinct values available for the current user's trade filters.

    Powers the dashboard's filter dropdowns without forcing the client to
    load an entire trade page just to learn which symbols/bots/exchanges
    it can filter by.
    """

    symbols: list[str]
    bots: list[TradeFilterBotOption]
    exchanges: list[str]
    statuses: list[str]


class TradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    leverage: int
    confidence: int
    reason: str
    status: str
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    fees: float = 0
    funding_paid: float = 0
    builder_fee: float = Field(
        default=0,
        description="Builder fee charged by Hyperliquid (USD). 0 for non-HL exchanges.",
    )
    entry_time: str
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None
    exchange: str = "bitget"
    demo_mode: bool = False
    bot_name: Optional[str] = None
    bot_exchange: Optional[str] = None
    # Trailing stop (computed live for open trades)
    trailing_stop_active: Optional[bool] = None
    trailing_stop_price: Optional[float] = None
    trailing_stop_distance: Optional[float] = None
    trailing_stop_distance_pct: Optional[float] = None
    can_close_at_loss: Optional[bool] = None


class TradeListResponse(BaseModel):
    trades: list[TradeResponse]
    total: int
    page: int = 1
    per_page: int = 50


# ---------------------------------------------------------------------------
# TP/SL update request / response models
# ---------------------------------------------------------------------------


class TrailingStopParams(BaseModel):
    """Trailing-stop sub-object on ``PUT /api/trades/{id}/tp-sl``."""

    callback_pct: float  # ATR multiplier (e.g., 2.5 = 2.5x ATR)

    @field_validator("callback_pct")
    @classmethod
    def validate_atr_range(cls, v: float) -> float:
        if v < 1.0 or v > 5.0:
            raise ValueError("ATR multiplier must be between 1.0 and 5.0")
        return v


class UpdateTpSlRequest(BaseModel):
    """Request body for ``PUT /api/trades/{id}/tp-sl``."""

    model_config = ConfigDict(extra="forbid")

    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    remove_tp: bool = False
    remove_sl: bool = False
    trailing_stop: Optional[TrailingStopParams] = None
    remove_trailing: bool = False


class RiskLegStatus(BaseModel):
    """Per-leg outcome surfaced from a RiskStateManager apply_intent call."""

    value: Optional[Any] = None
    status: str  # pending | confirmed | rejected | cleared | cancel_failed
    order_id: Optional[str] = None
    error: Optional[str] = None
    latency_ms: int = 0


class TpSlResponse(BaseModel):
    """Aggregate response for the RiskStateManager-backed TP/SL endpoint."""

    trade_id: int
    tp: Optional[RiskLegStatus] = None
    sl: Optional[RiskLegStatus] = None
    trailing: Optional[RiskLegStatus] = None
    applied_at: datetime
    overall_status: str  # all_confirmed | partial_success | all_rejected | no_change
