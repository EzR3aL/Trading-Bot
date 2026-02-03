"""Tax report endpoints (user-scoped)."""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.models.database import TradeRecord, User
from src.models.session import get_db

router = APIRouter(prefix="/api/tax-report", tags=["tax-report"])


@router.get("")
async def get_tax_report(
    year: int = Query(default=None, ge=2020, le=2030),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get tax report for a given year."""
    if year is None:
        year = datetime.utcnow().year

    result = await db.execute(
        select(TradeRecord)
        .where(
            TradeRecord.user_id == user.id,
            TradeRecord.status == "closed",
            TradeRecord.entry_time >= datetime(year, 1, 1),
            TradeRecord.entry_time < datetime(year + 1, 1, 1),
        )
        .order_by(TradeRecord.entry_time)
    )
    trades = result.scalars().all()

    total_pnl = sum(t.pnl or 0 for t in trades)
    total_fees = sum(t.fees or 0 for t in trades)
    total_funding = sum(t.funding_paid or 0 for t in trades)

    # Monthly breakdown
    months = {}
    for t in trades:
        month_key = t.entry_time.strftime("%Y-%m")
        if month_key not in months:
            months[month_key] = {"trades": 0, "pnl": 0, "fees": 0, "funding": 0}
        months[month_key]["trades"] += 1
        months[month_key]["pnl"] += t.pnl or 0
        months[month_key]["fees"] += t.fees or 0
        months[month_key]["funding"] += t.funding_paid or 0

    return {
        "year": year,
        "total_trades": len(trades),
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "total_funding": total_funding,
        "net_pnl": total_pnl - total_fees - abs(total_funding),
        "months": [
            {"month": k, **v}
            for k, v in sorted(months.items())
        ],
    }


@router.get("/csv")
async def download_tax_report_csv(
    year: int = Query(default=None, ge=2020, le=2030),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download tax report as CSV."""
    if year is None:
        year = datetime.utcnow().year

    result = await db.execute(
        select(TradeRecord)
        .where(
            TradeRecord.user_id == user.id,
            TradeRecord.status == "closed",
            TradeRecord.entry_time >= datetime(year, 1, 1),
            TradeRecord.entry_time < datetime(year + 1, 1, 1),
        )
        .order_by(TradeRecord.entry_time)
    )
    trades = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Symbol", "Side", "Size", "Entry Price", "Exit Price",
        "PnL (USDT)", "PnL %", "Fees", "Funding", "Net PnL", "Exchange",
    ])

    for t in trades:
        net = (t.pnl or 0) - (t.fees or 0) - abs(t.funding_paid or 0)
        writer.writerow([
            t.entry_time.strftime("%Y-%m-%d") if t.entry_time else "",
            t.symbol, t.side, t.size, t.entry_price, t.exit_price,
            f"{t.pnl:.2f}" if t.pnl else "0",
            f"{t.pnl_percent:.2f}" if t.pnl_percent else "0",
            f"{t.fees:.2f}" if t.fees else "0",
            f"{t.funding_paid:.2f}" if t.funding_paid else "0",
            f"{net:.2f}",
            t.exchange,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=tax_report_{year}.csv"},
    )
