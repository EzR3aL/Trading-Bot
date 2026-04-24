"""Tests for bot-level Prometheus instrumentation (#327 PR-3).

Covers the four call-site groups landed in PR-3:

1. ``BotWorker._analyze_symbol_locked`` — ``BOT_SIGNALS_GENERATED_TOTAL``
   is incremented with ``(bot_id, exchange, strategy, side)`` labels for
   long/short signals and left alone for neutral / ``None``.
2. ``TradeExecutor.execute`` — ``BOT_TRADES_EXECUTED_TOTAL`` with a
   ``result`` label in ``{success, rejected, failed}`` plus
   ``BOT_TRADE_EXECUTION_DURATION_SECONDS`` observed at least once.
3. ``PositionMonitor.monitor`` —
   ``BOT_POSITION_MONITOR_TICK_DURATION_SECONDS`` observed per tick.
4. ``_collect_observability_bot_gauges`` — ``BOT_OPEN_POSITIONS`` and
   ``BOT_DAILY_PNL`` set from worker + DB state.

Registry isolation
------------------
The observability registry is a single process-global
``CollectorRegistry`` (PR-1). Counters and histograms cannot be reset
in-place, so these tests diff label-specific values before and after
the call-site runs, following the pattern established in
``tests/unit/api/middleware/test_metrics_middleware.py``.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure repo root on sys.path before importing src.*
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo=")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _counter_value(counter, **labels) -> float:
    """Read the current value of a labelled ``prometheus_client`` Counter/Gauge."""
    return counter.labels(**labels)._value.get()


def _histogram_sum(histogram, **labels) -> float:
    """Return ``_sum`` of a labelled histogram. >0 proves ``.observe`` ran."""
    return histogram.labels(**labels)._sum.get()


def _histogram_sum(histogram, **labels) -> float:
    """Return the labelled histogram's running ``_sum`` value.

    ``prometheus_client.Histogram`` does not expose a public counter of
    the total observation count per child series, so the tests diff
    ``_sum`` before / after the call site runs: every real observation
    adds a strictly positive duration to the sum, which proves at
    least one ``.observe()`` landed on that label combination.
    """
    return histogram.labels(**labels)._sum.get()


# ---------------------------------------------------------------------------
# 1. BotWorker signal emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBotSignalsGenerated:
    """``BotWorker._analyze_symbol_locked`` — signal counter semantics."""

    async def test_long_signal_increments_counter_with_expected_labels(self):
        from src.bot.bot_worker import BotWorker
        from src.observability.metrics import BOT_SIGNALS_GENERATED_TOTAL
        from src.strategy.base import SignalDirection, TradeSignal

        worker = BotWorker.__new__(BotWorker)
        worker.bot_config_id = 4242
        worker._config = MagicMock(
            exchange_type="bitget",
            strategy_type="edge_indicator",
        )
        worker._shutting_down = False
        worker._last_signal_keys = {}

        risk_manager = MagicMock()
        risk_manager.can_trade.return_value = (True, "")
        worker._risk_manager = risk_manager

        strategy = MagicMock()
        signal = TradeSignal(
            direction=SignalDirection.LONG,
            confidence=80,
            symbol="BTCUSDT",
            entry_price=50000.0,
            target_price=52000.0,
            stop_loss=48000.0,
            reason="unit-test",
            metrics_snapshot={},
            timestamp=datetime.now(timezone.utc),
        )
        strategy.generate_signal = AsyncMock(return_value=signal)
        strategy.should_trade = AsyncMock(return_value=(False, "halt-for-test"))
        worker._strategy = strategy

        before = _counter_value(
            BOT_SIGNALS_GENERATED_TOTAL,
            bot_id="4242",
            exchange="bitget",
            strategy="edge_indicator",
            side="long",
        )

        # Use a context manager that short-circuits the DB + cooldown paths
        # so the test focuses purely on signal-counter semantics.
        with patch.object(worker, "_get_symbol_lock"), \
             patch.object(worker, "_get_strategy_param", return_value=0.0), \
             patch("src.bot.bot_worker.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                execute=AsyncMock(
                    return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
                )
            ))
            gs.return_value.__aexit__ = AsyncMock(return_value=False)

            await worker._analyze_symbol_locked("BTCUSDT", force=True)

        after = _counter_value(
            BOT_SIGNALS_GENERATED_TOTAL,
            bot_id="4242",
            exchange="bitget",
            strategy="edge_indicator",
            side="long",
        )
        assert after == before + 1

    async def test_neutral_signal_does_not_increment_counter(self):
        from src.bot.bot_worker import BotWorker
        from src.observability.metrics import BOT_SIGNALS_GENERATED_TOTAL
        from src.strategy.base import SignalDirection, TradeSignal

        worker = BotWorker.__new__(BotWorker)
        worker.bot_config_id = 4243
        worker._config = MagicMock(
            exchange_type="bitget",
            strategy_type="edge_indicator",
        )
        worker._shutting_down = False
        worker._last_signal_keys = {}
        risk_manager = MagicMock()
        risk_manager.can_trade.return_value = (True, "")
        worker._risk_manager = risk_manager

        strategy = MagicMock()
        strategy.generate_signal = AsyncMock(return_value=TradeSignal(
            direction=SignalDirection.NEUTRAL,
            confidence=0,
            symbol="BTCUSDT",
            entry_price=50000.0,
            target_price=None,
            stop_loss=None,
            reason="unit-test-neutral",
            metrics_snapshot={},
            timestamp=datetime.now(timezone.utc),
        ))
        strategy.should_trade = AsyncMock(return_value=(False, "neutral"))
        worker._strategy = strategy

        # Snapshot every label the emitter could have touched for this bot.
        before_long = _counter_value(
            BOT_SIGNALS_GENERATED_TOTAL,
            bot_id="4243", exchange="bitget", strategy="edge_indicator", side="long",
        )
        before_short = _counter_value(
            BOT_SIGNALS_GENERATED_TOTAL,
            bot_id="4243", exchange="bitget", strategy="edge_indicator", side="short",
        )

        with patch.object(worker, "_get_symbol_lock"), \
             patch.object(worker, "_get_strategy_param", return_value=0.0), \
             patch("src.bot.bot_worker.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                execute=AsyncMock(
                    return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
                )
            ))
            gs.return_value.__aexit__ = AsyncMock(return_value=False)

            await worker._analyze_symbol_locked("BTCUSDT", force=True)

        assert _counter_value(
            BOT_SIGNALS_GENERATED_TOTAL,
            bot_id="4243", exchange="bitget", strategy="edge_indicator", side="long",
        ) == before_long
        assert _counter_value(
            BOT_SIGNALS_GENERATED_TOTAL,
            bot_id="4243", exchange="bitget", strategy="edge_indicator", side="short",
        ) == before_short


# ---------------------------------------------------------------------------
# 2. TradeExecutor.execute — trade counter + histogram
# ---------------------------------------------------------------------------


def _make_trade_signal(direction_value: str = "long"):
    from src.strategy.base import SignalDirection, TradeSignal

    direction = {
        "long": SignalDirection.LONG,
        "short": SignalDirection.SHORT,
    }[direction_value]
    return TradeSignal(
        direction=direction,
        confidence=80,
        symbol="BTCUSDT",
        entry_price=50000.0,
        target_price=52000.0,
        stop_loss=48000.0,
        reason="unit-test",
        metrics_snapshot={},
        timestamp=datetime.now(timezone.utc),
    )


def _make_executor_config(**overrides):
    cfg = MagicMock()
    cfg.user_id = 1
    cfg.name = "TestBot"
    cfg.per_asset_config = "{}"
    cfg.leverage = 2
    cfg.take_profit_percent = None
    cfg.stop_loss_percent = None
    cfg.margin_mode = "cross"
    cfg.exchange_type = "bitget"
    cfg.demo_mode = True
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _trade_executor_session_ctx():
    """Minimal async session stub for ``get_session`` inside execute()."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
