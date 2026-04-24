"""Focused unit tests for :mod:`src.bot.components.risk.daily_stats` (#326 PR-5).

The Phase-0 characterization tests (``test_risk_state_manager_characterization.py``)
freeze the *observable* behaviour through the :class:`RiskManager` façade.
These tests exercise the aggregator in isolation so a future refactor
that swaps the façade wiring still verifies the aggregator's own
contracts.

Coverage:

* ``initialize_day`` — fresh state, same-day idempotency (the midnight
  reset is implicit via the date check), new-day replacement.
* ``get_daily_stats`` — ``None`` before init, snapshot identity after.
* ``record_entry`` / ``record_exit`` — pure counter + PnL mutation,
  pre-init safety, win/loss split, max-drawdown update.
* ``hydrate`` — replaces snapshot with caller-provided dataclass.
* ``hydrate_from_dict`` — strips the three computed fields (``net_pnl``
  / ``return_percent`` / ``win_rate``) before dataclass construction;
  round-trip with ``DailyStats.to_dict()`` works in both directions.
* Computed ``@property`` fields behave consistently with raw counters.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from src.bot.components.risk.daily_stats import (
    DailyStats,
    DailyStatsAggregator,
)


# ---------------------------------------------------------------------------
# DailyStats dataclass + computed-field behaviour
# ---------------------------------------------------------------------------


class TestDailyStatsComputedFields:
    """Lock the @property math so the persistence-strip helper stays justified."""

    def _make(self, **overrides) -> DailyStats:
        defaults = dict(
            date="2026-04-24",
            starting_balance=10_000.0,
            current_balance=10_000.0,
            trades_executed=0,
            winning_trades=0,
            losing_trades=0,
            total_pnl=0.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
        )
        defaults.update(overrides)
        return DailyStats(**defaults)

    def test_net_pnl_subtracts_fees_and_funding(self):
        stats = self._make(total_pnl=100.0, total_fees=5.0, total_funding=2.0)
        assert stats.net_pnl == pytest.approx(93.0)

    def test_net_pnl_adds_back_negative_funding(self):
        """Negative funding = funding received → boosts net_pnl."""
        stats = self._make(total_pnl=50.0, total_fees=1.0, total_funding=-10.0)
        assert stats.net_pnl == pytest.approx(59.0)

    def test_return_percent_zero_when_starting_balance_is_zero(self):
        stats = self._make(starting_balance=0.0, total_pnl=100.0)
        assert stats.return_percent == 0.0

    def test_return_percent_computes_against_starting_balance(self):
        stats = self._make(total_pnl=250.0, starting_balance=10_000.0)
        assert stats.return_percent == pytest.approx(2.5)

    def test_win_rate_zero_when_no_closed_trades(self):
        stats = self._make()
        assert stats.win_rate == 0.0

    def test_win_rate_percentage(self):
        stats = self._make(winning_trades=3, losing_trades=1)
        assert stats.win_rate == pytest.approx(75.0)

    def test_to_dict_includes_computed_fields(self):
        """``to_dict`` emits the computed fields — the persistence layer
        serialises this; ``hydrate_from_dict`` must strip them on load."""
        stats = self._make(total_pnl=100.0, total_fees=5.0, winning_trades=1)
        d = stats.to_dict()
        assert "net_pnl" in d
        assert "return_percent" in d
        assert "win_rate" in d
        assert d["net_pnl"] == pytest.approx(95.0)


# ---------------------------------------------------------------------------
# DailyStatsAggregator — lifecycle
# ---------------------------------------------------------------------------


class TestAggregatorLifecycle:
    def test_get_daily_stats_returns_none_before_init(self):
        agg = DailyStatsAggregator()
        assert agg.get_daily_stats() is None

    def test_initialize_day_creates_zeroed_snapshot(self):
        agg = DailyStatsAggregator()
        stats = agg.initialize_day(starting_balance=10_000.0)

        assert isinstance(stats, DailyStats)
        assert stats.date == datetime.now().strftime("%Y-%m-%d")
        assert stats.starting_balance == 10_000.0
        assert stats.current_balance == 10_000.0
        assert stats.trades_executed == 0
        assert stats.winning_trades == 0
        assert stats.losing_trades == 0
        assert stats.total_pnl == 0.0
        assert stats.total_fees == 0.0
        assert stats.total_funding == 0.0
        assert stats.max_drawdown == 0.0
        assert stats.is_trading_halted is False
        assert stats.halt_reason == ""
        assert stats.symbol_trades == {}
        assert stats.symbol_pnl == {}
        assert stats.halted_symbols == {}

    def test_initialize_day_is_idempotent_same_day(self):
        """Safe against bot restarts within the day — counters preserved,
        starting_balance NOT overwritten on same-day re-init."""
        agg = DailyStatsAggregator()
        first = agg.initialize_day(10_000.0)
        first.trades_executed = 3
        first.total_pnl = 50.0

        second = agg.initialize_day(99_999.0)

        assert second is first  # same object identity
        assert second.trades_executed == 3
        assert second.total_pnl == 50.0
        assert second.starting_balance == 10_000.0

    def test_initialize_day_replaces_snapshot_on_new_day(self):
        """Midnight reset trigger: when ``date`` changes the aggregator
        replaces the snapshot. We force this by manually flipping the
        stored date to yesterday and re-calling initialize_day."""
        agg = DailyStatsAggregator()
        old = agg.initialize_day(10_000.0)
        old.trades_executed = 7
        old.date = "1999-01-01"  # force the "different day" branch

        new = agg.initialize_day(20_000.0)

        assert new is not old
        assert new.starting_balance == 20_000.0
        assert new.trades_executed == 0
        assert agg.get_daily_stats() is new

    def test_initialize_day_uses_today_utc_date(self):
        """Date string uses ``datetime.now().strftime(%Y-%m-%d)``. If a
        later refactor swaps in UTC, this test needs updating in lockstep."""
        agg = DailyStatsAggregator()
        with patch("src.bot.components.risk.daily_stats.datetime") as dt:
            dt.now.return_value = datetime(2026, 4, 24, 14, 30)
            stats = agg.initialize_day(1_000.0)
        assert stats.date == "2026-04-24"

    def test_hydrate_replaces_current_snapshot(self):
        """``hydrate`` is the persistence-layer hook — replaces whatever
        the aggregator had with the supplied DailyStats."""
        agg = DailyStatsAggregator()
        agg.initialize_day(10_000.0)

        loaded = DailyStats(
            date="2026-01-01",
            starting_balance=5_000.0,
            current_balance=5_200.0,
            trades_executed=4,
            winning_trades=3,
            losing_trades=1,
            total_pnl=200.0,
            total_fees=3.0,
            total_funding=0.0,
            max_drawdown=1.0,
        )
        agg.hydrate(loaded)

        current = agg.get_daily_stats()
        assert current is loaded
        assert current.trades_executed == 4


# ---------------------------------------------------------------------------
# DailyStatsAggregator — record_entry
# ---------------------------------------------------------------------------


class TestRecordEntry:
    def test_returns_false_when_not_initialised(self):
        agg = DailyStatsAggregator()
        assert agg.record_entry("BTCUSDT") is False

    def test_increments_global_and_per_symbol_counters(self):
        agg = DailyStatsAggregator()
        agg.initialize_day(10_000.0)

        assert agg.record_entry("BTCUSDT") is True
        assert agg.record_entry("ETHUSDT") is True
        assert agg.record_entry("BTCUSDT") is True

        stats = agg.get_daily_stats()
        assert stats.trades_executed == 3
        assert stats.symbol_trades == {"BTCUSDT": 2, "ETHUSDT": 1}


# ---------------------------------------------------------------------------
# DailyStatsAggregator — record_exit
# ---------------------------------------------------------------------------


class TestRecordExit:
    def _entry_then_exit(self, agg: DailyStatsAggregator, **exit_kwargs) -> tuple:
        agg.record_entry(exit_kwargs["symbol"])
        return agg.record_exit(**exit_kwargs)

    def test_returns_none_when_not_initialised(self):
        agg = DailyStatsAggregator()
        assert (
            agg.record_exit(
                symbol="BTCUSDT",
                side="long",
                size=0.1,
                entry_price=50_000,
                exit_price=51_000,
                fees=0.0,
                funding_paid=0.0,
            )
            is None
        )

    def test_winning_trade_updates_counters_and_pnl(self):
        agg = DailyStatsAggregator()
        agg.initialize_day(10_000.0)

        result = self._entry_then_exit(
            agg,
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50_000,
            exit_price=51_000,
            fees=2.0,
            funding_paid=0.0,
        )

        assert result is not None
        pnl, pnl_percent = result
        assert pnl == pytest.approx(100.0)

        stats = agg.get_daily_stats()
        assert stats.total_pnl == pytest.approx(100.0)
        assert stats.total_fees == pytest.approx(2.0)
        assert stats.winning_trades == 1
        assert stats.losing_trades == 0
        assert stats.symbol_pnl["BTCUSDT"] == pytest.approx(100.0)
        # current_balance = 10000 + (100 - 2 - 0)
        assert stats.current_balance == pytest.approx(10_098.0)

    def test_losing_trade_updates_losing_counter(self):
        agg = DailyStatsAggregator()
        agg.initialize_day(10_000.0)

        self._entry_then_exit(
            agg,
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50_000,
            exit_price=49_000,
            fees=1.0,
            funding_paid=0.0,
        )

        stats = agg.get_daily_stats()
        assert stats.winning_trades == 0
        assert stats.losing_trades == 1
        assert stats.total_pnl == pytest.approx(-100.0)

    def test_funding_paid_flows_into_totals_and_balance(self):
        """Negative funding (received) boosts net_pnl + current_balance;
        positive funding (paid) reduces them."""
        agg = DailyStatsAggregator()
        agg.initialize_day(10_000.0)

        self._entry_then_exit(
            agg,
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50_000,
            exit_price=51_000,
            fees=5.0,
            funding_paid=-20.0,
        )
        stats = agg.get_daily_stats()
        assert stats.total_funding == pytest.approx(-20.0)
        assert stats.net_pnl == pytest.approx(100.0 - 5.0 - (-20.0))  # 115.0
        # current_balance = 10000 + (100 - 5 - (-20)) = 10115
        assert stats.current_balance == pytest.approx(10_115.0)

    def test_max_drawdown_tracks_worst_return(self):
        """Max drawdown climbs with losses, does NOT shrink when the day recovers."""
        agg = DailyStatsAggregator()
        agg.initialize_day(10_000.0)

        # Loss first — drawdown jumps
        self._entry_then_exit(
            agg,
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50_000,
            exit_price=49_000,
            fees=0.0,
            funding_paid=0.0,
        )
        stats = agg.get_daily_stats()
        assert stats.max_drawdown > 0
        dd_after_loss = stats.max_drawdown

        # Winning trade → return_percent climbs back, drawdown stays at peak
        self._entry_then_exit(
            agg,
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50_000,
            exit_price=52_000,
            fees=0.0,
            funding_paid=0.0,
        )
        stats = agg.get_daily_stats()
        assert stats.max_drawdown == pytest.approx(dd_after_loss)

    def test_short_side_pnl_is_inverted(self):
        """``calculate_pnl`` returns positive PnL on a profitable short —
        the aggregator must forward that sign unchanged."""
        agg = DailyStatsAggregator()
        agg.initialize_day(10_000.0)
        result = self._entry_then_exit(
            agg,
            symbol="BTCUSDT",
            side="short",
            size=0.1,
            entry_price=50_000,
            exit_price=49_000,
            fees=0.0,
            funding_paid=0.0,
        )
        pnl, _ = result
        assert pnl == pytest.approx(100.0)
        stats = agg.get_daily_stats()
        assert stats.winning_trades == 1

    def test_per_symbol_pnl_accumulates_across_multiple_exits(self):
        agg = DailyStatsAggregator()
        agg.initialize_day(10_000.0)
        for exit_price in (51_000, 49_000, 52_000):
            self._entry_then_exit(
                agg,
                symbol="BTCUSDT",
                side="long",
                size=0.1,
                entry_price=50_000,
                exit_price=exit_price,
                fees=0.0,
                funding_paid=0.0,
            )
        stats = agg.get_daily_stats()
        # 100 + (-100) + 200 = 200
        assert stats.symbol_pnl["BTCUSDT"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# DailyStatsAggregator — hydrate_from_dict (the persistence strip helper)
# ---------------------------------------------------------------------------


class TestHydrateFromDict:
    """Lock the DB-load strip contract — if this breaks, any bot with
    persisted stats (prod, staging, integration tests) fails to start."""

    def test_strips_net_pnl_before_constructor(self):
        """The core regression: ``DailyStats(**data)`` rejects ``net_pnl``
        — the strip helper removes it before construction."""
        payload = {
            "date": "2026-04-24",
            "starting_balance": 10_000.0,
            "current_balance": 10_150.0,
            "trades_executed": 3,
            "winning_trades": 2,
            "losing_trades": 1,
            "total_pnl": 150.0,
            "total_fees": 5.0,
            "total_funding": 0.0,
            "max_drawdown": 1.0,
            "is_trading_halted": False,
            "halt_reason": "",
            "symbol_trades": {},
            "symbol_pnl": {},
            "halted_symbols": {},
            # Computed fields — MUST be stripped or the constructor raises.
            "net_pnl": 145.0,
            "return_percent": 1.45,
            "win_rate": 66.67,
        }
        stats = DailyStatsAggregator.hydrate_from_dict(dict(payload))
        assert isinstance(stats, DailyStats)
        assert stats.trades_executed == 3
        # Computed fields recomputed from raw counters — not from the stripped values.
        assert stats.net_pnl == pytest.approx(145.0)

    def test_round_trip_to_dict_and_hydrate(self):
        """``to_dict`` + ``hydrate_from_dict`` must round-trip without
        field loss."""
        original = DailyStats(
            date="2026-04-24",
            starting_balance=10_000.0,
            current_balance=10_250.0,
            trades_executed=5,
            winning_trades=3,
            losing_trades=2,
            total_pnl=250.0,
            total_fees=10.0,
            total_funding=-5.0,
            max_drawdown=2.0,
            is_trading_halted=True,
            halt_reason="daily loss cap",
            symbol_trades={"BTCUSDT": 3, "ETHUSDT": 2},
            symbol_pnl={"BTCUSDT": 180.0, "ETHUSDT": 70.0},
            halted_symbols={"SOLUSDT": "per-symbol loss"},
        )
        round_tripped = DailyStatsAggregator.hydrate_from_dict(original.to_dict())

        assert round_tripped.date == original.date
        assert round_tripped.starting_balance == original.starting_balance
        assert round_tripped.current_balance == original.current_balance
        assert round_tripped.trades_executed == original.trades_executed
        assert round_tripped.winning_trades == original.winning_trades
        assert round_tripped.losing_trades == original.losing_trades
        assert round_tripped.total_pnl == original.total_pnl
        assert round_tripped.total_fees == original.total_fees
        assert round_tripped.total_funding == original.total_funding
        assert round_tripped.max_drawdown == original.max_drawdown
        assert round_tripped.is_trading_halted == original.is_trading_halted
        assert round_tripped.halt_reason == original.halt_reason
        assert round_tripped.symbol_trades == original.symbol_trades
        assert round_tripped.symbol_pnl == original.symbol_pnl
        assert round_tripped.halted_symbols == original.halted_symbols
        # Computed fields recompute identically.
        assert round_tripped.net_pnl == pytest.approx(original.net_pnl)
        assert round_tripped.return_percent == pytest.approx(original.return_percent)
        assert round_tripped.win_rate == pytest.approx(original.win_rate)

    def test_strip_tolerates_missing_computed_fields(self):
        """A payload that *doesn't* include the computed fields (older
        schema) must still hydrate — ``pop(..., None)`` is the contract."""
        payload = {
            "date": "2026-04-24",
            "starting_balance": 10_000.0,
            "current_balance": 10_000.0,
            "trades_executed": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "total_funding": 0.0,
            "max_drawdown": 0.0,
        }
        stats = DailyStatsAggregator.hydrate_from_dict(dict(payload))
        assert stats.trades_executed == 0
        assert stats.symbol_trades == {}

    def test_raw_constructor_rejects_computed_fields(self):
        """Sanity check the invariant the strip helper exists to enforce.
        If this ever stops raising, the helper becomes a no-op and the
        round-trip test above becomes the only safety net."""
        bad_payload = {
            "date": "2026-04-24",
            "starting_balance": 10_000.0,
            "current_balance": 10_000.0,
            "trades_executed": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "total_funding": 0.0,
            "max_drawdown": 0.0,
            "net_pnl": 0.0,  # @property — rejected by dataclass __init__
        }
        with pytest.raises(TypeError):
            DailyStats(**bad_payload)


# ---------------------------------------------------------------------------
# RiskManager façade delegation — lightweight integration tests that
# pin the thin orchestration lines the aggregator now serves. These
# complement the Phase-0 characterization tests by covering a few paths
# the frozen set doesn't reach (pre-init observables, save-without-loop).
# ---------------------------------------------------------------------------


class TestRiskManagerFacadeDelegation:
    """Ensure :class:`RiskManager` still reads through the aggregator."""

    def test_get_daily_stats_forwards_to_aggregator(self):
        from src.risk.risk_manager import RiskManager

        rm = RiskManager(bot_config_id=None)
        assert rm.get_daily_stats() is None

        stats = rm.initialize_day(5_000.0)
        assert rm.get_daily_stats() is stats
        # Identity is preserved by the aggregator's same-day idempotency.
        assert rm.initialize_day(999.0) is stats

    def test_remaining_trades_and_budget_before_init(self):
        """Pre-init observables on the façade return effective caps
        without crashing — aggregator returns ``None``, façade guards."""
        from src.risk.risk_manager import RiskManager

        rm = RiskManager(
            max_trades_per_day=4,
            daily_loss_limit_percent=3.0,
            per_symbol_limits={"BTCUSDT": {"max_trades": 2}},
            bot_config_id=None,
        )
        # Global cap — no stats yet.
        assert rm.get_remaining_trades() == 4
        assert rm.get_remaining_risk_budget() == 3.0
        # Per-symbol cap — no stats yet.
        assert rm.get_remaining_trades(symbol="BTCUSDT") == 2

    def test_save_daily_stats_swallows_no_running_loop(self):
        """``_save_daily_stats`` is called synchronously from
        ``record_trade_entry`` / ``initialize_day``. When no event loop
        is running (pure-sync test context) the call must log + return
        without raising — the stats stay in memory and are persisted on
        the next async-context call."""
        from src.risk.risk_manager import RiskManager

        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        rm.initialize_day(10_000.0)
        # No asyncio event loop here — get_running_loop raises RuntimeError,
        # which the façade swallows at the ``except RuntimeError`` branch.
        rm._save_daily_stats()
        # State unchanged, no propagation.
        assert rm.get_daily_stats() is not None

    def test_get_historical_stats_returns_empty_list_legacy_wrapper(self):
        """The sync wrapper always returns ``[]`` after the JSON-file
        storage removal (#188). Locked to catch accidental re-reintroduction
        of the on-disk path."""
        from src.risk.risk_manager import RiskManager

        rm = RiskManager(bot_config_id=None)
        assert rm.get_historical_stats() == []
        assert rm.get_historical_stats(days=7) == []
