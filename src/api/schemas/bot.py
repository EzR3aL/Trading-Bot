"""Bot control schemas."""

from typing import List, Optional

from pydantic import BaseModel, Field


class BotStartRequest(BaseModel):
    exchange_type: str = Field(default="bitget", pattern="^(bitget|weex|hyperliquid)$")
    preset_id: Optional[int] = None
    demo_mode: bool = True


class BotStopRequest(BaseModel):
    exchange_type: str = Field(pattern="^(bitget|weex|hyperliquid)$")


class BotModeRequest(BaseModel):
    exchange_type: str = Field(default="bitget", pattern="^(bitget|weex|hyperliquid)$")
    demo_mode: bool


class BotStatusResponse(BaseModel):
    is_running: bool
    exchange_type: Optional[str] = None
    demo_mode: bool = True
    active_preset_id: Optional[int] = None
    active_preset_name: Optional[str] = None
    started_at: Optional[str] = None
    last_analysis: Optional[str] = None


class MultiBotStatusResponse(BaseModel):
    bots: List[BotStatusResponse] = []