class TestBotTradesExecuted:
    async def test_success_increments_counter_and_histogram(self):
        from src.bot.components.trade_executor import TradeExecutor
        from src.observability.metrics import (
            BOT_TRADES_EXECUTED_TOTAL,
            BOT_TRADE_EXECUTION_DURATION_SECONDS,
        )

        config = _make_executor_config(exchange_type="bitget")
        risk_manager = MagicMock()
        risk_manager.can_trade.return_value = (True, "")
        risk_manager.calculate_position_size.return_value = (200.0, 0.004)

        executor = TradeExecutor(
            bot_config_id=11,
            config_getter=lambda: config,
            risk_manager_getter=lambda: risk_manager,
            close_trade=AsyncMock(),
            notification_sender=AsyncMock(),
            client_getter=lambda: None,
            on_trade_opened=MagicMock(),
            on_fatal_error=MagicMock(),
        )

        order = MagicMock()
        order.order_id = "ord-success"
        order.price = 50000.0
        order.tpsl_failed = False

        client = AsyncMock()
        client.get_account_balance.return_value = MagicMock(available=1000)
        client.set_leverage = AsyncMock(return_value=True)
        client.place_market_order = AsyncMock(return_value=order)
        client.get_fill_price = AsyncMock(return_value=50000.0)

        label_kw = dict(
            bot_id="11", exchange="bitget", mode="demo", result="success",
        )
        before_count = _counter_value(BOT_TRADES_EXECUTED_TOTAL, **label_kw)
        before_hist_sum = BOT_TRADE_EXECUTION_DURATION_SECONDS.labels(
            exchange="bitget",
        )._sum.get()

        with patch(
            "src.bot.components.trade_executor.get_session",
            return_value=_trade_executor_session_ctx(),
        ):
            await executor.execute(_make_trade_signal(), client, demo_mode=True)

        assert _counter_value(BOT_TRADES_EXECUTED_TOTAL, **label_kw) == before_count + 1
        after_hist_sum = BOT_TRADE_EXECUTION_DURATION_SECONDS.labels(
            exchange="bitget",
        )._sum.get()
        assert after_hist_sum > before_hist_sum, (
            "trade-execution histogram must advance by the observed duration"
        )

    async def test_rejected_when_place_market_order_returns_none(self):
        from src.bot.components.trade_executor import TradeExecutor
        from src.observability.metrics import BOT_TRADES_EXECUTED_TOTAL

        config = _make_executor_config(exchange_type="bitget")
        risk_manager = MagicMock()
        risk_manager.can_trade.return_value = (True, "")
        risk_manager.calculate_position_size.return_value = (200.0, 0.004)

        executor = TradeExecutor(
            bot_config_id=12,
            config_getter=lambda: config,
            risk_manager_getter=lambda: risk_manager,
            close_trade=AsyncMock(),
            notification_sender=AsyncMock(),
            client_getter=lambda: None,
            on_trade_opened=MagicMock(),
            on_fatal_error=MagicMock(),
        )

        client = AsyncMock()
        client.get_account_balance.return_value = MagicMock(available=1000)
        client.set_leverage = AsyncMock(return_value=True)
        client.place_market_order = AsyncMock(return_value=None)

        label_kw = dict(
            bot_id="12", exchange="bitget", mode="live", result="rejected",
        )
        before = _counter_value(BOT_TRADES_EXECUTED_TOTAL, **label_kw)

        with patch(
            "src.bot.components.trade_executor.get_session",
            return_value=_trade_executor_session_ctx(),
        ):
            await executor.execute(_make_trade_signal(), client, demo_mode=False)

        assert _counter_value(BOT_TRADES_EXECUTED_TOTAL, **label_kw) == before + 1

    async def test_failed_when_exchange_raises(self):
        from src.bot.components.trade_executor import TradeExecutor
        from src.exceptions import ExchangeError
        from src.observability.metrics import BOT_TRADES_EXECUTED_TOTAL

        config = _make_executor_config(exchange_type="hyperliquid")
        risk_manager = MagicMock()
        risk_manager.can_trade.return_value = (True, "")
        risk_manager.calculate_position_size.return_value = (200.0, 0.004)

        executor = TradeExecutor(
            bot_config_id=13,
            config_getter=lambda: config,
            risk_manager_getter=lambda: risk_manager,
            close_trade=AsyncMock(),
            notification_sender=AsyncMock(),
            client_getter=lambda: None,
            on_trade_opened=MagicMock(),
            on_fatal_error=MagicMock(),
        )

        client = AsyncMock()
        client.get_account_balance.return_value = MagicMock(available=1000)
        client.set_leverage = AsyncMock(return_value=True)
        client.place_market_order = AsyncMock(side_effect=ExchangeError(
            "hyperliquid", "nope",
        ))

        label_kw = dict(
            bot_id="13", exchange="hyperliquid", mode="demo", result="failed",
        )
        before = _counter_value(BOT_TRADES_EXECUTED_TOTAL, **label_kw)

        # Stub the failure-notification side effects so the test stays
        # narrow — they are covered by the existing trade_executor tests.
        executor.notify_trade_failure = AsyncMock()
        executor.resolve_pending_trade = AsyncMock()

        with patch(
            "src.bot.components.trade_executor.get_session",
            return_value=_trade_executor_session_ctx(),
        ):
            await executor.execute(_make_trade_signal(), client, demo_mode=True)

        assert _counter_value(BOT_TRADES_EXECUTED_TOTAL, **label_kw) == before + 1


