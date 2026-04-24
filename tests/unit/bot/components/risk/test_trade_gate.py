"""Focused unit tests for :mod:`src.bot.components.risk.trade_gate` (#326 PR-6).

These tests pin the gate's behaviour in isolation (no RiskManager
façade). The Phase-0 characterization tests at
``tests/unit/bot/test_risk_state_manager_characterization.py`` continue
to pin the full-stack behaviour through the façade — this file adds
reachability on branches the frozen set doesn't cover explicitly (zero
divisions, pre-init reads, save-stats hook wiring, dynamic loss limit
flooring, eager/lazy halt consolidation).
"""

from __future__ import annotations

import pytest

from src.bot.components.risk.daily_stats import DailyStats, DailyStatsAggregator
from src.bot.components.risk.trade_gate import TradeGate


def _fresh_agg(starting_balance: float = 10_000.0) -> DailyStatsAggregator:
    agg = DailyStatsAggregator()
    agg.initialize_day(starting_balance)
    return agg


# ---------------------------------------------------------------------------
# Pre-init observables
# ---------------------------------------------------------------------------


class TestPreInit:
    def test_can_trade_rejects_when_stats_not_initialised(self):
        gate = TradeGate(aggregator=DailyStatsAggregator())
        allowed, reason = gate.can_trade()
        assert allowed is False
        assert "not initialized" in reason.lower()

    def test_halted_symbols_returns_empty_before_init(self):
        gate = TradeGate(aggregator=DailyStatsAggregator())
        assert gate.halted_symbols == {}

    def test_remaining_trades_returns_sentinel_when_no_cap(self):
        gate = TradeGate(aggregator=DailyStatsAggregator())
        assert gate.get_remaining_trades() == 999
        assert gate.get_remaining_trades(symbol="BTCUSDT") == 999

    def test_remaining_trades_returns_cap_before_init(self):
        gate = TradeGate(
            aggregator=DailyStatsAggregator(),
            max_trades_per_day=5,
        )
        assert gate.get_remaining_trades() == 5

    def test_remaining_risk_budget_none_without_cap(self):
        gate = TradeGate(aggregator=DailyStatsAggregator())
        assert gate.get_remaining_risk_budget() is None

    def test_remaining_risk_budget_returns_cap_before_init(self):
        gate = TradeGate(
            aggregator=DailyStatsAggregator(),
            daily_loss_limit_percent=3.0,
        )
        assert gate.get_remaining_risk_budget() == 3.0

    def test_halt_trading_noop_without_stats(self):
        """``_halt_trading`` must not raise when stats are uninitialised."""
        saves = []
        gate = TradeGate(
            aggregator=DailyStatsAggregator(),
            save_stats=lambda: saves.append(1),
        )
        gate._halt_trading("nothing to halt")
        assert saves == []

    def test_check_and_halt_noop_without_stats(self):
        saves = []
        gate = TradeGate(
            aggregator=DailyStatsAggregator(),
            per_symbol_limits={"BTCUSDT": {"loss_limit": 1.0}},
            save_stats=lambda: saves.append(1),
        )
        gate.check_and_halt("BTCUSDT")
        assert saves == []


# ---------------------------------------------------------------------------
# Global gating — trade-count + loss cap
# ---------------------------------------------------------------------------


