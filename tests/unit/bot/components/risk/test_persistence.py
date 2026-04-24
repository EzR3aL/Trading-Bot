"""Unit tests for ``RiskStatePersistence`` (ARCH-H2 Phase 1 PR-7, #326).

These tests lock the contract the RiskStatePersistence component must
meet in isolation — independent of the ``RiskManager`` façade that
delegates to it. Characterization tests in
``tests/unit/bot/test_risk_state_manager_characterization.py`` cover
the façade-level wiring; this module covers the component directly.

Contracts covered:

1. **Enabled gate** — ``enabled`` is ``True`` iff both ``bot_config_id``
   and ``session_factory`` are provided; all three methods short-circuit
   to their empty-return when disabled.
2. **Round-trip** — ``save_stats`` then ``load_stats`` yields a
   byte-equal ``DailyStats`` (via ``to_dict`` comparison). This is the
   load/save invariant for #188 DB truth-source.
3. **Computed-fields strip on load** — the three ``@property`` fields
   (``net_pnl`` / ``return_percent`` / ``win_rate``) are stripped from
   the JSON blob before the dataclass constructor runs.
4. **Upsert semantics** — ``save_stats`` UPDATES on an existing row,
   INSERTS on a missing row.
5. **Exception swallow on all three code paths** — load returns
   ``None``, save returns silently, historical returns ``[]``, on any
   raise from the session.
6. **Historical happy path** — parses every row's ``stats_json`` and
   returns the list newest-first.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent.parent))

from src.bot.components.risk.persistence import (
    RiskStatePersistence,
    _COMPUTED_DAILYSTATS_FIELDS,
)
from src.risk.risk_manager import DailyStats


# ---------------------------------------------------------------------------
# Fake async session + factory — mirrors the pattern in the characterization
# tests so the persistence tests stay consistent with the existing suite.
# ---------------------------------------------------------------------------


class _FakeQueryResult:
    """Minimal stand-in for a SQLAlchemy result with ``scalar_one_or_none``."""

    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeMultiResult:
    """Stand-in for the list-result used by ``get_historical_stats``."""

    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        class _S:
            def __init__(self_inner, rows):
                self_inner._rows = rows

            def all(self_inner):
                return self_inner._rows

        return _S(self._rows)


class _FakeSession:
    """Async-context-manager session stand-in."""

    def __init__(
        self,
        row=None,
        rows=None,
        raises: Exception | None = None,
        multi: bool = False,
    ):
        self._row = row
        self._rows = rows or []
        self._raises = raises
        self._multi = multi
        self.added: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _stmt):
        if self._raises is not None:
            raise self._raises
        if self._multi:
            return _FakeMultiResult(self._rows)
        return _FakeQueryResult(self._row)

    def add(self, row):
        self.added.append(row)


def _factory(session: _FakeSession):
    """Return a callable ``() -> session`` — matches the ``get_session()`` shape."""
    def _f():
        return session
    return _f


def _make_dailystats(**overrides) -> DailyStats:
    """Build a fresh ``DailyStats`` with safe defaults for round-trip tests."""
    base = dict(
        date=datetime.now().strftime("%Y-%m-%d"),
        starting_balance=10_000.0,
        current_balance=10_100.0,
        trades_executed=3,
        winning_trades=2,
        losing_trades=1,
        total_pnl=150.0,
        total_fees=10.0,
        total_funding=5.0,
        max_drawdown=2.5,
        is_trading_halted=False,
        halt_reason="",
        symbol_trades={"BTCUSDT": 2, "ETHUSDT": 1},
        symbol_pnl={"BTCUSDT": 150.0, "ETHUSDT": 0.0},
        halted_symbols={},
    )
    base.update(overrides)
    return DailyStats(**base)


# ---------------------------------------------------------------------------
# Enabled-gate: disabled instances no-op on every method
# ---------------------------------------------------------------------------


class TestEnabledGate:
    """``enabled`` is the single source of truth for DB-touching methods."""

    def test_disabled_when_no_bot_config_id(self):
        p = RiskStatePersistence(bot_config_id=None, session_factory=_factory(_FakeSession()))
        assert p.enabled is False

    def test_disabled_when_no_session_factory(self):
        p = RiskStatePersistence(bot_config_id=42, session_factory=None)
        assert p.enabled is False

    def test_enabled_when_both_present(self):
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(_FakeSession()))
        assert p.enabled is True

    @pytest.mark.asyncio
    async def test_load_stats_returns_none_when_disabled(self):
        p = RiskStatePersistence(bot_config_id=None, session_factory=None)
        assert await p.load_stats() is None

    @pytest.mark.asyncio
    async def test_save_stats_is_noop_when_disabled(self):
        """Disabled save must NOT hit the DB. We pass a session that would
        raise if touched — if the no-op path is broken, this test raises."""
        session = _FakeSession(raises=RuntimeError("must not be called"))
        p = RiskStatePersistence(bot_config_id=None, session_factory=_factory(session))
        # Must NOT raise.
        await p.save_stats(_make_dailystats())

    @pytest.mark.asyncio
    async def test_save_stats_noop_when_stats_is_none(self):
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(_FakeSession()))
        # None stats is also a no-op even when enabled.
        await p.save_stats(None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_get_historical_stats_returns_empty_when_disabled(self):
        p = RiskStatePersistence(bot_config_id=None, session_factory=None)
        assert await p.get_historical_stats(days=30) == []


# ---------------------------------------------------------------------------
# Load path — happy + edge cases + computed-fields strip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLoadStats:
    """Freezes the load path including the computed-fields strip."""

    async def test_loads_row_and_reconstructs_dailystats(self):
        today = datetime.now().strftime("%Y-%m-%d")
        blob = {
            "date": today,
            "starting_balance": 10_000.0,
            "current_balance": 10_100.0,
            "trades_executed": 2,
            "winning_trades": 1,
            "losing_trades": 1,
            "total_pnl": 150.0,
            "total_fees": 10.0,
            "total_funding": 5.0,
            "max_drawdown": 2.5,
            "is_trading_halted": False,
            "halt_reason": "",
            "symbol_trades": {"BTCUSDT": 2},
            "symbol_pnl": {"BTCUSDT": 150.0},
            "halted_symbols": {},
            # Computed @property fields — MUST be stripped before __init__
            "net_pnl": 135.0,
            "return_percent": 1.35,
            "win_rate": 50.0,
        }
        row = MagicMock()
        row.stats_json = json.dumps(blob)
        session = _FakeSession(row=row)
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))

        stats = await p.load_stats()
        assert stats is not None
        assert isinstance(stats, DailyStats)
        assert stats.trades_executed == 2
        assert stats.starting_balance == 10_000.0
        assert stats.symbol_trades == {"BTCUSDT": 2}
        # Computed re-derived from raw counters, not the stale blob values.
        assert stats.net_pnl == pytest.approx(150.0 - 10.0 - 5.0)

    async def test_returns_none_on_missing_row(self):
        """No row for today → return None (caller initialises a fresh day)."""
        session = _FakeSession(row=None)
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))
        assert await p.load_stats() is None

    async def test_strips_all_three_computed_fields(self):
        """Explicit lock on the strip list. If a future refactor drops
        ``win_rate`` from the strip-set, the ``DailyStats(**data)`` call
        raises ``TypeError: unexpected keyword argument``."""
        today = datetime.now().strftime("%Y-%m-%d")
        # Verify the constant matches the three DailyStats @property names.
        assert set(_COMPUTED_DAILYSTATS_FIELDS) == {
            "net_pnl",
            "return_percent",
            "win_rate",
        }
        blob = {
            "date": today,
            "starting_balance": 1.0,
            "current_balance": 1.0,
            "trades_executed": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "total_funding": 0.0,
            "max_drawdown": 0.0,
            "is_trading_halted": False,
            "halt_reason": "",
            "symbol_trades": {},
            "symbol_pnl": {},
            "halted_symbols": {},
            # All three computed fields present — must not crash DailyStats().
            "net_pnl": 999.0,
            "return_percent": 999.0,
            "win_rate": 999.0,
        }
        row = MagicMock()
        row.stats_json = json.dumps(blob)
        session = _FakeSession(row=row)
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))
        stats = await p.load_stats()
        assert stats is not None
        # Computed values come from the raw counters (all zero), not the blob.
        assert stats.net_pnl == 0.0
        assert stats.return_percent == 0.0
        assert stats.win_rate == 0.0

    async def test_swallows_exception_and_returns_none(self):
        """Any raise from the session path → logged warning, return None."""
        session = _FakeSession(raises=RuntimeError("DB down"))
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))
        assert await p.load_stats() is None  # must NOT raise

    async def test_swallows_json_decode_error(self):
        """Corrupt ``stats_json`` blob → swallowed, returns None."""
        row = MagicMock()
        row.stats_json = "not-valid-json{{"
        session = _FakeSession(row=row)
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))
        assert await p.load_stats() is None


# ---------------------------------------------------------------------------
# Save path — happy (insert + update) + exception swallow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSaveStats:
    """Freezes the upsert semantics and exception-swallow contract."""

    async def test_inserts_new_row_when_none_exists(self):
        session = _FakeSession(row=None)
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))
        stats = _make_dailystats()
        await p.save_stats(stats)
        assert len(session.added) == 1
        added = session.added[0]
        assert added.bot_config_id == 42
        assert added.date == stats.date
        assert added.trades_count == stats.trades_executed
        assert added.daily_pnl == pytest.approx(stats.net_pnl)
        assert added.is_halted is stats.is_trading_halted

    async def test_updates_existing_row_without_insert(self):
        existing = MagicMock()
        session = _FakeSession(row=existing)
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))
        stats = _make_dailystats(trades_executed=7, is_trading_halted=True)
        await p.save_stats(stats)
        # No INSERT — update path mutates the existing row.
        assert session.added == []
        assert existing.trades_count == 7
        assert existing.is_halted is True
        assert existing.daily_pnl == pytest.approx(stats.net_pnl)

    async def test_inserted_blob_roundtrips_via_load(self):
        """End-to-end: save → read the inserted row's ``stats_json`` back
        through ``load_stats`` and confirm byte-identical ``to_dict``."""
        session_save = _FakeSession(row=None)
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session_save))
        original = _make_dailystats()
        await p.save_stats(original)
        assert len(session_save.added) == 1
        inserted = session_save.added[0]

        # Hand the inserted row to the load path via a second fake session.
        load_row = MagicMock()
        load_row.stats_json = inserted.stats_json
        session_load = _FakeSession(row=load_row)
        p2 = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session_load))
        loaded = await p2.load_stats()
        assert loaded is not None
        # Compare via to_dict — the DailyStats dataclass does not implement __eq__.
        assert loaded.to_dict() == original.to_dict()

    async def test_swallows_exception_on_save(self):
        """DB-write failure is swallowed — caller never sees the error."""
        session = _FakeSession(raises=RuntimeError("write rejected"))
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))
        # Must NOT raise.
        await p.save_stats(_make_dailystats())

    async def test_serialises_net_pnl_into_row(self):
        """The ``daily_pnl`` column must reflect ``stats.net_pnl``
        (total_pnl − fees − funding), not ``total_pnl``."""
        session = _FakeSession(row=None)
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))
        stats = _make_dailystats(total_pnl=100.0, total_fees=5.0, total_funding=-20.0)
        await p.save_stats(stats)
        assert session.added[0].daily_pnl == pytest.approx(100.0 - 5.0 - (-20.0))


# ---------------------------------------------------------------------------
# Historical read path — parses + swallows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetHistoricalStats:
    """Freezes the historical read path."""

    async def test_returns_parsed_rows_in_order(self):
        row1 = MagicMock()
        row1.stats_json = json.dumps({"date": "2026-04-20", "trades_executed": 3})
        row2 = MagicMock()
        row2.stats_json = json.dumps({"date": "2026-04-19", "trades_executed": 5})
        session = _FakeSession(rows=[row1, row2], multi=True)
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))

        rows = await p.get_historical_stats(days=30)
        assert len(rows) == 2
        assert rows[0]["trades_executed"] == 3
        assert rows[1]["trades_executed"] == 5

    async def test_returns_empty_list_when_no_rows(self):
        session = _FakeSession(rows=[], multi=True)
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))
        assert await p.get_historical_stats(days=30) == []

    async def test_swallows_exception_and_returns_empty(self):
        session = _FakeSession(raises=RuntimeError("db gone"))
        p = RiskStatePersistence(bot_config_id=42, session_factory=_factory(session))
        assert await p.get_historical_stats(days=30) == []


# ---------------------------------------------------------------------------
# Protocol conformance — isinstance check against the runtime_checkable
# Protocol from ``src/bot/components/risk/protocols.py``.
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_runtime_checkable_protocol(self):
        from src.bot.components.risk.protocols import RiskStatePersistenceProtocol

        p = RiskStatePersistence(bot_config_id=None, session_factory=None)
        assert isinstance(p, RiskStatePersistenceProtocol)


# ---------------------------------------------------------------------------
# DailyStats class injection — lets the component be tested without
# importing the real DailyStats class. Guard the indirection works.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDailyStatsClassInjection:
    """Locks the ``dailystats_cls`` override seam used in isolated unit tests."""

    async def test_uses_injected_class_on_load(self):
        sentinel = MagicMock()
        sentinel.return_value = "sentinel-instance"
        today = datetime.now().strftime("%Y-%m-%d")
        blob = {
            "date": today,
            "starting_balance": 1.0,
            "current_balance": 1.0,
            "trades_executed": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "total_funding": 0.0,
            "max_drawdown": 0.0,
            "is_trading_halted": False,
            "halt_reason": "",
            "symbol_trades": {},
            "symbol_pnl": {},
            "halted_symbols": {},
        }
        row = MagicMock()
        row.stats_json = json.dumps(blob)
        session = _FakeSession(row=row)
        p = RiskStatePersistence(
            bot_config_id=42,
            session_factory=_factory(session),
            dailystats_cls=sentinel,
        )
        # logger.info call on the result needs .trades_executed + .net_pnl,
        # so we patch those as MagicMock attrs on the returned sentinel.
        sentinel_instance = MagicMock()
        sentinel_instance.trades_executed = 0
        sentinel_instance.net_pnl = 0.0
        sentinel.return_value = sentinel_instance

        result = await p.load_stats()
        assert result is sentinel_instance
        sentinel.assert_called_once()

    async def test_falls_back_to_module_dailystats_when_not_injected(self):
        """When ``dailystats_cls`` is not provided, the lazy lookup
        resolves ``src.risk.risk_manager.DailyStats`` (proves the import
        cycle guard still works)."""
        from src.risk.risk_manager import DailyStats as _real_cls

        today = datetime.now().strftime("%Y-%m-%d")
        blob = {
            "date": today,
            "starting_balance": 1.0,
            "current_balance": 1.0,
            "trades_executed": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "total_funding": 0.0,
            "max_drawdown": 0.0,
            "is_trading_halted": False,
            "halt_reason": "",
            "symbol_trades": {},
            "symbol_pnl": {},
            "halted_symbols": {},
        }
        row = MagicMock()
        row.stats_json = json.dumps(blob)
        session = _FakeSession(row=row)
        p = RiskStatePersistence(
            bot_config_id=42,
            session_factory=_factory(session),
            # dailystats_cls deliberately omitted
        )
        stats = await p.load_stats()
        assert stats is not None
        assert isinstance(stats, _real_cls)


# ---------------------------------------------------------------------------
# Integration-lite: via RiskManager façade with patched get_session.
# Complements the characterization tests by asserting the delegation
# surface is thin (no extra mutations of ``_daily_stats`` beyond the
# contract).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRiskManagerDelegationSurface:
    """Regression guard on the façade's delegation to RiskStatePersistence."""

    async def test_load_via_facade_assigns_stats(self):
        from src.risk.risk_manager import RiskManager

        today = datetime.now().strftime("%Y-%m-%d")
        blob = {
            "date": today,
            "starting_balance": 5_000.0,
            "current_balance": 5_000.0,
            "trades_executed": 1,
            "winning_trades": 1,
            "losing_trades": 0,
            "total_pnl": 100.0,
            "total_fees": 1.0,
            "total_funding": 0.0,
            "max_drawdown": 0.0,
            "is_trading_halted": False,
            "halt_reason": "",
            "symbol_trades": {"BTCUSDT": 1},
            "symbol_pnl": {"BTCUSDT": 100.0},
            "halted_symbols": {},
        }
        row = MagicMock()
        row.stats_json = json.dumps(blob)
        session = _FakeSession(row=row)

        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        with patch("src.risk.risk_manager.get_session", _factory(session)):
            await rm.load_stats_from_db()

        stats = rm.get_daily_stats()
        assert stats is not None
        assert stats.trades_executed == 1
        assert stats.starting_balance == 5_000.0

    async def test_load_miss_leaves_facade_stats_none(self):
        from src.risk.risk_manager import RiskManager

        session = _FakeSession(row=None)
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        with patch("src.risk.risk_manager.get_session", _factory(session)):
            await rm.load_stats_from_db()
        assert rm.get_daily_stats() is None

    async def test_save_via_facade_delegates_and_upserts(self):
        """Happy path: façade ``_save_stats_to_db`` delegates to the
        persistence component and the upsert INSERT path runs."""
        from src.risk.risk_manager import RiskManager

        session = _FakeSession(row=None)
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        rm.initialize_day(10_000.0)
        with patch("src.risk.risk_manager.get_session", _factory(session)):
            await rm._save_stats_to_db()
        assert len(session.added) == 1

    async def test_historical_via_facade_delegates(self):
        """``get_historical_stats_from_db`` delegates to the persistence
        component and returns parsed rows."""
        from src.risk.risk_manager import RiskManager

        row1 = MagicMock()
        row1.stats_json = json.dumps({"date": "2026-04-20", "trades_executed": 3})
        session = _FakeSession(rows=[row1], multi=True)
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        with patch("src.risk.risk_manager.get_session", _factory(session)):
            rows = await rm.get_historical_stats_from_db(days=7)
        assert len(rows) == 1
        assert rows[0]["trades_executed"] == 3

    async def test_historical_facade_noop_when_db_disabled(self):
        from src.risk.risk_manager import RiskManager

        rm = RiskManager(bot_config_id=None)  # _use_db = False
        rows = await rm.get_historical_stats_from_db(days=7)
        assert rows == []

    async def test_save_facade_noop_when_no_stats(self):
        """Delegator short-circuits when stats is None even if _use_db=True."""
        from src.risk.risk_manager import RiskManager

        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        # initialize_day NOT called → _daily_stats is None
        session = _FakeSession(raises=RuntimeError("must not be called"))
        with patch("src.risk.risk_manager.get_session", _factory(session)):
            # Must NOT raise — delegator short-circuits before DB.
            await rm._save_stats_to_db()

    async def test_save_daily_stats_running_loop_schedules_task(self):
        """``_save_daily_stats`` in async context schedules a task via
        ``loop.create_task``. Covers the happy-path branch of the sync
        scheduling wrapper."""
        import asyncio

        from src.risk.risk_manager import RiskManager

        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        # initialize_day inside an async context ALSO fires _save_daily_stats;
        # create the stats directly so we isolate just the wrapper call.
        rm._daily_stats_aggregator.hydrate(_make_dailystats())

        session = _FakeSession(row=None)
        with patch("src.risk.risk_manager.get_session", _factory(session)):
            # Inside an async test, get_running_loop() succeeds; the scheduled
            # task runs on the next event-loop tick.
            rm._save_daily_stats()
            # Let the scheduled task run.
            await asyncio.sleep(0)

        # Exactly one INSERT went through.
        assert len(session.added) == 1

