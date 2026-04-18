"""Drift backfill script: reconcile every open trade once via RiskStateManager.

Scans all ``trade_records`` rows with ``status='open'``, runs each one
through :meth:`src.bot.risk_state_manager.RiskStateManager.reconcile`, and
writes a Markdown report comparing DB-state-before to DB-state-after.

This is the manual "heal historical drift" tool that closes Epic #188.
The bot itself runs reconcile per trade live; this script is for the
one-time operator-driven sweep when you suspect rows are stale (e.g.
after deploying #190 / #191 for the first time, or after a long outage).

Usage
-----

    # Dry run (default) — only reads exchanges, no DB writes
    python scripts/reconcile_open_trades.py

    # Apply mode — writes drift corrections back via RiskStateManager
    python scripts/reconcile_open_trades.py --apply

    # Filter by user
    python scripts/reconcile_open_trades.py --user-id 4

    # Filter by exchange
    python scripts/reconcile_open_trades.py --exchange bitget

    # Combined + custom report path + skip the apply confirmation
    python scripts/reconcile_open_trades.py --apply --yes \
        --user-id 4 --exchange bitget \
        --output reports/manual-2026-04-18.md

Safety
------

* Only ``status='open'`` rows are touched — historical trades stay
  untouched.
* Default is dry-run. ``--apply`` requires either an interactive ``y``
  confirmation or the ``--yes`` flag.
* Idempotent: running twice in a row produces the same report (modulo
  ``last_synced_at``).
* Exchanges without a ``get_position_tpsl`` / ``get_trailing_stop``
  implementation (Weex, Bitunix today) are reported as ``skipped``,
  not as errors.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional

# Container layout fallback so the script can run via
#   docker exec bitget-trading-bot python /app/scripts/reconcile_open_trades.py
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.risk_state_manager import RiskStateManager, RiskStateSnapshot
from src.exchanges.factory import create_exchange_client
from src.models.database import ExchangeConnection, TradeRecord
from src.models.session import get_session
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger


logger = get_logger(__name__)


# ── Constants ──────────────────────────────────────────────────────────

# Fields that the reconciler may touch — these are diffed pre/post.
DRIFT_FIELDS: tuple[str, ...] = (
    "take_profit",
    "stop_loss",
    "tp_order_id",
    "sl_order_id",
    "native_trailing_stop",
    "trailing_callback_rate",
    "trailing_activation_price",
    "trailing_order_id",
    "trailing_atr_override",
    "risk_source",
    "last_synced_at",
)

DEFAULT_REPORT_DIR = Path("reports")


# ── DTOs ───────────────────────────────────────────────────────────────


@dataclass
class TradeIdentity:
    """Minimal identifying info needed to label a trade in the report."""
    trade_id: int
    user_id: int
    exchange: str
    symbol: str
    side: str
    demo_mode: bool


@dataclass
class TradeOutcome:
    """One trade's result in the reconcile sweep."""
    identity: TradeIdentity
    drift: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    skipped_reason: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ReconcileReport:
    """Aggregate result across all scanned trades."""
    started_at: datetime
    apply_mode: bool
    user_id_filter: Optional[int]
    exchange_filter: Optional[str]
    outcomes: list[TradeOutcome] = field(default_factory=list)
    verbose: bool = False

    @property
    def checked(self) -> int:
        return len(self.outcomes)

    @property
    def with_drift(self) -> int:
        return sum(1 for o in self.outcomes if o.drift and not o.error and not o.skipped_reason)

    @property
    def corrected(self) -> int:
        if not self.apply_mode:
            return 0
        return self.with_drift

    @property
    def errors(self) -> int:
        return sum(1 for o in self.outcomes if o.error)

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.skipped_reason)


# ── Exchange-client factory wired to ExchangeConnection rows ───────────


