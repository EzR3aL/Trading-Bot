"""Shared helpers for the #216 audit scripts.

Each of the four ``audit_*.py`` scripts reuses the same plumbing:

* :class:`ConnectionBackedClientFactory` — resolves ``ExchangeConnection``
  rows into ready ``ExchangeClient`` instances with credential caching.
* :func:`session_factory` — async-contextmanager wrapper around
  ``src.models.session.get_session`` (same signature the RiskStateManager
  session_factory expects).
* :func:`default_report_path` / :func:`write_report` — consistent naming
  and on-disk layout under ``reports/``.
* :func:`confirm_apply` — interactive confirmation for ``--apply`` mode.
* :func:`build_base_parser` — argparse defaults shared across audits.

Kept intentionally small: the scripts that import this module still own
their own business logic. This file is about structural sameness.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.exchanges.factory import create_exchange_client
from src.models.database import ExchangeConnection, TradeRecord
from src.models.session import get_session
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger


logger = get_logger(__name__)


# ── Constants ──────────────────────────────────────────────────────────

DEFAULT_REPORT_DIR = Path("reports")

# TP/SL size tolerance: exchange rounding can move a size by a fraction of
# one contract. 0.5 % stays on the "noise" side without masking real drift.
SIZE_TOLERANCE_PCT = 0.5

# Price sanity threshold: a >2 % gap between DB entry/exit_price and the
# 1-minute kline open/close at that timestamp is considered suspicious.
PRICE_DEVIATION_THRESHOLD_PCT = 2.0


# ── Exchange-client factory ────────────────────────────────────────────


class ConnectionBackedClientFactory:
    """Provide ExchangeClient instances from ``exchange_connections`` rows.

    Cached per ``(user_id, exchange, demo_mode)`` so we do not decrypt the
    same credentials over and over for users with many open trades on one
    exchange. Mirrors :class:`scripts.reconcile_open_trades.ConnectionBackedClientFactory`.
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
            except Exception:  # pragma: no cover — cleanup only
                logger.debug("client close raised — ignoring", exc_info=True)


# ── Session factory ────────────────────────────────────────────────────


@asynccontextmanager
async def session_factory() -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession that auto-commits / rolls back on exit."""
    async with get_session() as session:
        yield session


# ── CLI helpers ────────────────────────────────────────────────────────


def build_base_parser(description: str) -> argparse.ArgumentParser:
    """Build the subset of CLI flags every audit script exposes."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--user-id", type=int, default=None,
        help="Only audit trades belonging to this user (default: all).",
    )
    parser.add_argument(
        "--exchange", type=str, default=None,
        help="Only audit trades for this exchange (bitget/bingx/hyperliquid/...).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Persist corrections where applicable (default: dry-run).",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the confirmation prompt for --apply.",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Markdown report path (default: reports/<audit-name>-<timestamp>.md).",
    )
    return parser


def confirm_apply(stream_in=None, stream_out=None) -> bool:
    """Interactive confirmation prompt for --apply mode (skipped if --yes)."""
    inp = stream_in or sys.stdin
    out = stream_out or sys.stdout
    out.write(
        "WARNING: --apply will write corrections to the DB. Continue? [y/N]: "
    )
    out.flush()
    answer = inp.readline().strip().lower()
    return answer in ("y", "yes")


# ── Reporting ──────────────────────────────────────────────────────────


def default_report_path(name: str, started_at: datetime) -> Path:
    """Default ``reports/<name>-YYYY-MM-DD-HHMM.md`` path."""
    stamp = started_at.strftime("%Y-%m-%d-%H%M")
    return DEFAULT_REPORT_DIR / f"{name}-{stamp}.md"


def write_report(report_text: str, output_path: Path) -> None:
    """Persist the rendered report to disk, creating parent dirs if needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text, encoding="utf-8")


def fmt_value(value: Any) -> str:
    """Render a field value for a Markdown table cell."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, str):
        return value
    return str(value)


def resolve_output_path(
    audit_name: str, arg_output: Optional[str], started_at: datetime,
) -> Path:
    """Pick the caller-supplied path or fall back to the default layout."""
    if arg_output:
        return Path(arg_output)
    return default_report_path(audit_name, started_at)


# ── Trade selection ────────────────────────────────────────────────────


async def select_open_trades(
    user_id: Optional[int],
    exchange: Optional[str],
    *,
    attrs: tuple[str, ...] = (),
) -> list[TradeRecord]:
    """Load every open TradeRecord matching the optional filters.

    ``attrs`` lists column names that callers need after the session has
    closed. We touch each so the ORM eagerly loads them.
    """
    async with get_session() as session:
        stmt = select(TradeRecord).where(TradeRecord.status == "open")
        if user_id is not None:
            stmt = stmt.where(TradeRecord.user_id == user_id)
        if exchange is not None:
            stmt = stmt.where(TradeRecord.exchange == exchange)
        stmt = stmt.order_by(TradeRecord.id)
        result = await session.execute(stmt)
        trades = list(result.scalars().all())
        for t in trades:
            _ = (t.user_id, t.exchange, t.symbol, t.side, t.demo_mode)
            for name in attrs:
                _ = getattr(t, name, None)
        return trades


# ── Report snippet helpers ────────────────────────────────────────────


def render_skip_error_blocks(
    lines: list[str], skipped: list[str], errors: list[str],
) -> None:
    """Append ``## Skipped`` / ``## Errors`` sections (mutates ``lines``)."""
    for title, items in (("## Skipped", skipped), ("## Errors", errors)):
        if not items:
            continue
        lines.append(title)
        lines.append("")
        lines.extend(f"- {item}" for item in items)
        lines.append("")


def render_summary_block(
    lines: list[str],
    title: str,
    started_at: datetime,
    summary_items: list[tuple[str, Any]],
    *,
    user_id_filter: Optional[int] = None,
    exchange_filter: Optional[str] = None,
) -> None:
    """Append ``# {title}`` header + ``## Summary`` block.

    ``summary_items`` is an ordered list of ``(label, value)`` pairs.
    Shared across audit scripts to keep their ``render_report`` small.
    """
    when = started_at.strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"# {title} — {when}")
    lines.append("")
    lines.append("## Summary")
    for label, value in summary_items:
        lines.append(f"- {label}: {value}")
    if user_id_filter is not None:
        lines.append(f"- Filter user_id: {user_id_filter}")
    if exchange_filter is not None:
        lines.append(f"- Filter exchange: {exchange_filter}")
    lines.append("")
