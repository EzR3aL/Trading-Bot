"""LLM provider registry and exports."""

from typing import Dict, Type

from src.ai.providers.anthropic_provider import AnthropicProvider
from src.ai.providers.base import BaseLLMProvider, LLMResponse
from src.ai.providers.gemini import GeminiProvider
from src.ai.providers.groq import GroqProvider
from src.ai.providers.mistral import MistralProvider
from src.ai.providers.openai_provider import OpenAIProvider
from src.ai.providers.perplexity import PerplexityProvider
from src.ai.providers.xai import XAIProvider

PROVIDER_REGISTRY: Dict[str, Type[BaseLLMProvider]] = {
    "groq": GroqProvider,
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "mistral": MistralProvider,
    "xai": XAIProvider,
    "perplexity": PerplexityProvider,
}

LLM_PROVIDERS_INFO = {
    "groq": {"name": "Groq (Llama 3.3 70B)", "free": True},
    "gemini": {"name": "Google Gemini 2.0 Flash", "free": True},
    "openai": {"name": "OpenAI GPT-4o-mini", "free": False},
    "anthropic": {"name": "Anthropic Claude Haiku 4.5", "free": False},
    "mistral": {"name": "Mistral Small", "free": False},
    "xai": {"name": "xAI Grok", "free": False},
    "perplexity": {"name": "Perplexity Sonar", "free": False},
}


def get_provider_class(provider_type: str) -> Type[BaseLLMProvider]:
    """Get provider class by type string."""
    if provider_type not in PROVIDER_REGISTRY:
        raise ValueError(
            f"Unknown LLM provider: {provider_type}. "
            f"Available: {', '.join(PROVIDER_REGISTRY.keys())}"
        )
    return PROVIDER_REGISTRY[provider_type]


__all__ = [
    "BaseLLMProvider",
    "LLMResponse",
    "PROVIDER_REGISTRY",
    "LLM_PROVIDERS_INFO",
    "get_provider_class",
    "GroqProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "MistralProvider",
    "XAIProvider",
    "PerplexityProvider",
]
