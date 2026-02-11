"""Backtest API schemas."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    """Request to start a new backtest."""
    strategy_type: str = Field(..., min_length=1)
    symbol: str = Field(default="BTCUSDT", min_length=1)
    timeframe: str = Field(default="1d", pattern="^(1m|5m|15m|30m|1h|4h|1d)$")
    start_date: str = Field(..., description="ISO date YYYY-MM-DD")
    end_date: str = Field(..., description="ISO date YYYY-MM-DD")
    initial_capital: float = Field(default=10000.0, ge=100, le=10_000_000)
    strategy_params: Optional[Dict[str, Any]] = None


class BacktestTradeResponse(BaseModel):
    """Single trade in backtest results."""
    entry_date: str
    exit_date: Optional[str] = None
    direction: str
    entry_price: float
    exit_price: Optional[float] = None
    position_value: float
    pnl: float
    pnl_percent: float
    fees: float
    net_pnl: float
    result: str
    reason: str
    confidence: int


class EquityPoint(BaseModel):
    """Single point on the equity curve."""
    timestamp: str
    equity: float


class BacktestMetrics(BaseModel):
    """Performance metrics."""
    total_return_percent: float
    win_rate: float
    max_drawdown_percent: float
    sharpe_ratio: Optional[float] = None
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    average_win: float
    average_loss: float
    total_pnl: float
    total_fees: float
    starting_capital: float
    ending_capital: float


class BacktestRunResponse(BaseModel):
    """Response for a single backtest run."""
    id: int
    strategy_type: str
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_capital: float
    strategy_params: Optional[Dict[str, Any]] = None
    status: str
    error_message: Optional[str] = None
    metrics: Optional[BacktestMetrics] = None
    equity_curve: Optional[List[EquityPoint]] = None
    trades: Optional[List[BacktestTradeResponse]] = None
    created_at: str
    completed_at: Optional[str] = None


class BacktestHistoryItem(BaseModel):
    """Summary item for the history list."""
    id: int
    strategy_type: str
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_capital: float
    status: str
    total_return_percent: Optional[float] = None
    win_rate: Optional[float] = None
    total_trades: Optional[int] = None
    created_at: str


class BacktestHistoryResponse(BaseModel):
    """Paginated list of backtest runs."""
    runs: List[BacktestHistoryItem]
    total: int
    page: int
    per_page: int
