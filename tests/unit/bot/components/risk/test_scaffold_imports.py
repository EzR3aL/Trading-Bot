"""Smoke tests for the ARCH-H2 Phase 0 scaffolding (issue #326).

This PR introduces only the ``src/bot/components/risk/`` package:
Protocols + ``RiskComponentDeps`` dataclass + empty module stubs. No
component is extracted yet. The tests here lock invariants that matter
for the Phase 1 extraction PRs (PR-4..PR-7):

1. The package imports cleanly (catches circular-import regressions
   the moment a later phase starts wiring real callers).
2. ``RiskComponentDeps`` can be instantiated with no args — Phase 1
   consumers will construct partial deps during tests.
3. The Protocols are ``runtime_checkable`` so a later contract test
   (Phase 1 onwards) can do ``isinstance(component, XProtocol)``.
4. The four stub modules import without side-effects.
"""

from __future__ import annotations

from dataclasses import is_dataclass

from src.bot.components.risk import (
    AlertThrottlerProtocol,
    DailyStatsAggregatorProtocol,
    RiskComponentDeps,
    RiskStatePersistenceProtocol,
    TradeGateProtocol,
)


class TestPackageImports:
    def test_all_symbols_exported(self):
        from src.bot.components.risk import __all__ as exported

        protocol_symbols = {
            "DailyStatsAggregatorProtocol",
            "TradeGateProtocol",
            "AlertThrottlerProtocol",
            "RiskStatePersistenceProtocol",
            "RiskComponentDeps",
        }
        assert protocol_symbols.issubset(set(exported))

    def test_stub_modules_import(self):
        # Empty placeholders — importing them must never raise, even
        # though they contain no symbols yet.
        from src.bot.components.risk import (  # noqa: F401
            alert_throttler,
            daily_stats,
            persistence,
            trade_gate,
        )


class TestRiskComponentDeps:
    def test_is_dataclass(self):
        assert is_dataclass(RiskComponentDeps)

    def test_defaults_construct(self):
        deps = RiskComponentDeps()
        assert deps.bot_config_id is None
        assert deps.max_trades_per_day is None
        assert deps.daily_loss_limit_percent is None
        assert deps.position_size_percent is None
        assert deps.per_symbol_limits == {}
        assert deps.enable_profit_lock is True
        assert deps.profit_lock_percent == 75.0
        assert deps.min_profit_floor == 0.5
        assert deps.notifier is None
        assert deps.session_factory is None

    def test_per_symbol_limits_is_per_instance(self):
        # Regression guard: mutable default must not be shared across instances.
        a = RiskComponentDeps()
        b = RiskComponentDeps()
        a.per_symbol_limits["BTCUSDT"] = {"max_trades": 5}
        assert "BTCUSDT" not in b.per_symbol_limits

    def test_fields_accept_overrides(self):
        deps = RiskComponentDeps(
            bot_config_id=42,
            max_trades_per_day=3,
            daily_loss_limit_percent=5.0,
            position_size_percent=10.0,
            per_symbol_limits={"BTCUSDT": {"max_trades": 2}},
            enable_profit_lock=False,
            profit_lock_percent=50.0,
            min_profit_floor=1.0,
        )
        assert deps.bot_config_id == 42
        assert deps.max_trades_per_day == 3
        assert deps.daily_loss_limit_percent == 5.0
        assert deps.position_size_percent == 10.0
        assert deps.per_symbol_limits == {"BTCUSDT": {"max_trades": 2}}
        assert deps.enable_profit_lock is False
        assert deps.profit_lock_percent == 50.0
        assert deps.min_profit_floor == 1.0


class TestProtocolsAreRuntimeCheckable:
    """Every protocol is ``@runtime_checkable`` so Phase 1+ can do
    ``isinstance(component, XProtocol)`` as a contract test. If a later
    edit accidentally drops the decorator, ``isinstance()`` raises
    ``TypeError``.
    """

    def test_aggregator_is_runtime_checkable(self):
        class Dummy:
            def initialize_day(self, starting_balance):
                return None

            def get_daily_stats(self):
                return None

            def record_trade_entry(
                self, symbol, side, size, entry_price, leverage, confidence, reason, order_id
            ):
                return True

            def record_trade_exit(
                self, symbol, side, size, entry_price, exit_price, fees, funding_paid, reason, order_id
            ):
                return True

        assert isinstance(Dummy(), DailyStatsAggregatorProtocol)

    def test_trade_gate_is_runtime_checkable(self):
        class Dummy:
            def can_trade(self, symbol=None):
                return True, "ok"

            def get_remaining_trades(self, symbol=None):
                return 0

            def get_remaining_risk_budget(self):
                return None

            def get_dynamic_loss_limit(self, symbol=None):
                return None

        assert isinstance(Dummy(), TradeGateProtocol)

    def test_alert_throttler_is_runtime_checkable(self):
        class Dummy:
            def should_emit(self, alert_key):
                return True

            def maybe_reset(self):
                return None

            def reset(self):
                return None

        assert isinstance(Dummy(), AlertThrottlerProtocol)

    def test_persistence_is_runtime_checkable(self):
        class Dummy:
            async def load_stats(self):
                return None

            async def save_stats(self, stats):
                return None

        assert isinstance(Dummy(), RiskStatePersistenceProtocol)

    def test_missing_method_is_rejected(self):
        class Incomplete:
            def can_trade(self, symbol=None):
                return True, "ok"

            # Missing get_remaining_trades, get_remaining_risk_budget, get_dynamic_loss_limit

        assert not isinstance(Incomplete(), TradeGateProtocol)