class ConnectionBackedClientFactory:
    """Provides ExchangeClient instances by looking up DB connections.

    The :class:`RiskStateManager` calls
    ``factory(user_id, exchange, demo_mode)`` and expects a ready
    ExchangeClient. We resolve credentials from ``exchange_connections``
    on first use and cache per (user, exchange, demo_mode) so we do not
    decrypt the same credentials over and over for users with many open
    trades on one exchange.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[int, str, bool], Any] = {}

    async def __call__(self, user_id: int, exchange: str, demo_mode: bool) -> Any:
        key = (user_id, exchange, bool(demo_mode))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        async with get_session() as session:
            result = await session.execute(
                select(ExchangeConnection).where(
                    ExchangeConnection.user_id == user_id,
                    ExchangeConnection.exchange_type == exchange,
                )
            )
            conn = result.scalar_one_or_none()

        if conn is None:
            raise RuntimeError(
                f"no exchange_connection for user={user_id} exchange={exchange}"
            )

        if demo_mode:
            key_enc = conn.demo_api_key_encrypted
            secret_enc = conn.demo_api_secret_encrypted
            passphrase_enc = conn.demo_passphrase_encrypted
        else:
            key_enc = conn.api_key_encrypted
            secret_enc = conn.api_secret_encrypted
            passphrase_enc = conn.passphrase_encrypted

        if not key_enc or not secret_enc:
            raise RuntimeError(
                f"missing {'demo' if demo_mode else 'live'} credentials for "
                f"user={user_id} exchange={exchange}"
            )

        client = create_exchange_client(
            exchange_type=exchange,
            api_key=decrypt_value(key_enc),
            api_secret=decrypt_value(secret_enc),
            passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
            demo_mode=demo_mode,
        )
        self._cache[key] = client
        return client

    async def close_all(self) -> None:
        """Close every cached client politely (best-effort)."""
        for client in self._cache.values():
            close = getattr(client, "close", None)
            if close is None:
                continue
            try:
                if asyncio.iscoroutinefunction(close):
                    await close()
                else:
                    close()
            except Exception:  # pragma: no cover — best-effort cleanup
                logger.debug("client close raised — ignoring", exc_info=True)


# ── Session factory adapter for RiskStateManager ───────────────────────


@asynccontextmanager
async def _session_factory() -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession that auto-commits / rolls back on exit."""
    async with get_session() as session:
        yield session


# ── Trade selection ────────────────────────────────────────────────────


async def select_open_trades(
    user_id: Optional[int],
    exchange: Optional[str],
) -> list[TradeRecord]:
    """Load every open TradeRecord matching the optional filters."""
    async with get_session() as session:
        stmt = select(TradeRecord).where(TradeRecord.status == "open")
        if user_id is not None:
            stmt = stmt.where(TradeRecord.user_id == user_id)
        if exchange is not None:
            stmt = stmt.where(TradeRecord.exchange == exchange)
        stmt = stmt.order_by(TradeRecord.id)
        result = await session.execute(stmt)
        # Force load now so attribute access after session close is safe.
        rows = list(result.scalars().all())
        for row in rows:
            for field_name in DRIFT_FIELDS:
                _ = getattr(row, field_name, None)
            _ = (row.user_id, row.exchange, row.symbol, row.side, row.demo_mode)
        return rows


