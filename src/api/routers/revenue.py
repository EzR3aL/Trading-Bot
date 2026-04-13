"""Admin revenue tracking endpoints (manual entries + auto builder fees)."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.schemas.revenue import (
    RevenueEntryCreate,
    RevenueEntryResponse,
    RevenueEntryUpdate,
)
from src.auth.dependencies import get_current_admin
from src.models.database import ExchangeConnection, RevenueEntry, TradeRecord, User
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


def _entry_to_response(entry: RevenueEntry) -> dict:
    """Convert DB model to frontend-compatible dict."""
    return {
        "id": entry.id,
        "date": entry.date,
        "exchange": entry.exchange,
        "type": entry.revenue_type,
        "amount": entry.amount_usd,
        "source": entry.source,
        "notes": entry.notes,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


# ---------------------------------------------------------------------------
# GET /api/admin/revenue — aggregated revenue overview
# ---------------------------------------------------------------------------


@router.get("")
@limiter.limit("30/minute")
async def get_revenue(
    request: Request,
    period: Literal["7d", "30d", "90d", "1y"] = Query("30d"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated revenue from manual entries and Hyperliquid builder fees."""
    days = _PERIOD_DAYS[period]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    today = date.today()
    seven_days_ago = today - timedelta(days=7)
    thirty_days_ago = today - timedelta(days=30)

    # --- 1. Manual revenue entries (exclude hyperliquid builder_fee to avoid double-counting) ---
    manual_rows = await db.execute(
        select(
            RevenueEntry.exchange,
            RevenueEntry.revenue_type,
            func.date(RevenueEntry.date).label("day"),
            func.sum(RevenueEntry.amount_usd).label("amount"),
            func.count().label("cnt"),
        )
        .where(
            RevenueEntry.date >= since.date(),
            # Hyperliquid builder fees are aggregated from trade_records (section 2),
            # so exclude them here to prevent double-counting.
            ~((RevenueEntry.exchange == "hyperliquid") & (RevenueEntry.revenue_type == "builder_fee")),
        )
        .group_by(RevenueEntry.exchange, RevenueEntry.revenue_type, func.date(RevenueEntry.date))
        .order_by(func.date(RevenueEntry.date))
    )
    manual_data = manual_rows.all()

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

    # --- 3. All manual entries (for the table) ---
    entries_result = await db.execute(
        select(RevenueEntry)
        .where(RevenueEntry.date >= since.date())
        .order_by(RevenueEntry.date.desc())
    )
    all_entries = entries_result.scalars().all()

    # --- 4. Merge into unified response ---

    # by_exchange: key = (exchange, revenue_type)
    exchange_agg: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"total": 0.0, "count": 0}
    )
    # daily: key = date string -> {exchange: amount}
    daily_map: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    # summary accumulators
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

    # Process manual entries
    for row in manual_data:
        _accumulate(
            row.exchange, row.revenue_type,
            _to_date(row.day), float(row.amount or 0), row.cnt or 0,
        )

    # Process builder fee data
    for row in builder_data:
        _accumulate(
            "hyperliquid", "builder_fee",
            _to_date(row.day), float(row.amount or 0), row.cnt or 0,
        )

    # Build response
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

    entries = [_entry_to_response(e) for e in all_entries]

    # --- 5. Affiliate signup counts per exchange ---
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

    return {
        "summary": {
            "today": round(sum_today, 2),
            "last_7d": round(sum_7d, 2),
            "last_30d": round(sum_30d, 2),
            "total": round(sum_total, 2),
        },
        "by_exchange": by_exchange,
        "daily": daily,
        "entries": entries,
        "signups": {
            "total": total_signups,
            "by_exchange": signups_by_exchange,
        },
    }


# ---------------------------------------------------------------------------
# POST /api/admin/revenue — create manual revenue entry
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
@limiter.limit("10/minute")
async def create_revenue_entry(
    request: Request,
    data: RevenueEntryCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a manual revenue entry."""
    rev_type = data.revenue_type or data.type
    if not rev_type:
        raise HTTPException(status_code=400, detail="revenue_type oder type ist erforderlich")

    entry = RevenueEntry(
        date=data.date,
        exchange=data.exchange.lower(),
        revenue_type=rev_type.lower(),
        amount_usd=data.amount_usd,
        source="manual",
        notes=data.notes,
    )
    db.add(entry)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ein Eintrag für diesen Tag, Exchange und Typ existiert bereits",
        )
    return _entry_to_response(entry)


# ---------------------------------------------------------------------------
# PUT /api/admin/revenue/{id} — update manual revenue entry
# ---------------------------------------------------------------------------


@router.put("/{entry_id}")
@limiter.limit("10/minute")
async def update_revenue_entry(
    request: Request,
    entry_id: int,
    data: RevenueEntryUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing manual revenue entry. Auto entries cannot be edited."""
    result = await db.execute(
        select(RevenueEntry).where(RevenueEntry.id == entry_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Einnahme-Eintrag nicht gefunden")

    if entry.source == "auto":
        raise HTTPException(
            status_code=400,
            detail="Automatische Einträge können nicht bearbeitet werden",
        )

    if data.date is not None:
        entry.date = data.date
    if data.exchange is not None:
        entry.exchange = data.exchange.lower()
    rev_type = data.revenue_type or data.type
    if rev_type is not None:
        entry.revenue_type = rev_type.lower()
    if data.amount_usd is not None:
        entry.amount_usd = data.amount_usd
    if data.notes is not None:
        entry.notes = data.notes

    await db.flush()
    return _entry_to_response(entry)


# ---------------------------------------------------------------------------
# DELETE /api/admin/revenue/{id} — delete manual revenue entry
# ---------------------------------------------------------------------------


@router.delete("/{entry_id}")
@limiter.limit("10/minute")
async def delete_revenue_entry(
    request: Request,
    entry_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a manual revenue entry. Auto entries cannot be deleted."""
    result = await db.execute(
        select(RevenueEntry).where(RevenueEntry.id == entry_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Einnahme-Eintrag nicht gefunden")

    if entry.source == "auto":
        raise HTTPException(
            status_code=400,
            detail="Automatische Einträge können nicht gelöscht werden",
        )

    await db.delete(entry)
    return {"detail": "deleted"}
