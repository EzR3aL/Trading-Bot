"""Free helper functions for the Hyperliquid client.

Pure-function utilities extracted from ``client.py`` during the structural
refactor. No behavior change — these are the same helpers, just colocated
in their own module so the main ``client.py`` stays focused on the class
shape. Re-exported from ``client.py`` to preserve every existing import.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Strip these suffixes to get coin name: "BTCUSDT" → "BTC"
_QUOTE_SUFFIXES = re.compile(r"(USDT|USDC|USD|PERP)$", re.IGNORECASE)


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol to Hyperliquid coin name. 'BTCUSDT' → 'BTC', 'ETH' → 'ETH'."""
    return _QUOTE_SUFFIXES.sub("", symbol.upper())


def _hl_float(value: Any) -> Optional[float]:
    """Parse a HL value to float; preserve 0.0, return None on missing."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hl_int(value: Any) -> Optional[int]:
    """Parse a HL value to int; return None on missing / unparseable."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _hl_ts_to_datetime(ts_ms: Optional[int]) -> Optional[datetime]:
    """Convert a HL millisecond timestamp to a UTC datetime."""
    if ts_ms is None or ts_ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_order_response(result: Any) -> Dict[str, Any]:
    """Extract order info from SDK response. Handles various response formats."""
    # Local import to avoid a circular dependency: signing imports nothing
    # from helpers, but client imports both, and tests patch
    # ``src.exchanges.hyperliquid.client.HyperliquidClientError`` etc.
    from src.exchanges.hyperliquid.signing import HyperliquidClientError

    logger.debug(f"Hyperliquid raw response: {result}")

    if isinstance(result, dict):
        # Check for top-level error
        resp_type = result.get("status", "")
        if resp_type == "err":
            raise HyperliquidClientError(f"Order rejected: {result.get('response', result)}")

        status = result.get("response", {}).get("data", {})
        if isinstance(status, dict) and "statuses" in status:
            statuses = status["statuses"]
            if statuses:
                first = statuses[0]
                # Filled order: {"filled": {"totalSz": "0.001", "avgPx": "95000", "oid": 123}}
                if "filled" in first:
                    return {
                        "oid": first["filled"].get("oid", ""),
                        "avgPx": first["filled"].get("avgPx", "0"),
                        "totalSz": first["filled"].get("totalSz", "0"),
                    }
                # Resting order: {"resting": {"oid": 123}}
                if "resting" in first:
                    return {"oid": first["resting"].get("oid", ""), "avgPx": "0"}
                # Error in status
                if "error" in first:
                    raise HyperliquidClientError(f"Order rejected: {first['error']}")

    logger.warning(f"Hyperliquid: could not parse order response: {result}")
    return {"oid": "hl-unknown", "avgPx": "0"}
