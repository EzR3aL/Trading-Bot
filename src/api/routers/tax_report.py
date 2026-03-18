"""Tax report endpoints (user-scoped)."""

import csv
import io
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.models.database import TradeRecord, User
from src.models.session import get_db


def _resolve_tz(tz_name: Optional[str]) -> ZoneInfo:
    """Resolve an IANA timezone name to a ZoneInfo object, falling back to UTC."""
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")


def _fmt_dt(dt: Optional[datetime], tz: ZoneInfo) -> str:
    """Format a datetime in ISO format (YYYY-MM-DD HH:MM) for English CSV export."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _fmt_dt_de(dt: Optional[datetime], tz: ZoneInfo) -> str:
    """Format a datetime in German format (DD.MM.YYYY HH:MM) for German CSV export."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%d.%m.%Y %H:%M")

router = APIRouter(prefix="/api/tax-report", tags=["tax-report"])


def _fmt(value: Optional[float], decimals: int = 2, de: bool = False) -> str:
    """Format a float with fixed decimals. German uses comma as decimal separator."""
    if value is None:
        value = 0
    result = f"{value:.{decimals}f}"
    if de:
        result = result.replace(".", ",")
    return result


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
    tz: Optional[str] = Query(None, description="IANA timezone, e.g. Europe/Berlin"),
    lang: str = Query("de", description="Language: 'de' or 'en'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download tax report as CSV — localized format (German or English)."""
    if year is None:
        year = datetime.now(timezone.utc).year
    user_tz = _resolve_tz(tz)
    tz_label = str(user_tz)
    de = lang.startswith("de")

    result = await db.execute(_query_trades(user.id, year, demo_mode))
    trades = result.scalars().all()

    output = io.StringIO()
    # UTF-8 BOM so Excel on Windows recognises encoding
    output.write("\ufeff")
    # German uses semicolon delimiter (Excel-compatible), English uses comma
    delimiter = ";" if de else ","
    writer = csv.writer(output, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)

    # ── Header section ──
    if de:
        writer.writerow(["STEUERREPORT KRYPTOWAEHRUNGSHANDEL"])
        writer.writerow(["Berichtszeitraum", f"{year}-01-01 bis {year}-12-31"])
        writer.writerow(["Erstellt am", datetime.now(timezone.utc).astimezone(user_tz).strftime(f"%d.%m.%Y %H:%M ({tz_label})")])
        mode_label = "Demo" if demo_mode is True else "Live" if demo_mode is False else "Alle"
        writer.writerow(["Modus", mode_label])
    else:
        writer.writerow(["TAX REPORT CRYPTOCURRENCY TRADING"])
        writer.writerow(["Reporting Period", f"{year}-01-01 to {year}-12-31"])
        writer.writerow(["Generated on", datetime.now(timezone.utc).astimezone(user_tz).strftime(f"%Y-%m-%d %H:%M ({tz_label})")])
        mode_label = "Demo" if demo_mode is True else "Live" if demo_mode is False else "All"
        writer.writerow(["Mode", mode_label])
    writer.writerow([])

    # ── Disclaimer ──
    if de:
        writer.writerow(["HINWEIS: Dieser Bericht dient nur zu Informationszwecken. "
                          "Konsultieren Sie einen Steuerberater fuer offizielle Steuererklaerungen."])
    else:
        writer.writerow(["NOTE: This report is for informational purposes only. "
                          "Consult a tax advisor for official tax declarations."])
    writer.writerow([])

    # ── Summary section ──
    total_pnl = sum(t.pnl or 0 for t in trades)
    total_fees = sum(t.fees or 0 for t in trades)
    total_funding = sum(abs(t.funding_paid or 0) for t in trades)
    total_gains = sum(t.pnl for t in trades if t.pnl and t.pnl > 0)
    total_losses = sum(t.pnl for t in trades if t.pnl and t.pnl < 0)
    net_pnl = total_pnl - total_fees - total_funding
    win_count = sum(1 for t in trades if t.pnl and t.pnl > 0)
    win_rate = (win_count / len(trades) * 100) if trades else 0.0
    f = lambda v, d=2: _fmt(v, d, de)

    if de:
        writer.writerow(["ZUSAMMENFASSUNG"])
        writer.writerow(["Metrik", "Wert (USDT)"])
        writer.writerow(["Anzahl Trades", len(trades)])
        writer.writerow(["Gewinne", f(total_gains)])
        writer.writerow(["Verluste", f(total_losses)])
        writer.writerow(["Brutto PnL", f(total_pnl)])
        writer.writerow(["Gebuehren", f(total_fees)])
        writer.writerow(["Finanzierungskosten", f(total_funding)])
        writer.writerow(["Netto PnL", f(net_pnl)])
        writer.writerow(["Gewinnrate", f"{win_rate:.1f}%".replace(".", ",")])
    else:
        writer.writerow(["SUMMARY"])
        writer.writerow(["Metric", "Value (USDT)"])
        writer.writerow(["Trade Count", len(trades)])
        writer.writerow(["Total Gains", f(total_gains)])
        writer.writerow(["Total Losses", f(total_losses)])
        writer.writerow(["Gross PnL", f(total_pnl)])
        writer.writerow(["Fees", f(total_fees)])
        writer.writerow(["Funding Costs", f(total_funding)])
        writer.writerow(["Net PnL", f(net_pnl)])
        writer.writerow(["Win Rate", f"{win_rate:.1f}%"])
    writer.writerow([])

    # ── Monthly breakdown ──
    months: dict = {}
    for t in trades:
        mk = t.entry_time.strftime("%Y-%m")
        if mk not in months:
            months[mk] = {"trades": 0, "pnl": 0.0, "fees": 0.0, "funding": 0.0}
        months[mk]["trades"] += 1
        months[mk]["pnl"] += t.pnl or 0
        months[mk]["fees"] += t.fees or 0
        months[mk]["funding"] += abs(t.funding_paid or 0)

    if de:
        writer.writerow(["MONATLICHE AUFSCHLUESSELUNG"])
        writer.writerow(["Monat", "Trades", "PnL (USDT)", "Gebuehren", "Finanzierung", "Netto"])
    else:
        writer.writerow(["MONTHLY BREAKDOWN"])
        writer.writerow(["Month", "Trades", "PnL (USDT)", "Fees", "Funding", "Net"])
    for mk in sorted(months.keys()):
        m = months[mk]
        if m["trades"] > 0:
            m_net = m["pnl"] - m["fees"] - m["funding"]
            writer.writerow([
                mk, m["trades"], f(m["pnl"]),
                f(m["fees"]), f(m["funding"]), f(m_net),
            ])
    writer.writerow([])

    # ── Detailed trades ──
    if de:
        writer.writerow(["EINZELTRANSAKTIONEN"])
        writer.writerow(["Zeitzone", tz_label])
        writer.writerow([
            "Einstieg", "Ausstieg", "Symbol", "Richtung", "Hebel",
            "Groesse", "Einstiegspreis", "Ausstiegspreis",
            "PnL (USDT)", "PnL %", "Gebuehren", "Finanzierung",
            "Netto PnL", "Haltedauer (h)", "Schlussgrund", "Boerse",
        ])
    else:
        writer.writerow(["DETAILED TRADES"])
        writer.writerow(["Timezone", tz_label])
        writer.writerow([
            "Entry Date", "Exit Date", "Symbol", "Side", "Leverage",
            "Size", "Entry Price", "Exit Price",
            "PnL (USDT)", "PnL %", "Fees", "Funding",
            "Net PnL", "Duration (h)", "Exit Reason", "Exchange",
        ])

    for t in trades:
        pnl = t.pnl or 0
        fees = t.fees or 0
        funding = abs(t.funding_paid or 0)
        net = pnl - fees - funding

        duration_h = ""
        if t.entry_time and t.exit_time:
            dur_sec = (t.exit_time - t.entry_time).total_seconds()
            duration_h = f"{dur_sec / 3600:.1f}"
            if de:
                duration_h = duration_h.replace(".", ",")

        entry_dt = _fmt_dt_de(t.entry_time, user_tz) if de else _fmt_dt(t.entry_time, user_tz)
        exit_dt = _fmt_dt_de(t.exit_time, user_tz) if de else _fmt_dt(t.exit_time, user_tz)

        writer.writerow([
            entry_dt,
            exit_dt,
            t.symbol,
            (t.side or "").upper(),
            t.leverage or 1,
            f(t.size, 6),
            f(t.entry_price, 4),
            f(t.exit_price, 4) if t.exit_price else "",
            f(pnl),
            f(t.pnl_percent),
            f(fees),
            f(funding),
            f(net),
            duration_h,
            t.exit_reason or "",
            t.exchange or "",
        ])

    filename = f"steuerreport_{year}.csv" if de else f"tax_report_{year}.csv"
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
