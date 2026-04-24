"""Trade CRUD, filters, pagination, export service (ARCH-C1).

This module contains FastAPI-free business logic for trade reads and
writes. The router maps domain results to HTTP responses; this module
never imports ``fastapi`` or raises ``HTTPException``. Domain errors
come from ``src.services.exceptions``.

Populated incrementally across ARCH-C1 Phase 2a PRs:
- PR-3 (#255): ``list_trades`` and ``get_filter_options``.
- PR-1 of #325: ``get_trade`` detail + ``get_risk_state_snapshot``.
- PR-2 of #325: ``sync_exchange_positions``, ``update_tp_sl_legacy``,
  ``update_tp_sl_via_manager`` (plus the shared TP/SL validation +
  trailing intent helpers lifted out of the router).

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

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.risk_state_manager import RiskLeg, RiskOpResult, RiskOpStatus, RiskStateManager
from src.data.market_data import MarketDataFetcher
from src.models.database import (
    BotConfig,
    ExchangeConnection,
    TradeRecord,
    User,
    UserConfig,
)
from src.services.exceptions import (
    ExchangeConnectionMissing,
    InvalidTpSlIntent,
    TpSlExchangeNotSupported,
    TpSlUpdateFailed,
    TradeNotFound,
    TradeNotOpen,
)
from src.strategy.base import resolve_strategy_params
from src.utils.logger import get_logger

logger = get_logger(__name__)


#: Strategies that compute an ATR-based trailing stop for the dashboard display.
#: Owned by the service after #325 PR-3 — external callers (router, portfolio
#: service, bots_statistics router) import from here.
TRAILING_STOP_STRATEGIES = ("edge_indicator", "liquidation_hunter")


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
# Status code sets used by the manager-path ``overall_status`` aggregate.
# ---------------------------------------------------------------------------


_RISK_OK_STATUSES = {RiskOpStatus.CONFIRMED.value, RiskOpStatus.CLEARED.value}
_RISK_FAIL_STATUSES = {
    RiskOpStatus.REJECTED.value,
    RiskOpStatus.CANCEL_FAILED.value,
}


def _derive_overall_status(legs: list[RiskLegOutcome]) -> str:
    """Aggregate per-leg statuses into a single overall outcome label."""
    if not legs:
        return "no_change"
    statuses = [leg.status for leg in legs]
    has_ok = any(s in _RISK_OK_STATUSES for s in statuses)
    has_fail = any(s in _RISK_FAIL_STATUSES for s in statuses)
    if has_ok and not has_fail:
        return "all_confirmed"
    if has_fail and not has_ok:
        return "all_rejected"
    if has_ok and has_fail:
        return "partial_success"
    return "no_change"


def _risk_result_to_outcome(result: RiskOpResult) -> RiskLegOutcome:
    """Convert a :class:`RiskOpResult` into the service-layer outcome type."""
    return RiskLegOutcome(
        value=result.value,
        status=result.status.value,
        order_id=result.order_id,
        error=result.error,
        latency_ms=result.latency_ms,
    )


# ---------------------------------------------------------------------------
# Trailing-stop helper (lifted from the router, FastAPI-free)
# ---------------------------------------------------------------------------


async def _compute_trailing_stop(
    trade: TradeRecord,
    strategy_type: Optional[str],
    strategy_params_json: Optional[str],
    klines_cache: Optional[dict] = None,
) -> dict:
    """Compute live trailing-stop fields for an open trade.

    Returns a dict with keys matching the ``TradeResponse`` trailing-stop
    fields. Uses ``resolve_strategy_params`` so the dashboard's view matches
    the live strategy exactly (same DEFAULTS -> RISK_PROFILE -> user_params
    merge, same ``kline_interval``).

    Behavior preserved verbatim from the pre-extract router handler.
    """
    if trade.status != "open":
        return {}

    has_manual_override = trade.trailing_atr_override is not None
    has_strategy = strategy_type in TRAILING_STOP_STRATEGIES

    if not has_manual_override and not has_strategy:
        return {}

    params = resolve_strategy_params(strategy_type, strategy_params_json)

    if not has_manual_override and not params.get("trailing_stop_enabled", True):
        return {}

    highest_price = trade.highest_price
    if highest_price is None:
        return {"trailing_stop_active": False, "can_close_at_loss": True}

    atr_period = params.get("atr_period", 14)
    interval = params.get("kline_interval", "1h")
    cache_key = (trade.symbol, interval)
    if klines_cache is not None and cache_key in klines_cache:
        klines = klines_cache[cache_key]
    else:
        try:
            fetcher = MarketDataFetcher()
            klines = await fetcher.get_binance_klines(
                trade.symbol, interval, atr_period + 15,
            )
            await fetcher.close()
        except Exception as exc:
            logger.debug("Trailing stop kline fetch failed for %s: %s", trade.symbol, exc)
            return {"trailing_stop_active": False}

    if not klines:
        return {"trailing_stop_active": False}

    atr_series = MarketDataFetcher.calculate_atr(klines, atr_period)
    atr_val = atr_series[-1] if atr_series else trade.entry_price * 0.015

    breakeven_atr = params.get("trailing_breakeven_atr", 1.5)
    trail_atr = (
        trade.trailing_atr_override
        if trade.trailing_atr_override is not None
        else params.get("trailing_trail_atr", 2.5)
    )
    breakeven_threshold = atr_val * breakeven_atr
    trail_distance = atr_val * trail_atr

    side = trade.side
    entry = trade.entry_price

    if side == "long":
        was_profitable = (highest_price - entry) >= breakeven_threshold
        if was_profitable:
            trailing_stop = max(highest_price - trail_distance, entry)
            distance = highest_price - trailing_stop
            distance_pct = (distance / highest_price) * 100 if highest_price else 0
            return {
                "trailing_stop_active": True,
                "trailing_stop_price": round(trailing_stop, 2),
                "trailing_stop_distance": round(distance, 2),
                "trailing_stop_distance_pct": round(distance_pct, 2),
                "can_close_at_loss": False,
            }
        return {
            "trailing_stop_active": False,
            "trailing_stop_distance_pct": round(trail_atr, 1),
            "can_close_at_loss": True,
        }
    # SHORT: highest_price tracks the lowest price since entry
    was_profitable = (entry - highest_price) >= breakeven_threshold
    if was_profitable:
        trailing_stop = min(highest_price + trail_distance, entry)
        distance = trailing_stop - highest_price
        distance_pct = (distance / highest_price) * 100 if highest_price else 0
        return {
            "trailing_stop_active": True,
            "trailing_stop_price": round(trailing_stop, 2),
            "trailing_stop_distance": round(distance, 2),
            "trailing_stop_distance_pct": round(distance_pct, 2),
            "can_close_at_loss": False,
        }
    return {
        "trailing_stop_active": False,
        "trailing_stop_distance_pct": round(trail_atr, 1),
        "can_close_at_loss": True,
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TradesService:
    """Trade CRUD, filters, pagination, export.

    PR-3 scope: ``list_trades`` + ``get_filter_options`` (read-only). Further
    methods (detail, stream) arrive in PR-4.
    """

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user

    # ---- list ------------------------------------------------------------

    async def list_trades(
        self,
        filters: TradeFilters,
        pagination: Pagination,
    ) -> TradeListResult:
        """Return a paginated + filtered list of the user's trades.

        Behavior matches the pre-extract ``GET /api/trades`` handler exactly,
        including the ilike escape on ``symbol`` and the date-range inclusivity
        rules (``entry_time >= date_from`` and ``entry_time < date_to+1d``).
        """
        user_id = self.user.id

        # Escape LIKE metacharacters in the user-supplied symbol so a value
        # like ``100%`` does not turn into an unbounded wildcard search.
        safe_symbol: Optional[str] = None
        if filters.symbol:
            safe_symbol = (
                filters.symbol.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )

        def _apply_common_filters(q):
            """Apply the shared WHERE clauses to both the row and count queries."""
            if filters.status:
                q = q.where(TradeRecord.status == filters.status)
            if safe_symbol is not None:
                q = q.where(TradeRecord.symbol.ilike(f"%{safe_symbol}%", escape="\\"))
            if filters.exchange:
                q = q.where(BotConfig.exchange_type == filters.exchange)
            if filters.bot_name:
                q = q.where(BotConfig.name == filters.bot_name)
            if filters.date_from:
                q = q.where(TradeRecord.entry_time >= datetime.fromisoformat(filters.date_from))
            if filters.date_to:
                q = q.where(
                    TradeRecord.entry_time
                    < datetime.fromisoformat(filters.date_to + "T23:59:59")
                )
            if filters.demo_mode is not None:
                q = q.where(TradeRecord.demo_mode == filters.demo_mode)
            return q

        # --- Main row query ---------------------------------------------------
        query = (
            select(
                TradeRecord,
                BotConfig.name.label("bot_name"),
                BotConfig.exchange_type.label("bot_exchange"),
                BotConfig.strategy_type.label("strategy_type"),
                BotConfig.strategy_params.label("strategy_params"),
            )
            .outerjoin(BotConfig, TradeRecord.bot_config_id == BotConfig.id)
            .where(TradeRecord.user_id == user_id)
        )
        query = _apply_common_filters(query)

        # --- Count (uses the same filters, but selects only IDs) --------------
        count_base = (
            select(TradeRecord.id)
            .outerjoin(BotConfig, TradeRecord.bot_config_id == BotConfig.id)
            .where(TradeRecord.user_id == user_id)
        )
        count_base = _apply_common_filters(count_base)
        count_query = select(func.count()).select_from(count_base.subquery())
        total = (await self.db.execute(count_query)).scalar() or 0

        # --- Pagination -------------------------------------------------------
        query = query.order_by(TradeRecord.entry_time.desc())
        query = query.offset((pagination.page - 1) * pagination.per_page).limit(
            pagination.per_page
        )

        result = await self.db.execute(query)
        rows = result.all()

        # --- Pre-fetch klines for all unique (symbol, interval) pairs so the
        # trailing-stop enrichment avoids N+1 Binance calls. Kept identical
        # to the original handler.
        klines_cache: dict[tuple[str, str], list] = {}
        prefetch_keys: set[tuple[str, str]] = set()
        for t, _, _, strat_type, strat_params in rows:
            if t.status != "open":
                continue
            if strat_type not in TRAILING_STOP_STRATEGIES and t.trailing_atr_override is None:
                continue
            resolved = resolve_strategy_params(strat_type, strat_params)
            interval = resolved.get("kline_interval", "1h")
            prefetch_keys.add((t.symbol, interval))

        if prefetch_keys:
            fetcher = MarketDataFetcher()
            try:
                for sym, interval in prefetch_keys:
                    try:
                        klines_cache[(sym, interval)] = await fetcher.get_binance_klines(
                            sym, interval, 14 + 15,
                        )
                    except Exception as exc:
                        logger.debug(
                            "Batch kline fetch failed for %s %s: %s", sym, interval, exc
                        )
            finally:
                await fetcher.close()

        # --- Shape the items --------------------------------------------------
        items: list[TradeListItem] = []
        for t, bot_name_val, bot_exchange_val, strat_type, strat_params in rows:
            ts_info: dict = {}
            if t.status == "open":
                try:
                    ts_info = await _compute_trailing_stop(
                        t, strat_type, strat_params, klines_cache,
                    )
                except Exception as exc:
                    logger.debug(
                        "Trailing stop enrichment failed for trade %s: %s", t.id, exc
                    )

            items.append(
                TradeListItem(
                    id=t.id,
                    symbol=t.symbol,
                    side=t.side,
                    size=t.size,
                    entry_price=t.entry_price,
                    exit_price=t.exit_price,
                    take_profit=t.take_profit,
                    stop_loss=t.stop_loss,
                    leverage=t.leverage,
                    confidence=t.confidence,
                    reason=t.reason,
                    status=t.status,
                    pnl=t.pnl,
                    pnl_percent=t.pnl_percent,
                    fees=t.fees or 0,
                    funding_paid=t.funding_paid or 0,
                    entry_time=t.entry_time.isoformat() if t.entry_time else "",
                    exit_time=t.exit_time.isoformat() if t.exit_time else None,
                    exit_reason=t.exit_reason,
                    exchange=t.exchange,
                    demo_mode=t.demo_mode,
                    bot_name=bot_name_val,
                    bot_exchange=bot_exchange_val,
                    trailing=ts_info,
                )
            )

        return TradeListResult(
            items=items,
            total=total,
            page=pagination.page,
            per_page=pagination.per_page,
        )

    # ---- filter options --------------------------------------------------

    async def get_filter_options(self) -> FilterOptionsResult:
        """Return distinct filter values available for the user's trades.

        Uses ``SELECT DISTINCT`` / grouped queries so the backend never pulls
        full trade rows just to populate a dropdown. Scope is restricted to
        the current user (same ownership filter as ``GET /api/trades``).
        """
        user_id = self.user.id

        # Distinct symbols from the user's trades
        symbols_result = await self.db.execute(
            select(TradeRecord.symbol)
            .where(TradeRecord.user_id == user_id)
            .distinct()
        )
        symbols = sorted(
            s for s in (row[0] for row in symbols_result.all()) if s
        )

        # Distinct exchanges — combine TradeRecord.exchange and BotConfig.exchange_type
        # so a bot that has never traded still shows up if the user owns it.
        trade_exchanges_result = await self.db.execute(
            select(TradeRecord.exchange)
            .where(TradeRecord.user_id == user_id)
            .distinct()
        )
        exchanges_set: set[str] = {
            e for e in (row[0] for row in trade_exchanges_result.all()) if e
        }

        bot_exchanges_result = await self.db.execute(
            select(BotConfig.exchange_type)
            .where(BotConfig.user_id == user_id)
            .distinct()
        )
        for row in bot_exchanges_result.all():
            if row[0]:
                exchanges_set.add(row[0])
        exchanges = sorted(exchanges_set)

        # Distinct non-null statuses — typically {open, closed, cancelled/failed}
        status_result = await self.db.execute(
            select(TradeRecord.status)
            .where(TradeRecord.user_id == user_id)
            .distinct()
        )
        statuses = sorted(
            s for s in (row[0] for row in status_result.all()) if s
        )

        # Bots the user owns. Pull (id, name) only — no full ORM objects.
        bots_result = await self.db.execute(
            select(BotConfig.id, BotConfig.name)
            .where(BotConfig.user_id == user_id)
            .order_by(BotConfig.name.asc())
        )
        bots = [
            FilterBotOption(id=row[0], name=row[1])
            for row in bots_result.all()
            if row[1]
        ]

        return FilterOptionsResult(
            symbols=symbols,
            bots=bots,
            exchanges=exchanges,
            statuses=statuses,
        )

    # ---- detail ----------------------------------------------------------

    async def get_trade(self, trade_id: int) -> TradeDetail:
        """Return a single trade owned by ``self.user``.

        Ownership is fused into the WHERE clause so an unknown trade and
        another user's trade are indistinguishable (both raise
        :class:`TradeNotFound`). This matches the pre-extract handler and is
        intentional security hardening — the router maps the exception to
        a generic 404 without leaking existence.

        Trailing-stop enrichment runs for open trades with either a
        trailing strategy or a manual ATR override, identical to the old
        handler.
        """
        user_id = self.user.id

        result = await self.db.execute(
            select(
                TradeRecord,
                BotConfig.name.label("bot_name"),
                BotConfig.exchange_type.label("bot_exchange"),
                BotConfig.strategy_type.label("strategy_type"),
                BotConfig.strategy_params.label("strategy_params"),
            )
            .outerjoin(BotConfig, TradeRecord.bot_config_id == BotConfig.id)
            .where(TradeRecord.id == trade_id, TradeRecord.user_id == user_id)
        )
        row = result.one_or_none()
        if not row:
            raise TradeNotFound(trade_id)

        trade, bot_name, bot_exchange, strat_type, strat_params = row

        ts_info: dict = {}
        if trade.status == "open":
            try:
                ts_info = await _compute_trailing_stop(
                    trade, strat_type, strat_params,
                )
            except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
                logger.debug(
                    "Trailing stop enrichment failed for trade %s: %s",
                    trade.id, exc,
                )

        return TradeDetail(
            id=trade.id,
            symbol=trade.symbol,
            side=trade.side,
            size=trade.size,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            take_profit=trade.take_profit,
            stop_loss=trade.stop_loss,
            leverage=trade.leverage,
            confidence=trade.confidence,
            reason=trade.reason,
            status=trade.status,
            pnl=trade.pnl,
            pnl_percent=trade.pnl_percent,
            fees=trade.fees or 0,
            funding_paid=trade.funding_paid or 0,
            entry_time=trade.entry_time.isoformat() if trade.entry_time else "",
            exit_time=trade.exit_time.isoformat() if trade.exit_time else None,
            exit_reason=trade.exit_reason,
            exchange=trade.exchange,
            demo_mode=trade.demo_mode,
            bot_name=bot_name,
            bot_exchange=bot_exchange,
            trailing=ts_info,
        )

    # ---- risk-state snapshot --------------------------------------------

    async def get_risk_state_snapshot(
        self,
        trade_id: int,
        manager: RiskStateManager,
    ) -> RiskStateSnapshotResult:
        """Return the post-readback risk-state snapshot for a trade.

        The caller (router) owns the feature-flag gate; this method runs
        under the assumption the flag is on. Ownership is enforced before
        :meth:`RiskStateManager.reconcile` is invoked so another user's
        trade is never leaked through a reconcile side-effect.

        Raises:
            TradeNotFound: when the trade does not exist, is not owned by
                ``self.user``, or when ``reconcile`` reports the row
                vanished mid-flight (``ValueError``).
        """
        user_id = self.user.id

        trade_result = await self.db.execute(
            select(TradeRecord).where(
                TradeRecord.id == trade_id,
                TradeRecord.user_id == user_id,
            )
        )
        trade = trade_result.scalar_one_or_none()
        if trade is None:
            raise TradeNotFound(trade_id)

        try:
            snapshot = await manager.reconcile(trade_id)
        except ValueError as exc:
            # reconcile() raises ValueError when the row vanishes mid-flight;
            # surface it to the router so the generic 404 mapping fires
            # with the exchange's error message preserved.
            raise TradeNotFound(str(exc)) from exc

        tp_snap = _leg_dict_to_snapshot(snapshot.tp)
        sl_snap = _leg_dict_to_snapshot(snapshot.sl)
        trailing_snap = _leg_dict_to_snapshot(snapshot.trailing)

        # A pure readback never writes, so overall is "all_confirmed"
        # (native orders are in place) or "no_change" (nothing attached).
        any_confirmed = any(
            s is not None and s.status == RiskOpStatus.CONFIRMED.value
            for s in (tp_snap, sl_snap, trailing_snap)
        )
        overall = "all_confirmed" if any_confirmed else "no_change"

        return RiskStateSnapshotResult(
            trade_id=trade_id,
            tp=tp_snap,
            sl=sl_snap,
            trailing=trailing_snap,
            applied_at=snapshot.last_synced_at,
            overall_status=overall,
        )

    # ---- sync ------------------------------------------------------------

    async def sync_exchange_positions(
        self,
        *,
        rsm_enabled: bool,
        decrypt_value: Callable[[str], str],
        create_exchange_client: Callable[..., Any],
        get_risk_state_manager: Callable[[], Any],
        discord_notifier_cls: Callable[..., Any],
    ) -> SyncResult:
        """Sync open trades with the exchange and close any that vanished.

        Behavior is preserved verbatim from the pre-extract handler,
        including the exception-swallowing semantics and the Discord
        webhook side-effect. All external dependencies are supplied by
        the router so its patched symbols (used by the characterization
        tests) remain the effective call targets.
        """
        user_id = self.user.id

        result = await self.db.execute(
            select(TradeRecord).where(
                TradeRecord.user_id == user_id,
                TradeRecord.status == "open",
            )
        )
        open_trades = list(result.scalars().all())

        if not open_trades:
            return SyncResult(synced=0, closed_trades=[])

        trades_by_exchange: dict[str, list[TradeRecord]] = defaultdict(list)
        for trade in open_trades:
            trades_by_exchange[trade.exchange].append(trade)

        closed_trades: list[SyncClosedTrade] = []

        for exchange_type, trades in trades_by_exchange.items():
            conn_result = await self.db.execute(
                select(ExchangeConnection).where(
                    ExchangeConnection.user_id == user_id,
                    ExchangeConnection.exchange_type == exchange_type,
                )
            )
            conn = conn_result.scalar_one_or_none()
            if not conn:
                logger.warning(
                    "Sync: no connection for %s, skipping %d trades",
                    exchange_type, len(trades),
                )
                continue

            # Create exchange client (prefer demo keys, then live)
            if conn.demo_api_key_encrypted:
                api_key = decrypt_value(conn.demo_api_key_encrypted)
                api_secret = decrypt_value(conn.demo_api_secret_encrypted)
                passphrase = (
                    decrypt_value(conn.demo_passphrase_encrypted)
                    if conn.demo_passphrase_encrypted else ""
                )
                demo_mode = True
            elif conn.api_key_encrypted:
                api_key = decrypt_value(conn.api_key_encrypted)
                api_secret = decrypt_value(conn.api_secret_encrypted)
                passphrase = (
                    decrypt_value(conn.passphrase_encrypted)
                    if conn.passphrase_encrypted else ""
                )
                demo_mode = False
            else:
                continue

            client = create_exchange_client(
                exchange_type=exchange_type,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase,
                demo_mode=demo_mode,
            )

            try:
                exchange_positions = await client.get_open_positions()
                open_on_exchange = {
                    (pos.symbol, pos.side) for pos in exchange_positions
                }

                for trade in trades:
                    if (trade.symbol, trade.side) in open_on_exchange:
                        continue  # Still open on exchange

                    try:
                        # Prefer the actual close-order fill price (matches
                        # exchange exactly).
                        exit_price = None
                        try:
                            exit_price = await client.get_close_fill_price(trade.symbol)
                        except Exception:
                            pass
                        if not exit_price:
                            ticker = await client.get_ticker(trade.symbol)
                            exit_price = ticker.last_price

                        exit_time_now = datetime.now(timezone.utc)
                        exit_reason = await _resolve_exit_reason(
                            trade=trade,
                            exit_price=exit_price,
                            exit_time_now=exit_time_now,
                            rsm_enabled=rsm_enabled,
                            get_risk_state_manager=get_risk_state_manager,
                        )

                        # Calculate PnL (late import preserves the router's
                        # current side-effect ordering).
                        from src.bot.pnl import calculate_pnl
                        pnl, pnl_percent = calculate_pnl(
                            trade.side, trade.entry_price, exit_price, trade.size,
                        )

                        # Fetch trading + funding fees; non-fatal on failure.
                        try:
                            if trade.order_id:
                                trade.fees = await client.get_trade_total_fees(
                                    symbol=trade.symbol,
                                    entry_order_id=trade.order_id,
                                    close_order_id=trade.close_order_id,
                                )
                        except Exception as e:
                            logger.warning(
                                "Failed to fetch trading fees for trade %s: %s",
                                trade.id, e,
                            )

                        try:
                            if trade.entry_time:
                                entry_ms = int(trade.entry_time.timestamp() * 1000)
                                exit_ms = int(
                                    datetime.now(timezone.utc).timestamp() * 1000
                                )
                                trade.funding_paid = await client.get_funding_fees(
                                    symbol=trade.symbol,
                                    start_time_ms=entry_ms,
                                    end_time_ms=exit_ms,
                                )
                        except Exception as e:
                            logger.warning(
                                "Failed to fetch funding fees for trade %s: %s",
                                trade.id, e,
                            )

                        # Apply the close to the ORM row
                        trade.status = "closed"
                        trade.exit_price = exit_price
                        trade.pnl = round(pnl, 4)
                        trade.pnl_percent = round(pnl_percent, 2)
                        trade.exit_time = exit_time_now
                        trade.exit_reason = exit_reason

                        # When RSM is active, reconcile the trade so per-leg
                        # status columns reflect the post-close exchange state.
                        # Failure is non-fatal — the close is already staged.
                        if rsm_enabled:
                            try:
                                await self.db.flush()
                                await get_risk_state_manager().reconcile(trade.id)
                            except Exception as rec_err:  # noqa: BLE001
                                logger.warning(
                                    "Sync: reconcile failed for trade %s: %s",
                                    trade.id, rec_err,
                                )

                        closed_trades.append(SyncClosedTrade(
                            id=trade.id,
                            symbol=trade.symbol,
                            side=trade.side,
                            exit_price=exit_price,
                            pnl=round(pnl, 2),
                            exit_reason=exit_reason,
                        ))

                        logger.info(
                            "Sync: closed trade #%s %s %s | %s | PnL: $%.2f (%+.2f%%)",
                            trade.id, trade.symbol, trade.side,
                            exit_reason, pnl, pnl_percent,
                        )
                    except Exception as e:
                        logger.error(
                            "Sync: failed to close trade #%s: %s", trade.id, e,
                        )

            except Exception as e:
                logger.error(
                    "Sync: failed to query %s positions: %s", exchange_type, e,
                )
            finally:
                await client.close()

        await self.db.flush()

        if closed_trades:
            await _send_sync_discord_notifications(
                db=self.db,
                user_id=user_id,
                open_trades=open_trades,
                closed_trades=closed_trades,
                decrypt_value=decrypt_value,
                discord_notifier_cls=discord_notifier_cls,
            )

        return SyncResult(synced=len(closed_trades), closed_trades=closed_trades)

    # ---- tp/sl update ----------------------------------------------------

    async def update_tp_sl_via_manager(
        self,
        trade_id: int,
        intent: TpSlIntent,
        *,
        idempotency_key: Optional[str],
        get_risk_state_manager: Callable[[], Any],
        get_idempotency_cache: Callable[[], Any],
        market_data_fetcher_cls: type,
    ) -> TpSlManagerResult:
        """Route a TP/SL/trailing update through :class:`RiskStateManager`.

        The caller (router) owns the feature-flag gate; this method runs
        under the assumption the flag is on. Per-leg try/except is
        load-bearing — a single leg failure must not block the others.

        Raises:
            TradeNotFound: when the trade does not exist or is owned by
                a different user.
            TradeNotOpen: when the trade is not in the ``open`` state.
            InvalidTpSlIntent: when the intent violates a side/entry or
                mutex check (router maps this to 422 on this path).
        """
        # Mutex checks (remove_X and set_X at the same time)
        if intent.remove_tp and intent.take_profit is not None:
            raise InvalidTpSlIntent("tp_conflict")
        if intent.remove_sl and intent.stop_loss is not None:
            raise InvalidTpSlIntent("sl_conflict")
        if intent.remove_trailing and intent.trailing_callback_pct is not None:
            raise InvalidTpSlIntent("trailing_conflict")

        user_id = self.user.id
        trade_result = await self.db.execute(
            select(TradeRecord).where(
                TradeRecord.id == trade_id,
                TradeRecord.user_id == user_id,
            )
        )
        trade = trade_result.scalar_one_or_none()
        if not trade:
            raise TradeNotFound(trade_id)
        if trade.status != "open":
            raise TradeNotOpen(trade_id)

        _validate_tp_sl_against_trade(intent, trade)

        cache = get_idempotency_cache()
        cache_key: Optional[str] = None
        if idempotency_key:
            cache_key = f"tp_sl:{trade_id}:{idempotency_key}"
            cached = await cache.get(cache_key)
            if cached is not None:
                return cached

        manager = get_risk_state_manager()
        legs: list[tuple[RiskLeg, RiskLegOutcome]] = []

        async def _apply(leg: RiskLeg, value: Any) -> RiskLegOutcome:
            try:
                result = await manager.apply_intent(trade_id, leg, value)
                outcome = _risk_result_to_outcome(result)
            except Exception as exc:  # noqa: BLE001 — surface as REJECTED
                logger.exception(
                    "tp_sl_endpoint manager.apply_intent crashed",
                    extra={
                        "event_type": "tp_sl_endpoint",
                        "trade_id": trade_id,
                        "leg": leg.value,
                        "status": "rejected",
                    },
                )
                outcome = RiskLegOutcome(
                    value=value,
                    status=RiskOpStatus.REJECTED.value,
                    order_id=None,
                    error=str(exc),
                    latency_ms=0,
                )
            logger.info(
                "tp_sl_endpoint leg=%s status=%s latency_ms=%s",
                leg.value, outcome.status, outcome.latency_ms,
                extra={
                    "event_type": "tp_sl_endpoint",
                    "trade_id": trade_id,
                    "leg": leg.value,
                    "status": outcome.status,
                    "latency_ms": outcome.latency_ms,
                },
            )
            return outcome

        # ── TP leg ───────────────────────────────────────────────────
        if intent.remove_tp:
            legs.append((RiskLeg.TP, await _apply(RiskLeg.TP, None)))
        elif intent.take_profit is not None:
            legs.append((RiskLeg.TP, await _apply(RiskLeg.TP, intent.take_profit)))

        # ── SL leg ───────────────────────────────────────────────────
        if intent.remove_sl:
            legs.append((RiskLeg.SL, await _apply(RiskLeg.SL, None)))
        elif intent.stop_loss is not None:
            legs.append((RiskLeg.SL, await _apply(RiskLeg.SL, intent.stop_loss)))

        # ── Trailing leg ─────────────────────────────────────────────
        if intent.remove_trailing:
            legs.append((RiskLeg.TRAILING, await _apply(RiskLeg.TRAILING, None)))
        elif intent.trailing_callback_pct is not None:
            trailing_value = await _build_trailing_intent(
                trade=trade,
                callback_pct=intent.trailing_callback_pct,
                market_data_fetcher_cls=market_data_fetcher_cls,
            )
            legs.append(
                (RiskLeg.TRAILING, await _apply(RiskLeg.TRAILING, trailing_value))
            )

        leg_dict: dict[RiskLeg, RiskLegOutcome] = dict(legs)
        overall = _derive_overall_status(list(leg_dict.values()))

        if overall == "partial_success":
            logger.warning(
                "tp_sl_endpoint partial_success trade=%s legs=%s",
                trade_id,
                {leg.value: status.status for leg, status in legs},
                extra={
                    "event_type": "tp_sl_endpoint",
                    "trade_id": trade_id,
                    "status": overall,
                },
            )

        response = TpSlManagerResult(
            trade_id=trade_id,
            tp=leg_dict.get(RiskLeg.TP),
            sl=leg_dict.get(RiskLeg.SL),
            trailing=leg_dict.get(RiskLeg.TRAILING),
            applied_at=datetime.now(timezone.utc),
            overall_status=overall,
        )

        if cache_key is not None:
            await cache.set(cache_key, response)

        return response

    async def update_tp_sl_legacy(
        self,
        trade_id: int,
        intent: TpSlIntent,
        *,
        decrypt_value: Callable[[str], str],
        create_exchange_client: Callable[..., Any],
        market_data_fetcher_cls: type,
    ) -> TpSlLegacyResult:
        """Update TP/SL on an open position via direct exchange calls.

        The legacy code path that runs when ``risk_state_manager_enabled``
        is off. Behavior is preserved verbatim, including the order of
        operations (cancel then set), the native-trailing-probe branch,
        and the 400/502 split for exchange errors.

        Raises:
            TradeNotFound: unknown trade id or owned by a different user.
            TradeNotOpen: the trade is not open.
            InvalidTpSlIntent: mutex conflict or price/side violation.
            ExchangeConnectionMissing: no connection row, or no API keys.
            TpSlExchangeNotSupported: the client raised ``NotImplementedError``.
            TpSlUpdateFailed: any other exchange-side failure (carries the
                raw error message for router-side 400/502 disambiguation).
        """
        # Mutex checks — legacy raises 400 (so `InvalidTpSlIntent`
        # short-circuits before DB work).
        if intent.remove_tp and intent.take_profit is not None:
            raise InvalidTpSlIntent("tp_conflict")
        if intent.remove_sl and intent.stop_loss is not None:
            raise InvalidTpSlIntent("sl_conflict")

        user_id = self.user.id
        trade_result = await self.db.execute(
            select(TradeRecord).where(
                TradeRecord.id == trade_id,
                TradeRecord.user_id == user_id,
            ).with_for_update()
        )
        trade = trade_result.scalar_one_or_none()
        if not trade:
            raise TradeNotFound(trade_id)
        if trade.status != "open":
            raise TradeNotOpen(trade_id)
        if trade.entry_price <= 0:
            raise InvalidTpSlIntent("invalid_entry_price")

        _validate_tp_sl_against_trade(intent, trade)

        # Load exchange connection
        conn_result = await self.db.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user_id,
                ExchangeConnection.exchange_type == trade.exchange,
            )
        )
        conn = conn_result.scalar_one_or_none()
        if not conn:
            raise ExchangeConnectionMissing("No exchange connection found")

        api_key_enc = (
            conn.demo_api_key_encrypted if trade.demo_mode else conn.api_key_encrypted
        )
        api_secret_enc = (
            conn.demo_api_secret_encrypted if trade.demo_mode else conn.api_secret_encrypted
        )
        passphrase_enc = (
            conn.demo_passphrase_encrypted if trade.demo_mode else conn.passphrase_encrypted
        )

        if not api_key_enc or not api_secret_enc:
            raise ExchangeConnectionMissing("API keys not configured for this mode")

        client = create_exchange_client(
            exchange_type=trade.exchange,
            api_key=decrypt_value(api_key_enc),
            api_secret=decrypt_value(api_secret_enc),
            passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
            demo_mode=trade.demo_mode,
        )

        # Resolve margin_mode from bot config (defaults to "cross")
        margin_mode = "cross"
        if trade.bot_config_id:
            bot_result = await self.db.execute(
                select(BotConfig.margin_mode).where(
                    BotConfig.id == trade.bot_config_id,
                )
            )
            bot_margin = bot_result.scalar_one_or_none()
            if bot_margin:
                margin_mode = bot_margin

        # Effective TP/SL values (after remove flags)
        effective_tp = (
            None if intent.remove_tp
            else (intent.take_profit if intent.take_profit is not None else trade.take_profit)
        )
        effective_sl = (
            None if intent.remove_sl
            else (intent.stop_loss if intent.stop_loss is not None else trade.stop_loss)
        )

        trailing_placed = False
        exchange_has_trailing: Optional[bool] = None
        fetcher = None
        try:
            has_tp_change = intent.take_profit is not None or intent.remove_tp
            has_sl_change = intent.stop_loss is not None or intent.remove_sl
            if has_tp_change or has_sl_change:
                final_tp = effective_tp
                final_sl = effective_sl

                # Step 1: Cancel ALL old TP/SL on exchange (clean slate)
                await client.cancel_position_tpsl(
                    symbol=trade.symbol,
                    side=trade.side,
                )

                # Step 2: Set new values if any remain
                if final_tp is not None or final_sl is not None:
                    await client.set_position_tpsl(
                        symbol=trade.symbol,
                        take_profit=final_tp,
                        stop_loss=final_sl,
                        side=trade.side,
                        size=trade.size,
                    )

            # Trailing Stop — compute trigger_price and callback from ATR
            if intent.trailing_callback_pct is not None:
                # Always cancel the existing native trailing before placing
                # a new one; otherwise Bitget reports "Insufficient position"
                # because the live moving_plan already reserves the full
                # position size.
                if hasattr(client, "cancel_native_trailing_stop"):
                    try:
                        await client.cancel_native_trailing_stop(
                            trade.symbol, trade.side,
                        )
                    except Exception as cancel_err:
                        logger.debug(
                            "cancel_native_trailing_stop for trade %s failed: %s",
                            trade_id, cancel_err,
                        )

                atr_mult = intent.trailing_callback_pct
                try:
                    fetcher = market_data_fetcher_cls()
                    klines = await fetcher.get_binance_klines(
                        trade.symbol, "1h", 30,
                    )
                    atr_series = market_data_fetcher_cls.calculate_atr(klines, 14)
                    atr_val = (
                        atr_series[-1] if atr_series
                        else trade.entry_price * 0.015
                    )
                except Exception as atr_err:
                    logger.warning(
                        "ATR fetch failed for %s, using 1.5%% estimate: %s",
                        trade.symbol, atr_err,
                    )
                    atr_val = trade.entry_price * 0.015

                trail_distance = atr_val * atr_mult
                callback_pct = (trail_distance / trade.entry_price) * 100
                breakeven_atr = 1.5
                trigger = (
                    trade.entry_price + atr_val * breakeven_atr
                    if trade.side == "long"
                    else trade.entry_price - atr_val * breakeven_atr
                )

                try:
                    trail_order = await client.place_trailing_stop(
                        symbol=trade.symbol,
                        hold_side=trade.side,
                        size=trade.size,
                        callback_ratio=round(callback_pct, 2),
                        trigger_price=round(trigger, 2),
                        margin_mode=margin_mode,
                    )
                    if trail_order is not None:
                        trailing_placed = True
                    else:
                        logger.info(
                            "Native trailing not supported by %s — using software "
                            "trailing for trade %s (ATR override=%sx)",
                            trade.exchange, trade_id, atr_mult,
                        )
                except Exception as trail_err:
                    logger.warning(
                        "Native trailing stop failed for trade %s on %s: %s — "
                        "falling back to software trailing",
                        trade_id, trade.exchange, trail_err,
                    )

            # Authoritative probe before closing the client.
            if getattr(type(client), "SUPPORTS_NATIVE_TRAILING_PROBE", False):
                try:
                    exchange_has_trailing = await client.has_native_trailing_stop(
                        trade.symbol, trade.side,
                    )
                except Exception as probe_err:
                    logger.debug(
                        "has_native_trailing_stop probe failed: %s", probe_err,
                    )
                    exchange_has_trailing = None
        except NotImplementedError:
            raise TpSlExchangeNotSupported(trade.exchange)
        except Exception as e:
            error_msg = str(e)
            logger.error(
                "Failed to set TP/SL on exchange for trade %s: %s",
                trade_id, error_msg,
            )
            raise TpSlUpdateFailed(error_msg)
        finally:
            await client.close()
            if fetcher is not None:
                await fetcher.close()

        # Resolve the authoritative native_trailing_stop state.
        if exchange_has_trailing is None:
            native_state = trailing_placed
        else:
            native_state = exchange_has_trailing
            if exchange_has_trailing and not trailing_placed:
                logger.info(
                    "TP/SL sync: trade %s flagged trailing_placed=False but "
                    "exchange still reports a live moving_plan — keeping "
                    "native_trailing_stop=True",
                    trade_id,
                )
            elif not exchange_has_trailing and trailing_placed:
                logger.warning(
                    "TP/SL sync: place_trailing_stop returned success for trade "
                    "%s but the exchange shows no live moving_plan — "
                    "persisting False",
                    trade_id,
                )

        trade.take_profit = effective_tp
        trade.stop_loss = effective_sl
        if intent.trailing_callback_pct is not None:
            trade.native_trailing_stop = native_state
            trade.trailing_atr_override = intent.trailing_callback_pct
        else:
            # User submitted the form but trailing was off — reflect real
            # exchange state.
            trade.trailing_atr_override = None
            trade.native_trailing_stop = native_state
        await self.db.commit()

        logger.info(
            "TP/SL updated for trade %s: TP=%s, SL=%s, trailing=%s (native=%s)",
            trade_id, effective_tp, effective_sl,
            intent.trailing_callback_pct is not None, trailing_placed,
        )
        return TpSlLegacyResult(
            take_profit=intent.take_profit,
            stop_loss=intent.stop_loss,
            trailing_stop_placed=trailing_placed,
            trailing_stop_software=(
                intent.trailing_callback_pct is not None and not trailing_placed
            ),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _leg_dict_to_snapshot(leg: Optional[dict]) -> Optional[RiskLegSnapshot]:
    """Convert a reconcile-leg dict into a :class:`RiskLegSnapshot`.

    Returns ``None`` when the manager reports no state for the leg so the
    router can project ``None`` onto the response's ``tp`` / ``sl`` /
    ``trailing`` fields directly.
    """
    if leg is None:
        return None
    return RiskLegSnapshot(
        value=leg.get("value"),
        status=leg.get("status", RiskOpStatus.CLEARED.value),
        order_id=leg.get("order_id"),
        error=leg.get("error"),
        latency_ms=int(leg.get("latency_ms", 0)),
    )


def _validate_tp_sl_against_trade(intent: TpSlIntent, trade: TradeRecord) -> None:
    """Run the shared side/entry-price validation.

    Mirrors the pre-extract router helper ``_validate_tp_sl_values``
    verbatim. Raises :class:`InvalidTpSlIntent` with a canonical reason
    string; the router maps the reason to the right error detail +
    status code for its path (400 on legacy, 400 on manager).
    """
    if intent.remove_tp and intent.take_profit is not None:
        raise InvalidTpSlIntent("tp_conflict")
    if intent.remove_sl and intent.stop_loss is not None:
        raise InvalidTpSlIntent("sl_conflict")
    if trade.entry_price <= 0:
        raise InvalidTpSlIntent("invalid_entry_price")

    is_long = trade.side == "long"
    if intent.take_profit is not None:
        if intent.take_profit <= 0:
            raise InvalidTpSlIntent("tp_non_positive")
        if is_long and intent.take_profit <= trade.entry_price:
            raise InvalidTpSlIntent("tp_below_entry_long")
        if not is_long and intent.take_profit >= trade.entry_price:
            raise InvalidTpSlIntent("tp_above_entry_short")
    if intent.stop_loss is not None:
        if intent.stop_loss <= 0:
            raise InvalidTpSlIntent("sl_non_positive")
        if is_long and intent.stop_loss >= trade.entry_price:
            raise InvalidTpSlIntent("sl_above_entry_long")
        if not is_long and intent.stop_loss <= trade.entry_price:
            raise InvalidTpSlIntent("sl_below_entry_short")


async def _compute_atr_for_trailing(
    symbol: str,
    entry_price: float,
    market_data_fetcher_cls: type,
) -> float:
    """Fetch ATR for the trailing-stop endpoint.

    Returns the live 1h/14-period ATR if available, otherwise a 1.5%
    fallback based on the trade's entry price. Accepts the fetcher class
    as a parameter so the router's patched class (from the
    characterization tests) is used rather than a fresh import.
    """
    fetcher = market_data_fetcher_cls()
    try:
        klines = await fetcher.get_binance_klines(symbol, "1h", 30)
        atr_series = market_data_fetcher_cls.calculate_atr(klines, 14)
        if atr_series:
            return atr_series[-1]
    except Exception as atr_err:  # noqa: BLE001 — fallback to estimate
        logger.warning(
            "ATR fetch failed for %s, using 1.5%% estimate: %s",
            symbol, atr_err,
        )
    finally:
        await fetcher.close()
    return entry_price * 0.015


async def _build_trailing_intent(
    *,
    trade: TradeRecord,
    callback_pct: float,
    market_data_fetcher_cls: type,
) -> dict:
    """Translate a UI trailing callback_pct into the manager's payload.

    Mirrors the router helper verbatim. The manager expects a dict with
    ``callback_rate``, ``activation_price``, ``trigger_price`` and
    ``atr_override`` keys so the user's chosen multiplier can be persisted
    on the trade row through Phase D.
    """
    atr_val = await _compute_atr_for_trailing(
        trade.symbol, trade.entry_price, market_data_fetcher_cls,
    )
    atr_mult = callback_pct
    trail_distance = atr_val * atr_mult
    callback_rate = (trail_distance / trade.entry_price) * 100
    breakeven_atr = 1.5
    if trade.side == "long":
        trigger = trade.entry_price + atr_val * breakeven_atr
    else:
        trigger = trade.entry_price - atr_val * breakeven_atr
    return {
        "callback_rate": round(callback_rate, 2),
        "activation_price": None,
        "trigger_price": round(trigger, 2),
        "atr_override": atr_mult,
    }


async def _resolve_exit_reason(
    *,
    trade: TradeRecord,
    exit_price: float,
    exit_time_now: datetime,
    rsm_enabled: bool,
    get_risk_state_manager: Callable[[], Any],
) -> str:
    """Resolve a trade's exit reason using classify_close or the heuristic.

    When ``rsm_enabled`` is True we defer to
    :meth:`RiskStateManager.classify_close` — it probes the exchange's
    order history and attributes the close precisely. On failure we fall
    back to the legacy heuristic. When the flag is off, only the
    heuristic runs. Behavior matches the pre-extract handler.
    """
    if rsm_enabled:
        try:
            manager = get_risk_state_manager()
            return await manager.classify_close(
                trade.id, exit_price, exit_time_now,
            )
        except Exception as classify_err:  # noqa: BLE001
            logger.warning(
                "Sync: classify_close failed for trade %s, falling back to "
                "heuristic: %s",
                trade.id, classify_err,
            )
    # Heuristic path (flag off or classify_close failed)
    if trade.take_profit and abs(exit_price - trade.take_profit) < trade.entry_price * 0.005:
        return "TAKE_PROFIT"
    if trade.stop_loss and abs(exit_price - trade.stop_loss) < trade.entry_price * 0.005:
        return "STOP_LOSS"
    return "MANUAL_CLOSE"


async def _send_sync_discord_notifications(
    *,
    db: AsyncSession,
    user_id: int,
    open_trades: list[TradeRecord],
    closed_trades: list[SyncClosedTrade],
    decrypt_value: Callable[[str], str],
    discord_notifier_cls: Callable[..., Any],
) -> None:
    """Fire-and-forget Discord webhook sends for closed trades.

    The router used to inline this block; we keep the try/except
    semantics unchanged so the sync response is never affected by a
    notifier failure.
    """
    cfg_result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user_id)
    )
    config = cfg_result.scalar_one_or_none()
    if not config or not config.discord_webhook_url:
        return

    try:
        webhook_url = decrypt_value(config.discord_webhook_url)
    except (ValueError, Exception):
        webhook_url = None

    if not webhook_url:
        return

    notifier = discord_notifier_cls(webhook_url=webhook_url)
    try:
        for ct in closed_trades:
            matching = [t for t in open_trades if t.id == ct.id]
            if not matching:  # pragma: no cover — notify loop skip
                continue
            trade = matching[0]

            duration_minutes = None
            if trade.entry_time:
                entry = trade.entry_time
                if entry.tzinfo is None:
                    entry = entry.replace(tzinfo=timezone.utc)
                duration = datetime.now(timezone.utc) - entry
                duration_minutes = int(duration.total_seconds() / 60)

            await notifier.send_trade_exit(
                symbol=trade.symbol,
                side=trade.side,
                size=trade.size,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                pnl=trade.pnl,
                pnl_percent=trade.pnl_percent,
                fees=trade.fees or 0,
                funding_paid=trade.funding_paid or 0,
                reason=trade.exit_reason,
                order_id=trade.order_id,
                duration_minutes=duration_minutes,
                demo_mode=trade.demo_mode,
                strategy_reason=trade.reason,
            )
    except Exception as e:
        logger.warning("Discord sync notification failed: %s", e)
    finally:
        await notifier.close()
