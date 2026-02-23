"""Multibot system schemas."""

import json as _json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Maximum serialized JSON size for dict fields (10 KB)
_MAX_JSON_FIELD_BYTES = 10240


class BotConfigCreate(BaseModel):
    """Request to create a new bot."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    strategy_type: str = Field(..., min_length=1)
    exchange_type: str = Field(..., pattern="^(bitget|weex|hyperliquid)$")
    mode: str = Field(default="demo", pattern="^(demo|live|both)$")

    # Trading parameters (all optional — empty = equal split, no TP/SL)
    trading_pairs: List[str] = Field(default=["BTCUSDT"], max_length=20)

    @field_validator("trading_pairs")
    @classmethod
    def validate_trading_pairs(cls, v: List[str]) -> List[str]:
        for pair in v:
            if not re.match(r'^[A-Z0-9_-]{1,30}$', pair):
                raise ValueError(f"Invalid trading pair format: {pair}")
        return v

    leverage: Optional[int] = Field(default=None, ge=1, le=20)
    position_size_percent: Optional[float] = Field(default=None, ge=1, le=25)
    max_trades_per_day: Optional[int] = Field(default=None, ge=1, le=10)
    take_profit_percent: Optional[float] = Field(default=None, ge=0.5, le=20)
    stop_loss_percent: Optional[float] = Field(default=None, ge=0.5, le=10)
    daily_loss_limit_percent: Optional[float] = Field(default=None, ge=1, le=20)

    # Per-asset configuration (optional overrides per trading pair)
    per_asset_config: Optional[Dict[str, Dict[str, Any]]] = Field(
        default=None,
        description='Per-asset overrides, e.g. {"BTCUSDT": {"position_pct": 10, "leverage": 5}}',
    )

    # Strategy-specific parameters
    strategy_params: Optional[Dict[str, Any]] = None

    # Schedule
    schedule_type: str = Field(default="market_sessions", pattern="^(market_sessions|interval|custom_cron|rotation_only)$")
    schedule_config: Optional[Dict[str, Any]] = None

    # Trade rotation: auto-close & reopen trades at fixed intervals
    rotation_enabled: bool = Field(default=False, description="Enable automatic trade rotation")
    rotation_interval_minutes: Optional[int] = Field(
        default=None, ge=5, le=10080,
        description="Close & reopen trades after this many minutes (5min to 7 days)",
    )
    rotation_start_time: Optional[str] = Field(
        default=None, pattern=r"^\d{2}:\d{2}$",
        description="UTC start time for rotation intervals (HH:MM format, e.g. '08:00')",
    )

    # Per-bot Discord webhook (optional)
    discord_webhook_url: Optional[str] = Field(
        default=None,
        description="Discord webhook URL for this bot's notifications",
    )

    # Per-bot Telegram notifications (optional)
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    @field_validator("strategy_params", "schedule_config", "per_asset_config", mode="before")
    @classmethod
    def validate_dict_field_size(cls, v: Any) -> Any:
        if v is not None and isinstance(v, dict):
            if len(_json.dumps(v)) > _MAX_JSON_FIELD_BYTES:
                raise ValueError(f"Field exceeds maximum size of {_MAX_JSON_FIELD_BYTES} bytes when serialized to JSON")
        return v

    @model_validator(mode="after")
    def validate_strategy_requirements(self):
        if self.strategy_type == "llm_signal":
            sp = self.strategy_params or {}
            if not sp.get("llm_provider"):
                raise ValueError("LLM strategy requires 'llm_provider' in strategy_params")
        if self.rotation_enabled and not self.rotation_interval_minutes:
            raise ValueError("rotation_interval_minutes is required when rotation_enabled is True")
        return self


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

    schedule_type: Optional[str] = Field(None, pattern="^(market_sessions|interval|custom_cron|rotation_only)$")
    schedule_config: Optional[Dict[str, Any]] = None

    rotation_enabled: Optional[bool] = Field(None, description="Enable automatic trade rotation")
    rotation_interval_minutes: Optional[int] = Field(
        None, ge=5, le=10080, description="Rotation interval in minutes (5min to 7 days)",
    )
    rotation_start_time: Optional[str] = Field(
        None, pattern=r"^\d{2}:\d{2}$",
        description="UTC start time for rotation intervals (HH:MM format)",
    )

    # Per-bot Discord webhook (optional)
    discord_webhook_url: Optional[str] = Field(
        default=None,
        description="Discord webhook URL for this bot (empty string clears it)",
    )

    # Per-asset configuration (optional overrides per trading pair)
    per_asset_config: Optional[Dict[str, Dict[str, Any]]] = None

    # Per-bot Telegram notifications (optional)
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    @field_validator("strategy_params", "schedule_config", "per_asset_config", mode="before")
    @classmethod
    def validate_dict_field_size(cls, v: Any) -> Any:
        if v is not None and isinstance(v, dict):
            if len(_json.dumps(v)) > _MAX_JSON_FIELD_BYTES:
                raise ValueError(f"Field exceeds maximum size of {_MAX_JSON_FIELD_BYTES} bytes when serialized to JSON")
        return v


class BotConfigResponse(BaseModel):
    """Bot configuration response."""
    id: int
    name: str
    description: Optional[str] = None
    strategy_type: str
    exchange_type: str
    mode: str
    trading_pairs: List[str]
    leverage: Optional[int] = None
    position_size_percent: Optional[float] = None
    max_trades_per_day: Optional[int] = None
    take_profit_percent: Optional[float] = None
    stop_loss_percent: Optional[float] = None
    daily_loss_limit_percent: Optional[float] = None
    per_asset_config: Optional[Dict[str, Dict[str, Any]]] = None
    strategy_params: Optional[Dict[str, Any]] = None
    schedule_type: str
    schedule_config: Optional[Dict[str, Any]] = None
    rotation_enabled: bool = False
    rotation_interval_minutes: Optional[int] = None
    rotation_start_time: Optional[str] = None
    is_enabled: bool
    discord_webhook_configured: bool = False
    telegram_configured: bool = False
    active_preset_id: Optional[int] = None
    active_preset_name: Optional[str] = None
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
    discord_webhook_configured: bool = False
    telegram_configured: bool = False
    active_preset_id: Optional[int] = None
    active_preset_name: Optional[str] = None

    # Hyperliquid revenue gates
    builder_fee_approved: Optional[bool] = None
    referral_verified: Optional[bool] = None

    # Affiliate UID (Bitget / Weex)
    affiliate_uid: Optional[str] = None
    affiliate_verified: Optional[bool] = None

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


class BotBudgetInfo(BaseModel):
    """Budget allocation info for a single bot."""
    bot_config_id: int
    bot_name: str
    exchange_type: str
    mode: str
    currency: str = "USDT"
    exchange_balance: float
    exchange_equity: float
    allocated_budget: float
    allocated_pct: float
    total_allocated_pct: float
    has_sufficient_funds: bool
    warning_message: Optional[str] = None


class BotBudgetListResponse(BaseModel):
    """Response listing budget info for all bots."""
    budgets: List[BotBudgetInfo] = []
