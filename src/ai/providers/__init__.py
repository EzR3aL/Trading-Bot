"""LLM provider registry and exports."""

from typing import Any, Dict, List, Type

from src.ai.providers.anthropic_provider import AnthropicProvider
from src.ai.providers.base import BaseLLMProvider, LLMResponse
from src.ai.providers.deepseek import DeepSeekProvider
from src.ai.providers.gemini import GeminiProvider
from src.ai.providers.groq import GroqProvider
from src.ai.providers.mistral import MistralProvider
from src.ai.providers.openai_provider import OpenAIProvider
from src.ai.providers.perplexity import PerplexityProvider
from src.ai.providers.xai import XAIProvider

PROVIDER_REGISTRY: Dict[str, Type[BaseLLMProvider]] = {
    "groq": GroqProvider,
    "gemini": GeminiProvider,
    "gemini_pro": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "deepseek": DeepSeekProvider,
    "mistral": MistralProvider,
    "xai": XAIProvider,
    "perplexity": PerplexityProvider,
}

LLM_PROVIDERS_INFO = {
    "groq": {"name": "Groq", "free": True},
    "gemini": {"name": "Google Gemini Flash", "free": True},
    "gemini_pro": {"name": "Google Gemini Pro", "free": False},
    "openai": {"name": "OpenAI", "free": False},
    "anthropic": {"name": "Anthropic Claude", "free": False},
    "deepseek": {"name": "DeepSeek", "free": False},
    "mistral": {"name": "Mistral", "free": False},
    "xai": {"name": "xAI Grok", "free": False},
    "perplexity": {"name": "Perplexity", "free": False},
}

# ── Model Catalog: families with 4 latest models (newest first) ──

MODEL_CATALOG: Dict[str, Dict[str, Any]] = {
    "groq": {
        "family_name": "Groq",
        "free": True,
        "models": [
            {"id": "meta-llama/llama-4-maverick-17b-128e-instruct", "name": "Llama 4 Maverick", "default": True},
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B"},
            {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B"},
            {"id": "qwen/qwen3-32b", "name": "Qwen3 32B"},
        ],
    },
    "gemini": {
        "family_name": "Google Gemini Flash",
        "free": True,
        "models": [
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "default": True},
            {"id": "gemini-3-flash-preview", "name": "Gemini 3 Flash (Preview)"},
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
            {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash-Lite"},
        ],
    },
    "gemini_pro": {
        "family_name": "Google Gemini Pro",
        "free": False,
        "models": [
            {"id": "gemini-3-pro-preview", "name": "Gemini 3 Pro (Preview)", "default": True},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
            {"id": "gemini-2.0-pro", "name": "Gemini 2.0 Pro"},
            {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro"},
        ],
    },
    "openai": {
        "family_name": "OpenAI",
        "free": False,
        "models": [
            {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini", "default": True},
            {"id": "gpt-5.2", "name": "GPT-5.2"},
            {"id": "o4-mini", "name": "o4-mini"},
            {"id": "o3", "name": "o3"},
        ],
    },
    "anthropic": {
        "family_name": "Anthropic Claude",
        "free": False,
        "models": [
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "default": True},
            {"id": "claude-sonnet-4-5-20250514", "name": "Claude Sonnet 4.5"},
            {"id": "claude-opus-4-6-20260101", "name": "Claude Opus 4.6"},
            {"id": "claude-opus-4-5-20250918", "name": "Claude Opus 4.5"},
        ],
    },
    "deepseek": {
        "family_name": "DeepSeek",
        "free": False,
        "models": [
            {"id": "deepseek-chat", "name": "DeepSeek V3 (Chat)", "default": True},
            {"id": "deepseek-reasoner", "name": "DeepSeek V3 (Reasoner)"},
        ],
    },
    "mistral": {
        "family_name": "Mistral",
        "free": False,
        "models": [
            {"id": "mistral-small-2506", "name": "Mistral Small 3.2", "default": True},
            {"id": "mistral-medium-2508", "name": "Mistral Medium 3.1"},
            {"id": "mistral-large-2512", "name": "Mistral Large 3"},
            {"id": "devstral-2512", "name": "Devstral 2"},
        ],
    },
    "xai": {
        "family_name": "xAI Grok",
        "free": False,
        "models": [
            {"id": "grok-3-mini", "name": "Grok 3 Mini", "default": True},
            {"id": "grok-3", "name": "Grok 3"},
            {"id": "grok-4-0709", "name": "Grok 4"},
            {"id": "grok-4-1-fast-reasoning", "name": "Grok 4.1 Fast"},
        ],
    },
    "perplexity": {
        "family_name": "Perplexity",
        "free": False,
        "models": [
            {"id": "sonar", "name": "Sonar", "default": True},
            {"id": "sonar-pro", "name": "Sonar Pro"},
            {"id": "sonar-reasoning-pro", "name": "Sonar Reasoning Pro"},
            {"id": "sonar-deep-research", "name": "Sonar Deep Research"},
        ],
    },
}


def get_default_model(provider_type: str) -> str:
    """Get the default model ID for a provider family."""
    family = MODEL_CATALOG.get(provider_type, {})
    for model in family.get("models", []):
        if model.get("default"):
            return model["id"]
    models = family.get("models", [])
    return models[0]["id"] if models else ""


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
    "MODEL_CATALOG",
    "get_provider_class",
    "get_default_model",
    "GroqProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "DeepSeekProvider",
    "MistralProvider",
    "XAIProvider",
    "PerplexityProvider",
]