# ---------------------------------------------------------------------------
# Micro-coverage top-ups on the RiskManager façade — lines that the
# pre-extraction test file hit via the inline DB code and that the
# delegation surface no longer exercises. Keeps the ≥85% gate green.
# ---------------------------------------------------------------------------


class TestFacadeBranchCoverage:
    """Small, targeted branches on ``RiskManager`` that are not the
    primary responsibility of any component — lock them here so the
    extraction PR does not regress coverage."""

    def test_save_daily_stats_no_running_loop_logs_debug(self):
        """Without an event loop the RuntimeError branch of
        ``_save_daily_stats`` is taken and a debug log is emitted — no
        raise, no side-effect on ``_daily_stats``. Covers the
        ``except RuntimeError`` sync-scheduling fallback."""
        from src.risk.risk_manager import RiskManager

        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        rm.initialize_day(10_000.0)
        # Call outside any event loop — must NOT raise.
        rm._save_daily_stats()
        # Stats still intact.
        assert rm.get_daily_stats() is not None

    def test_remaining_trades_per_symbol_override_before_init(self):
        """Per-symbol override with no stats yet → returns ``effective_max``
        (line 582 in ``risk_manager.py``)."""
        from src.risk.risk_manager import RiskManager

        rm = RiskManager(
            bot_config_id=None,
            per_symbol_limits={"BTCUSDT": {"max_trades": 4}},
        )
        # No initialize_day → _daily_stats is None
        assert rm.get_remaining_trades(symbol="BTCUSDT") == 4

    def test_get_historical_stats_sync_always_returns_empty(self):
        """The deprecated sync ``get_historical_stats`` method is now a
        stub that returns ``[]`` — locked as line 607."""
        from src.risk.risk_manager import RiskManager

        rm = RiskManager(bot_config_id=None)
        assert rm.get_historical_stats(days=30) == []

    def test_get_performance_summary_empty_history_returns_zeros(self):
        """Empty ``get_historical_stats`` → the zero-filled summary dict."""
        from src.risk.risk_manager import RiskManager

        rm = RiskManager(bot_config_id=None)
        summary = rm.get_performance_summary(days=30)
        assert summary["period_days"] == 0
        assert summary["total_trades"] == 0
        assert summary["win_rate"] == 0.0
        assert summary["sharpe_estimate"] == 0.0

    def test_return_percent_zero_starting_balance(self):
        """Edge: ``starting_balance == 0`` → ``return_percent`` returns 0.0
        (line 64). Covers the divide-by-zero guard directly."""
        from src.risk.risk_manager import DailyStats

        stats = DailyStats(
            date="2026-04-24",
            starting_balance=0.0,
            current_balance=0.0,
            trades_executed=0,
            winning_trades=0,
            losing_trades=0,
            total_pnl=100.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
        )
        assert stats.return_percent == 0.0
