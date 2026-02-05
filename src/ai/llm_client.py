"""
Anthropic Claude client wrapper with circuit breaker and streaming.

Provides a provider-agnostic interface for LLM interactions.
"""

import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from anthropic import AsyncAnthropic

from src.utils.circuit_breaker import CircuitBreakerError, circuit_registry
from src.utils.logger import get_logger

logger = get_logger(__name__)

MODEL_MAP = {
    "fast": "claude-haiku-4-5-20250514",
    "complex": "claude-sonnet-4-5-20241022",
}

COST_PER_1M = {
    "claude-haiku-4-5-20250514": {"input": 0.25, "output": 1.25},
    "claude-sonnet-4-5-20241022": {"input": 3.0, "output": 15.0},
}


@dataclass
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int
    model: str
    tool_calls: list = field(default_factory=list)
    stop_reason: str = ""


class LLMClient:
    """Anthropic Claude client with circuit breaker integration."""

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self._client = AsyncAnthropic(api_key=api_key)
        self._breaker = circuit_registry.get(
            "anthropic_api", fail_threshold=3, reset_timeout=120
        )

    async def chat(
        self,
        messages: list[dict],
        system: str,
        tools: Optional[list[dict]] = None,
        tier: str = "fast",
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Non-streaming chat completion with circuit breaker."""
        model = MODEL_MAP.get(tier, MODEL_MAP["fast"])
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = await self._breaker.call(
                self._client.messages.create, **kwargs
            )
        except CircuitBreakerError:
            logger.warning("Anthropic API circuit breaker is open")
            raise

        content_text = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        return LLMResponse(
            content=content_text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=model,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
        )

    async def chat_stream(
        self,
        messages: list[dict],
        system: str,
        tools: Optional[list[dict]] = None,
        tier: str = "fast",
        max_tokens: int = 2048,
    ) -> AsyncIterator[dict]:
        """Streaming chat completion yielding SSE-compatible events."""
        model = MODEL_MAP.get(tier, MODEL_MAP["fast"])
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            stream = await self._breaker.call(
                self._client.messages.create, stream=True, **kwargs
            )
        except CircuitBreakerError:
            logger.warning("Anthropic API circuit breaker is open")
            raise

        input_tokens = 0
        output_tokens = 0
        current_tool: Optional[dict] = None
        tool_input_json = ""

        async with stream as s:
            async for event in s:
                if event.type == "message_start":
                    if hasattr(event.message, "usage"):
                        input_tokens = event.message.usage.input_tokens

                elif event.type == "content_block_start":
                    if event.content_block.type == "text":
                        pass
                    elif event.content_block.type == "tool_use":
                        current_tool = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                        }
                        tool_input_json = ""

                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield {"type": "text", "content": event.delta.text}
                    elif event.delta.type == "input_json_delta":
                        tool_input_json += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool is not None:
                        import json
                        try:
                            parsed_input = json.loads(tool_input_json) if tool_input_json else {}
                        except json.JSONDecodeError:
                            parsed_input = {}
                        current_tool["input"] = parsed_input
                        yield {"type": "tool_use", "tool": current_tool}
                        current_tool = None
                        tool_input_json = ""

                elif event.type == "message_delta":
                    if hasattr(event, "usage") and event.usage:
                        output_tokens = event.usage.output_tokens
                    yield {
                        "type": "message_delta",
                        "stop_reason": getattr(event.delta, "stop_reason", None),
                    }

                elif event.type == "message_stop":
                    yield {
                        "type": "done",
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "model": model,
                    }

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """Estimate cost in USD."""
        rates = COST_PER_1M.get(model, COST_PER_1M["claude-haiku-4-5-20250514"])
        return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
