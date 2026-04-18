"""Unit tests for ``scripts/reconcile_open_trades.py`` (Issue #198).

Exercises the script's public surface end-to-end with an in-memory
SQLite DB, a mocked ``RiskStateManager.reconcile``, and a temporary
report path.

Coverage targets:
* Dry-run: reconcile is called but no DB UPDATEs survive afterwards.
* Apply-mode: reconcile is called once per matching open trade and
  writes are kept.
* ``--user-id`` and ``--exchange`` filters narrow the trade set.
* ``NotImplementedError`` from the manager is reported as ``skipped``.
* ``select_open_trades`` does not pick up closed/cancelled rows.
* ``render_report`` produces well-formed Markdown.
"""
from __future__ import annotations

import importlib.util
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "reconcile_open_trades.py"

# Make src/ importable so the script's own imports resolve.
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def reconcile_module():
    """Import scripts/reconcile_open_trades.py as a module once."""
    spec = importlib.util.spec_from_file_location("reconcile_open_trades", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_open_trades"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── In-memory DB fixture ───────────────────────────────────────────────


@pytest_asyncio.fixture
async def memory_db():
    """Spin up an in-memory SQLite engine + session factory + seed users."""
    from src.models.database import Base, TradeRecord, User

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Seed two users + four trades (two open + two closed across 2 exchanges).
    async with maker() as session:
        u1 = User(username="u1", email="u1@x", password_hash="x", role="user", is_active=True)
        u2 = User(username="u2", email="u2@x", password_hash="x", role="user", is_active=True)
        session.add_all([u1, u2])
        await session.commit()
        await session.refresh(u1)
        await session.refresh(u2)

        now = datetime.now(timezone.utc)
        trades = [
            # Open trade for user1 on bitget — should always be picked up.
            TradeRecord(
                user_id=u1.id, exchange="bitget", symbol="BTCUSDT", side="long",
                size=0.01, entry_price=68200.0, leverage=10, confidence=80,
                reason="open user1 bitget", order_id="o1", status="open",
                entry_time=now, demo_mode=True,
                take_profit=None, stop_loss=None, risk_source="unknown",
            ),
            # Open trade for user2 on bingx.
            TradeRecord(
                user_id=u2.id, exchange="bingx", symbol="ETHUSDT", side="short",
                size=0.1, entry_price=3500.0, leverage=5, confidence=70,
                reason="open user2 bingx", order_id="o2", status="open",
                entry_time=now, demo_mode=False,
                take_profit=None, stop_loss=None, risk_source="unknown",
            ),
            # Closed trade — must not appear in the sweep.
            TradeRecord(
                user_id=u1.id, exchange="bitget", symbol="BTCUSDT", side="long",
                size=0.01, entry_price=68000.0, leverage=10, confidence=80,
                reason="closed", order_id="o3", status="closed",
                entry_time=now, exit_time=now, demo_mode=True,
            ),
            # Cancelled trade — must not appear in the sweep.
            TradeRecord(
                user_id=u2.id, exchange="bingx", symbol="ETHUSDT", side="short",
                size=0.1, entry_price=3400.0, leverage=5, confidence=70,
                reason="cancelled", order_id="o4", status="cancelled",
                entry_time=now, demo_mode=False,
            ),
        ]
        session.add_all(trades)
        await session.commit()
        for t in trades:
            await session.refresh(t)
        seeded_ids = {
            "open_bitget_user1": trades[0].id,
            "open_bingx_user2": trades[1].id,
            "closed": trades[2].id,
            "cancelled": trades[3].id,
        }

    yield engine, factory, seeded_ids
    await engine.dispose()


@pytest.fixture
def patched_session(memory_db, reconcile_module):
    """Route the script's ``get_session`` to the in-memory DB."""
    _engine, factory, _ids = memory_db
    with patch.object(reconcile_module, "get_session", factory):
        yield factory


# ── Helpers ────────────────────────────────────────────────────────────


def _make_snapshot(reconcile_module, trade_id: int, *, tp=None, tp_id=None, source="native_exchange"):
    """Build a RiskStateSnapshot the way the manager would return one."""
    from src.bot.risk_state_manager import RiskStateSnapshot
    return RiskStateSnapshot(
        trade_id=trade_id,
        tp={"value": tp, "status": "confirmed", "order_id": tp_id} if tp_id else None,
        sl=None,
        trailing=None,
        risk_source=source,
        last_synced_at=datetime.now(timezone.utc),
    )


# ── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_select_open_trades_only_returns_open_rows(memory_db, patched_session, reconcile_module):
    """Closed / cancelled rows MUST NOT appear in the sweep."""
    trades = await reconcile_module.select_open_trades(user_id=None, exchange=None)
    statuses = {t.status for t in trades}
    assert statuses == {"open"}
    assert len(trades) == 2


@pytest.mark.asyncio
async def test_filter_user_id_only_picks_that_user(memory_db, patched_session, reconcile_module):
    """``--user-id`` filter is honoured."""
    _, _, ids = memory_db
    trades = await reconcile_module.select_open_trades(
        user_id=1, exchange=None,  # u1 was seeded first → id=1
    )
    assert len(trades) == 1
    assert trades[0].id == ids["open_bitget_user1"]


@pytest.mark.asyncio
async def test_filter_exchange_only_picks_that_exchange(memory_db, patched_session, reconcile_module):
    """``--exchange`` filter is honoured."""
    _, _, ids = memory_db
    trades = await reconcile_module.select_open_trades(
        user_id=None, exchange="bingx",
    )
    assert len(trades) == 1
    assert trades[0].id == ids["open_bingx_user2"]


@pytest.mark.asyncio
async def test_dry_run_does_not_persist_changes(
    tmp_path, memory_db, patched_session, reconcile_module,
):
    """Dry-run: reconcile is called, but the DB returns to its pre-image."""
    _, factory, ids = memory_db

    # Reconcile pretends the exchange has a TP that the DB lacks.
    async def fake_reconcile(trade_id):
        # Caller writes through the manager — to mimic that, we use the
        # real session factory the script wired in:
        from src.models.database import TradeRecord
        async with factory() as session:
            t = await session.get(TradeRecord, trade_id)
            t.take_profit = 70246.0
            t.tp_order_id = "exch_tp_42"
            t.risk_source = "native_exchange"
            t.last_synced_at = datetime.now(timezone.utc)
            await session.commit()
        return _make_snapshot(reconcile_module, trade_id, tp=70246.0, tp_id="exch_tp_42")

    output = tmp_path / "report.md"
    with patch(
        "src.bot.risk_state_manager.RiskStateManager.reconcile",
        new=AsyncMock(side_effect=fake_reconcile),
    ):
        report = await reconcile_module.run_reconcile(
            user_id=None, exchange=None, apply_mode=False, verbose=False,
            output_path=output,
        )

    assert report.with_drift == 2
    assert report.corrected == 0  # dry-run never reports corrections

    # DB pre-image was restored — take_profit must NOT be persisted.
    from src.models.database import TradeRecord
    async with factory() as session:
        t = await session.get(TradeRecord, ids["open_bitget_user1"])
        assert t.take_profit is None
        assert t.tp_order_id is None
        assert t.risk_source == "unknown"


@pytest.mark.asyncio
async def test_apply_mode_calls_reconcile_per_open_trade(
    tmp_path, memory_db, patched_session, reconcile_module,
):
    """``--apply`` invokes ``manager.reconcile`` once for every open trade."""
    _, factory, ids = memory_db

    called_with: list[int] = []

    async def fake_reconcile(trade_id):
        called_with.append(trade_id)
        from src.models.database import TradeRecord
        async with factory() as session:
            t = await session.get(TradeRecord, trade_id)
            t.take_profit = 999.0
            t.risk_source = "native_exchange"
            t.last_synced_at = datetime.now(timezone.utc)
            await session.commit()
        return _make_snapshot(reconcile_module, trade_id, tp=999.0, tp_id="x")

    output = tmp_path / "applied.md"
    with patch(
        "src.bot.risk_state_manager.RiskStateManager.reconcile",
        new=AsyncMock(side_effect=fake_reconcile),
    ):
        report = await reconcile_module.run_reconcile(
            user_id=None, exchange=None, apply_mode=True, verbose=False,
            output_path=output,
        )

    assert sorted(called_with) == sorted([
        ids["open_bitget_user1"], ids["open_bingx_user2"],
    ])
    assert report.checked == 2
    assert report.with_drift == 2
    assert report.corrected == 2
    assert report.errors == 0

    # Apply-mode keeps the writes.
    from src.models.database import TradeRecord
    async with factory() as session:
        t = await session.get(TradeRecord, ids["open_bitget_user1"])
        assert t.take_profit == 999.0


@pytest.mark.asyncio
async def test_filter_user_id_passed_to_select(
    tmp_path, memory_db, patched_session, reconcile_module,
):
    """--user-id end-to-end: only that user's trade is reconciled."""
    _, _, ids = memory_db
    called_with: list[int] = []

    async def fake_reconcile(trade_id):
        called_with.append(trade_id)
        return _make_snapshot(reconcile_module, trade_id, source="software_bot")

    output = tmp_path / "user.md"
    with patch(
        "src.bot.risk_state_manager.RiskStateManager.reconcile",
        new=AsyncMock(side_effect=fake_reconcile),
    ):
        report = await reconcile_module.run_reconcile(
            user_id=1, exchange=None, apply_mode=True, verbose=True,
            output_path=output,
        )

    assert called_with == [ids["open_bitget_user1"]]
    assert report.checked == 1


@pytest.mark.asyncio
async def test_filter_exchange_passed_to_select(
    tmp_path, memory_db, patched_session, reconcile_module,
):
    """--exchange end-to-end: only that exchange's trade is reconciled."""
    _, _, ids = memory_db
    called_with: list[int] = []

    async def fake_reconcile(trade_id):
        called_with.append(trade_id)
        return _make_snapshot(reconcile_module, trade_id, source="software_bot")

    output = tmp_path / "exch.md"
    with patch(
        "src.bot.risk_state_manager.RiskStateManager.reconcile",
        new=AsyncMock(side_effect=fake_reconcile),
    ):
        report = await reconcile_module.run_reconcile(
            user_id=None, exchange="bingx", apply_mode=True, verbose=True,
            output_path=output,
        )

    assert called_with == [ids["open_bingx_user2"]]
    assert report.checked == 1


@pytest.mark.asyncio
async def test_not_implemented_error_appears_as_skipped(
    tmp_path, memory_db, patched_session, reconcile_module,
):
    """NotImplementedError from manager → outcome.skipped_reason set, not an error."""
    output = tmp_path / "skipped.md"
    with patch(
        "src.bot.risk_state_manager.RiskStateManager.reconcile",
        new=AsyncMock(side_effect=NotImplementedError("weex has no probe")),
    ):
        report = await reconcile_module.run_reconcile(
            user_id=None, exchange=None, apply_mode=False, verbose=True,
            output_path=output,
        )

    assert report.skipped == 2
    assert report.errors == 0
    assert report.with_drift == 0
    text = output.read_text(encoding="utf-8")
    assert "## Skipped" in text
    assert "exchange not supported" in text


@pytest.mark.asyncio
async def test_arbitrary_exception_appears_as_error(
    tmp_path, memory_db, patched_session, reconcile_module,
):
    """Unexpected exceptions surface in the Errors section."""
    output = tmp_path / "errors.md"
    with patch(
        "src.bot.risk_state_manager.RiskStateManager.reconcile",
        new=AsyncMock(side_effect=RuntimeError("api down")),
    ):
        report = await reconcile_module.run_reconcile(
            user_id=None, exchange=None, apply_mode=False, verbose=True,
            output_path=output,
        )

    assert report.errors == 2
    assert report.skipped == 0
    text = output.read_text(encoding="utf-8")
    assert "## Errors" in text
    assert "RuntimeError" in text
    assert "api down" in text


def test_render_report_emits_markdown_sections(reconcile_module):
    """``render_report`` formats the headline, summary, drift table, etc."""
    identity = reconcile_module.TradeIdentity(
        trade_id=207, user_id=1, exchange="bitget",
        symbol="BTCUSDT", side="long", demo_mode=True,
    )
    outcome = reconcile_module.TradeOutcome(
        identity=identity,
        drift={
            "tp_order_id": (None, "1428"),
            "risk_source": ("unknown", "native_exchange"),
        },
    )
    report = reconcile_module.ReconcileReport(
        started_at=datetime(2026, 4, 18, 12, 34, tzinfo=timezone.utc),
        apply_mode=True,
        user_id_filter=None,
        exchange_filter=None,
        outcomes=[outcome],
    )
    text = reconcile_module.render_report(report)

    assert "# Reconcile Report — 2026-04-18 12:34 UTC" in text
    assert "## Summary" in text
    assert "Trades geprüft: 1" in text
    assert "Mit Drift: 1" in text
    assert "Korrigiert (--apply): 1" in text
    assert "## Drift-Trades" in text
    assert "Trade #207" in text
    assert "BTCUSDT long" in text
    assert "user=1" in text
    assert "bitget demo" in text
    # Table contains both diffed fields.
    assert "tp_order_id" in text
    assert "risk_source" in text
    assert "native_exchange" in text


def test_render_report_dry_run_marks_apply_column(reconcile_module):
    """Dry-run mode renders ``(dry-run)`` in the apply column."""
    identity = reconcile_module.TradeIdentity(
        trade_id=210, user_id=2, exchange="bingx",
        symbol="ETHUSDT", side="short", demo_mode=False,
    )
    outcome = reconcile_module.TradeOutcome(
        identity=identity,
        drift={"take_profit": (None, 3300.5)},
    )
    report = reconcile_module.ReconcileReport(
        started_at=datetime(2026, 4, 18, 13, 0, tzinfo=timezone.utc),
        apply_mode=False,
        user_id_filter=None,
        exchange_filter=None,
        outcomes=[outcome],
    )
    text = reconcile_module.render_report(report)

    assert "Korrigiert (--apply): 0 (dry-run)" in text
    assert "(dry-run)" in text


def test_render_report_includes_filter_summary(reconcile_module):
    """Filters are echoed back in the summary so the report is self-describing."""
    report = reconcile_module.ReconcileReport(
        started_at=datetime(2026, 4, 18, 14, 0, tzinfo=timezone.utc),
        apply_mode=False,
        user_id_filter=4,
        exchange_filter="bitget",
        outcomes=[],
    )
    text = reconcile_module.render_report(report)
    assert "Filter user_id: 4" in text
    assert "Filter exchange: bitget" in text


def test_render_report_verbose_shows_clean_trades(reconcile_module):
    """When verbose=True, clean (no-drift) trades appear in their own section."""
    identity_clean = reconcile_module.TradeIdentity(
        trade_id=300, user_id=1, exchange="bitget",
        symbol="BTCUSDT", side="long", demo_mode=True,
    )
    clean_outcome = reconcile_module.TradeOutcome(identity=identity_clean)  # no drift/error/skip
    report = reconcile_module.ReconcileReport(
        started_at=datetime(2026, 4, 18, 14, 0, tzinfo=timezone.utc),
        apply_mode=False,
        user_id_filter=None,
        exchange_filter=None,
        outcomes=[clean_outcome],
        verbose=True,
    )
    text = reconcile_module.render_report(report)
    assert "## Clean (no drift)" in text
    assert "Trade #300" in text


def test_render_report_non_verbose_hides_clean_trades(reconcile_module):
    """When verbose=False, clean trades do not pollute the report body."""
    identity_clean = reconcile_module.TradeIdentity(
        trade_id=300, user_id=1, exchange="bitget",
        symbol="BTCUSDT", side="long", demo_mode=True,
    )
    clean_outcome = reconcile_module.TradeOutcome(identity=identity_clean)
    report = reconcile_module.ReconcileReport(
        started_at=datetime(2026, 4, 18, 14, 0, tzinfo=timezone.utc),
        apply_mode=False,
        user_id_filter=None,
        exchange_filter=None,
        outcomes=[clean_outcome],
        verbose=False,
    )
    text = reconcile_module.render_report(report)
    assert "## Clean" not in text
    assert "Trade #300" not in text


def test_default_report_path_uses_timestamp(reconcile_module):
    """Default path slot is ``reports/reconcile-<stamp>.md``."""
    when = datetime(2026, 4, 18, 12, 34, tzinfo=timezone.utc)
    path = reconcile_module.default_report_path(when)
    assert path.parent.name == "reports"
    assert path.name == "reconcile-2026-04-18-1234.md"


def test_diff_snapshots_only_returns_changed_fields(reconcile_module):
    """``diff_snapshots`` is used to build the drift table — must be precise."""
    before = {f: None for f in reconcile_module.DRIFT_FIELDS}
    before["take_profit"] = 100.0
    before["risk_source"] = "unknown"
    after = dict(before)
    after["risk_source"] = "native_exchange"
    after["tp_order_id"] = "abc"

    diff = reconcile_module.diff_snapshots(before, after)
    assert set(diff.keys()) == {"risk_source", "tp_order_id"}
    assert diff["risk_source"] == ("unknown", "native_exchange")
    assert diff["tp_order_id"] == (None, "abc")


def test_parse_args_defaults_match_dry_run(reconcile_module):
    """Argparse defaults must match the documented behaviour."""
    args = reconcile_module.parse_args([])
    assert args.apply is False
    assert args.yes is False
    assert args.verbose is False
    assert args.user_id is None
    assert args.exchange is None
    assert args.output is None


def test_parse_args_accepts_all_flags(reconcile_module):
    """Smoke-test that every advertised flag round-trips through argparse."""
    args = reconcile_module.parse_args([
        "--user-id", "4",
        "--exchange", "bitget",
        "--apply",
        "--yes",
        "--verbose",
        "--output", "/tmp/r.md",
    ])
    assert args.user_id == 4
    assert args.exchange == "bitget"
    assert args.apply is True
    assert args.yes is True
    assert args.verbose is True
    assert args.output == "/tmp/r.md"


def test_confirm_apply_accepts_y(reconcile_module):
    """Confirmation prompt: ``y`` / ``yes`` mean go-ahead."""
    import io
    out = io.StringIO()
    assert reconcile_module.confirm_apply(io.StringIO("y\n"), out) is True
    assert reconcile_module.confirm_apply(io.StringIO("yes\n"), out) is True


def test_confirm_apply_rejects_other(reconcile_module):
    """Confirmation prompt: anything else aborts."""
    import io
    out = io.StringIO()
    assert reconcile_module.confirm_apply(io.StringIO("\n"), out) is False
    assert reconcile_module.confirm_apply(io.StringIO("n\n"), out) is False
    assert reconcile_module.confirm_apply(io.StringIO("nope\n"), out) is False
