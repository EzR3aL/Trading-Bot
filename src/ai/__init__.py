"""AI/LLM integration for trading signal generation.

Provides a unified interface to multiple LLM providers (Groq, Gemini,
OpenAI, Anthropic, DeepSeek, Mistral, xAI, Perplexity) for generating
trading signals from market data.
"""

from src.ai.providers import (
    PROVIDER_REGISTRY,
    LLM_PROVIDERS_INFO,
    MODEL_CATALOG,
    get_provider_class,
    get_default_model,
)
from src.ai.providers.base import (
    BaseLLMProvider,
    LLMResponse,
    parse_llm_response,
    format_market_data_prompt,
    sanitize_text,
)

__all__ = [
    # Core abstractions
    "BaseLLMProvider",
    "LLMResponse",
    # Registry & catalog
    "PROVIDER_REGISTRY",
    "LLM_PROVIDERS_INFO",
    "MODEL_CATALOG",
    # Helper functions
    "get_provider_class",
    "get_default_model",
    "parse_llm_response",
    "format_market_data_prompt",
    "sanitize_text",
]
