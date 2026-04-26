"""Trade CRUD, filters, pagination, export service (ARCH-C1).

This module contains FastAPI-free business logic for trade reads and
writes. The router maps domain results to HTTP responses; this module
never imports ``fastapi`` or raises ``HTTPException``. Domain errors
come from ``src.services.exceptions``.

Module structure
----------------
This file is the **public façade**. The actual implementation lives in
focused mixin modules so each concern can be reviewed and tested in
isolation:

* ``_trades_helpers``               — pure helpers + module-level async
                                       utilities (trailing-stop math,
                                       ATR fetch, intent validation,
                                       sync notifications)
* ``_trades_list_mixin``            — list / detail / filter-options
                                       (read-only queries)
* ``_trades_risk_snapshot_mixin``   — ``get_risk_state_snapshot`` (RSM
                                       readback)
* ``_trades_sync_mixin``            — ``sync_exchange_positions``
* ``_trades_tpsl_mixin``            — TP/SL/trailing update flows
                                       (manager + legacy paths)

Every name a consumer or test imports from
``src.services.trades_service`` is re-exported below — this file is the
source of truth for the public API surface.

Router-patched dependencies
---------------------------
Several Phase-0 characterization tests patch module-level symbols on
``src/api/routers/trades.py`` (``settings``, ``decrypt_value``,
``create_exchange_client``, ``MarketDataFetcher``, the notifier class,
``get_risk_state_manager``). The write-handler service methods therefore
accept these as explicit arguments so the router can forward its own
(patched) references rather than re-importing them here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import User
from src.services._trades_helpers import (
    TRAILING_STOP_STRATEGIES,
    _build_trailing_intent,
    _compute_atr_for_trailing,
    _compute_trailing_stop,
    _derive_overall_status,
    _leg_dict_to_snapshot,
    _resolve_exit_reason,
    _risk_result_to_outcome,
    _send_sync_discord_notifications,
    _validate_tp_sl_against_trade,
)
from src.services._trades_list_mixin import ListMixin
from src.services._trades_risk_snapshot_mixin import RiskSnapshotMixin
from src.services._trades_sync_mixin import SyncMixin
from src.services._trades_tpsl_mixin import TpSlMixin
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Public re-exports kept here so existing
# ``from src.services.trades_service import X`` imports keep resolving for
# every prior consumer (portfolio service, routers, tests). The leading
# underscore on the helpers is preserved to signal "module-level helper"
# while still being importable.
__all__ = [
    # Strategy constant
    "TRAILING_STOP_STRATEGIES",
    # Input dataclasses
    "TradeFilters",
    "Pagination",
    # Result dataclasses
    "TradeListItem",
    "TradeListResult",
    "TradeDetail",
    "RiskLegSnapshot",
    "RiskStateSnapshotResult",
    "FilterBotOption",
    "FilterOptionsResult",
    "TpSlIntent",
    "RiskLegOutcome",
    "TpSlManagerResult",
    "TpSlLegacyResult",
    "SyncClosedTrade",
    "SyncResult",
    # Module-level helpers (re-exported for portfolio_service,
    # bots_statistics router and several test modules).
    "_build_trailing_intent",
    "_compute_atr_for_trailing",
    "_compute_trailing_stop",
    "_derive_overall_status",
    "_leg_dict_to_snapshot",
    "_resolve_exit_reason",
    "_risk_result_to_outcome",
    "_send_sync_discord_notifications",
    "_validate_tp_sl_against_trade",
    # Service
    "TradesService",
]


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TradeFilters:
    """Filter parameters accepted by ``list_trades``.

    All fields mirror the query parameters of ``GET /api/trades``. The router
    is responsible for validating shapes (regex on ``status``, date format)
    before constructing this object.
    """

    status: Optional[str] = None
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    bot_name: Optional[str] = None
    date_from: Optional[str] = None  # ISO YYYY-MM-DD
    date_to: Optional[str] = None    # ISO YYYY-MM-DD
    demo_mode: Optional[bool] = None


@dataclass(slots=True)
class Pagination:
    """Pagination parameters for listing handlers."""

    page: int = 1
    per_page: int = 50


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TradeListItem:
    """A single enriched trade row returned by ``list_trades``.

    Fields match the router's ``TradeResponse`` pydantic model so the router
    can construct the response with a simple ``TradeResponse(**item)``-style
    projection. Trailing-stop fields are optional (``None`` when not
    applicable).
    """

    id: int
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: Optional[float]
    take_profit: Optional[float]
    stop_loss: Optional[float]
    leverage: int
    confidence: int
    reason: str
    status: str
    pnl: Optional[float]
    pnl_percent: Optional[float]
    fees: float
    funding_paid: float
    entry_time: str
    exit_time: Optional[str]
    exit_reason: Optional[str]
    exchange: str
    demo_mode: bool
    bot_name: Optional[str]
    bot_exchange: Optional[str]
    trailing: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TradeListResult:
    """Aggregate result for ``list_trades``."""

    items: list[TradeListItem]
    total: int
    page: int
    per_page: int


@dataclass(slots=True)
class TradeDetail:
    """A single enriched trade row returned by ``get_trade``.

    Mirrors ``TradeListItem`` so the router maps both shapes onto the
    same ``TradeResponse`` pydantic model. The ``trailing`` dict stays
    empty for closed trades / trades without a trailing strategy, matching
    the pre-extract handler behavior exactly.
    """

    id: int
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: Optional[float]
    take_profit: Optional[float]
    stop_loss: Optional[float]
    leverage: int
    confidence: int
    reason: str
    status: str
    pnl: Optional[float]
    pnl_percent: Optional[float]
    fees: float
    funding_paid: float
    entry_time: str
    exit_time: Optional[str]
    exit_reason: Optional[str]
    exchange: str
    demo_mode: bool
    bot_name: Optional[str]
    bot_exchange: Optional[str]
    trailing: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RiskLegSnapshot:
    """One per-leg slice of a reconcile result, FastAPI-free.

    Mirrors the dict that ``RiskStateManager.reconcile`` returns for each
    leg, plus a default status so the router can materialize a
    ``RiskLegStatus`` without re-deriving fallback values.
    """

    value: Any = None
    status: str = ""
    order_id: Optional[str] = None
    error: Optional[str] = None
    latency_ms: int = 0


@dataclass(slots=True)
class RiskStateSnapshotResult:
    """Aggregate result for ``get_risk_state_snapshot``.

    Mirrors the relevant fields of ``TpSlResponse`` so the router can
    project them onto the pydantic model without any extra logic.
    """

    trade_id: int
    tp: Optional[RiskLegSnapshot]
    sl: Optional[RiskLegSnapshot]
    trailing: Optional[RiskLegSnapshot]
    applied_at: datetime
    overall_status: str


@dataclass(slots=True)
class FilterBotOption:
    """A bot option for the filter dropdown (id + display name)."""

    id: int
    name: str


@dataclass(slots=True)
class FilterOptionsResult:
    """Distinct filter values for the current user.

    Mirrors the four fields of ``TradeFilterOptionsResponse`` exactly.
    """

    symbols: list[str]
    bots: list[FilterBotOption]
    exchanges: list[str]
    statuses: list[str]


# ---------------------------------------------------------------------------
# Write-handler inputs / results (PR-2)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TpSlIntent:
    """FastAPI-free translation of the ``UpdateTpSlRequest`` pydantic model.

    The router validates the incoming JSON + applies ``extra='forbid'``
    and the ``callback_pct`` range check; it then projects the pydantic
    object onto this dataclass so the service receives a plain value
    object rather than a framework-coupled model.
    """

    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    remove_tp: bool = False
    remove_sl: bool = False
    trailing_callback_pct: Optional[float] = None  # ATR multiplier (1.0 - 5.0)
    remove_trailing: bool = False


@dataclass(slots=True)
class RiskLegOutcome:
    """Per-leg outcome of an ``apply_intent`` call, FastAPI-free.

    Mirrors the router's ``RiskLegStatus`` pydantic model so the router
    can project directly onto it via ``RiskLegStatus(**dataclasses.asdict(x))``.
    """

    value: Any = None
    status: str = ""
    order_id: Optional[str] = None
    error: Optional[str] = None
    latency_ms: int = 0


@dataclass(slots=True)
class TpSlManagerResult:
    """Aggregate result of :meth:`TradesService.update_tp_sl_via_manager`.

    Mirrors the fields of the router's ``TpSlResponse`` exactly — the
    router instantiates that pydantic model with ``asdict(result)``-style
    projection.
    """

    trade_id: int
    tp: Optional[RiskLegOutcome]
    sl: Optional[RiskLegOutcome]
    trailing: Optional[RiskLegOutcome]
    applied_at: datetime
    overall_status: str


@dataclass(slots=True)
class TpSlLegacyResult:
    """Aggregate result of :meth:`TradesService.update_tp_sl_legacy`.

    Mirrors the ``{"status": "ok", ...}`` dict that the legacy handler
    returns — intentionally preserved verbatim (characterization-frozen)
    until the frontend migrates to the manager shape.
    """

    take_profit: Optional[float]
    stop_loss: Optional[float]
    trailing_stop_placed: bool
    trailing_stop_software: bool


@dataclass(slots=True)
class SyncClosedTrade:
    """One entry of the ``closed_trades`` list returned by sync.

    Matches the dict shape that the pre-extract handler built:
    ``{id, symbol, side, exit_price, pnl, exit_reason}``.
    """

    id: int
    symbol: str
    side: str
    exit_price: float
    pnl: float
    exit_reason: str


@dataclass(slots=True)
class SyncResult:
    """Aggregate result of :meth:`TradesService.sync_exchange_positions`."""

    synced: int
    closed_trades: list[SyncClosedTrade] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TradesService(
    ListMixin,
    RiskSnapshotMixin,
    SyncMixin,
    TpSlMixin,
):
    """Trade CRUD, filters, pagination, export.

    Implementation is split across per-concern mixins (see module
    docstring for the layout). The constructor is the only thing this
    class owns directly; all behavior comes from the mixins above.
    """

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
