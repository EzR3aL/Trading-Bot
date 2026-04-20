"""TP/SL flag audit (#216 S2.4): DB plan presence vs. exchange reality.

For every open trade the script calls ``client.get_position_tpsl(symbol,
side)`` and compares the returned snapshot to DB's ``take_profit`` /
``stop_loss`` + ``tp_order_id`` / ``sl_order_id`` columns.

Kinds: ``db_only_tp`` | ``exchange_only_tp`` | ``db_only_sl`` |
``exchange_only_sl``. Read-only — use ``reconcile_open_trades.py --apply``
to heal findings.

Run::  python scripts/audit_tp_sl_flags.py [--user-id N] [--exchange bitget]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Container layout fallback so the script runs via
#   docker exec bitget-trading-bot python /app/scripts/audit_tp_sl_flags.py
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from scripts._audit_common import (
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

AUDIT_NAME = "audit-tp-sl-flags"


@dataclass
class FlagMismatch:
    """One TP/SL inconsistency for a single open trade."""
    trade_id: int
    user_id: int
    exchange: str
    symbol: str
    side: str
    demo_mode: bool
    kind: str          # "db_only_tp" | "exchange_only_tp" | "db_only_sl" | "exchange_only_sl"
    db_value: Optional[float]
    exchange_value: Optional[float]


@dataclass
class AuditReport:
    """Aggregate result of one sweep."""
    started_at: datetime
    apply_mode: bool
    user_id_filter: Optional[int]
    exchange_filter: Optional[str]
    checked: int = 0
    mismatches: list[FlagMismatch] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_outcome(self) -> dict:
        """Return a JSON-safe summary used by the scheduler + tests."""
        return {
            "audit": AUDIT_NAME,
            "started_at": self.started_at.isoformat(),
            "checked": self.checked,
            "mismatches": [
                {
                    "trade_id": m.trade_id,
                    "exchange": m.exchange,
                    "symbol": m.symbol,
                    "kind": m.kind,
                    "db_value": m.db_value,
                    "exchange_value": m.exchange_value,
                }
                for m in self.mismatches
            ],
            "skipped": list(self.skipped),
            "errors": list(self.errors),
        }


def compare_tp_sl(trade: TradeRecord, snapshot) -> list[FlagMismatch]:
    """Return mismatches between DB TP/SL fields and exchange snapshot."""
    def _mm(kind: str, db_value, exch_value) -> FlagMismatch:
        return FlagMismatch(
            trade_id=trade.id, user_id=trade.user_id, exchange=trade.exchange,
            symbol=trade.symbol, side=trade.side, demo_mode=bool(trade.demo_mode),
            kind=kind, db_value=db_value, exchange_value=exch_value,
        )

    tp_snap = getattr(snapshot, "tp_price", None)
    sl_snap = getattr(snapshot, "sl_price", None)
    db_has_tp = bool(trade.take_profit) or bool(trade.tp_order_id)
    db_has_sl = bool(trade.stop_loss) or bool(trade.sl_order_id)
    ex_has_tp = bool(tp_snap) or bool(getattr(snapshot, "tp_order_id", None))
    ex_has_sl = bool(sl_snap) or bool(getattr(snapshot, "sl_order_id", None))

    result: list[FlagMismatch] = []
    if db_has_tp and not ex_has_tp:
        result.append(_mm("db_only_tp", trade.take_profit, None))
    elif ex_has_tp and not db_has_tp:
        result.append(_mm("exchange_only_tp", None, tp_snap))
    if db_has_sl and not ex_has_sl:
        result.append(_mm("db_only_sl", trade.stop_loss, None))
    elif ex_has_sl and not db_has_sl:
        result.append(_mm("exchange_only_sl", None, sl_snap))
    return result


async def run_audit(
    *,
    user_id: Optional[int],
    exchange: Optional[str],
    apply_mode: bool,
    output_path: Path,
    factory: Optional[ConnectionBackedClientFactory] = None,
) -> AuditReport:
    """Top-level orchestration: select trades, probe, write report."""
    started_at = datetime.now(timezone.utc)
    report = AuditReport(
        started_at=started_at,
        apply_mode=apply_mode,
        user_id_filter=user_id,
        exchange_filter=exchange,
    )

    trades = await select_open_trades(
        user_id=user_id, exchange=exchange,
        attrs=("take_profit", "stop_loss", "tp_order_id", "sl_order_id"),
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
        "audit_tp_sl_flags.done checked=%s mismatches=%s skipped=%s errors=%s",
        report.checked, len(report.mismatches),
        len(report.skipped), len(report.errors),
    )
    return report


async def _audit_one_trade(
    trade: TradeRecord,
    factory: ConnectionBackedClientFactory,
    report: AuditReport,
) -> None:
    """Probe one trade and append findings to ``report``."""
    try:
        client = await factory(trade.user_id, trade.exchange, bool(trade.demo_mode))
        snap = await client.get_position_tpsl(trade.symbol, trade.side)
    except NotImplementedError:
        report.skipped.append(
            f"trade={trade.id} exchange={trade.exchange} (no get_position_tpsl)"
        )
        return
    except Exception as e:  # noqa: BLE001 — surface any failure verbatim
        report.errors.append(f"trade={trade.id}: {type(e).__name__}: {e}")
        return

    for mismatch in compare_tp_sl(trade, snap):
        report.mismatches.append(mismatch)


def render_report(report: AuditReport) -> str:
    """Build the Markdown body for the audit report."""
    lines: list[str] = []
    render_summary_block(
        lines, "TP/SL Flag Audit", report.started_at,
        summary_items=[
            ("Trades geprüft", report.checked),
            ("Mismatches", len(report.mismatches)),
            ("Übersprungen", len(report.skipped)),
            ("Fehler", len(report.errors)),
        ],
        user_id_filter=report.user_id_filter,
        exchange_filter=report.exchange_filter,
    )

    if report.mismatches:
        lines.append("## Mismatches")
        lines.append("")
        lines.append("| Trade | Exchange | Symbol | Kind | DB Value | Exchange Value |")
        lines.append("|---|---|---|---|---|---|")
        for m in report.mismatches:
            lines.append(
                f"| #{m.trade_id} | {m.exchange} | {m.symbol} | {m.kind} "
                f"| {fmt_value(m.db_value)} | {fmt_value(m.exchange_value)} |"
            )
        lines.append("")
        lines.append(
            "Zum Korrigieren: `python scripts/reconcile_open_trades.py --apply`."
        )
        lines.append("")

    render_skip_error_blocks(lines, report.skipped, report.errors)
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = build_base_parser(
        description="Compare DB TP/SL flags with the live exchange plan state."
    )
    return parser.parse_args(argv)


async def main_async(argv: Optional[list[str]] = None) -> int:
    """Async entry point — also imported by ``AuditScheduler``."""
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
        f"Checked={report.checked}  Mismatches={len(report.mismatches)}  "
        f"Skipped={len(report.skipped)}  Errors={len(report.errors)}"
    )
    return 0 if not report.errors else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
