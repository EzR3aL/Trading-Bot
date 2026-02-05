"""
Core AI Trading Assistant service.

Manages conversations, tool-use loops, and streaming responses.
"""

import json
import os
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.llm_client import LLMClient
from src.ai.prompts import SYSTEM_PROMPT, TOOL_DEFINITIONS
from src.ai.tools import ToolExecutor
from src.models.database import Conversation, Message, User
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_TOOL_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 20
DEFAULT_DAILY_TOKEN_BUDGET = 100_000

COMPLEX_KEYWORDS = [
    "analyze", "explain", "why", "coaching", "anomaly", "pattern",
    "recommend", "improve", "strategy", "review", "compare",
    "analysiere", "erklaere", "warum", "muster", "empfehlung", "verbessern",
]


class TradingAssistant:
    """Orchestrates conversations between users and Claude."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def chat(
        self,
        user: User,
        message: str,
        conversation_id: Optional[int],
        db: AsyncSession,
    ) -> AsyncIterator[str]:
        """
        Process a user message and yield SSE event strings.

        Handles the multi-turn tool-use loop:
        1. Send user message + history to Claude
        2. If Claude calls a tool -> execute, feed result back
        3. Continue until Claude produces a text response
        4. Yield SSE events for each chunk
        5. Save all messages to DB
        """
        # Check token budget
        if not await self._check_token_budget(user.id, db):
            yield self._sse({"type": "error", "message": "daily_token_budget_exceeded"})
            return

        # Get or create conversation
        conversation = await self._get_or_create_conversation(
            user.id, conversation_id, message, db
        )

        # Save user message
        user_msg = Message(
            conversation_id=conversation.id,
            role="user",
            content=message,
        )
        db.add(user_msg)
        await db.flush()

        # Build messages for Claude
        history = await self._build_messages(conversation.id, db)

        # Select model tier
        tier = self._select_tier(message)
        language = "German" if user.language == "de" else "English"
        system = SYSTEM_PROMPT.replace("{language}", language)

        tool_executor = ToolExecutor(user.id, db)
        total_input_tokens = 0
        total_output_tokens = 0
        model_used = ""
        full_response_text = ""
        all_tool_calls = []
        all_tool_results = []

        for iteration in range(MAX_TOOL_ITERATIONS):
            accumulated_text = ""
            pending_tool_calls = []

            async for event in self.llm.chat_stream(
                messages=history,
                system=system,
                tools=TOOL_DEFINITIONS,
                tier=tier,
                max_tokens=2048,
            ):
                if event["type"] == "text":
                    accumulated_text += event["content"]
                    yield self._sse({"type": "text", "content": event["content"]})

                elif event["type"] == "tool_use":
                    tool = event["tool"]
                    pending_tool_calls.append(tool)
                    yield self._sse({
                        "type": "tool_call",
                        "name": tool["name"],
                        "input": tool["input"],
                    })

                elif event["type"] == "done":
                    total_input_tokens += event.get("input_tokens", 0)
                    total_output_tokens += event.get("output_tokens", 0)
                    model_used = event.get("model", "")

                elif event["type"] == "message_delta":
                    pass  # stop_reason handled below via pending_tool_calls

            full_response_text += accumulated_text

            # If no tool calls, we're done
            if not pending_tool_calls:
                break

            # Execute tool calls and add results to history
            assistant_content = []
            if accumulated_text:
                assistant_content.append({"type": "text", "text": accumulated_text})
            for tc in pending_tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            history.append({"role": "assistant", "content": assistant_content})

            tool_results_for_history = []
            for tc in pending_tool_calls:
                result = await tool_executor.execute(tc["name"], tc["input"])
                all_tool_calls.append(tc)
                all_tool_results.append({"name": tc["name"], "result": result})

                # Check for bot_config_preview
                if result.get("action") == "bot_config_preview":
                    yield self._sse({
                        "type": "bot_config_preview",
                        "config": result["config"],
                    })

                yield self._sse({
                    "type": "tool_result",
                    "name": tc["name"],
                    "data": result,
                })

                tool_results_for_history.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": json.dumps(result),
                })

            history.append({"role": "user", "content": tool_results_for_history})

        # Save assistant message
        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=full_response_text,
            tool_calls=json.dumps(all_tool_calls) if all_tool_calls else None,
            tool_results=json.dumps(all_tool_results) if all_tool_results else None,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            model_used=model_used,
        )
        db.add(assistant_msg)

        # Auto-title conversation from first message
        if not conversation.title and message:
            conversation.title = message[:100]

        await db.commit()

        yield self._sse({
            "type": "done",
            "conversation_id": conversation.id,
            "tokens": {
                "input": total_input_tokens,
                "output": total_output_tokens,
            },
        })

    async def _check_token_budget(self, user_id: int, db: AsyncSession) -> bool:
        """Check if user has remaining daily token budget."""
        budget = int(os.getenv("AI_DAILY_TOKEN_BUDGET", str(DEFAULT_DAILY_TOKEN_BUDGET)))
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        result = await db.execute(
            select(func.sum(Message.input_tokens + Message.output_tokens))
            .join(Conversation)
            .where(
                Conversation.user_id == user_id,
                Message.created_at >= today_start,
            )
        )
        used = result.scalar() or 0
        return used < budget

    async def get_token_usage(self, user_id: int, db: AsyncSession) -> dict:
        """Get today's token usage for a user."""
        budget = int(os.getenv("AI_DAILY_TOKEN_BUDGET", str(DEFAULT_DAILY_TOKEN_BUDGET)))
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        result = await db.execute(
            select(func.sum(Message.input_tokens + Message.output_tokens))
            .join(Conversation)
            .where(
                Conversation.user_id == user_id,
                Message.created_at >= today_start,
            )
        )
        used = result.scalar() or 0
        return {
            "used_today": used,
            "daily_limit": budget,
            "remaining": max(0, budget - used),
        }

    async def _get_or_create_conversation(
        self, user_id: int, conversation_id: Optional[int], message: str, db: AsyncSession
    ) -> Conversation:
        """Get existing or create new conversation."""
        if conversation_id:
            result = await db.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
            conv = result.scalars().first()
            if conv:
                return conv

        conv = Conversation(user_id=user_id)
        db.add(conv)
        await db.flush()
        return conv

    async def _build_messages(self, conversation_id: int, db: AsyncSession) -> list:
        """Load conversation history and format for Claude API."""
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(MAX_HISTORY_MESSAGES)
        )
        messages_db = list(reversed(result.scalars().all()))

        messages = []
        for msg in messages_db:
            if msg.role == "user":
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                messages.append({"role": "assistant", "content": msg.content})

        return messages

    def _select_tier(self, message: str) -> str:
        """Select model tier based on message content."""
        lower = message.lower()
        for keyword in COMPLEX_KEYWORDS:
            if keyword in lower:
                return "complex"
        return "fast"

    @staticmethod
    def _sse(data: dict) -> str:
        """Format a dict as an SSE event string."""
        return f"data: {json.dumps(data)}\n\n"
