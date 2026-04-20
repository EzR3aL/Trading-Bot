"""Price-sanity audit (#216 S2.4): DB entry/exit_price vs Binance 1m klines.

For every trade closed in the last ``--hours`` window the script fetches
the 1-minute Binance kline at ``entry_time`` / ``exit_time`` and flags
deviations larger than ``PRICE_DEVIATION_THRESHOLD_PCT`` (2 %).

Typical causes: wrong parse of the close-fill price, DB pointing at the
wrong bar, or extreme slippage during a thin-book liquidation.

Read-only; ``--apply`` accepted for interface parity but never writes.
Run::  python scripts/audit_price_sanity.py [--hours 48] [--exchange X]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from sqlalchemy import select

from scripts._audit_common import (
    PRICE_DEVIATION_THRESHOLD_PCT,
    build_base_parser,
    confirm_apply,
    fmt_value,
    render_skip_error_blocks,
    render_summary_block,
    resolve_output_path,
    write_report,
)
from src.data.market_data import MarketDataFetcher
from src.models.database import TradeRecord
from src.models.session import get_session
from src.utils.logger import get_logger


logger = get_logger(__name__)

AUDIT_NAME = "audit-price-sanity"

# Binance returns klines as [open_time, open, high, low, close, volume, close_time, ...]
KLINE_OPEN_TIME_IDX = 0
KLINE_OPEN_IDX = 1
KLINE_CLOSE_IDX = 4


@dataclass
class PriceFinding:
    """One price deviation for a single closed trade."""
    trade_id: int
    user_id: int
    exchange: str
    symbol: str
    side: str
    kind: str  # "entry" | "exit"
    db_price: float
    kline_price: float
    deviation_pct: float
    candle_time: Optional[datetime]


@dataclass
class AuditReport:
    started_at: datetime
    hours: int
    apply_mode: bool
    user_id_filter: Optional[int]
    exchange_filter: Optional[str]
    checked: int = 0
    findings: list[PriceFinding] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_outcome(self) -> dict:
        keys = ("trade_id", "exchange", "symbol", "kind",
                "db_price", "kline_price", "deviation_pct")
        return {
            "audit": AUDIT_NAME,
            "started_at": self.started_at.isoformat(),
            "window_hours": self.hours,
            "checked": self.checked,
            "findings": [{k: getattr(f, k) for k in keys} for f in self.findings],
            "skipped": list(self.skipped),
            "errors": list(self.errors),
        }


async def select_recent_closed_trades(
    hours: int, user_id: Optional[int], exchange: Optional[str],
) -> list[TradeRecord]:
    """Load ``status='closed'`` trades whose ``exit_time`` falls in the window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with get_session() as session:
        stmt = (
            select(TradeRecord)
            .where(TradeRecord.status == "closed")
            .where(TradeRecord.exit_time.is_not(None))
            .where(TradeRecord.exit_time >= cutoff)
        )
        if user_id is not None:
            stmt = stmt.where(TradeRecord.user_id == user_id)
        if exchange is not None:
            stmt = stmt.where(TradeRecord.exchange == exchange)
        result = await session.execute(stmt.order_by(TradeRecord.id))
        trades = list(result.scalars().all())
        # Eager-load attrs we touch after session close.
        for t in trades:
            _ = (t.user_id, t.exchange, t.symbol, t.side,
                 t.entry_price, t.exit_price, t.entry_time, t.exit_time)
        return trades


def _normalize_binance_symbol(symbol: str) -> str:
    """Strip exchange-specific suffixes (e.g. BTCUSDT_UMCBL → BTCUSDT)."""
    for sep in ("_", "-", ":"):
        if sep in symbol:
            symbol = symbol.split(sep, 1)[0]
    return symbol.upper()


def _find_kline_at(klines: list[list], when: datetime) -> Optional[list]:
    """Return the kline whose open_time is closest to ``when``."""
    if not klines or when is None:
        return None
    target_ms = int(when.timestamp() * 1000)
    return min(
        (row for row in klines if row),
        key=lambda row: abs(int(row[KLINE_OPEN_TIME_IDX]) - target_ms),
        default=None,
    )


def _deviation_pct(db_price: float, kline_price: float) -> float:
    """Return ``(db - kline) / kline * 100``, guarding div-by-zero."""
    return 0.0 if kline_price == 0 else (db_price - kline_price) / kline_price * 100.0