# ---------------------------------------------------------------------------
# 3. PositionMonitor.monitor — tick-duration histogram
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPositionMonitorTickDuration:
    async def test_monitor_tick_observes_duration_histogram(self):
        from src.bot.components.position_monitor import PositionMonitor
        from src.observability.metrics import (
            BOT_POSITION_MONITOR_TICK_DURATION_SECONDS,
        )

        monitor = PositionMonitor(
            bot_config_id=21,
            config_getter=lambda: MagicMock(pnl_alert_settings=None),
            strategy_getter=lambda: None,
            risk_state_manager_getter=lambda: None,
            client_factory=lambda _demo: None,
            close_trade=AsyncMock(),
            notification_sender=AsyncMock(),
        )

        before_sum = BOT_POSITION_MONITOR_TICK_DURATION_SECONDS.labels(
            bot_id="21",
        )._sum.get()

        # Stub the inner body so we're only asserting on the timing wrapper.
        monitor._monitor_body = AsyncMock()

        await monitor.monitor()

        after_sum = BOT_POSITION_MONITOR_TICK_DURATION_SECONDS.labels(
            bot_id="21",
        )._sum.get()
        assert after_sum > before_sum, (
            "monitor tick histogram must advance by the observed duration"
        )

    async def test_histogram_still_observed_when_body_raises(self):
        from src.bot.components.position_monitor import PositionMonitor
        from src.observability.metrics import (
            BOT_POSITION_MONITOR_TICK_DURATION_SECONDS,
        )

        monitor = PositionMonitor(
            bot_config_id=22,
            config_getter=lambda: MagicMock(pnl_alert_settings=None),
            strategy_getter=lambda: None,
            risk_state_manager_getter=lambda: None,
            client_factory=lambda _demo: None,
            close_trade=AsyncMock(),
            notification_sender=AsyncMock(),
        )

        monitor._monitor_body = AsyncMock(side_effect=RuntimeError("boom"))

        before = BOT_POSITION_MONITOR_TICK_DURATION_SECONDS.labels(
            bot_id="22",
        )._sum.get()

        with pytest.raises(RuntimeError):
            await monitor.monitor()

        after = BOT_POSITION_MONITOR_TICK_DURATION_SECONDS.labels(
            bot_id="22",
        )._sum.get()
        assert after > before, (
            "tick histogram must be observed even when the body raises"
        )


