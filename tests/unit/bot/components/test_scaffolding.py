"""Smoke tests for the ARCH-H1 component scaffolding (issue #266).

This PR introduces only the directory + protocols + deps dataclass. No
component is extracted yet. The tests here lock three invariants that
matter for later phases:

1. The package imports cleanly (catches circular-import regressions
   the moment a later phase starts wiring real callers).
2. ``BotWorkerDeps`` can be instantiated with no args — Phase 1
   consumers will construct partial deps during tests.
3. The Protocols are ``runtime_checkable`` — a later contract test
   (Phase 1 onwards) will do ``isinstance(notifier, NotifierProtocol)``.
"""

from __future__ import annotations

from src.bot.components import (
    BotWorkerDeps,
    NotifierProtocol,
    PositionMonitorProtocol,
    TradeCloserProtocol,
    TradeExecutorProtocol,
)


class TestPackageImports:
    def test_all_symbols_exported(self):
        from src.bot.components import __all__ as exported

        assert set(exported) == {
            "BotWorkerDeps",
            "NotifierProtocol",
            "PositionMonitorProtocol",
            "TradeCloserProtocol",
            "TradeExecutorProtocol",
        }


class TestBotWorkerDeps:
    def test_defaults_construct(self):
        deps = BotWorkerDeps()
        assert deps.bot_config is None
        assert deps.client is None
        assert deps.symbol_locks == {}
        assert deps.user_trade_lock is None

    def test_symbol_locks_is_per_instance(self):
        # Regression guard: mutable default must not be shared across instances.
        a = BotWorkerDeps()
        b = BotWorkerDeps()
        a.symbol_locks["BTCUSDT"] = object()  # type: ignore[assignment]
        assert "BTCUSDT" not in b.symbol_locks


class TestProtocolsAreRuntimeCheckable:
    # Every protocol is decorated @runtime_checkable so Phase 1+ can do
    # isinstance(component, XProtocol) as a contract test. If a later
    # edit accidentally drops the decorator, isinstance() raises TypeError.
    def test_executor_is_runtime_checkable(self):
        class Dummy:
            async def open(self, signal): return None
            async def cancel_pending(self, trade_id): return None

        assert isinstance(Dummy(), TradeExecutorProtocol)

    def test_monitor_is_runtime_checkable(self):
        class Dummy:
            async def poll_positions(self): return None
            async def on_closed(self, trade): return None

        assert isinstance(Dummy(), PositionMonitorProtocol)

    def test_closer_is_runtime_checkable(self):
        class Dummy:
            async def close_manual(self, trade_id, reason): return None
            async def run_due_exits(self): return None

        assert isinstance(Dummy(), TradeCloserProtocol)

    def test_notifier_is_runtime_checkable(self):
        class Dummy:
            async def on_trade_opened(self, trade): return None
            async def on_trade_closed(self, trade): return None
            async def on_error(self, exc): return None

        assert isinstance(Dummy(), NotifierProtocol)

    def test_missing_method_is_rejected(self):
        class Incomplete:
            async def open(self, signal): return None
            # cancel_pending missing

        assert not isinstance(Incomplete(), TradeExecutorProtocol)