def compare_prices(
    trade: TradeRecord,
    entry_kline: Optional[list],
    exit_kline: Optional[list],
) -> list[PriceFinding]:
    """Return any price deviation findings for one trade."""
    findings: list[PriceFinding] = []
    common = dict(
        trade_id=trade.id, user_id=trade.user_id, exchange=trade.exchange,
        symbol=trade.symbol, side=trade.side,
    )

    def _check(kline, price_attr: str, kline_idx: int, kind: str) -> None:
        price = getattr(trade, price_attr, None)
        if kline is None or not price:
            return
        kline_price = float(kline[kline_idx])
        dev = _deviation_pct(float(price), kline_price)
        if abs(dev) <= PRICE_DEVIATION_THRESHOLD_PCT:
            return
        candle_time = datetime.fromtimestamp(
            int(kline[KLINE_OPEN_TIME_IDX]) / 1000, tz=timezone.utc,
        )
        findings.append(PriceFinding(
            kind=kind, db_price=float(price), kline_price=kline_price,
            deviation_pct=dev, candle_time=candle_time, **common,
        ))

    _check(entry_kline, "entry_price", KLINE_OPEN_IDX, "entry")
    _check(exit_kline, "exit_price", KLINE_CLOSE_IDX, "exit")
    return findings


async def run_audit(
    *, hours: int, user_id: Optional[int], exchange: Optional[str],
    apply_mode: bool, output_path: Path,
    fetcher: Optional[MarketDataFetcher] = None,
) -> AuditReport:
    """Top-level orchestration: select trades, fetch klines, render report."""
    started_at = datetime.now(timezone.utc)
    report = AuditReport(
        started_at=started_at, hours=hours, apply_mode=apply_mode,
        user_id_filter=user_id, exchange_filter=exchange,
    )

    trades = await select_recent_closed_trades(
        hours=hours, user_id=user_id, exchange=exchange,
    )
    report.checked = len(trades)
    if not trades:
        write_report(render_report(report), output_path)
        return report

    own_fetcher = fetcher is None
    md = fetcher or MarketDataFetcher()
    try:
        for trade in trades:
            await _audit_one_trade(trade, md, report)
    finally:
        if own_fetcher:
            await md.close()

    write_report(render_report(report), output_path)
    logger.info(
        "audit_price_sanity.done checked=%s findings=%s skipped=%s errors=%s",
        report.checked, len(report.findings),
        len(report.skipped), len(report.errors),
    )
    return report


async def _audit_one_trade(
    trade: TradeRecord, fetcher: MarketDataFetcher, report: AuditReport,
) -> None:
    """Fetch klines for one trade and record any >threshold deviation."""
    symbol = _normalize_binance_symbol(trade.symbol)
    try:
        entry_kline = exit_kline = None
        if trade.entry_time:
            k = await fetcher.get_binance_klines(symbol, "1m", limit=60)
            entry_kline = _find_kline_at(k, trade.entry_time)
        if trade.exit_time:
            k = await fetcher.get_binance_klines(symbol, "1m", limit=60)
            exit_kline = _find_kline_at(k, trade.exit_time)
    except Exception as e:  # noqa: BLE001
        report.errors.append(f"trade={trade.id} {symbol}: {type(e).__name__}: {e}")
        return
    if entry_kline is None and exit_kline is None:
        report.skipped.append(f"trade={trade.id} {symbol} (no matching kline)")
        return
    report.findings.extend(compare_prices(trade, entry_kline, exit_kline))


def render_report(report: AuditReport) -> str:
    lines: list[str] = []
    render_summary_block(
        lines, "Price Sanity Audit", report.started_at,
        summary_items=[
            ("Fenster", f"letzte {report.hours} h"),
            ("Trades geprüft", report.checked),
            (
                f"Findings (> {PRICE_DEVIATION_THRESHOLD_PCT}% Abweichung)",
                len(report.findings),
            ),
            ("Übersprungen", len(report.skipped)),
            ("Fehler", len(report.errors)),
        ],
        user_id_filter=report.user_id_filter,
        exchange_filter=report.exchange_filter,
    )

    if report.findings:
        lines += [
            "## Findings", "",
            "| Trade | Exchange | Symbol | Kind | DB Price | Kline Price | Deviation | Candle |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for f in report.findings:
            lines.append(
                f"| #{f.trade_id} | {f.exchange} | {f.symbol} | {f.kind} "
                f"| {fmt_value(f.db_price)} | {fmt_value(f.kline_price)} "
                f"| {f.deviation_pct:+.3f}% | {fmt_value(f.candle_time)} |"
            )
        lines.append("")

    render_skip_error_blocks(lines, report.skipped, report.errors)
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = build_base_parser(
        description="Compare DB entry/exit_price against Binance 1m klines."
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="Lookback window in hours (default: 24).",
    )
    return parser.parse_args(argv)


async def main_async(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.apply and not args.yes and not confirm_apply():
        print("Aborted.")
        return 1

    output_path = resolve_output_path(
        AUDIT_NAME, args.output, datetime.now(timezone.utc),
    )
    report = await run_audit(
        hours=args.hours, user_id=args.user_id, exchange=args.exchange,
        apply_mode=args.apply, output_path=output_path,
    )
    print(f"Report written to {output_path}")
    print(
        f"Window={report.hours}h  Checked={report.checked}  "
        f"Findings={len(report.findings)}  Errors={len(report.errors)}"
    )
    return 0 if not report.errors else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
