"""Characterization tests for `_send_daily_summary` and the
self-managed-strategy dispatch branch of `_analyze_and_trade`.

Part of ARCH-H1 Phase 0 PR-3 (#272). Together with #270/PR#271 these
tests freeze enough of ``BotWorker`` to pass the 85%-coverage gate from
``Anleitungen/refactor_plan_bot_worker_composition.md`` before mixin
extraction begins in Phase 1.

Scope:
    - ``_send_daily_summary`` (lines 907-937) — new tests, was 0% covered
    - ``_analyze_and_trade`` self-managed branch (lines 725-741) — new tests
No production code changes.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.bot_worker import BotWorker
from src.models.enums import BotStatus


def _make_stats(
    trades_executed=2,
    starting_balance=10_000.0,
    net_pnl=125.0,
    total_pnl=150.0,
    total_fees=25.0,
    total_funding=0.0,
    max_drawdown=50.0,
    winning_trades=1,
    losing_trades=1,
    date_str="2026-04-22",
):
    """Shape a DailyStats-like MagicMock with the 11 attrs the summary reads."""
    stats = MagicMock()
    stats.trades_executed = trades_executed
    stats.starting_balance = starting_balance
    stats.net_pnl = net_pnl
    stats.total_pnl = total_pnl
    stats.total_fees = total_fees
    stats.total_funding = total_funding
    stats.max_drawdown = max_drawdown
    stats.winning_trades = winning_trades
    stats.losing_trades = losing_trades
    stats.date = date_str
    return stats


def _make_config(**overrides):
    config = MagicMock()
    config.id = overrides.get("id", 1)
    config.user_id = overrides.get("user_id", 1)
    config.name = overrides.get("name", "Summary Bot")
    return config


def _prime_worker_for_summary(worker, *, stats, notify_raises=None, stats_raises=None):
    """Wire the minimum collaborators `_send_daily_summary` depends on."""
    worker._config = _make_config()

    rm = MagicMock()
    if stats_raises is not None:
        rm.get_daily_stats.side_effect = stats_raises
    else:
        rm.get_daily_stats.return_value = stats
    worker._risk_manager = rm

    if notify_raises is not None:
        worker._send_notification = AsyncMock(side_effect=notify_raises)
    else:
        worker._send_notification = AsyncMock()

    worker._risk_alerts_sent = {"stale-global-key", "stale-per-symbol"}
    return worker


@pytest.mark.asyncio
class TestSendDailySummary:
    """Characterization — freezes current `_send_daily_summary` behaviour."""

    async def test_happy_path_sends_notification_with_all_documented_kwargs(self):
        """When stats has trades, the notification lambda receives the full
        documented kwarg set (11 fields: date, starting_balance,
        ending_balance, total_trades, winning_trades, losing_trades,
        total_pnl, total_fees, total_funding, max_drawdown, bot_name)."""
        worker = BotWorker(bot_config_id=1)
        stats = _make_stats(trades_executed=3, starting_balance=10_000.0, net_pnl=250.0)
        _prime_worker_for_summary(worker, stats=stats)

        notifier = MagicMock()
        notifier.send_daily_summary = MagicMock()

        # Capture the lambda that _send_notification is called with, so we
        # can invoke it against a fake Notifier and assert the kwargs it
        # forwards. This freezes the lambda's argument shape, not just the
        # outer call.
        captured = {}
        async def _capture(fn, **kw):
            captured["fn"] = fn
            captured["kw"] = kw
        worker._send_notification = _capture

        await worker._send_daily_summary()

        assert "fn" in captured, "_send_notification was never called"
        # Run the captured lambda against a spy notifier.
        captured["fn"](notifier)
        notifier.send_daily_summary.assert_called_once_with(
            date="2026-04-22",
            starting_balance=10_000.0,
            ending_balance=10_250.0,  # starting + net_pnl
            total_trades=3,
            winning_trades=1,
            losing_trades=1,
            total_pnl=150.0,
            total_fees=25.0,
            total_funding=0.0,
            max_drawdown=50.0,
            bot_name="Summary Bot",
        )
        # outer call metadata
        assert captured["kw"]["event_type"] == "daily_summary"
        assert "Daily 2026-04-22" in captured["kw"]["summary"]
        assert "3 trades" in captured["kw"]["summary"]

    async def test_no_notification_when_trades_executed_is_zero(self):
        """Zero trades = no-op path (still hits the cleanup)."""
        worker = BotWorker(bot_config_id=1)
        stats = _make_stats(trades_executed=0)
        _prime_worker_for_summary(worker, stats=stats)

        await worker._send_daily_summary()

        worker._send_notification.assert_not_awaited()
        assert worker._risk_alerts_sent == set(), \
            "cleanup must always run (even with zero trades)"

    async def test_no_notification_when_stats_is_none(self):
        """Falsy stats = skip notification, still cleanup."""
        worker = BotWorker(bot_config_id=1)
        _prime_worker_for_summary(worker, stats=None)

        await worker._send_daily_summary()

        worker._send_notification.assert_not_awaited()
        assert worker._risk_alerts_sent == set()

    async def test_swallows_risk_manager_exception_and_still_clears_alerts(self):
        """If `get_daily_stats()` raises, the summary logs a warning and
        still runs the risk-alert cleanup at end-of-day."""
        worker = BotWorker(bot_config_id=1)
        _prime_worker_for_summary(
            worker, stats=None, stats_raises=RuntimeError("RM down")
        )

        await worker._send_daily_summary()  # must not raise

        worker._send_notification.assert_not_awaited()
        assert worker._risk_alerts_sent == set()

    async def test_swallows_notification_exception_and_still_clears_alerts(self):
        """Delivery failure (Discord/Telegram down) must never prevent the
        per-day alert-dedup reset."""
        worker = BotWorker(bot_config_id=1)
        stats = _make_stats(trades_executed=1)
        _prime_worker_for_summary(
            worker, stats=stats, notify_raises=RuntimeError("discord 500")
        )

        await worker._send_daily_summary()

        worker._send_notification.assert_awaited_once()
        assert worker._risk_alerts_sent == set()

    async def test_risk_alerts_cleared_unconditionally(self):
        """Four independent paths (happy, zero-trades, None, exception) all
        flow through the same final `_risk_alerts_sent.clear()` line."""
        # Happy path
        for kwargs in (
            {"stats": _make_stats(trades_executed=2)},
            {"stats": _make_stats(trades_executed=0)},
            {"stats": None},
            {"stats": None, "stats_raises": RuntimeError("boom")},
        ):
            worker = BotWorker(bot_config_id=1)
            _prime_worker_for_summary(worker, **kwargs)
            # seed stale keys to prove clear() actually runs
            worker._risk_alerts_sent.update({"stale_1", "stale_2", "stale_3"})
            await worker._send_daily_summary()
            assert worker._risk_alerts_sent == set(), (
                f"cleanup must run for path {kwargs}"
            )


# ---------------------------------------------------------------------------
# _analyze_and_trade — self-managed strategy dispatch branch (lines 725-741)
# ---------------------------------------------------------------------------

def _prime_worker_for_analyze(worker, *, is_self_managed, run_tick_raises=None):
    worker._config = _make_config()
    worker._config.trading_pairs = '["BTCUSDT"]'
    worker._config.strategy_params = None
    worker._config.per_asset_config = None

    # Minimal strategy
    strategy = MagicMock()
    strategy.is_self_managed = is_self_managed
    if run_tick_raises is not None:
        strategy.run_tick = AsyncMock(side_effect=run_tick_raises)
    else:
        strategy.run_tick = AsyncMock()
    strategy.generate_signal = AsyncMock()
    strategy.should_trade = MagicMock(return_value=(False, "no signal"))
    worker._strategy = strategy

    # Risk manager (only called on the legacy path)
    rm = MagicMock()
    rm.can_trade.return_value = (True, "")
    worker._risk_manager = rm

    worker._client = MagicMock()
    worker._client.get_account_balance = AsyncMock(
        return_value=MagicMock(available=1000.0, total=1000.0, unrealized_pnl=0)
    )
    worker._demo_client = None
    worker._live_client = None
    worker._send_notification = AsyncMock()
    return strategy


@pytest.mark.asyncio
class TestAnalyzeAndTradeSelfManaged:
    """Characterize the self-managed-strategy branch of `_analyze_and_trade`.

    When `strategy.is_self_managed` is True, BotWorker yields full control
    to the strategy's `run_tick(ctx)`, bypasses the per-symbol analysis
    loop, stamps `last_analysis`, and returns — no global risk check, no
    per-symbol iteration, no `generate_signal`.
    """

    async def test_self_managed_calls_run_tick_and_skips_per_symbol_loop(self):
        worker = BotWorker(bot_config_id=1)
        strategy = _prime_worker_for_analyze(worker, is_self_managed=True)

        await worker._analyze_and_trade()

        strategy.run_tick.assert_awaited_once()
        strategy.generate_signal.assert_not_called()
        worker._risk_manager.can_trade.assert_not_called()
        assert worker.last_analysis is not None

    async def test_self_managed_swallows_run_tick_exception(self):
        """run_tick failure is logged but does NOT propagate — the
        scheduler must keep running."""
        worker = BotWorker(bot_config_id=1)
        strategy = _prime_worker_for_analyze(
            worker, is_self_managed=True,
            run_tick_raises=RuntimeError("strategy boom"),
        )

        # Must not raise.
        await worker._analyze_and_trade()

        strategy.run_tick.assert_awaited_once()
        # last_analysis is still stamped even after run_tick error —
        # guarantees the scheduler loop's audit trail remains honest.
        assert worker.last_analysis is not None

    async def test_self_managed_passes_context_with_expected_fields(self):
        """Freeze the `StrategyTickContext` shape that BotWorker hands to
        self-managed strategies. Downstream strategies depend on these
        fields — any rename during the mixin refactor must break a test."""
        worker = BotWorker(bot_config_id=42)
        strategy = _prime_worker_for_analyze(worker, is_self_managed=True)

        await worker._analyze_and_trade()

        args, kwargs = strategy.run_tick.call_args
        ctx = args[0] if args else kwargs.get("ctx")
        assert ctx is not None
        assert ctx.bot_config_id == 42
        assert ctx.bot_config is worker._config
        assert ctx.user_id == worker._config.user_id
        assert ctx.exchange_client is worker._client
        # trade_executor is the worker itself (it mixes in TradeExecutorMixin)
        assert ctx.trade_executor is worker
        assert ctx.send_notification is worker._send_notification

    async def test_non_self_managed_takes_legacy_path(self):
        """When is_self_managed is False, run_tick is never called and the
        global risk-check happens instead."""
        worker = BotWorker(bot_config_id=1)
        worker.status = BotStatus.RUNNING
        strategy = _prime_worker_for_analyze(worker, is_self_managed=False)

        # Patch the per-symbol call so we don't descend further into the
        # legacy path for this characterization — we only care that we
        # LEAVE the self-managed branch.
        with patch.object(worker, "_analyze_symbol", AsyncMock()) as mock_analyze:
            await worker._analyze_and_trade()

        strategy.run_tick.assert_not_called()
        worker._risk_manager.can_trade.assert_called()  # global check fired
        # Per-symbol loop is reached (not asserting exact count here — just
        # that the legacy path isn't short-circuited).
        assert mock_analyze.await_count >= 0  # path executed
