"""Shared helpers for JSON field parsing on ORM models."""

import json
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


def parse_json_field(value: Any, *, field_name: str = "field", context: str = "", default: Any = None) -> Any:
    """Parse a JSON string field, returning *default* on failure.

    Handles the common pattern where an ORM column stores JSON as text:
    - ``None`` / empty → *default*
    - already a dict/list → returned as-is
    - string → ``json.loads``
    """
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError) as e:
        ctx = f" for {context}" if context else ""
        logger.warning("Failed to parse %s%s: %s", field_name, ctx, e)
        return default
