"""Bot management service (ARCH-C1 Phase 2b).

FastAPI-free business logic for ``/api/bots`` handlers. The router is a
thin HTTP adapter: it parses query params, calls the service, and maps
the returned plain dicts onto Pydantic response models.

Populated incrementally — PR-1 ships the two static read-only handlers
(``list_strategies`` + ``list_data_sources``) so the service module
exists for the larger list-bots / get-bot / create-bot extractions that
follow.
"""

from __future__ import annotations

from typing import Any

from src.data.data_source_registry import DATA_SOURCES, DEFAULT_SOURCES
from src.strategy import StrategyRegistry


def list_strategies() -> list[dict[str, Any]]:
    """Return the registry of available trading strategies.

    Each entry is the plain-dict shape that ``StrategyInfo`` serializes
    from. The router wraps the list in ``StrategiesListResponse``.
    """
    return StrategyRegistry.list_available()


def list_data_sources() -> dict[str, Any]:
    """Return the catalog of market data sources + defaults.

    Mirrors the router-level response verbatim:
    ``{"sources": [<DataSource.to_dict()>, ...], "defaults": [...]}``.
    The router returns this dict directly (no Pydantic model wrapping).
    """
    return {
        "sources": [ds.to_dict() for ds in DATA_SOURCES],
        "defaults": DEFAULT_SOURCES,
    }