class TestGlobalGating:
    def test_allows_within_limits(self):
        agg = _fresh_agg()
        gate = TradeGate(
            aggregator=agg,
            max_trades_per_day=5,
            daily_loss_limit_percent=3.0,
        )
        allowed, reason = gate.can_trade()
        assert allowed is True
        assert reason == "Trading allowed"

    def test_no_caps_configured_allows(self):
        gate = TradeGate(aggregator=_fresh_agg())
        allowed, _ = gate.can_trade()
        assert allowed is True

    def test_blocks_at_max_trades(self):
        agg = _fresh_agg()
        gate = TradeGate(aggregator=agg, max_trades_per_day=2)
        agg.get_daily_stats().trades_executed = 2
        allowed, reason = gate.can_trade()
        assert allowed is False
        assert reason == "Global trade limit reached (2/2)"

    def test_blocks_at_daily_loss_cap_and_halts(self):
        agg = _fresh_agg(starting_balance=10_000.0)
        saves = []
        gate = TradeGate(
            aggregator=agg,
            daily_loss_limit_percent=5.0,
            save_stats=lambda: saves.append(1),
        )
        # -6% return → trips 5% cap.
        stats = agg.get_daily_stats()
        stats.total_pnl = -600.0
        allowed, reason = gate.can_trade()
        assert allowed is False
        assert "Daily loss limit exceeded" in reason
        # Side effects: global halt flag + save hook fired.
        assert stats.is_trading_halted is True
        assert "Daily loss limit exceeded" in stats.halt_reason
        assert saves == [1]

    def test_skips_loss_cap_when_starting_balance_zero(self):
        """Zero-division guard — if starting_balance is 0 the loss cap
        branch is skipped entirely (legacy behaviour, locked here)."""
        agg = DailyStatsAggregator()
        agg.initialize_day(0.0)
        agg.get_daily_stats().total_pnl = -5_000.0
        gate = TradeGate(aggregator=agg, daily_loss_limit_percent=1.0)
        allowed, _ = gate.can_trade()
        assert allowed is True

    def test_global_halt_blocks_everything(self):
        agg = _fresh_agg()
        agg.get_daily_stats().is_trading_halted = True
        agg.get_daily_stats().halt_reason = "manual"
        gate = TradeGate(aggregator=agg)
        allowed, reason = gate.can_trade()
        assert allowed is False
        assert "manual" in reason
        # Also blocks per-symbol calls without reaching per-symbol branches.
        allowed_sym, _ = gate.can_trade(symbol="BTCUSDT")
        assert allowed_sym is False


# ---------------------------------------------------------------------------
# Per-symbol gating
# ---------------------------------------------------------------------------


class TestPerSymbolGating:
    def test_blocks_at_per_symbol_max_trades(self):
        agg = _fresh_agg()
        gate = TradeGate(
            aggregator=agg,
            per_symbol_limits={"BTCUSDT": {"max_trades": 1}},
        )
        agg.record_entry("BTCUSDT")
        allowed, reason = gate.can_trade(symbol="BTCUSDT")
        assert allowed is False
        assert "trade limit reached" in reason
        assert "1/1" in reason

    def test_other_symbol_unaffected_by_per_symbol_cap(self):
        agg = _fresh_agg()
        gate = TradeGate(
            aggregator=agg,
            per_symbol_limits={"BTCUSDT": {"max_trades": 1}},
        )
        agg.record_entry("BTCUSDT")
        allowed, _ = gate.can_trade(symbol="ETHUSDT")
        assert allowed is True

    def test_blocks_on_pre_halted_symbol(self):
        agg = _fresh_agg()
        agg.get_daily_stats().halted_symbols["BTCUSDT"] = "manual"
        gate = TradeGate(aggregator=agg)
        allowed, reason = gate.can_trade(symbol="BTCUSDT")
        assert allowed is False
        assert "BTCUSDT halted: manual" == reason

    def test_per_symbol_override_beats_global(self):
        agg = _fresh_agg()
        gate = TradeGate(
            aggregator=agg,
            max_trades_per_day=1,
            per_symbol_limits={"BTCUSDT": {"max_trades": 5}},
        )
        agg.record_entry("BTCUSDT")
        # Per-symbol branch sees 1 < 5 → allowed, even though global 1/1.
        allowed, _ = gate.can_trade(symbol="BTCUSDT")
        assert allowed is True


# ---------------------------------------------------------------------------
# Eager + lazy halt consolidation — both paths go through the same code.
# ---------------------------------------------------------------------------


