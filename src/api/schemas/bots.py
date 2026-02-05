"""Multibot system schemas."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BotConfigCreate(BaseModel):
    """Request to create a new bot."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    strategy_type: str = Field(..., min_length=1)
    exchange_type: str = Field(..., pattern="^(bitget|weex|hyperliquid)$")
    mode: str = Field(default="demo", pattern="^(demo|live|both)$")

    # Trading parameters
    trading_pairs: List[str] = Field(default=["BTCUSDT"])
    leverage: int = Field(default=4, ge=1, le=20)
    position_size_percent: float = Field(default=7.5, ge=1, le=25)
    max_trades_per_day: int = Field(default=2, ge=1, le=10)
    take_profit_percent: float = Field(default=4.0, ge=0.5, le=20)
    stop_loss_percent: float = Field(default=1.5, ge=0.5, le=10)
    daily_loss_limit_percent: float = Field(default=5.0, ge=1, le=20)

    # Strategy-specific parameters
    strategy_params: Optional[Dict[str, Any]] = None

    # Schedule
    schedule_type: str = Field(default="market_sessions", pattern="^(market_sessions|interval|custom_cron)$")
    schedule_config: Optional[Dict[str, Any]] = None


class BotConfigUpdate(BaseModel):
    """Request to update a bot config."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    strategy_type: Optional[str] = None
    exchange_type: Optional[str] = Field(None, pattern="^(bitget|weex|hyperliquid)$")
    mode: Optional[str] = Field(None, pattern="^(demo|live|both)$")

    trading_pairs: Optional[List[str]] = None
    leverage: Optional[int] = Field(None, ge=1, le=20)
    position_size_percent: Optional[float] = Field(None, ge=1, le=25)
    max_trades_per_day: Optional[int] = Field(None, ge=1, le=10)
    take_profit_percent: Optional[float] = Field(None, ge=0.5, le=20)
    stop_loss_percent: Optional[float] = Field(None, ge=0.5, le=10)
    daily_loss_limit_percent: Optional[float] = Field(None, ge=1, le=20)

    strategy_params: Optional[Dict[str, Any]] = None

    schedule_type: Optional[str] = Field(None, pattern="^(market_sessions|interval|custom_cron)$")
    schedule_config: Optional[Dict[str, Any]] = None


class BotConfigResponse(BaseModel):
    """Bot configuration response."""
    id: int
    name: str
    description: Optional[str] = None
    strategy_type: str
    exchange_type: str
    mode: str
    trading_pairs: List[str]
    leverage: int
    position_size_percent: float
    max_trades_per_day: int
    take_profit_percent: float
    stop_loss_percent: float
    daily_loss_limit_percent: float
    strategy_params: Optional[Dict[str, Any]] = None
    schedule_type: str
    schedule_config: Optional[Dict[str, Any]] = None
    is_enabled: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BotRuntimeStatus(BaseModel):
    """Runtime status of a bot."""
    bot_config_id: int
    name: str
    strategy_type: str
    exchange_type: str
    mode: str
    trading_pairs: List[str]
    status: str  # idle | starting | running | error | stopped
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    last_analysis: Optional[str] = None
    trades_today: int = 0
    is_enabled: bool = False

    # Summary metrics (from DB)
    total_trades: int = 0
    total_pnl: float = 0.0
    open_trades: int = 0


class BotListResponse(BaseModel):
    """Response listing all bots for a user."""
    bots: List[BotRuntimeStatus] = []


class StrategyInfo(BaseModel):
    """Strategy information for the builder UI."""
    name: str
    description: str
    param_schema: Dict[str, Any]


class StrategiesListResponse(BaseModel):
    """Response listing available strategies."""
    strategies: List[StrategyInfo] = []
