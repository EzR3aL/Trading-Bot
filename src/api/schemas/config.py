"""Configuration and settings schemas."""

from typing import List, Optional

from pydantic import BaseModel, Field


class TradingConfigUpdate(BaseModel):
    max_trades_per_day: int = Field(ge=1, le=10, default=3)
    daily_loss_limit_percent: float = Field(ge=1.0, le=20.0, default=5.0)
    position_size_percent: float = Field(ge=1.0, le=25.0, default=7.5)
    leverage: int = Field(ge=1, le=20, default=4)
    take_profit_percent: float = Field(ge=0.5, le=20.0, default=4.0)
    stop_loss_percent: float = Field(ge=0.5, le=10.0, default=1.5)
    trading_pairs: List[str] = Field(default=["BTCUSDT", "ETHUSDT"])
    demo_mode: bool = True


class StrategyConfigUpdate(BaseModel):
    fear_greed_extreme_fear: int = Field(ge=0, le=50, default=20)
    fear_greed_extreme_greed: int = Field(ge=50, le=100, default=80)
    long_short_crowded_longs: float = Field(ge=1.5, le=5.0, default=2.5)
    long_short_crowded_shorts: float = Field(ge=0.2, le=0.7, default=0.4)
    funding_rate_high: float = Field(default=0.0005)
    funding_rate_low: float = Field(default=-0.0002)
    high_confidence_min: int = Field(ge=50, le=100, default=85)
    low_confidence_min: int = Field(ge=50, le=100, default=60)


class ApiKeysUpdate(BaseModel):
    exchange_type: str = Field(pattern="^(bitget|weex|hyperliquid)$")
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    demo_api_key: str = ""
    demo_api_secret: str = ""
    demo_passphrase: str = ""


class ExchangeConfigUpdate(BaseModel):
    exchange_type: str = Field(pattern="^(bitget|weex|hyperliquid)$")


class ExchangeConnectionResponse(BaseModel):
    exchange_type: str
    api_keys_configured: bool = False
    demo_api_keys_configured: bool = False
    affiliate_uid: Optional[str] = None
    affiliate_verified: Optional[bool] = None


class ExchangeConnectionUpdate(BaseModel):
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    demo_api_key: str = ""
    demo_api_secret: str = ""
    demo_passphrase: str = ""


class ConfigResponse(BaseModel):
    trading: Optional[TradingConfigUpdate] = None
    strategy: Optional[StrategyConfigUpdate] = None
    connections: List[ExchangeConnectionResponse] = []
    # Deprecated: kept for backward compatibility
    exchange_type: str = "bitget"
    api_keys_configured: bool = False
    demo_api_keys_configured: bool = False


# ── LLM Connection Schemas ──────────────────────────────────


class LLMConnectionUpdate(BaseModel):
    """Request body for updating an LLM provider API key."""
    api_key: str = Field(..., min_length=1)


class LLMConnectionResponse(BaseModel):
    """Response for LLM connection status."""
    provider_type: str
    api_key_configured: bool
    display_name: str
    free_tier: bool
