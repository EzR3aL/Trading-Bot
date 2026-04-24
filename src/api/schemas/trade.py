"""Trade schemas."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
