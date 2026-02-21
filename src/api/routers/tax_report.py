"""Tax report endpoints (user-scoped)."""

import csv
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.models.database import TradeRecord, User
from src.models.session import get_db

router = APIRouter(prefix="/api/tax-report", tags=["tax-report"])


def _fmt(value: Optional[float], decimals: int = 2) -> str:
    """Format a float with fixed decimals, defaulting to '0.00'."""
    if value is None:
        return f"{0:.{decimals}f}"
    return f"{value:.{decimals}f}"


def _query_trades(user_id: int, year: int, demo_mode: Optional[bool]):
    """Build common trade query filters."""
    filters = [
        TradeRecord.user_id == user_id,
        TradeRecord.status == "closed",
        TradeRecord.entry_time >= datetime(year, 1, 1),
        TradeRecord.entry_time < datetime(year + 1, 1, 1),
    ]
    if demo_mode is not None:
        filters.append(TradeRecord.demo_mode == demo_mode)
    return select(TradeRecord).where(*filters).order_by(TradeRecord.entry_time)


@router.get("")
async def get_tax_report(
    year: int = Query(default=None, ge=2020, le=2030),
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get tax report for a given year."""
    if year is None:
        year = datetime.now(timezone.utc).year

    result = await db.execute(_query_trades(user.id, year, demo_mode))
    trades = result.scalars().all()

    total_pnl = sum(t.pnl or 0 for t in trades)
    total_fees = sum(t.fees or 0 for t in trades)
    total_funding = sum(t.funding_paid or 0 for t in trades)

    # Monthly breakdown
    months: dict = {}
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
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download tax report as CSV — German tax-compliant format with bilingual headers."""
    if year is None:
        year = datetime.now(timezone.utc).year

    result = await db.execute(_query_trades(user.id, year, demo_mode))
    trades = result.scalars().all()

    output = io.StringIO()
    # UTF-8 BOM so Excel on Windows recognises encoding
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    # ── Header section ──
    writer.writerow(["STEUERREPORT KRYPTOWAEHRUNGSHANDEL / TAX REPORT CRYPTOCURRENCY TRADING"])
    writer.writerow(["Berichtszeitraum / Reporting Period", f"{year}-01-01 bis/to {year}-12-31"])
    writer.writerow(["Erstellt am / Generated on", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")])
    mode_label = "Demo" if demo_mode is True else "Live" if demo_mode is False else "Alle/All"
    writer.writerow(["Modus / Mode", mode_label])
    writer.writerow([])

    # ── Disclaimer ──
    writer.writerow(["HINWEIS: Dieser Bericht dient nur zu Informationszwecken. "
                      "Konsultieren Sie einen Steuerberater fuer offizielle Steuererklaerungen."])
    writer.writerow(["NOTE: This report is for informational purposes only. "
                      "Consult a tax advisor for official tax declarations."])
    writer.writerow([])

    # ── Summary section ──
    total_pnl = sum(t.pnl or 0 for t in trades)
    total_fees = sum(t.fees or 0 for t in trades)
    total_funding = sum(abs(t.funding_paid or 0) for t in trades)
    total_builder = sum(t.builder_fee or 0 for t in trades)
    total_gains = sum(t.pnl for t in trades if t.pnl and t.pnl > 0)
    total_losses = sum(t.pnl for t in trades if t.pnl and t.pnl < 0)
    net_pnl = total_pnl - total_fees - total_funding - total_builder
    win_count = sum(1 for t in trades if t.pnl and t.pnl > 0)
    win_rate = (win_count / len(trades) * 100) if trades else 0.0

    writer.writerow(["ZUSAMMENFASSUNG / SUMMARY"])
    writer.writerow(["Metrik / Metric", "Wert / Value (USDT)"])
    writer.writerow(["Anzahl Trades / Trade Count", len(trades)])
    writer.writerow(["Gewinne / Total Gains", _fmt(total_gains)])
    writer.writerow(["Verluste / Total Losses", _fmt(total_losses)])
    writer.writerow(["Brutto PnL / Gross PnL", _fmt(total_pnl)])
    writer.writerow(["Gebuehren / Fees", _fmt(total_fees)])
    writer.writerow(["Finanzierungskosten / Funding Costs", _fmt(total_funding)])
    writer.writerow(["Builder Fee", _fmt(total_builder)])
    writer.writerow(["Netto PnL / Net PnL", _fmt(net_pnl)])
    writer.writerow(["Gewinnrate / Win Rate", f"{win_rate:.1f}%"])
    writer.writerow([])

    # ── Monthly breakdown ──
    months: dict = {}
    for t in trades:
        mk = t.entry_time.strftime("%Y-%m")
        if mk not in months:
            months[mk] = {"trades": 0, "pnl": 0.0, "fees": 0.0, "funding": 0.0, "builder": 0.0}
        months[mk]["trades"] += 1
        months[mk]["pnl"] += t.pnl or 0
        months[mk]["fees"] += t.fees or 0
        months[mk]["funding"] += abs(t.funding_paid or 0)
        months[mk]["builder"] += t.builder_fee or 0

    writer.writerow(["MONATLICHE AUFSCHLUESSELUNG / MONTHLY BREAKDOWN"])
    writer.writerow([
        "Monat / Month", "Trades", "PnL (USDT)",
        "Gebuehren / Fees", "Finanzierung / Funding",
        "Builder Fee", "Netto / Net",
    ])
    for mk in sorted(months.keys()):
        m = months[mk]
        if m["trades"] > 0:
            m_net = m["pnl"] - m["fees"] - m["funding"] - m["builder"]
            writer.writerow([
                mk, m["trades"], _fmt(m["pnl"]),
                _fmt(m["fees"]), _fmt(m["funding"]),
                _fmt(m["builder"]), _fmt(m_net),
            ])
    writer.writerow([])

    # ── Detailed trades ──
    writer.writerow(["EINZELTRANSAKTIONEN / DETAILED TRADES"])
    writer.writerow([
        "Einstieg / Entry Date",
        "Ausstieg / Exit Date",
        "Symbol",
        "Richtung / Side",
        "Hebel / Leverage",
        "Groesse / Size",
        "Einstiegspreis / Entry Price",
        "Ausstiegspreis / Exit Price",
        "PnL (USDT)",
        "PnL %",
        "Gebuehren / Fees",
        "Finanzierung / Funding",
        "Builder Fee",
        "Netto / Net PnL",
        "Haltedauer (h) / Duration (h)",
        "Schlussgrund / Exit Reason",
        "Boerse / Exchange",
    ])

    for t in trades:
        pnl = t.pnl or 0
        fees = t.fees or 0
        funding = abs(t.funding_paid or 0)
        builder = t.builder_fee or 0
        net = pnl - fees - funding - builder

        duration_h = ""
        if t.entry_time and t.exit_time:
            dur_sec = (t.exit_time - t.entry_time).total_seconds()
            duration_h = f"{dur_sec / 3600:.1f}"

        writer.writerow([
            t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "",
            t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "",
            t.symbol,
            (t.side or "").upper(),
            t.leverage or 1,
            _fmt(t.size, 6),
            _fmt(t.entry_price, 4),
            _fmt(t.exit_price, 4) if t.exit_price else "",
            _fmt(pnl),
            _fmt(t.pnl_percent),
            _fmt(fees),
            _fmt(funding),
            _fmt(builder),
            _fmt(net),
            duration_h,
            t.exit_reason or "",
            t.exchange or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="steuerreport_{year}.csv"'},
    )
