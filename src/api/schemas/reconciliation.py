"""Position reconciliation response schemas."""

from typing import Any, Dict, List

from pydantic import BaseModel


class UntrackedPosition(BaseModel):
    """Position found on exchange but not tracked in the database."""
    symbol: str
    side: str
    size: float
    entry_price: float
    unrealized_pnl: float
    leverage: int


class PhantomTrade(BaseModel):
    """Trade recorded in DB but no matching position on exchange."""
    trade_id: int
    symbol: str
    side: str
    size: float
    entry_price: float
    entry_time: str  # ISO datetime


class ReconciliationResult(BaseModel):
    """Result of comparing exchange positions with database trade records."""
    bot_id: int
    bot_name: str
    exchange: str
    checked_at: str  # ISO datetime
    is_consistent: bool
    untracked_positions: List[UntrackedPosition]
    phantom_trades: List[PhantomTrade]
    matched: int  # number of matching positions
