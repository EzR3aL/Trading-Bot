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

    # Trade rotation: auto-close & reopen trades at fixed intervals
    rotation_enabled: bool = Field(default=False, description="Enable automatic trade rotation")
    rotation_interval_minutes: Optional[int] = Field(
        default=None, ge=5, le=10080,
        description="Close & reopen trades after this many minutes (5min to 7 days)",
    )


class BotConfigUpdate(BaseModel):
    """Request to update a bot config. Only provided fields are updated."""
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

    rotation_enabled: Optional[bool] = Field(None, description="Enable automatic trade rotation")
    rotation_interval_minutes: Optional[int] = Field(
        None, ge=5, le=10080, description="Rotation interval in minutes (5min to 7 days)",
    )


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
    rotation_enabled: bool = False
    rotation_interval_minutes: Optional[int] = None
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
    total_fees: float = 0.0
    total_funding: float = 0.0
    open_trades: int = 0

    # LLM-specific metrics (only populated for llm_signal strategy)
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_last_direction: Optional[str] = None  # "LONG" | "SHORT"
    llm_last_confidence: Optional[int] = None  # 0-100
    llm_last_reasoning: Optional[str] = None
    llm_accuracy: Optional[float] = None  # Win rate %
    llm_total_predictions: Optional[int] = None
    llm_total_tokens_used: Optional[int] = None
    llm_avg_tokens_per_call: Optional[float] = None


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
