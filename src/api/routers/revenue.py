"""Admin revenue tracking — fully automated via affiliate fetcher.

Manual entry endpoints have been removed. All revenue is pulled from
exchange APIs every 6h by `affiliate_revenue_fetcher`. Bitunix has no
public API and is reported as 'unsupported'.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.auth.dependencies import get_current_admin
from src.models.database import (
    AffiliateState,
    ExchangeConnection,
    RevenueEntry,
    TradeRecord,
    User,
)
from src.models.session import get_db

router = APIRouter(prefix="/api/admin/revenue", tags=["revenue"])

_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}

# Fallback to entry_time when exit_time is NULL
_closed_date = func.coalesce(TradeRecord.exit_time, TradeRecord.entry_time)


def _to_date(val) -> date:
    """Coerce a date-like value to a Python date."""
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    return date.fromisoformat(str(val))


@router.get("")
@limiter.limit("30/minute")
async def get_revenue(
    request: Request,
    period: Literal["7d", "30d", "90d", "1y"] = Query("30d"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated affiliate revenue across all exchanges + per-tile sync status."""
    days = _PERIOD_DAYS[period]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    today = date.today()
    seven_days_ago = today - timedelta(days=7)
    thirty_days_ago = today - timedelta(days=30)

    # --- 1. Auto-imported affiliate/referral revenue (exclude HL builder_fee
    #        to avoid double-counting with the trade-derived sum below) ---
    auto_rows = await db.execute(
        select(
            RevenueEntry.exchange,
            RevenueEntry.revenue_type,
            func.date(RevenueEntry.date).label("day"),
            func.sum(RevenueEntry.amount_usd).label("amount"),
            func.count().label("cnt"),
        )
        .where(
            RevenueEntry.date >= since.date(),
            ~((RevenueEntry.exchange == "hyperliquid") & (RevenueEntry.revenue_type == "builder_fee")),
        )
        .group_by(RevenueEntry.exchange, RevenueEntry.revenue_type, func.date(RevenueEntry.date))
        .order_by(func.date(RevenueEntry.date))
    )
    auto_data = auto_rows.all()

    # --- 2. Hyperliquid builder fees (auto from trade_records) ---
    builder_rows = await db.execute(
        select(
            func.date(_closed_date).label("day"),
            func.sum(TradeRecord.builder_fee).label("amount"),
            func.count().label("cnt"),
        )
        .where(
            TradeRecord.exchange == "hyperliquid",
            TradeRecord.status == "closed",
            _closed_date >= since,
            TradeRecord.builder_fee > 0,
        )
        .group_by(func.date(_closed_date))
        .order_by(func.date(_closed_date))
    )
    builder_data = builder_rows.all()

    # --- 3. Aggregation ---
    exchange_agg: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"total": 0.0, "count": 0}
    )
    daily_map: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sum_today = 0.0
    sum_7d = 0.0
    sum_30d = 0.0
    sum_total = 0.0

    def _accumulate(exchange: str, rev_type: str, row_date: date, amount: float, count: int):
        nonlocal sum_today, sum_7d, sum_30d, sum_total
        key = (exchange, rev_type)
        exchange_agg[key]["total"] += amount
        exchange_agg[key]["count"] += count
        daily_map[str(row_date)][exchange] += amount
        sum_total += amount
        if row_date == today:
            sum_today += amount
        if row_date >= seven_days_ago:
            sum_7d += amount
        if row_date >= thirty_days_ago:
            sum_30d += amount

    for row in auto_data:
        _accumulate(
            row.exchange, row.revenue_type,
            _to_date(row.day), float(row.amount or 0), row.cnt or 0,
        )
    for row in builder_data:
        _accumulate(
            "hyperliquid", "builder_fee",
            _to_date(row.day), float(row.amount or 0), row.cnt or 0,
        )

    by_exchange = [
        {
            "exchange": ex,
            "type": rt,
            "total": round(totals["total"], 2),
            "count": totals["count"],
        }
        for (ex, rt), totals in sorted(exchange_agg.items())
    ]

    daily = [
        {
            "date": d,
            "total": round(sum(amounts.values()), 2),
            "by_exchange": {k: round(v, 2) for k, v in amounts.items()},
        }
        for d, amounts in sorted(daily_map.items())
    ]

    # --- 4. Affiliate signup counts per exchange ---
    signup_rows = await db.execute(
        select(
            ExchangeConnection.exchange_type,
            func.count().label("cnt"),
        )
        .where(
            (ExchangeConnection.affiliate_verified == True)  # noqa: E712
            | (ExchangeConnection.referral_verified == True)  # noqa: E712
        )
        .group_by(ExchangeConnection.exchange_type)
    )
    signups_by_exchange = {row.exchange_type: row.cnt for row in signup_rows.all()}
    total_signups = sum(signups_by_exchange.values())

    # --- 5. Per-exchange fetcher status ---
    state_rows = (await db.execute(select(AffiliateState))).scalars().all()
    sync_status = {
        s.exchange: {
            "status": s.last_status,  # ok | error | unsupported | not_configured | None
            "last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None,
            "error": s.last_error,
        }
        for s in state_rows
    }

    return {
        "summary": {
            "today": round(sum_today, 2),
            "last_7d": round(sum_7d, 2),
            "last_30d": round(sum_30d, 2),
            "total": round(sum_total, 2),
        },
        "by_exchange": by_exchange,
        "daily": daily,
        "signups": {
            "total": total_signups,
            "by_exchange": signups_by_exchange,
        },
        "sync_status": sync_status,
    }


@router.post("/sync", status_code=202)
@limiter.limit("3/minute")
async def trigger_sync(
    request: Request,
    admin: User = Depends(get_current_admin),
):
    """Manually trigger an affiliate fetch run (otherwise: every 6h)."""
    from src.services.affiliate_revenue_fetcher import run_affiliate_fetch
    summary = await run_affiliate_fetch()
    return {"detail": "synced", "summary": summary}
