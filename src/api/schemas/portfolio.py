"""Pydantic schemas for portfolio views."""


from typing import Optional

from pydantic import BaseModel


class ExchangeSummary(BaseModel):
    exchange: str
    total_pnl: float = 0
    total_trades: int = 0
    winning_trades: int = 0
    win_rate: float = 0
    total_fees: float = 0
    total_funding: float = 0


class PortfolioSummary(BaseModel):
    total_pnl: float = 0
    total_trades: int = 0
    overall_win_rate: float = 0
    total_fees: float = 0
    total_funding: float = 0
    exchanges: list[ExchangeSummary] = []


class PortfolioPosition(BaseModel):
    trade_id: Optional[int] = None
    exchange: str
    symbol: str
    side: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    leverage: int
    margin: float = 0
    bot_name: Optional[str] = None
    demo_mode: bool = False
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    trailing_stop_active: bool = False
    trailing_stop_price: Optional[float] = None
    trailing_stop_distance_pct: Optional[float] = None
    can_close_at_loss: Optional[bool] = None


class PortfolioAllocation(BaseModel):
    exchange: str
    balance: float
    currency: str = "USDT"


class PortfolioDaily(BaseModel):
    date: str
    exchange: str
    pnl: float = 0
    trades: int = 0
    fees: float = 0
