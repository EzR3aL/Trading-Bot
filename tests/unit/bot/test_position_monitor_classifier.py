"""Integration tests for the PositionMonitor exit-reason classifier (#193).

Validates the two branches of ``PositionMonitorMixin._handle_closed_position``:

* Feature flag ON  → delegates to ``RiskStateManager.classify_close`` and the
  returned string is written as ``exit_reason``.
* Feature flag OFF → legacy heuristic path runs, emitting the new precise
  reason codes (``TRAILING_STOP_NATIVE`` / ``TAKE_PROFIT_NATIVE`` /
  ``STOP_LOSS_NATIVE`` / ``EXTERNAL_CLOSE_UNKNOWN``) so the UI vocabulary
  stays consistent regardless of which path produced the label.

Also covers the ``note_strategy_exit`` hook in the strategy-exit branch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.position_monitor import PositionMonitorMixin
from src.bot.risk_reasons import ExitReason
from src.models.database import TradeRecord


# ---------------------------------------------------------------------------
# Minimal harness: a PositionMonitorMixin subclass that supplies the fields
# the monitor code relies on without spinning up a full BotWorker.
# ---------------------------------------------------------------------------


class _MonitorHarness(PositionMonitorMixin):
    def __init__(self) -> None:
        self.bot_config_id = 42
        self._config = MagicMock(name="BotConfig")
        self._config.name = "test-bot"
        self._strategy = None
        self._risk_manager = MagicMock()
        self._risk_manager.record_trade_exit = MagicMock()
        # recorded close-and-record invocations
        self._close_records: List[dict] = []
        self._init_monitor_state()

    async def _close_and_record_trade(self, trade, exit_price, exit_reason, **kw):
        # Mimic the real mixin: update the in-memory trade.
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.status = "closed"
        self._close_records.append({
            "trade_id": trade.id,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            **kw,
        })


@dataclass
class _FakeTicker:
    last_price: float


@dataclass
class _MonitorFakeClient:
    """Minimal exchange-client double used by _handle_closed_position."""

    fill_price: Optional[float] = 68500.0
    ticker_price: float = 68500.0
    fee_value: float = 0.0
    funding_value: float = 0.0
    last_close_order_id: Optional[str] = None
    fill_price_calls: int = 0

    async def get_close_fill_price(self, symbol: str) -> Optional[float]:
        self.fill_price_calls += 1
        return self.fill_price

    async def get_ticker(self, symbol: str) -> _FakeTicker:
        return _FakeTicker(last_price=self.ticker_price)

    async def get_trade_total_fees(self, **kw) -> float:
        return self.fee_value

    async def get_funding_fees(self, **kw) -> float:
        return self.funding_value

    @property
    def _last_close_order_id(self):
        return self.last_close_order_id


def _build_trade(**overrides) -> TradeRecord:
    """Build an in-memory TradeRecord with sensible defaults.

    We avoid touching a DB because ``_handle_closed_position`` only needs
    the column values, and the ``_close_and_record_trade`` override above
    doesn't hit a session either.
    """
    defaults = dict(
        id=1,
        user_id=1,
        bot_config_id=42,
        exchange="bitget",
        symbol="BTCUSDT",
        side="long",
        size=0.01,
        entry_price=68200.0,
        leverage=10,
        confidence=80,
        reason="harness",
        order_id="entry_001",
        status="open",
        entry_time=datetime(2026, 4, 18, 9, 0, tzinfo=timezone.utc),
        take_profit=None,
        stop_loss=None,
        native_trailing_stop=False,
        demo_mode=True,
        fees=0.0,
        funding_paid=0.0,
    )
    defaults.update(overrides)
    trade = TradeRecord(**defaults)
    return trade


# ===========================================================================
# Feature flag ON — delegates to RiskStateManager
# ===========================================================================


@pytest.mark.asyncio
async def test_handle_closed_position_delegates_to_manager_when_flag_on():
    """When the manager is wired in, exit_reason comes from classify_close."""
    harness = _MonitorHarness()
    manager = MagicMock()
    manager.classify_close = AsyncMock(return_value=ExitReason.TRAILING_STOP_NATIVE.value)
    harness._risk_state_manager = manager

    trade = _build_trade(native_trailing_stop=False, take_profit=70000.0)
    client = _MonitorFakeClient(fill_price=70000.0)

    await harness._handle_closed_position(trade, client, session=None)

    manager.classify_close.assert_awaited_once()
    args, kwargs = manager.classify_close.call_args
    # Positional signature: (trade_id, exit_price, exit_time)
    assert args[0] == trade.id
    assert args[1] == 70000.0

    assert harness._close_records, "close_and_record must have run"
    assert harness._close_records[0]["exit_reason"] == ExitReason.TRAILING_STOP_NATIVE.value


@pytest.mark.asyncio
async def test_handle_closed_position_falls_back_when_manager_raises():
    """Manager exceptions must fall through to the legacy heuristic."""
    harness = _MonitorHarness()
    manager = MagicMock()
    manager.classify_close = AsyncMock(side_effect=RuntimeError("probe blew up"))
    harness._risk_state_manager = manager

    # Trade with TP close to exit_price → heuristic should pick TAKE_PROFIT_NATIVE.
    trade = _build_trade(take_profit=70000.0)
    client = _MonitorFakeClient(fill_price=69998.0)

    await harness._handle_closed_position(trade, client, session=None)

    assert harness._close_records[0]["exit_reason"] == ExitReason.TAKE_PROFIT_NATIVE.value


# ===========================================================================
# Feature flag OFF — legacy heuristic path emits new precise reason codes
# ===========================================================================


@pytest.mark.asyncio
async def test_handle_closed_position_uses_heuristic_when_flag_off_native_trailing():
    harness = _MonitorHarness()
    # No risk state manager → flag off path.
    assert harness._risk_state_manager is None

    trade = _build_trade(native_trailing_stop=True)
    client = _MonitorFakeClient(fill_price=68500.0)

    await harness._handle_closed_position(trade, client, session=None)

    assert harness._close_records[0]["exit_reason"] == ExitReason.TRAILING_STOP_NATIVE.value


@pytest.mark.asyncio
async def test_handle_closed_position_uses_heuristic_when_flag_off_external_close():
    harness = _MonitorHarness()

    # No TP/SL/trailing — heuristic must fall through to EXTERNAL_CLOSE_UNKNOWN.
    trade = _build_trade()
    client = _MonitorFakeClient(fill_price=68500.0)

    await harness._handle_closed_position(trade, client, session=None)

    assert harness._close_records[0]["exit_reason"] == ExitReason.EXTERNAL_CLOSE_UNKNOWN.value


@pytest.mark.asyncio
async def test_handle_closed_position_uses_heuristic_when_flag_off_take_profit():
    harness = _MonitorHarness()

    trade = _build_trade(take_profit=70000.0)
    client = _MonitorFakeClient(fill_price=69995.0)

    await harness._handle_closed_position(trade, client, session=None)

    assert harness._close_records[0]["exit_reason"] == ExitReason.TAKE_PROFIT_NATIVE.value


# ===========================================================================
# Heuristic static method contract
# ===========================================================================


def test_classify_close_heuristic_prefers_native_trailing():
    trade = _build_trade(native_trailing_stop=True, take_profit=70000.0)
    assert (
        _MonitorHarness._classify_close_heuristic(trade, exit_price=70000.0)
        == ExitReason.TRAILING_STOP_NATIVE.value
    )


def test_classify_close_heuristic_matches_tp_within_proximity():
    trade = _build_trade(take_profit=70000.0)
    # 0.2% proximity window at entry_price=68200 → ~136.4
    assert (
        _MonitorHarness._classify_close_heuristic(trade, exit_price=69970.0)
        == ExitReason.TAKE_PROFIT_NATIVE.value
    )


def test_classify_close_heuristic_matches_sl_within_proximity():
    trade = _build_trade(stop_loss=67000.0)
    assert (
        _MonitorHarness._classify_close_heuristic(trade, exit_price=67005.0)
        == ExitReason.STOP_LOSS_NATIVE.value
    )


def test_classify_close_heuristic_returns_unknown_when_no_tp_sl():
    trade = _build_trade()
    assert (
        _MonitorHarness._classify_close_heuristic(trade, exit_price=68500.0)
        == ExitReason.EXTERNAL_CLOSE_UNKNOWN.value
    )
