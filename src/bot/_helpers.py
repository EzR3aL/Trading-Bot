"""Module-level helpers used by the BotWorker and its mixins.

Extracted from ``src/bot/bot_worker.py`` as part of the BotWorker mixin
split refactor (mirrors PR #361 pattern). Pure functions and constants
only — no class state. The legacy names (``_safe_json_loads``,
``_noop_async``, ``DEFAULT_MARKET_HOURS``) remain re-exported from
``src/bot/bot_worker.py`` so any test that patches them in place keeps
working.
"""

import json
from typing import Any, List


# Default market session schedule (UTC hours).
DEFAULT_MARKET_HOURS = [1, 8, 14, 21]


def _safe_json_loads(value: Any, default: List = None) -> List:
    """Safely parse JSON, returning default on error."""
    if default is None:
        default = []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


async def _noop_async(*_args, **_kwargs) -> None:  # pragma: no cover - defensive default
    return None
