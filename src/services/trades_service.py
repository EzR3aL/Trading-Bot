"""Trade CRUD, filters, pagination, export service (ARCH-C1).

This module contains FastAPI-free business logic for trade reads. The
router maps domain results to HTTP responses; this module never imports
``fastapi`` or raises ``HTTPException``. Domain errors (when needed) come
from ``src.services.exceptions``.

Populated incrementally across ARCH-C1 Phase 2a PRs — PR-3 adds the two
read-only handlers (``list_trades`` and ``get_filter_options``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.market_data import MarketDataFetcher
from src.models.database import BotConfig, TradeRecord, User
from src.strategy.base import resolve_strategy_params
from src.utils.logger import get_logger

logger = get_logger(__name__)


#: Strategies that compute an ATR-based trailing stop for the dashboard display.
#: Kept in sync with the router-side constant; moved here as the service owns
#: the enrichment logic now.
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
