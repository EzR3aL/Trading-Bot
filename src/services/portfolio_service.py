"""Portfolio aggregation service (ARCH-C1 Phase 2a PR-5).

FastAPI-free business logic for the 4 portfolio handlers. The router is a
thin HTTP adapter: it parses query params, calls the service, and maps the
returned dataclasses back onto Pydantic response models.

Behavior is preserved verbatim from the pre-extract handlers — same
aggregation, same trade-lookup key, same trailing-stop enrichment, same
error-swallowing on exchange timeouts. Caching stays in the router because
its TTL is module-scoped (shared across requests); the service only
computes uncached values.

Populated incrementally across ARCH-C1 Phase 2a PRs — PR-5 covers
``get_summary`` / ``list_positions`` / ``get_daily`` / ``get_allocation``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.exchanges.symbol_map import normalize_symbol
from src.models.database import BotConfig, TradeRecord, User
from src.services.trades_service import (
    TRAILING_STOP_STRATEGIES,
    _compute_trailing_stop,
)
from src.strategy.base import resolve_strategy_params
from src.utils.logger import get_logger

logger = get_logger(__name__)

#: SQL expression for "closed-date" — exit_time if set, otherwise entry_time.
#: Mirrors the router-side constant verbatim.
_closed_date = func.coalesce(TradeRecord.exit_time, TradeRecord.entry_time)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------


#: Callable the router injects for loading a user's exchange clients. Kept
#: as a parameter rather than a hard import so the characterization tests
#: can monkeypatch ``portfolio_router._get_all_user_clients`` and the
#: service observes the patched version.
ClientsLoader = Callable[
    [int, AsyncSession], Awaitable[list[tuple[str, bool, Any]]]
]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExchangeSummaryItem:
    """Per-exchange aggregation row used by ``get_summary``."""

    exchange: str
    total_pnl: float
    total_trades: int
    winning_trades: int
    win_rate: float
    total_fees: float
    total_funding: float


@dataclass(slots=True)
class PortfolioSummaryResult:
    """Aggregate result for ``get_summary``."""

    total_pnl: float
    total_trades: int
    overall_win_rate: float
    total_fees: float
    total_funding: float
    exchanges: list[ExchangeSummaryItem] = field(default_factory=list)


@dataclass(slots=True)
class PortfolioPositionItem:
    """A single enriched position returned by ``list_positions``.

    Fields line up 1:1 with the router's ``PortfolioPosition`` pydantic
    model so the router can project with a direct constructor call.
    """

    trade_id: Optional[int]
    exchange: str
    symbol: str
    side: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    leverage: int
    margin: float
    bot_name: Optional[str]
    demo_mode: bool
    take_profit: Optional[float]
    stop_loss: Optional[float]
    trailing_stop_active: bool
    trailing_stop_price: Optional[float]
    trailing_stop_distance_pct: Optional[float]
    trailing_atr_override: Optional[float]
    native_trailing_stop: bool
    can_close_at_loss: Optional[bool]


@dataclass(slots=True)
class PortfolioDailyItem:
    """One (date, exchange) bucket returned by ``get_daily``."""

    date: str
    exchange: str
    pnl: float
    trades: int
    fees: float


@dataclass(slots=True)
class PortfolioAllocationItem:
    """One per-exchange balance bucket returned by ``get_allocation``."""

    exchange: str
    balance: float
    currency: str


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PortfolioService:
    """Portfolio PnL, positions, daily timeseries, capital allocation.

    The service is FastAPI-free. The router owns rate limiting, the cache
    (TTL is module-scoped), and the pydantic response mapping. The service
    owns DB aggregation, live exchange calls, and trailing-stop enrichment.
    """

    def __init__(
        self,
        db: AsyncSession,
        user: User,
        clients_loader: Optional[ClientsLoader] = None,
    ) -> None:
        self.db = db
        self.user = user
        # ``clients_loader`` is injected by the router so tests can
        # monkeypatch the router-module attribute they always have.
        self._clients_loader = clients_loader

    # ---- /summary -------------------------------------------------------

    async def get_summary(
        self,
        days: int,
        demo_mode: Optional[str],
    ) -> PortfolioSummaryResult:
        """Aggregated PnL summary grouped by exchange.

        Behavior matches the pre-extract ``GET /api/portfolio/summary``
        handler exactly — same ``days``-window filter on closed-date, same
        demo-mode triage (``None`` / ``"all"`` → no filter, ``"true"`` /
        ``"false"`` → boolean), same zero-trade defaults.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        filters = [
            TradeRecord.user_id == self.user.id,
            TradeRecord.status == "closed",
            _closed_date >= since,
        ]
        if demo_mode and demo_mode != "all":
            filters.append(TradeRecord.demo_mode == (demo_mode == "true"))

        result = await self.db.execute(
            select(
                TradeRecord.exchange,
                func.count().label("total_trades"),
                func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("winning_trades"),
                func.sum(TradeRecord.pnl).label("total_pnl"),
                func.sum(TradeRecord.fees).label("total_fees"),
                func.sum(TradeRecord.funding_paid).label("total_funding"),
            )
            .where(*filters)
            .group_by(TradeRecord.exchange)
        )
        rows = result.all()

        exchanges: list[ExchangeSummaryItem] = []
        grand_pnl = 0.0
        grand_trades = 0
        grand_wins = 0
        grand_fees = 0.0
        grand_funding = 0.0

        for row in rows:
            total = row.total_trades or 0
            wins = row.winning_trades or 0
            pnl = row.total_pnl or 0
            fees = row.total_fees or 0
            funding = row.total_funding or 0

            exchanges.append(ExchangeSummaryItem(
                exchange=row.exchange,
                total_pnl=pnl,
                total_trades=total,
                winning_trades=wins,
                win_rate=(wins / total * 100) if total > 0 else 0,
                total_fees=fees,
                total_funding=funding,
            ))

            grand_pnl += pnl
            grand_trades += total
            grand_wins += wins
            grand_fees += fees
            grand_funding += funding

        return PortfolioSummaryResult(
            total_pnl=grand_pnl,
            total_trades=grand_trades,
            overall_win_rate=(grand_wins / grand_trades * 100) if grand_trades > 0 else 0,
            total_fees=grand_fees,
            total_funding=grand_funding,
            exchanges=exchanges,
        )

    # ---- /positions -----------------------------------------------------

    async def list_positions(self) -> list[PortfolioPositionItem]:
        """Fetch live open positions across all connected exchanges.

        The caller (router) handles TTL caching — this method always does
        the full computation. Returns an empty list if the user has no
        connected exchange credentials.
        """
        if self._clients_loader is None:
            return []
        clients = await self._clients_loader(self.user.id, self.db)
        if not clients:
            return []

        # Pre-load open trades with bot configs for trailing stop calculation
        open_trades_result = await self.db.execute(
            select(TradeRecord)
            .where(TradeRecord.user_id == self.user.id, TradeRecord.status == "open")
        )
        open_trades = open_trades_result.scalars().all()

        # Build lookup: (exchange, base_symbol, side, demo_mode) -> trade.
        # demo_mode is part of the key so a user running both a live and a demo
        # bot on the same symbol+side can see both positions independently — and
        # more importantly so a demo trade doesn't collide with a live one when
        # get_all_user_clients returns both modes for the same connection (#141).
        trade_lookup: dict[tuple, TradeRecord] = {}
        for t in open_trades:
            base_sym = normalize_symbol(t.symbol, t.exchange)
            key = (t.exchange, base_sym, t.side, bool(t.demo_mode))
            existing = trade_lookup.get(key)
            if existing is None or (t.entry_time and existing.entry_time and t.entry_time > existing.entry_time):
                trade_lookup[key] = t

        # Batch-load all referenced BotConfigs in a single query (fix N+1)
        bot_cache: dict[int, BotConfig] = {}
        bot_ids = {t.bot_config_id for t in open_trades if t.bot_config_id}
        if bot_ids:
            bot_result = await self.db.execute(
                select(BotConfig).where(BotConfig.id.in_(bot_ids))
            )
            for bot in bot_result.scalars().all():
                bot_cache[bot.id] = bot

        # Batch pre-fetch klines for trailing stop calculation (avoid N+1 Binance API calls).
        # Cache is keyed by (symbol, interval) because different bots may use
        # different kline_intervals (e.g. edge_indicator conservative uses 4h,
        # standard uses 1h, liquidation_hunter uses 1h). Using the resolved per-bot
        # interval guarantees the dashboard sees the same data as the live strategy.
        klines_cache: dict[tuple[str, str], list] = {}
        prefetch_keys: set[tuple[str, str]] = set()
        for t in open_trades:
            if t.status != "open":
                continue
            bot = bot_cache.get(t.bot_config_id) if t.bot_config_id else None
            strat_type = bot.strategy_type if bot else None
            has_strat_trailing = strat_type in TRAILING_STOP_STRATEGIES
            has_override = t.trailing_atr_override is not None
            if not has_strat_trailing and not has_override:
                continue
            strat_params_json = bot.strategy_params if bot else None
            resolved = resolve_strategy_params(strat_type, strat_params_json)
            interval = resolved.get("kline_interval", "1h")
            prefetch_keys.add((t.symbol, interval))

        if prefetch_keys:
            try:
                from src.data.market_data import MarketDataFetcher
                fetcher = MarketDataFetcher()
                for sym, interval in prefetch_keys:
                    try:
                        klines_cache[(sym, interval)] = await fetcher.get_binance_klines(sym, interval, 30)
                    except Exception:
                        pass
                await fetcher.close()
            except Exception:
                pass

        positions: list[PortfolioPositionItem] = []

        async def fetch_positions(exchange_type: str, demo_mode: bool, client):
            try:
                open_positions = await asyncio.wait_for(
                    client.get_open_positions(), timeout=10.0
                )
                for pos in open_positions:
                    # Match with DB trade including the client's mode so demo
                    # and live positions can coexist for the same symbol+side (#141)
                    base_sym = normalize_symbol(pos.symbol, exchange_type)
                    key = (exchange_type, base_sym, pos.side, demo_mode)
                    trade = trade_lookup.get(key)
                    if trade is None:
                        logger.debug(
                            "No DB trade match: exchange=%s demo=%s symbol=%s (base=%s) side=%s",
                            exchange_type, demo_mode, pos.symbol, base_sym, pos.side,
                        )
                    bot_name = None
                    ts_info: dict = {}
                    if trade:
                        bot = bot_cache.get(trade.bot_config_id) if trade.bot_config_id else None
                        bot_name = bot.name if bot else None
                        strat_type = bot.strategy_type if bot else None
                        strat_params = bot.strategy_params if bot else None
                        try:
                            ts_info = await _compute_trailing_stop(trade, strat_type, strat_params, klines_cache=klines_cache)
                        except Exception:
                            pass

                    positions.append(PortfolioPositionItem(
                        trade_id=trade.id if trade else None,
                        exchange=exchange_type,
                        symbol=pos.symbol,
                        side=pos.side,
                        size=pos.size,
                        entry_price=pos.entry_price,
                        current_price=pos.current_price,
                        unrealized_pnl=pos.unrealized_pnl,
                        leverage=pos.leverage,
                        margin=pos.margin,
                        bot_name=bot_name,
                        demo_mode=trade.demo_mode if trade else demo_mode,
                        take_profit=trade.take_profit if trade else None,
                        stop_loss=trade.stop_loss if trade else None,
                        trailing_stop_active=ts_info.get("trailing_stop_active", False),
                        trailing_stop_price=ts_info.get("trailing_stop_price"),
                        trailing_stop_distance_pct=ts_info.get("trailing_stop_distance_pct"),
                        trailing_atr_override=trade.trailing_atr_override if trade else None,
                        native_trailing_stop=trade.native_trailing_stop if trade else False,
                        can_close_at_loss=ts_info.get("can_close_at_loss"),
                    ))
            except asyncio.TimeoutError:
                logger.warning(
                    f"Position fetch timeout for {exchange_type} "
                    f"({'demo' if demo_mode else 'live'})"
                )
            except Exception as e:
                logger.warning(
                    f"Position fetch failed for {exchange_type} "
                    f"({'demo' if demo_mode else 'live'}): {e}"
                )

        await asyncio.gather(
            *(fetch_positions(ex, demo, cl) for ex, demo, cl in clients)
        )

        return positions

    # ---- /daily ---------------------------------------------------------

    async def get_daily(
        self,
        days: int,
        demo_mode: Optional[str],
    ) -> list[PortfolioDailyItem]:
        """Daily PnL breakdown per exchange for stacked charts.

        Behavior matches the pre-extract handler: same date-truncation on
        the ``_closed_date`` coalesce, same demo-mode triage, same output
        ordering (ascending by date).
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        filters = [
            TradeRecord.user_id == self.user.id,
            TradeRecord.status == "closed",
            _closed_date >= since,
        ]
        if demo_mode and demo_mode != "all":
            filters.append(TradeRecord.demo_mode == (demo_mode == "true"))

        result = await self.db.execute(
            select(
                func.date(_closed_date).label("date"),
                TradeRecord.exchange,
                func.sum(TradeRecord.pnl).label("pnl"),
                func.count().label("trades"),
                func.sum(TradeRecord.fees).label("fees"),
            )
            .where(*filters)
            .group_by(func.date(_closed_date), TradeRecord.exchange)
            .order_by(func.date(_closed_date))
        )

        return [
            PortfolioDailyItem(
                date=str(row.date),
                exchange=row.exchange,
                pnl=row.pnl or 0,
                trades=row.trades,
                fees=row.fees or 0,
            )
            for row in result.all()
        ]

    # ---- /allocation ----------------------------------------------------

    async def get_allocation(self) -> list[PortfolioAllocationItem]:
        """Balance distribution per exchange (for pie/donut chart).

        The caller (router) handles TTL caching. Returns an empty list if
        the user has no connected exchange credentials. One bucket PER
        exchange — prefers live client over demo so a user with both modes
        doesn't get their capital double-counted in the pie.
        """
        if self._clients_loader is None:
            return []
        clients = await self._clients_loader(self.user.id, self.db)
        if not clients:
            return []

        # For allocation we only want ONE balance per exchange — summing demo and
        # live would double-count, and the pie chart is a capital-distribution
        # view. Prefer the live client; fall back to demo if only demo exists.
        per_exchange: dict[str, tuple[bool, object]] = {}
        for exchange_type, demo_mode, client in clients:
            existing = per_exchange.get(exchange_type)
            if existing is None or (existing[0] and not demo_mode):
                per_exchange[exchange_type] = (demo_mode, client)

        allocations: list[PortfolioAllocationItem] = []

        async def fetch_balance(exchange_type: str, client):
            try:
                balance = await asyncio.wait_for(
                    client.get_account_balance(), timeout=10.0
                )
                allocations.append(PortfolioAllocationItem(
                    exchange=exchange_type,
                    balance=balance.total,
                    currency=balance.currency,
                ))
            except asyncio.TimeoutError:
                logger.warning(f"Balance fetch timeout for {exchange_type}")
            except Exception as e:
                logger.warning(f"Balance fetch failed for {exchange_type}: {e}")

        await asyncio.gather(
            *(fetch_balance(ex, client) for ex, (_demo, client) in per_exchange.items())
        )

        return allocations
