"""Config preset schemas."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None
    exchange_type: str = Field(default="any", pattern="^(any|bitget|weex|hyperliquid)$")
    trading_config: Optional[Dict[str, Any]] = None
    strategy_config: Optional[Dict[str, Any]] = None
    trading_pairs: List[str] = Field(default=["BTCUSDT", "ETHUSDT"])


class PresetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = None
    trading_config: Optional[Dict[str, Any]] = None
    strategy_config: Optional[Dict[str, Any]] = None
    trading_pairs: Optional[List[str]] = None


class PresetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    exchange_type: str
    is_active: bool
    trading_config: Optional[dict] = None
    strategy_config: Optional[dict] = None
    trading_pairs: Optional[list] = None
