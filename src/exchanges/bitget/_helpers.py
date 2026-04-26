"""Free helpers for the Bitget client.

Pure-function value parsers, the cancel-outcome classifier and the
``orderSource`` → canonical plan_type mapping. Extracted from
``client.py`` during the structural refactor.

Re-exported from ``client.py`` so existing imports continue to resolve.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from src.utils.logger import get_logger

# Use the client module's logger name so test fixtures that target
# ``src.exchanges.bitget.client`` (caplog.set_level(..., logger=...))
# still capture log records emitted from this helper module.
logger = get_logger("src.exchanges.bitget.client")


def _parse_float(value: Any) -> Optional[float]:
    """Parse a value to float; return None on missing / unparseable input."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> Optional[int]:
    """Parse a value to int; return None on missing / unparseable input."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ts_to_datetime(ts_ms: Optional[int]) -> Optional[datetime]:
    """Convert a Bitget millisecond timestamp to a UTC datetime."""
    if ts_ms is None or ts_ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


# Bitget error tokens that mean "nothing to cancel" — benign no-ops.
# Rendered on message body, not status code, since the SDK surfaces the
# message string. Kept conservative: only substrings we have seen return
# for "plan does not exist"; anything else escalates to WARN per #225.
_BITGET_BENIGN_CANCEL_TOKENS: tuple[str, ...] = (
    "no plan",
    "no order",
    "not found",
    "no matching",
    "does not exist",
    "40768",  # Bitget "Order not exists" code
)


def _log_bitget_cancel_outcome(
    caller: str, plan_type: str, symbol: str, exc: Exception,
) -> None:
    """Classify a Bitget cancel-plan failure and log at the right level.

    Benign "no matching plan" responses stay at DEBUG (legitimate no-op
    when the leg was never placed or was already cancelled). Anything
    else — network, auth, contract errors — escalates to WARN so a real
    cancel failure is visible and does not mask a stale exchange-side
    plan (Pattern C mitigation per #225).
    """
    msg = str(exc).lower()
    if any(tok in msg for tok in _BITGET_BENIGN_CANCEL_TOKENS):
        logger.debug(
            "bitget.%s cancel %s for %s: %s (no matching plan)",
            caller, plan_type, symbol, exc,
        )
    else:
        logger.warning(
            "bitget.%s cancel %s for %s FAILED: %s",
            caller, plan_type, symbol, exc,
        )


_BITGET_ORDER_SOURCE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("pos_loss", "pos_loss"),
    ("pos_profit", "pos_profit"),
    # Bitget emits the trigger origin for native trailings as one of
    # ``track_plan_*`` (docs), ``moving_plan_*``, or the abbreviated
    # ``move_*`` (observed on demo accounts — e.g. ``move_market``).
    # Map all three to the same canonical plan_type so the classifier
    # produces TRAILING_STOP_NATIVE regardless of Bitget's spelling.
    ("track_plan", "moving_plan"),
    ("moving_plan", "moving_plan"),
    ("move_", "moving_plan"),
    ("liquidation", "liquidation"),
    # NOTE: a ``normal_plan_*`` source is intentionally NOT mapped here.
    # ``normal_plan`` is not a key in ``_PLAN_TYPE_TO_REASON``, so emitting
    # it would silently fall through to EXTERNAL_CLOSE_UNKNOWN — exactly
    # the bug backfill #220 had to clean up. Falling through to the
    # function's default of ``"manual"`` produces MANUAL_CLOSE_EXCHANGE,
    # which is the closest semantic match for an operator/script-driven
    # conditional. If Bitget ever exposes a distinct normal-plan trigger
    # in the response, add both sides (prefix + ExitReason) at once.
)


def _bitget_order_source_to_plan_type(order_source: str) -> str:
    """Map a Bitget ``orderSource`` to the canonical plan_type key.

    Bitget suffixes the source with the execution type (``_market`` /
    ``_limit``). We match by prefix so future variants don't silently
    reclassify a triggered close as ``manual``. Any unknown / absent
    source defaults to ``manual`` so downstream classification still
    produces a sensible ExitReason.
    """
    src = (order_source or "").lower()
    for prefix, plan_type in _BITGET_ORDER_SOURCE_PREFIXES:
        if src.startswith(prefix):
            return plan_type
    return "manual"
