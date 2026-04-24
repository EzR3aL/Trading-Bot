"""Tests for ``RiskManager.can_trade`` Prometheus instrumentation (#327 PR-4).

Contract coverage
-----------------

Every branch of ``can_trade`` must emit exactly one
``risk_trade_gate_decisions_total`` observation with the right
``decision`` label:

* ``allow``                     — happy path
* ``block_max_trades``          — global trade-count limit
* ``block_daily_loss``          — global daily-loss limit
* ``block_max_trades_symbol``   — per-symbol trade-count limit
* ``block_daily_loss_symbol``   — per-symbol daily-loss limit (eager path)
* ``block_global_halted``       — prior trading halt
* ``block_symbol_halted``       — prior per-symbol halt
* ``block_uninitialized``       — stats not initialised

Registry isolation
------------------
The observability registry is a single process-global
``CollectorRegistry``. Counters cannot be reset in-place, so these
tests diff the label-specific ``_value.get()`` before and after each
call. This makes them robust against other tests in the same process
that may have touched the same labels.

Per-symbol loss limit double-path note
--------------------------------------
The per-symbol loss limit has two emission points in
``risk_manager.py``: the eager pre-check inside ``can_trade``
(instrumented) and the lazy write inside ``record_trade_exit`` (NOT
instrumented — a trade already executed, no gate decision is happening
there). We assert the eager path increments the counter and that the
exit-time flip does NOT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo root on sys.path, mirroring the pattern used by the other
# observability tests.
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo=")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def _counter_value(counter, **labels) -> float:
    """Read the current value of a prometheus_client Counter by label set."""
    return counter.labels(**labels)._value.get()


# ---------------------------------------------------------------------------
# allow path
# ---------------------------------------------------------------------------

def test_can_trade_allow_increments_allow_decision():
    from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
    from src.risk.risk_manager import RiskManager

    rm = RiskManager(
        max_trades_per_day=5,
        daily_loss_limit_percent=3.0,
        position_size_percent=10.0,
        bot_config_id=42,
    )
    rm.initialize_day(starting_balance=1000.0)

    before = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL, bot_id="42", decision="allow"
    )

    ok, reason = rm.can_trade()

    assert ok is True
    assert reason == "Trading allowed"

    after = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL, bot_id="42", decision="allow"
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# block_max_trades — global trade-count limit
# ---------------------------------------------------------------------------

def test_can_trade_global_trade_limit_increments_block_max_trades():
    from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
    from src.risk.risk_manager import RiskManager

    rm = RiskManager(
        max_trades_per_day=2,
        daily_loss_limit_percent=5.0,
        bot_config_id=7,
    )
    rm.initialize_day(starting_balance=1000.0)
    # Force the limit to be hit without going through record_trade_entry
    # (that would also persist stats — irrelevant for this check).
    rm._daily_stats.trades_executed = 2

    before = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL, bot_id="7", decision="block_max_trades"
    )

    ok, _ = rm.can_trade()

    assert ok is False

    after = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL, bot_id="7", decision="block_max_trades"
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# block_daily_loss — global daily-loss limit
# ---------------------------------------------------------------------------

def test_can_trade_global_loss_limit_increments_block_daily_loss():
    from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
    from src.risk.risk_manager import RiskManager

    rm = RiskManager(
        max_trades_per_day=10,
        daily_loss_limit_percent=2.0,
        bot_config_id=13,
        enable_profit_lock=False,
    )
    rm.initialize_day(starting_balance=1000.0)
    # Simulate a realized loss that pushes us past the loss limit.
    rm._daily_stats.total_pnl = -30.0  # -3.0% of 1000

    before = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL, bot_id="13", decision="block_daily_loss"
    )

    ok, _ = rm.can_trade()

    assert ok is False

    after = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL, bot_id="13", decision="block_daily_loss"
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# block_max_trades_symbol — per-symbol trade-count limit
# ---------------------------------------------------------------------------

def test_can_trade_symbol_trade_limit_increments_block_max_trades_symbol():
    from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
    from src.risk.risk_manager import RiskManager

    rm = RiskManager(
        max_trades_per_day=100,
        daily_loss_limit_percent=5.0,
        per_symbol_limits={"BTCUSDT": {"max_trades": 1, "loss_limit": 5.0}},
        bot_config_id=55,
    )
    rm.initialize_day(starting_balance=1000.0)
    rm._daily_stats.symbol_trades["BTCUSDT"] = 1

    before = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL,
        bot_id="55",
        decision="block_max_trades_symbol",
    )

    ok, _ = rm.can_trade(symbol="BTCUSDT")

    assert ok is False

    after = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL,
        bot_id="55",
        decision="block_max_trades_symbol",
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# block_daily_loss_symbol — per-symbol daily-loss limit (eager path)
# ---------------------------------------------------------------------------

def test_can_trade_symbol_loss_limit_increments_block_daily_loss_symbol():
    from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
    from src.risk.risk_manager import RiskManager

    rm = RiskManager(
        max_trades_per_day=100,
        daily_loss_limit_percent=10.0,
        per_symbol_limits={"BTCUSDT": {"max_trades": 100, "loss_limit": 2.0}},
        bot_config_id=77,
    )
    rm.initialize_day(starting_balance=1000.0)
    # -3% on BTC specifically — exceeds the 2% per-symbol limit.
    rm._daily_stats.symbol_pnl["BTCUSDT"] = -30.0

    before = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL,
        bot_id="77",
        decision="block_daily_loss_symbol",
    )

    ok, _ = rm.can_trade(symbol="BTCUSDT")

    assert ok is False

    after = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL,
        bot_id="77",
        decision="block_daily_loss_symbol",
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# block_global_halted — prior halt blocks next gate
# ---------------------------------------------------------------------------

def test_can_trade_after_global_halt_increments_block_global_halted():
    from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
    from src.risk.risk_manager import RiskManager

    rm = RiskManager(
        max_trades_per_day=10,
        daily_loss_limit_percent=5.0,
        bot_config_id=99,
    )
    rm.initialize_day(starting_balance=1000.0)
    rm._daily_stats.is_trading_halted = True
    rm._daily_stats.halt_reason = "test halt"

    before = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL,
        bot_id="99",
        decision="block_global_halted",
    )

    ok, _ = rm.can_trade()

    assert ok is False

    after = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL,
        bot_id="99",
        decision="block_global_halted",
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# block_symbol_halted — per-symbol halt blocks next gate for that symbol
# ---------------------------------------------------------------------------

def test_can_trade_after_symbol_halt_increments_block_symbol_halted():
    from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
    from src.risk.risk_manager import RiskManager

    rm = RiskManager(
        max_trades_per_day=10,
        daily_loss_limit_percent=5.0,
        bot_config_id=111,
    )
    rm.initialize_day(starting_balance=1000.0)
    rm._daily_stats.halted_symbols["ETHUSDT"] = "manually halted"

    before = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL,
        bot_id="111",
        decision="block_symbol_halted",
    )

    ok, _ = rm.can_trade(symbol="ETHUSDT")

    assert ok is False

    after = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL,
        bot_id="111",
        decision="block_symbol_halted",
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# block_uninitialized — stats not initialised
# ---------------------------------------------------------------------------

def test_can_trade_without_init_increments_block_uninitialized():
    from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
    from src.risk.risk_manager import RiskManager

    rm = RiskManager(
        max_trades_per_day=5,
        daily_loss_limit_percent=3.0,
        bot_config_id=222,
    )
    # no initialize_day() on purpose

    before = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL,
        bot_id="222",
        decision="block_uninitialized",
    )

    ok, _ = rm.can_trade()

    assert ok is False

    after = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL,
        bot_id="222",
        decision="block_uninitialized",
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# bot_id="unknown" fallback when bot_config_id is missing
# ---------------------------------------------------------------------------

def test_can_trade_without_bot_config_id_uses_unknown_label():
    from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
    from src.risk.risk_manager import RiskManager

    rm = RiskManager(
        max_trades_per_day=5,
        daily_loss_limit_percent=3.0,
        # no bot_config_id
    )
    rm.initialize_day(starting_balance=1000.0)

    before = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL, bot_id="unknown", decision="allow"
    )

    ok, _ = rm.can_trade()

    assert ok is True
    after = _counter_value(
        RISK_TRADE_GATE_DECISIONS_TOTAL, bot_id="unknown", decision="allow"
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# Per-symbol loss limit: exit-time flip MUST NOT increment the gate counter.
# Only the gate-time eager path is counted — see docstring of this module.
# ---------------------------------------------------------------------------

def test_record_trade_exit_per_symbol_halt_does_not_increment_counter():
    from src.observability.metrics import RISK_TRADE_GATE_DECISIONS_TOTAL
    from src.risk.risk_manager import RiskManager

    rm = RiskManager(
        max_trades_per_day=100,
        daily_loss_limit_percent=10.0,
        per_symbol_limits={"BTCUSDT": {"max_trades": 100, "loss_limit": 2.0}},
        bot_config_id=333,
    )
    rm.initialize_day(starting_balance=1000.0)
    # Snapshot all decision labels for this bot_id — we'll assert no
    # label was incremented by record_trade_exit.
    snapshot = {
        decision: _counter_value(
            RISK_TRADE_GATE_DECISIONS_TOTAL, bot_id="333", decision=decision
        )
        for decision in (
            "allow",
            "block_max_trades",
            "block_daily_loss",
            "block_max_trades_symbol",
            "block_daily_loss_symbol",
            "block_global_halted",
            "block_symbol_halted",
            "block_uninitialized",
        )
    }

    # A losing trade that pushes the per-symbol loss limit past 2%.
    ok = rm.record_trade_exit(
        symbol="BTCUSDT",
        side="long",
        size=1.0,
        entry_price=100.0,
        exit_price=70.0,  # realises a $30 loss on 1 unit at $100
        fees=0.0,
        funding_paid=0.0,
        reason="stop_loss",
        order_id="test-1",
    )
    assert ok is True
    # Verify the exit-time halt actually fired so the test is meaningful.
    assert "BTCUSDT" in rm._daily_stats.halted_symbols

    for decision, before in snapshot.items():
        after = _counter_value(
            RISK_TRADE_GATE_DECISIONS_TOTAL, bot_id="333", decision=decision
        )
        assert after == before, (
            f"record_trade_exit must not emit any trade-gate decision — "
            f"but bot_id=333 decision={decision} changed {before} -> {after}"
        )
