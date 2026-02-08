"""Trade schemas."""

from typing import Optional

from pydantic import BaseModel


class TradeResponse(BaseModel):
    id: int
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: Optional[float] = None
    take_profit: float
    stop_loss: float
    leverage: int
    confidence: int
    reason: str
    status: str
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    fees: float = 0
    funding_paid: float = 0
    entry_time: str
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None
    exchange: str = "bitget"
    demo_mode: bool = False
    bot_name: Optional[str] = None
    bot_exchange: Optional[str] = None

    class Config:
        from_attributes = True


class TradeListResponse(BaseModel):
    trades: list[TradeResponse]
    total: int
    page: int = 1
    per_page: int = 50
