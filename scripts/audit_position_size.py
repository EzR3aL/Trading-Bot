"""Position-size audit (#216 S2.4): DB ``trade.size`` vs live position.

For every open trade the script calls ``client.get_position(symbol)`` and
classifies the delta between ``trade.size`` and ``position.size``:

* ``rounded`` — |delta| <= ``SIZE_TOLERANCE_PCT`` (expected contract rounding)
* ``desync``  — |delta| >  ``SIZE_TOLERANCE_PCT`` (actionable drift)
* ``missing`` — exchange has no position for this trade (possibly closed)

Read-only; ``--apply`` is accepted for interface parity but never writes.
Run::  python scripts/audit_position_size.py [--user-id N] [--exchange X]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from scripts._audit_common import (
    SIZE_TOLERANCE_PCT,
    ConnectionBackedClientFactory,
    build_base_parser,
    confirm_apply,
    fmt_value,
    render_skip_error_blocks,
    render_summary_block,
    resolve_output_path,
    select_open_trades,
    write_report,
)
from src.models.database import TradeRecord
from src.utils.logger import get_logger


logger = get_logger(__name__)

AUDIT_NAME = "audit-position-size"


@dataclass
class SizeFinding:
    """One size-drift finding for a single open trade."""
    trade_id: int
    user_id: int
    exchange: str
    symbol: str
    side: str
    demo_mode: bool
    db_size: float
    exchange_size: Optional[float]
    delta_pct: Optional[float]
    severity: str  # "rounded" | "desync" | "missing"


@dataclass
class AuditReport:
    started_at: datetime
    apply_mode: bool
    user_id_filter: Optional[int]
    exchange_filter: Optional[str]
    checked: int = 0
    findings: list[SizeFinding] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def desync_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "desync")

    @property
    def rounded_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "rounded")

    @property
    def missing_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "missing")

    def as_outcome(self) -> dict:
        return {
            "audit": AUDIT_NAME,
            "started_at": self.started_at.isoformat(),
            "checked": self.checked,
            "desync": self.desync_count,
            "rounded": self.rounded_count,
            "missing": self.missing_count,
            "findings": [
                {
                    "trade_id": f.trade_id,
                    "exchange": f.exchange,
                    "symbol": f.symbol,
                    "severity": f.severity,
                    "db_size": f.db_size,
                    "exchange_size": f.exchange_size,
                    "delta_pct": f.delta_pct,
                }
                for f in self.findings
            ],
            "skipped": list(self.skipped),
            "errors": list(self.errors),
        }


def classify_size_drift(
    trade: TradeRecord, exchange_size: Optional[float],
) -> SizeFinding:
    """Return a ``SizeFinding`` describing how exchange_size relates to DB."""
    db_size = float(trade.size or 0)
    common = dict(
        trade_id=trade.id, user_id=trade.user_id, exchange=trade.exchange,
        symbol=trade.symbol, side=trade.side, demo_mode=bool(trade.demo_mode),
        db_size=db_size,
    )
    if exchange_size is None:
        return SizeFinding(exchange_size=None, delta_pct=None,
                           severity="missing", **common)

    # Degenerate DB row (size=0) — treat any live position as desync.
    if db_size == 0:
        delta_pct = 100.0 if exchange_size else 0.0
    else:
        delta_pct = (exchange_size - db_size) / db_size * 100.0
    severity = "desync" if abs(delta_pct) > SIZE_TOLERANCE_PCT else "rounded"
    return SizeFinding(
        exchange_size=float(exchange_size), delta_pct=delta_pct,
        severity=severity, **common,
    )


async def run_audit(
    *,
    user_id: Optional[int],
    exchange: Optional[str],
    apply_mode: bool,
    output_path: Path,
    factory: Optional[ConnectionBackedClientFactory] = None,
) -> AuditReport:
    """Top-level orchestration: select trades, probe, render report."""
    started_at = datetime.now(timezone.utc)
    report = AuditReport(
        started_at=started_at,
        apply_mode=apply_mode,
        user_id_filter=user_id,
        exchange_filter=exchange,
    )

    trades = await select_open_trades(
        user_id=user_id, exchange=exchange, attrs=("size",),
    )
    report.checked = len(trades)
    if not trades:
        write_report(render_report(report), output_path)
        return report

    client_factory = factory or ConnectionBackedClientFactory()
    try:
        for trade in trades:
            await _audit_one_trade(trade, client_factory, report)
    finally:
        if factory is None:
            await client_factory.close_all()

    write_report(render_report(report), output_path)
    logger.info(
        "audit_position_size.done checked=%s desync=%s rounded=%s missing=%s",
        report.checked, report.desync_count,
        report.rounded_count, report.missing_count,
    )
    return report


async def _audit_one_trade(
    trade: TradeRecord,
    factory: ConnectionBackedClientFactory,
    report: AuditReport,
) -> None:
    try:
        client = await factory(trade.user_id, trade.exchange, bool(trade.demo_mode))
        position = await client.get_position(trade.symbol)
    except NotImplementedError:
        report.skipped.append(
            f"trade={trade.id} exchange={trade.exchange} (no get_position)"
        )
        return
    except Exception as e:  # noqa: BLE001
        report.errors.append(f"trade={trade.id}: {type(e).__name__}: {e}")
        return

    exchange_size = float(position.size) if position is not None else None
    finding = classify_size_drift(trade, exchange_size)
    # Only record findings that are actionable — silent "rounded" matches
    # get skipped unless debugging. The scheduler alerts on desync only.
    if finding.severity in ("desync", "missing"):
        report.findings.append(finding)
    elif abs(finding.delta_pct or 0.0) > 0.0:
        # Keep rounded deltas in the report for transparency.
        report.findings.append(finding)


def render_report(report: AuditReport) -> str:
    lines: list[str] = []
    render_summary_block(
        lines, "Position-Size Audit", report.started_at,
        summary_items=[
            ("Trades geprüft", report.checked),
            (f"Desync (> {SIZE_TOLERANCE_PCT}%)", report.desync_count),
            (f"Rounded (<= {SIZE_TOLERANCE_PCT}%)", report.rounded_count),
            ("Missing (keine Exchange-Position)", report.missing_count),
            ("Übersprungen", len(report.skipped)),
            ("Fehler", len(report.errors)),
        ],
        user_id_filter=report.user_id_filter,
        exchange_filter=report.exchange_filter,
    )

    if report.findings:
        lines.append("## Findings")
        lines.append("")
        lines.append("| Trade | Exchange | Symbol | Severity | DB Size | Exchange Size | Delta % |")
        lines.append("|---|---|---|---|---|---|---|")
        for f in report.findings:
            delta = f"{f.delta_pct:+.3f}%" if f.delta_pct is not None else "n/a"
            lines.append(
                f"| #{f.trade_id} | {f.exchange} | {f.symbol} | {f.severity} "
                f"| {fmt_value(f.db_size)} | {fmt_value(f.exchange_size)} | {delta} |"
            )
        lines.append("")

    render_skip_error_blocks(lines, report.skipped, report.errors)
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = build_base_parser(
        description="Compare DB trade.size with live exchange position.contracts."
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
        user_id=args.user_id, exchange=args.exchange,
        apply_mode=args.apply, output_path=output_path,
    )
    print(f"Report written to {output_path}")
    print(
        f"Checked={report.checked}  Desync={report.desync_count}  "
        f"Rounded={report.rounded_count}  Missing={report.missing_count}"
    )
    return 0 if not report.errors else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
