"""
AI Trading Assistant API endpoints.

Provides chat (SSE streaming), conversation management, and usage tracking.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.assistant import (
    ChatRequest,
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
    TokenUsageResponse,
)
from src.auth.dependencies import get_current_user
from src.models.database import Conversation, Message, User
from src.models.session import get_db
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
limiter = Limiter(key_func=get_remote_address)

# Module-level assistant reference, set by main_app during lifespan
_assistant = None


def set_assistant(assistant):
    """Set the TradingAssistant instance (called from main_app lifespan)."""
    global _assistant
    _assistant = assistant


def _require_assistant():
    """Raise 503 if assistant is not available."""
    if _assistant is None:
        raise HTTPException(
            status_code=503,
            detail="AI Assistant not available. ANTHROPIC_API_KEY not configured.",
        )
    return _assistant


@router.get("/status")
async def assistant_status():
    """Check if the AI assistant is available."""
    return {"available": _assistant is not None}


@router.post("/chat")
@limiter.limit("20/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a message and get a streaming SSE response."""
    assistant = _require_assistant()

    async def event_stream():
        try:
            async for sse_event in assistant.chat(
                user=user,
                message=body.message,
                conversation_id=body.conversation_id,
                db=db,
            ):
                yield sse_event
        except Exception as e:
            logger.error(f"Assistant chat error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's conversations, most recent first."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.created_at.desc())
        .limit(50)
    )
    conversations = result.scalars().all()

    items = []
    for conv in conversations:
        # Get message count and last message
        msg_result = await db.execute(
            select(func.count()).where(Message.conversation_id == conv.id)
        )
        msg_count = msg_result.scalar() or 0

        last_msg_result = await db.execute(
            select(Message.content)
            .where(Message.conversation_id == conv.id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_msg = last_msg_result.scalar()

        items.append(ConversationResponse(
            id=conv.id,
            title=conv.title,
            created_at=conv.created_at.isoformat() if conv.created_at else "",
            updated_at=conv.updated_at.isoformat() if conv.updated_at else None,
            message_count=msg_count,
            last_message_preview=last_msg[:100] if last_msg else None,
        ))

    return items


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all messages in a conversation."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    conv = result.scalars().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    )
    messages = msg_result.scalars().all()

    return ConversationDetailResponse(
        id=conv.id,
        title=conv.title,
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                tool_calls=json.loads(m.tool_calls) if m.tool_calls else None,
                created_at=m.created_at.isoformat() if m.created_at else "",
            )
            for m in messages
        ],
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation and all its messages."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    conv = result.scalars().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.delete(conv)
    await db.commit()
    return {"deleted": True}


@router.post("/conversations", response_model=ConversationResponse)
async def new_conversation(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new empty conversation."""
    conv = Conversation(user_id=user.id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        message_count=0,
    )


@router.get("/usage", response_model=TokenUsageResponse)
async def get_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get today's token usage for the current user."""
    assistant = _require_assistant()
    return await assistant.get_token_usage(user.id, db)