class TestHaltConsolidation:
    def test_lazy_halt_path_in_can_trade(self):
        """When per-symbol PnL crosses the cap without going through
        ``check_and_halt``, ``can_trade`` halts the symbol on-the-fly."""
        agg = _fresh_agg()
        saves = []
        gate = TradeGate(
            aggregator=agg,
            per_symbol_limits={"BTCUSDT": {"loss_limit": 2.0}},
            save_stats=lambda: saves.append(1),
        )
        stats = agg.get_daily_stats()
        stats.symbol_pnl["BTCUSDT"] = -300.0  # 3% loss on 10k
        assert "BTCUSDT" not in stats.halted_symbols  # precondition

        allowed, reason = gate.can_trade(symbol="BTCUSDT")
        assert allowed is False
        assert "Loss limit exceeded" in reason
        assert "BTCUSDT" in stats.halted_symbols
        assert saves == [1]

    def test_eager_halt_path_via_check_and_halt(self):
        """The façade calls :meth:`check_and_halt` post-PnL-update on
        ``record_trade_exit``. This pins that the eager path mutates
        ``halted_symbols`` + triggers the save hook."""
        agg = _fresh_agg()
        saves = []
        gate = TradeGate(
            aggregator=agg,
            per_symbol_limits={"BTCUSDT": {"loss_limit": 1.0}},
            save_stats=lambda: saves.append(1),
        )
        stats = agg.get_daily_stats()
        stats.symbol_pnl["BTCUSDT"] = -200.0  # 2% loss on 10k

        gate.check_and_halt("BTCUSDT")
        assert "BTCUSDT" in stats.halted_symbols
        # Eager phrasing — legacy "Loss limit reached: X%" wording.
        assert stats.halted_symbols["BTCUSDT"].startswith("Loss limit reached:")
        assert saves == [1]

    def test_eager_halt_noop_when_below_cap(self):
        agg = _fresh_agg()
        saves = []
        gate = TradeGate(
            aggregator=agg,
            per_symbol_limits={"BTCUSDT": {"loss_limit": 5.0}},
            save_stats=lambda: saves.append(1),
        )
        agg.get_daily_stats().symbol_pnl["BTCUSDT"] = -100.0  # 1% loss, cap is 5%
        gate.check_and_halt("BTCUSDT")
        assert "BTCUSDT" not in agg.get_daily_stats().halted_symbols
        assert saves == []

    def test_eager_halt_skips_when_no_loss_limit(self):
        agg = _fresh_agg()
        saves = []
        gate = TradeGate(aggregator=agg, save_stats=lambda: saves.append(1))
        agg.get_daily_stats().symbol_pnl["BTCUSDT"] = -500.0
        gate.check_and_halt("BTCUSDT")
        assert "BTCUSDT" not in agg.get_daily_stats().halted_symbols
        assert saves == []

    def test_eager_halt_skips_when_starting_balance_zero(self):
        """Zero-division guard on the eager path."""
        agg = DailyStatsAggregator()
        agg.initialize_day(0.0)
        agg.get_daily_stats().symbol_pnl["BTCUSDT"] = -100.0
        gate = TradeGate(
            aggregator=agg,
            per_symbol_limits={"BTCUSDT": {"loss_limit": 1.0}},
        )
        gate.check_and_halt("BTCUSDT")
        assert "BTCUSDT" not in agg.get_daily_stats().halted_symbols


# ---------------------------------------------------------------------------
# Dynamic loss limit (Profit Lock-In)
# ---------------------------------------------------------------------------


