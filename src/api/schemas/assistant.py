"""Pydantic schemas for the AI Trading Assistant."""

from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[int] = None


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    tool_calls: Optional[list] = None
    created_at: str


class ConversationResponse(BaseModel):
    id: int
    title: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    message_count: int = 0
    last_message_preview: Optional[str] = None


class ConversationDetailResponse(BaseModel):
    id: int
    title: Optional[str] = None
    messages: list[MessageResponse]


class TokenUsageResponse(BaseModel):
    used_today: int
    daily_limit: int
    remaining: int