# ---------------------------------------------------------------------------
# 4. Collector gauges — BOT_OPEN_POSITIONS + BOT_DAILY_PNL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCollectorObservabilityGauges:
    async def test_open_positions_and_daily_pnl_are_set_per_bot(self):
        from src.monitoring.collectors import _collect_observability_bot_gauges
        from src.observability.metrics import BOT_DAILY_PNL, BOT_OPEN_POSITIONS

        worker = MagicMock()
        worker._config = MagicMock(exchange_type="bitget")

        stats = MagicMock()
        stats.net_pnl = 42.5
        risk_manager = MagicMock()
        risk_manager.get_daily_stats.return_value = stats
        worker._risk_manager = risk_manager

        workers = {55: worker}

        # The collector queries the DB for the open-positions count; stub
        # ``get_session`` so the gauge picks up a deterministic value.
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one=MagicMock(return_value=3)),
        )
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.models.session.get_session",
            return_value=session,
        ):
            await _collect_observability_bot_gauges(workers)

        assert (
            _counter_value(
                BOT_OPEN_POSITIONS, bot_id="55", exchange="bitget",
            )
            == 3
        )
        assert (
            _counter_value(
                BOT_DAILY_PNL, bot_id="55", exchange="bitget",
            )
            == pytest.approx(42.5)
        )