class TestDynamicLossLimit:
    def test_returns_none_when_no_base_cap(self):
        gate = TradeGate(aggregator=_fresh_agg())
        assert gate.get_dynamic_loss_limit() is None

    def test_returns_base_cap_when_profit_lock_disabled(self):
        gate = TradeGate(
            aggregator=_fresh_agg(),
            daily_loss_limit_percent=5.0,
            enable_profit_lock=False,
        )
        assert gate.get_dynamic_loss_limit() == 5.0

    def test_returns_base_cap_before_init(self):
        gate = TradeGate(
            aggregator=DailyStatsAggregator(),
            daily_loss_limit_percent=5.0,
        )
        assert gate.get_dynamic_loss_limit() == 5.0

    def test_returns_base_cap_when_return_not_positive(self):
        agg = _fresh_agg()
        gate = TradeGate(
            aggregator=agg,
            daily_loss_limit_percent=5.0,
        )
        agg.get_daily_stats().total_pnl = -100.0
        assert gate.get_dynamic_loss_limit() == 5.0

    def test_tightens_after_profit_with_floor(self):
        """Return=3%, min_profit_floor=0.5% → new_limit = 3 - 0.5 = 2.5."""
        agg = _fresh_agg()
        gate = TradeGate(
            aggregator=agg,
            daily_loss_limit_percent=5.0,
            min_profit_floor=0.5,
        )
        agg.get_daily_stats().total_pnl = 300.0  # 3% return on 10k
        assert gate.get_dynamic_loss_limit() == pytest.approx(2.5)

    def test_dynamic_limit_floored_at_half_percent(self):
        """Return=0.6%, min_profit_floor=0.5% → theoretical limit 0.1%,
        but gate floors at 0.5%."""
        agg = _fresh_agg()
        gate = TradeGate(
            aggregator=agg,
            daily_loss_limit_percent=5.0,
            min_profit_floor=0.5,
        )
        agg.get_daily_stats().total_pnl = 60.0  # 0.6% return on 10k
        assert gate.get_dynamic_loss_limit() == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Remaining-trades + remaining-budget accessors
# ---------------------------------------------------------------------------


class TestRemainingAccessors:
    def test_remaining_trades_global_cap(self):
        agg = _fresh_agg()
        gate = TradeGate(aggregator=agg, max_trades_per_day=5)
        agg.get_daily_stats().trades_executed = 2
        assert gate.get_remaining_trades() == 3

    def test_remaining_trades_clamped_to_zero(self):
        agg = _fresh_agg()
        gate = TradeGate(aggregator=agg, max_trades_per_day=3)
        agg.get_daily_stats().trades_executed = 99
        assert gate.get_remaining_trades() == 0

    def test_remaining_trades_per_symbol_uses_override(self):
        agg = _fresh_agg()
        gate = TradeGate(
            aggregator=agg,
            max_trades_per_day=100,
            per_symbol_limits={"BTCUSDT": {"max_trades": 4}},
        )
        agg.get_daily_stats().symbol_trades["BTCUSDT"] = 1
        assert gate.get_remaining_trades(symbol="BTCUSDT") == 3

    def test_remaining_trades_per_symbol_falls_back_to_global(self):
        """Symbol without per-symbol override picks up global cap."""
        agg = _fresh_agg()
        gate = TradeGate(
            aggregator=agg,
            max_trades_per_day=5,
            per_symbol_limits={"BTCUSDT": {"loss_limit": 2.0}},
        )
        agg.get_daily_stats().symbol_trades["ETHUSDT"] = 1
        # Falls back to global cap of 5; symbol_count=1 → remaining=4.
        assert gate.get_remaining_trades(symbol="ETHUSDT") == 4

    def test_remaining_risk_budget_shrinks_after_loss(self):
        agg = _fresh_agg()
        gate = TradeGate(aggregator=agg, daily_loss_limit_percent=5.0)
        agg.get_daily_stats().total_pnl = -200.0  # -2% return
        assert gate.get_remaining_risk_budget() == pytest.approx(3.0)

    def test_remaining_risk_budget_clamped_to_zero(self):
        agg = _fresh_agg()
        gate = TradeGate(aggregator=agg, daily_loss_limit_percent=2.0)
        agg.get_daily_stats().total_pnl = -500.0  # -5% return, cap 2%
        assert gate.get_remaining_risk_budget() == 0


# ---------------------------------------------------------------------------
# halted_symbols proxy — mutations go through to the snapshot.
# ---------------------------------------------------------------------------


class TestHaltedSymbolsProxy:
    def test_mutation_persists_on_snapshot(self):
        agg = _fresh_agg()
        gate = TradeGate(aggregator=agg)
        gate.halted_symbols["BTCUSDT"] = "via proxy"
        # The dict IS the snapshot's halted_symbols by reference.
        assert agg.get_daily_stats().halted_symbols["BTCUSDT"] == "via proxy"
