"""HTTP-wire mappers for the trades router.

Collected here so ``src/api/routers/trades.py`` stays a thin handler
surface. Everything in this module is about translating between
FastAPI/pydantic wire shapes and :class:`TradesService` dataclasses —
there is no business logic below this line.
"""

from dataclasses import asdict
from typing import Optional, Union

from src.api.schemas.trade import RiskLegStatus, TradeResponse, UpdateTpSlRequest
from src.errors import (
    ERR_SL_ABOVE_ENTRY_SHORT,
    ERR_SL_BELOW_ENTRY_LONG,
    ERR_SL_POSITIVE,
    ERR_TP_ABOVE_ENTRY_LONG,
    ERR_TP_BELOW_ENTRY_SHORT,
    ERR_TP_POSITIVE,
    ERR_TP_SL_CONFLICT_SL,
    ERR_TP_SL_CONFLICT_TP,
)
from src.services.trades_service import RiskLegOutcome, RiskLegSnapshot, TpSlIntent


def trade_response(item) -> TradeResponse:
    """Project a :class:`TradeListItem` or :class:`TradeDetail` onto the wire model.

    The service dataclasses share field names with ``TradeResponse``
    except for ``trailing`` (a dict of extra keys). We flatten that dict
    onto the top-level model so the frontend sees one unified shape.
    """
    payload = asdict(item)
    trailing = payload.pop("trailing", {}) or {}
    return TradeResponse(**payload, **trailing)


def leg_to_status(
    leg: Optional[Union[RiskLegOutcome, RiskLegSnapshot]],
) -> Optional[RiskLegStatus]:
    """Project a service-layer per-leg dataclass onto the wire model.

    Both :class:`RiskLegOutcome` (write path) and :class:`RiskLegSnapshot`
    (read-only snapshot) carry the same fields, so a single helper covers
    both shapes.
    """
    if leg is None:
        return None
    return RiskLegStatus(
        value=leg.value,
        status=leg.status,
        order_id=leg.order_id,
        error=leg.error,
        latency_ms=leg.latency_ms,
    )


def intent_from_body(body: UpdateTpSlRequest) -> TpSlIntent:
    """Translate a pydantic request body into the FastAPI-free service intent."""
    return TpSlIntent(
        take_profit=body.take_profit,
        stop_loss=body.stop_loss,
        remove_tp=body.remove_tp,
        remove_sl=body.remove_sl,
        trailing_callback_pct=(
            body.trailing_stop.callback_pct if body.trailing_stop is not None else None
        ),
        remove_trailing=body.remove_trailing,
    )


# Map ``InvalidTpSlIntent`` reason strings to user-facing error detail strings.
# Both paths (legacy / manager) use this table — only the HTTP status code
# differs (see ``MUTEX_CONFLICT_REASONS``). Central mapping so the router
# stays declarative.
_INVALID_INTENT_DETAIL: dict[str, str] = {
    "tp_conflict": ERR_TP_SL_CONFLICT_TP,
    "sl_conflict": ERR_TP_SL_CONFLICT_SL,
    "trailing_conflict": "Cannot both set and remove trailing stop",
    "invalid_entry_price": "Trade has invalid entry price",
    "tp_non_positive": ERR_TP_POSITIVE,
    "tp_below_entry_long": ERR_TP_ABOVE_ENTRY_LONG,
    "tp_above_entry_short": ERR_TP_BELOW_ENTRY_SHORT,
    "sl_non_positive": ERR_SL_POSITIVE,
    "sl_above_entry_long": ERR_SL_BELOW_ENTRY_LONG,
    "sl_below_entry_short": ERR_SL_ABOVE_ENTRY_SHORT,
}


#: Reasons that represent a mutex conflict (set + remove on the same leg).
#: On the manager path these map to 422; everything else — price/side
#: validation — stays 400 so users can fix the value. On the legacy path
#: all validation errors are 400 regardless.
MUTEX_CONFLICT_REASONS = frozenset({"tp_conflict", "sl_conflict", "trailing_conflict"})


#: Exchange-error hints that disambiguate user-fixable 400s from upstream
#: 502s. When the raw exchange message contains any of these substrings we
#: surface a translated 400 (user can adjust the TP/SL). Otherwise the
#: error is opaque and we return a generic 502.
EXCHANGE_ERROR_HINTS = (
    "price",
    "less than",
    "greater than",
    "invalid",
    "must be",
    "should be",
)


def invalid_intent_detail(reason: str) -> str:
    """Look up the user-facing detail string for an intent-validation reason."""
    return _INVALID_INTENT_DETAIL.get(reason, reason)
