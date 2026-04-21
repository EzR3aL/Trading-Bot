"""Classify-method audit (#216 S2.4): heuristic-fallback rate per exchange.

Scans rotating bot log files under ``--log-dir`` for emissions of
``risk_state.classify_close`` (see :meth:`src.bot.risk_state_manager.
RiskStateManager.classify_close`) and aggregates per-exchange counts of
each ``method`` (``strategy_signal`` / ``history_match`` / ``history_empty``
/ ``heuristic_fallback`` / ``no_trade``).

A fallback share above ``ALERT_FALLBACK_THRESHOLD`` on any exchange is
flagged — Pattern B of our risk-state anti-patterns (#218, #221). Supports
both the plain-text dev format and the JSON production format.

Run::  python scripts/audit_classify_method.py [--hours 24] [--log-dir X]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from sqlalchemy import select

from scripts._audit_common import (
    build_base_parser,
    confirm_apply,
    render_skip_error_blocks,
    render_summary_block,
    resolve_output_path,
    write_report,
)
from src.models.database import TradeRecord
from src.models.session import get_session
from src.utils.logger import get_logger


logger = get_logger(__name__)

AUDIT_NAME = "classify-method"
DEFAULT_LOG_DIR = Path("logs")
DEFAULT_LOG_GLOB = "trading_bot.log*"

# Fallback share threshold: above this share on any exchange we emit an
# alert. Tuned conservatively — single fallback in a small window is
# noise; 30% sustained is a Pattern-B regression (#218, #221).
ALERT_FALLBACK_THRESHOLD = 0.30

# Methods emitted by ``classify_close`` (sync with risk_state_manager).
KNOWN_METHODS = (
    "strategy_signal", "history_match", "history_empty",
    "heuristic_fallback", "no_trade",
)

_TEXT_RE = re.compile(
    r"risk_state\.classify_close\s+trade=(?P<trade_id>\d+)\s+"
    r"reason=(?P<reason>\S+)\s+method=(?P<method>\S+)"
)
_TS_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})")


@dataclass
class ClassifyEvent:
    """One parsed classify_close emission."""
    timestamp: datetime
    trade_id: int
    reason: str
    method: str
    exchange: Optional[str] = None  # resolved from trade_records


@dataclass
class ExchangeStats:
    exchange: str
    total: int = 0
    by_method: dict[str, int] = field(default_factory=dict)

    @property
    def fallback_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.by_method.get("heuristic_fallback", 0) / self.total


@dataclass
class AuditReport:
    started_at: datetime
    hours: int
    log_dir: Path
    apply_mode: bool
    events: list[ClassifyEvent] = field(default_factory=list)
    stats: dict[str, ExchangeStats] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_events(self) -> int:
        return len(self.events)

    def as_outcome(self) -> dict:
        return {
            "audit": AUDIT_NAME,
            "started_at": self.started_at.isoformat(),
            "window_hours": self.hours,
            "total_events": self.total_events,
            "per_exchange": {
                ex: {"total": s.total, "fallback_rate": s.fallback_rate,
                     "by_method": dict(s.by_method)}
                for ex, s in self.stats.items()
            },
            "alerts": list(self.alerts),
            "errors": list(self.errors),
        }


def iter_log_files(log_dir: Path, glob: str = DEFAULT_LOG_GLOB) -> Iterable[Path]:
    """Yield every log file matching ``glob`` in ``log_dir`` (recursive)."""
    if not log_dir.exists():
        return
    for path in sorted(log_dir.glob(glob)):
        if path.is_file():
            yield path


def parse_event_line(line: str) -> Optional[ClassifyEvent]:
    """Parse one raw log line into a ``ClassifyEvent`` (or return None)."""
    line = line.rstrip("\n")
    if not line:
        return None
    stripped = line.lstrip()
    if stripped.startswith("{"):
        event = _parse_json_line(stripped)
        if event is not None:
            return event
    return _parse_text_line(line)


def _extract_field(text: str, key: str) -> Optional[str]:
    """Return the ``key=value`` token value inside ``text``, if present."""
    match = re.search(rf"{re.escape(key)}=([^\s]+)", text)
    return match.group(1) if match else None


def _parse_iso_timestamp(value) -> Optional[datetime]:
    """Parse a timestamp from a JSON log line → tz-aware UTC datetime.

    Accepts ISO-8601 (``YYYY-MM-DDTHH:MM:SS[.fff][Z|+HH:MM]``) as well as the
    Python-logger default format ``YYYY-MM-DD HH:MM:SS,fff`` (comma decimal,
    no timezone). Naive results are normalized to UTC — trading-bot logs are
    always emitted in UTC.
    """
    if not value:
        return None
    try:
        if isinstance(value, str):
            if "," in value:
                value = value.replace(",", ".", 1)
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_json_line(line: str) -> Optional[ClassifyEvent]:
    """Parse a JSON log line."""
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    message = payload.get("message") or ""
    if "risk_state.classify_close" not in message:
        return None
    method = payload.get("method") or _extract_field(message, "method")
    trade_id = payload.get("trade_id") or _extract_field(message, "trade")
    ts = _parse_iso_timestamp(payload.get("timestamp"))
    if not method or trade_id is None or ts is None:
        return None
    try:
        tid = int(trade_id)
    except (TypeError, ValueError):
        return None
    reason = payload.get("reason") or _extract_field(message, "reason")
    return ClassifyEvent(timestamp=ts, trade_id=tid,
                        reason=str(reason or "unknown"), method=str(method))


def _parse_text_line(line: str) -> Optional[ClassifyEvent]:
    """Parse a plain-text log line."""
    m = _TEXT_RE.search(line)
    ts_m = _TS_RE.search(line)
    if not m or not ts_m:
        return None
    try:
        ts = datetime.strptime(ts_m.group("ts"), "%Y-%m-%d %H:%M:%S")
        tid = int(m.group("trade_id"))
    except ValueError:
        return None
    return ClassifyEvent(
        timestamp=ts.replace(tzinfo=timezone.utc), trade_id=tid,
        reason=m.group("reason"), method=m.group("method"),
    )


def collect_events(
    log_dir: Path, since: datetime, glob: str = DEFAULT_LOG_GLOB,
) -> tuple[list[ClassifyEvent], list[str]]:
    """Scan every log file, return (events, file-level errors)."""
    events: list[ClassifyEvent] = []
    errors: list[str] = []
    for path in iter_log_files(log_dir, glob=glob):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    event = parse_event_line(raw)
                    if event is not None and event.timestamp >= since:
                        events.append(event)
        except OSError as e:
            errors.append(f"{path.name}: {type(e).__name__}: {e}")
    return events, errors


async def resolve_trade_exchanges(trade_ids: Iterable[int]) -> dict[int, str]:
    """Load ``{trade_id: exchange}`` for every id found in the logs."""
    ids = list({int(tid) for tid in trade_ids})
    if not ids:
        return {}
    async with get_session() as session:
        stmt = select(TradeRecord.id, TradeRecord.exchange).where(
            TradeRecord.id.in_(ids)
        )
        result = await session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}


def aggregate_stats(events: list[ClassifyEvent]) -> dict[str, ExchangeStats]:
    """Bucket events per exchange and per method."""
    stats: dict[str, ExchangeStats] = {}
    for event in events:
        bucket = stats.setdefault(event.exchange or "unknown",
                                  ExchangeStats(exchange=event.exchange or "unknown"))
        bucket.total += 1
        bucket.by_method[event.method] = bucket.by_method.get(event.method, 0) + 1
    return stats


def compute_alerts(
    stats: dict[str, ExchangeStats],
    threshold: float = ALERT_FALLBACK_THRESHOLD,
) -> list[str]:
    """Flag exchanges whose fallback share is above ``threshold``."""
    return [
        f"exchange={ex} fallback_rate={s.fallback_rate:.2%} "
        f"(threshold {threshold:.0%}, n={s.total})"
        for ex, s in stats.items() if s.fallback_rate > threshold
    ]


async def run_audit(
    *, hours: int, log_dir: Path, apply_mode: bool, output_path: Path,
    log_glob: str = DEFAULT_LOG_GLOB,
) -> AuditReport:
    """Top-level orchestration: parse logs, resolve exchanges, render report."""
    started_at = datetime.now(timezone.utc)
    since = started_at - timedelta(hours=hours)
    report = AuditReport(
        started_at=started_at, hours=hours,
        log_dir=log_dir, apply_mode=apply_mode,
    )

    events, parse_errors = collect_events(log_dir, since, glob=log_glob)
    report.errors.extend(parse_errors)

    exchange_map = await resolve_trade_exchanges(e.trade_id for e in events)
    for event in events:
        event.exchange = exchange_map.get(event.trade_id)
    report.events = events
    report.stats = aggregate_stats(events)
    report.alerts = compute_alerts(report.stats)

    write_report(render_report(report), output_path)
    logger.info(
        "audit_classify_method.done events=%s exchanges=%s alerts=%s",
        report.total_events, len(report.stats), len(report.alerts),
    )
    return report


def render_report(report: AuditReport) -> str:
    lines: list[str] = []
    render_summary_block(
        lines, "Classify-Method Audit", report.started_at,
        summary_items=[
            ("Fenster", f"letzte {report.hours} h"),
            ("Log-Dir", f"`{report.log_dir}`"),
            ("Events", report.total_events),
            ("Exchanges beobachtet", len(report.stats)),
            ("Alerts", len(report.alerts)),
            ("Parse-Fehler", len(report.errors)),
        ],
    )

    if report.stats:
        header = ["Exchange", "Total", *KNOWN_METHODS, "Fallback %"]
        lines += [
            "## Per Exchange", "",
            "| " + " | ".join(header) + " |",
            "|" + "|".join(["---"] * len(header)) + "|",
        ]
        for ex in sorted(report.stats.keys()):
            s = report.stats[ex]
            cells = [ex, str(s.total)] \
                + [str(s.by_method.get(m, 0)) for m in KNOWN_METHODS] \
                + [f"{s.fallback_rate:.1%}"]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    if report.alerts:
        lines += ["## Alerts", ""]
        lines.extend(f"- {item}" for item in report.alerts)
        lines.append("")

    render_skip_error_blocks(lines, [], report.errors)
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = build_base_parser(
        description="Scan bot logs for classify_close emissions and "
                    "compute the heuristic-fallback rate per exchange."
    )
    parser.add_argument("--hours", type=int, default=1,
                        help="Lookback window in hours (default: 1).")
    parser.add_argument("--log-dir", type=str, default=str(DEFAULT_LOG_DIR),
                        help="Bot-log directory (default: logs/).")
    parser.add_argument("--log-glob", type=str, default=DEFAULT_LOG_GLOB,
                        help=f"Filename glob (default: {DEFAULT_LOG_GLOB}).")
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
        hours=args.hours, log_dir=Path(args.log_dir),
        apply_mode=args.apply, output_path=output_path,
        log_glob=args.log_glob,
    )
    print(f"Report written to {output_path}")
    print(
        f"Events={report.total_events}  Exchanges={len(report.stats)}  "
        f"Alerts={len(report.alerts)}"
    )
    return 0 if not report.alerts else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
