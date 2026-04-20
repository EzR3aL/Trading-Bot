"""Backfill exit_reason on closed trades via RiskStateManager.classify_close.

Runs ``RiskStateManager.classify_close(trade_id, exit_price, exit_time)``
against closed trades whose stored ``exit_reason`` is weak
(``EXTERNAL_CLOSE_UNKNOWN`` by default) or explicit via ``--trade-ids``.
Each proposed reason is compared against the current DB value; only rows
that actually change are UPDATEd (and only when ``--apply`` is passed).

Intended for one-off cleanup after #218 — the earlier bot close-path was
never given an RSM instance, so any close that fell outside the 0.2 %
proximity heuristic window was recorded as ``EXTERNAL_CLOSE_UNKNOWN``
even when Bitget's orders-plan-history knew exactly which plan fired.

Usage
-----

    # Dry run — prints proposed reasons, touches no rows.
    python scripts/backfill_classify_close.py

    # Target specific trades.
    python scripts/backfill_classify_close.py --trade-ids 251,262,276

    # Apply the changes.
    python scripts/backfill_classify_close.py --apply --yes

    # Filter scope.
    python scripts/backfill_classify_close.py --exchange bitget \
        --reason EXTERNAL_CLOSE_UNKNOWN

Safety
------

* Only ``status='closed'`` rows are considered.
* Default is dry-run. ``--apply`` requires an interactive ``y`` prompt or
  ``--yes``.
* Idempotent: a second run after ``--apply`` produces no writes because
  the DB reason already matches the classifier output.
* Re-uses the same ``ConnectionBackedClientFactory`` pattern as
  ``reconcile_open_trades.py`` so Weex/Bitunix trades that lack readback
  surface as ``skipped``, not as errors.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.reconcile_open_trades import ConnectionBackedClientFactory
from src.bot.risk_state_manager import RiskStateManager
from src.models.database import TradeRecord
from src.models.session import get_session
from src.utils.logger import get_logger


logger = get_logger(__name__)


DEFAULT_WEAK_REASONS = ("EXTERNAL_CLOSE_UNKNOWN",)


@dataclass
class BackfillOutcome:
    trade_id: int
    exchange: str
    symbol: str
    side: str
    exit_price: float
    exit_time: datetime
    before_reason: str
    after_reason: Optional[str] = None
    applied: bool = False
    skipped_reason: Optional[str] = None
    error: Optional[str] = None

    @property
    def changed(self) -> bool:
        return (
            self.after_reason is not None
            and self.after_reason != self.before_reason
            and self.error is None
            and self.skipped_reason is None
        )


@dataclass
class BackfillReport:
    started_at: datetime
    apply_mode: bool
    reason_filter: tuple[str, ...]
    trade_id_filter: Optional[tuple[int, ...]]
    exchange_filter: Optional[str]
    outcomes: list[BackfillOutcome] = field(default_factory=list)

    @property
    def checked(self) -> int:
        return len(self.outcomes)

    @property
    def with_change(self) -> int:
        return sum(1 for o in self.outcomes if o.changed)

    @property
    def applied(self) -> int:
        return sum(1 for o in self.outcomes if o.applied)

    @property
    def errors(self) -> int:
        return sum(1 for o in self.outcomes if o.error)

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.skipped_reason)


@asynccontextmanager
async def _session_factory() -> AsyncIterator[AsyncSession]:
    async with get_session() as session:
        yield session


async def select_closed_trades(
    reasons: tuple[str, ...],
    trade_ids: Optional[tuple[int, ...]],
    exchange: Optional[str],
) -> list[TradeRecord]:
    async with get_session() as session:
        stmt = select(TradeRecord).where(TradeRecord.status == "closed")
        if trade_ids:
            stmt = stmt.where(TradeRecord.id.in_(trade_ids))
        else:
            stmt = stmt.where(TradeRecord.exit_reason.in_(reasons))
        if exchange:
            stmt = stmt.where(TradeRecord.exchange == exchange)
        stmt = stmt.order_by(TradeRecord.id)
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        for row in rows:
            _ = (
                row.id, row.exchange, row.symbol, row.side,
                row.exit_price, row.exit_time, row.exit_reason,
            )
        return rows


async def _apply_exit_reason(trade_id: int, new_reason: str) -> None:
    async with get_session() as session:
        await session.execute(
            update(TradeRecord)
            .where(TradeRecord.id == trade_id)
            .values(exit_reason=new_reason, updated_at=datetime.now(timezone.utc))
        )
        await session.commit()


async def backfill_one(
    manager: RiskStateManager,
    trade: TradeRecord,
    *,
    apply_mode: bool,
) -> BackfillOutcome:
    outcome = BackfillOutcome(
        trade_id=trade.id,
        exchange=trade.exchange,
        symbol=trade.symbol,
        side=trade.side,
        exit_price=float(trade.exit_price) if trade.exit_price is not None else 0.0,
        exit_time=trade.exit_time or datetime.now(timezone.utc),
        before_reason=trade.exit_reason or "",
    )

    if trade.exit_price is None or trade.exit_time is None:
        outcome.skipped_reason = "missing exit_price or exit_time"
        return outcome

    try:
        new_reason = await manager.classify_close(
            trade.id, float(trade.exit_price), trade.exit_time,
        )
    except NotImplementedError as e:
        outcome.skipped_reason = f"exchange not supported: {e}"
        return outcome
    except Exception as e:  # noqa: BLE001 — surface failures verbatim
        outcome.error = f"{type(e).__name__}: {e}"
        return outcome

    outcome.after_reason = new_reason

    if outcome.changed and apply_mode:
        try:
            await _apply_exit_reason(trade.id, new_reason)
            outcome.applied = True
        except Exception as e:  # noqa: BLE001
            outcome.error = f"db_update_failed: {type(e).__name__}: {e}"

    return outcome


async def run_backfill(
    *,
    apply_mode: bool,
    reason_filter: tuple[str, ...],
    trade_id_filter: Optional[tuple[int, ...]],
    exchange_filter: Optional[str],
) -> BackfillReport:
    report = BackfillReport(
        started_at=datetime.now(timezone.utc),
        apply_mode=apply_mode,
        reason_filter=reason_filter,
        trade_id_filter=trade_id_filter,
        exchange_filter=exchange_filter,
    )

    trades = await select_closed_trades(reason_filter, trade_id_filter, exchange_filter)
    if not trades:
        return report

    client_factory = ConnectionBackedClientFactory()
    manager = RiskStateManager(
        exchange_client_factory=client_factory,
        session_factory=_session_factory,
    )
    try:
        for trade in trades:
            outcome = await backfill_one(manager, trade, apply_mode=apply_mode)
            report.outcomes.append(outcome)
    finally:
        await client_factory.close_all()

    return report


def format_report(report: BackfillReport) -> str:
    mode = "APPLY" if report.apply_mode else "DRY-RUN"
    lines = [
        f"Backfill classify_close — {mode}",
        f"  started={report.started_at.isoformat()}",
        f"  reason_filter={report.reason_filter}",
        f"  trade_id_filter={report.trade_id_filter or '-'}",
        f"  exchange_filter={report.exchange_filter or '-'}",
        f"  checked={report.checked} "
        f"change-proposed={report.with_change} "
        f"applied={report.applied} "
        f"skipped={report.skipped} errors={report.errors}",
        "",
        f"{'id':>5} {'exchange':<10} {'symbol':<14} {'before':<26} {'after':<26} {'note':<20}",
        "-" * 110,
    ]
    for o in report.outcomes:
        note = ""
        if o.error:
            note = f"ERROR {o.error}"
        elif o.skipped_reason:
            note = f"SKIPPED {o.skipped_reason}"
        elif o.applied:
            note = "applied"
        elif o.changed:
            note = "proposed"
        else:
            note = "no-change"
        lines.append(
            f"{o.trade_id:>5} {o.exchange:<10} {o.symbol:<14} "
            f"{o.before_reason:<26} {(o.after_reason or '-'):<26} {note:<20}"
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--apply", action="store_true", help="Write changes to DB")
    p.add_argument("--yes", action="store_true", help="Skip apply confirmation")
    p.add_argument(
        "--reason",
        action="append",
        help="Exit reason to target (repeatable). "
        f"Default: {','.join(DEFAULT_WEAK_REASONS)}",
    )
    p.add_argument(
        "--trade-ids",
        help="Comma-separated trade IDs (overrides --reason filter)",
    )
    p.add_argument("--exchange", help="Limit to one exchange")
    return p.parse_args()


def _parse_trade_ids(raw: Optional[str]) -> Optional[tuple[int, ...]]:
    if not raw:
        return None
    return tuple(int(x) for x in raw.split(",") if x.strip())


async def main_async(args: argparse.Namespace) -> int:
    reason_filter = tuple(args.reason) if args.reason else DEFAULT_WEAK_REASONS
    trade_id_filter = _parse_trade_ids(args.trade_ids)

    if args.apply and not args.yes:
        prompt = (
            "This will UPDATE exit_reason on matching rows. Continue? [y/N] "
        )
        try:
            answer = input(prompt).strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            print("aborted.")
            return 2

    report = await run_backfill(
        apply_mode=args.apply,
        reason_filter=reason_filter,
        trade_id_filter=trade_id_filter,
        exchange_filter=args.exchange,
    )
    print(format_report(report))
    return 0 if report.errors == 0 else 1


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
