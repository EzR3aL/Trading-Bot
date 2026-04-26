"""Read/query operations for :class:`TradesService`.

Houses ``list_trades``, ``get_trade`` and ``get_filter_options`` — the
read-only methods extracted from the original monolithic
``trades_service.py``.

Methods rely on ``self.db`` (an :class:`AsyncSession`) and ``self.user``
(a :class:`User`) — both supplied by the host class's constructor.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select

from src.models.database import BotConfig, TradeRecord
from src.services._trades_helpers import (
    TRAILING_STOP_STRATEGIES,
    _compute_trailing_stop,
)
from src.services.exceptions import TradeNotFound
from src.strategy.base import resolve_strategy_params
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ListMixin:
    """List, detail and filter-option queries for ``TradesService``."""

    # ---- list ------------------------------------------------------------

    async def list_trades(self, filters, pagination):
        """Return a paginated + filtered list of the user's trades.

        Behavior matches the pre-extract ``GET /api/trades`` handler exactly,
        including the ilike escape on ``symbol`` and the date-range inclusivity
        rules (``entry_time >= date_from`` and ``entry_time < date_to+1d``).
        """
        # Imported lazily so the result dataclasses live in trades_service.py
        # (where every external caller still imports them from).
        from src.data.market_data import MarketDataFetcher
        from src.services.trades_service import (
            TradeListItem,
            TradeListResult,
        )

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

    async def get_filter_options(self):
        """Return distinct filter values available for the user's trades.

        Uses ``SELECT DISTINCT`` / grouped queries so the backend never pulls
        full trade rows just to populate a dropdown. Scope is restricted to
        the current user (same ownership filter as ``GET /api/trades``).
        """
        from src.services.trades_service import (
            FilterBotOption,
            FilterOptionsResult,
        )

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

    async def get_trade(self, trade_id: int):
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
        from src.services.trades_service import TradeDetail

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
