"""Pydantic schemas for portfolio views."""


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
    exchange: str
    symbol: str
    side: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    leverage: int
    margin: float = 0


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