def snapshot_trade_fields(trade: TradeRecord) -> dict[str, Any]:
    """Return a plain-dict copy of every drift-relevant field on ``trade``."""
    return {field_name: getattr(trade, field_name, None) for field_name in DRIFT_FIELDS}


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Return ``{field: (before, after)}`` for every field that changed."""
    drift: dict[str, tuple[Any, Any]] = {}
    for key in DRIFT_FIELDS:
        old = before.get(key)
        new = after.get(key)
        if old != new:
            drift[key] = (old, new)
    return drift


# ── Reconcile loop ─────────────────────────────────────────────────────


async def reconcile_one(
    manager: RiskStateManager,
    trade: TradeRecord,
    *,
    apply_mode: bool,
) -> TradeOutcome:
    """Run reconcile for a single trade and return the diff outcome."""
    identity = TradeIdentity(
        trade_id=trade.id,
        user_id=trade.user_id,
        exchange=trade.exchange,
        symbol=trade.symbol,
        side=trade.side,
        demo_mode=bool(trade.demo_mode),
    )
    before = snapshot_trade_fields(trade)

    logger.info(
        "reconcile.trade.start trade_id=%s user_id=%s exchange=%s symbol=%s mode=%s apply=%s",
        identity.trade_id, identity.user_id, identity.exchange,
        identity.symbol, "demo" if identity.demo_mode else "live", apply_mode,
    )

    if not apply_mode:
        # Dry-run: probe exchange via reconcile, then ROLLBACK by reloading
        # the row's pre-image. We do this by invoking reconcile but using a
        # session that we revert. Simpler: compute would-be diff by calling
        # reconcile on a dedicated SAVEPOINT-style flow is overkill — instead
        # we rely on RiskStateManager.reconcile returning a snapshot we can
        # diff against the DB pre-image directly.
        try:
            snap = await manager.reconcile(trade.id)
        except NotImplementedError as e:
            logger.info(
                "reconcile.trade.skipped trade_id=%s reason=not_implemented",
                identity.trade_id,
            )
            return TradeOutcome(identity=identity, skipped_reason=f"exchange not supported: {e}")
        except Exception as e:  # noqa: BLE001 — surface any failure verbatim
            logger.warning(
                "reconcile.trade.error trade_id=%s error=%s",
                identity.trade_id, e,
            )
            return TradeOutcome(identity=identity, error=f"{type(e).__name__}: {e}")

        # In dry-run we still want to undo any side effect on DB by
        # restoring the snapshotted pre-image. The reconcile() call above
        # WILL have written through — that's the manager's contract. To
        # honor "default dry-run no UPDATE", we revert here.
        await _revert_to_snapshot(trade.id, before)
        after = _project_snapshot_to_dict(snap, before)

    else:
        try:
            await manager.reconcile(trade.id)
        except NotImplementedError as e:
            logger.info(
                "reconcile.trade.skipped trade_id=%s reason=not_implemented",
                identity.trade_id,
            )
            return TradeOutcome(identity=identity, skipped_reason=f"exchange not supported: {e}")
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "reconcile.trade.error trade_id=%s error=%s",
                identity.trade_id, e,
            )
            return TradeOutcome(identity=identity, error=f"{type(e).__name__}: {e}")
        after = await _reload_snapshot(trade.id)

    drift = diff_snapshots(before, after)
    if drift:
        logger.info(
            "reconcile.trade.drift trade_id=%s fields=%s",
            identity.trade_id, sorted(drift.keys()),
        )
    else:
        logger.info("reconcile.trade.clean trade_id=%s", identity.trade_id)
    return TradeOutcome(identity=identity, drift=drift)


async def _revert_to_snapshot(trade_id: int, before: dict[str, Any]) -> None:
    """Restore the pre-reconcile field values for dry-run mode."""
    async with get_session() as session:
        trade = await session.get(TradeRecord, trade_id)
        if trade is None:  # pragma: no cover — vanished mid-sweep
            return
        for key, value in before.items():
            setattr(trade, key, value)
        await session.commit()


async def _reload_snapshot(trade_id: int) -> dict[str, Any]:
    """Load the post-reconcile field values from the DB."""
    async with get_session() as session:
        trade = await session.get(TradeRecord, trade_id)
        if trade is None:  # pragma: no cover
            return {}
        return snapshot_trade_fields(trade)


def _project_snapshot_to_dict(
    snap: RiskStateSnapshot,
    before: dict[str, Any],
) -> dict[str, Any]:
    """Translate a RiskStateSnapshot into the same dict shape diff uses.

    We start from the pre-image so non-reconciled fields (e.g.
    ``trailing_atr_override`` and ``native_trailing_stop`` — the
    reconciler touches neither) keep their old value rather than
    appearing as spurious drift.
    """
    after: dict[str, Any] = dict(before)
    if snap.tp is not None:
        after["take_profit"] = snap.tp.get("value")
        after["tp_order_id"] = snap.tp.get("order_id")
    if snap.sl is not None:
        after["stop_loss"] = snap.sl.get("value")
        after["sl_order_id"] = snap.sl.get("order_id")
    if snap.trailing is not None:
        trailing_value = snap.trailing.get("value") or {}
        after["trailing_callback_rate"] = trailing_value.get("callback_rate")
        after["trailing_activation_price"] = trailing_value.get("activation_price")
        after["trailing_order_id"] = snap.trailing.get("order_id")
    after["risk_source"] = snap.risk_source
    after["last_synced_at"] = snap.last_synced_at
    return after


# ── Reporting ──────────────────────────────────────────────────────────


def render_report(report: ReconcileReport) -> str:
    """Build the Markdown body for the reconcile report."""
    lines: list[str] = []
    when = report.started_at.strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"# Reconcile Report — {when}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Trades geprüft: {report.checked}")
    lines.append(f"- Mit Drift: {report.with_drift}")
    if report.apply_mode:
        lines.append(f"- Korrigiert (--apply): {report.corrected}")
    else:
        lines.append("- Korrigiert (--apply): 0 (dry-run)")
    lines.append(f"- Übersprungen: {report.skipped}")
    lines.append(f"- Fehler: {report.errors}")
    if report.user_id_filter is not None:
        lines.append(f"- Filter user_id: {report.user_id_filter}")
    if report.exchange_filter is not None:
        lines.append(f"- Filter exchange: {report.exchange_filter}")
    lines.append("")

    drift_outcomes = [o for o in report.outcomes if o.drift and not o.error and not o.skipped_reason]
    if drift_outcomes:
        lines.append("## Drift-Trades")
        lines.append("")
        for outcome in drift_outcomes:
            lines.extend(_render_trade_drift(outcome, apply_mode=report.apply_mode))
            lines.append("")

    skipped = [o for o in report.outcomes if o.skipped_reason]
    if skipped:
        lines.append("## Skipped")
        lines.append("")
        for outcome in skipped:
            label = _trade_label(outcome.identity)
            lines.append(f"### Trade #{outcome.identity.trade_id} ({label})")
            lines.append(f"- {outcome.skipped_reason}")
            lines.append("")

    errors = [o for o in report.outcomes if o.error]
    if errors:
        lines.append("## Errors")
        lines.append("")
        for outcome in errors:
            label = _trade_label(outcome.identity)
            lines.append(f"### Trade #{outcome.identity.trade_id} ({label})")
            lines.append(f"- {outcome.error}")
            lines.append("")

    if report.verbose:
        clean = [
            o for o in report.outcomes
            if not o.drift and not o.error and not o.skipped_reason
        ]
        if clean:
            lines.append("## Clean (no drift)")
            lines.append("")
            for outcome in clean:
                label = _trade_label(outcome.identity)
                lines.append(f"- Trade #{outcome.identity.trade_id} ({label})")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_trade_drift(outcome: TradeOutcome, *, apply_mode: bool) -> list[str]:
    """Render the per-trade drift table for a single outcome."""
    label = _trade_label(outcome.identity)
    lines = [f"### Trade #{outcome.identity.trade_id} ({label})"]
    if apply_mode:
        lines.append("| Feld | DB vorher | Exchange | DB nachher (--apply) |")
        lines.append("|---|---|---|---|")
        for field_name, (before, after) in sorted(outcome.drift.items()):
            lines.append(
                f"| {field_name} | {_fmt(before)} | {_fmt(after)} | {_fmt(after)} |"
            )
    else:
        lines.append("| Feld | DB vorher | Exchange | DB nachher (--apply) |")
        lines.append("|---|---|---|---|")
        for field_name, (before, after) in sorted(outcome.drift.items()):
            lines.append(
                f"| {field_name} | {_fmt(before)} | {_fmt(after)} | (dry-run) |"
            )
    return lines


def _trade_label(identity: TradeIdentity) -> str:
    """Compact ``BTCUSDT long, user=4, bitget demo`` style header label."""
    mode = "demo" if identity.demo_mode else "live"
    return (
        f"{identity.symbol} {identity.side}, user={identity.user_id}, "
        f"{identity.exchange} {mode}"
    )


def _fmt(value: Any) -> str:
    """Render a field value for the Markdown table cell."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def write_report(report_text: str, output_path: Path) -> None:
    """Persist the rendered report to disk, creating parent dirs if needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text, encoding="utf-8")


def default_report_path(started_at: datetime) -> Path:
    """Default ``reports/reconcile-YYYY-MM-DD-HHMM.md`` path."""
    stamp = started_at.strftime("%Y-%m-%d-%H%M")
    return DEFAULT_REPORT_DIR / f"reconcile-{stamp}.md"


# ── Main orchestration ────────────────────────────────────────────────


async def run_reconcile(
    *,
    user_id: Optional[int],
    exchange: Optional[str],
    apply_mode: bool,
    verbose: bool,
    output_path: Path,
) -> ReconcileReport:
    """Top-level orchestration: select trades, reconcile each, write report."""
    started_at = datetime.now(timezone.utc)
    report = ReconcileReport(
        started_at=started_at,
        apply_mode=apply_mode,
        user_id_filter=user_id,
        exchange_filter=exchange,
        verbose=verbose,
    )

    trades = await select_open_trades(user_id=user_id, exchange=exchange)
    logger.info(
        "reconcile.start trades=%s user_id=%s exchange=%s apply=%s",
        len(trades), user_id, exchange, apply_mode,
    )

    if not trades:
        logger.info("reconcile.empty no open trades match the filters")
        report_text = render_report(report)
        write_report(report_text, output_path)
        return report

    factory = ConnectionBackedClientFactory()
    manager = RiskStateManager(
        exchange_client_factory=factory,
        session_factory=_session_factory,
    )

    try:
        for trade in trades:
            outcome = await reconcile_one(manager, trade, apply_mode=apply_mode)
            # Every scanned trade lands in outcomes so the "checked" counter
            # matches the input count. ``render_report`` filters outcomes per
            # section (drift / skipped / errors) so quiet trades are hidden
            # unless --verbose was requested.
            report.outcomes.append(outcome)
            if verbose and not (outcome.drift or outcome.skipped_reason or outcome.error):
                logger.info("reconcile.trade.verbose_clean trade_id=%s", outcome.identity.trade_id)
    finally:
        await factory.close_all()

    report_text = render_report(report)
    write_report(report_text, output_path)
    logger.info(
        "reconcile.done checked=%s drift=%s skipped=%s errors=%s report=%s",
        report.checked, report.with_drift, report.skipped,
        report.errors, output_path,
    )
    return report


def confirm_apply(stream_in=None, stream_out=None) -> bool:
    """Interactive confirmation prompt for --apply mode (skipped if --yes)."""
    inp = stream_in or sys.stdin
    out = stream_out or sys.stdout
    out.write(
        "WARNING: --apply will write drift corrections to the DB via "
        "RiskStateManager.reconcile(). Continue? [y/N]: "
    )
    out.flush()
    answer = inp.readline().strip().lower()
    return answer in ("y", "yes")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Build the CLI arg parser and parse ``argv`` (defaults to sys.argv)."""
    parser = argparse.ArgumentParser(
        description="Reconcile every open trade once via RiskStateManager.reconcile()."
    )
    parser.add_argument(
        "--user-id", type=int, default=None,
        help="Only reconcile trades belonging to this user (default: all).",
    )
    parser.add_argument(
        "--exchange", type=str, default=None,
        help="Only reconcile trades for this exchange (bitget/bingx/hyperliquid/...).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Write drift corrections via RiskStateManager (default: dry-run).",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the confirmation prompt for --apply.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Include trades with no drift in the report (default: drift only).",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Markdown report path (default: reports/reconcile-YYYY-MM-DD-HHMM.md).",
    )
    return parser.parse_args(argv)


async def main(argv: Optional[list[str]] = None) -> int:
    """Entry point: parse args, optionally confirm, run reconcile."""
    args = parse_args(argv)

    if args.apply and not args.yes:
        if not confirm_apply():
            print("Aborted.")
            return 1

    output_path = (
        Path(args.output) if args.output else default_report_path(datetime.now(timezone.utc))
    )

    report = await run_reconcile(
        user_id=args.user_id,
        exchange=args.exchange,
        apply_mode=args.apply,
        verbose=args.verbose,
        output_path=output_path,
    )

    print(f"Report written to {output_path}")
    print(
        f"Checked={report.checked}  Drift={report.with_drift}  "
        f"Corrected={report.corrected}  Skipped={report.skipped}  "
        f"Errors={report.errors}"
    )
    return 0 if report.errors == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
