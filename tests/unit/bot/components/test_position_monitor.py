"""Unit tests for PositionMonitor component (ARCH-H1 Phase 1 PR-4, #281)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.components.position_monitor import (
    PositionMonitor,
    _GLITCH_ALERT_THRESHOLD,
    _POSITION_GONE_THRESHOLD,
)


def _make_trade(
    trade_id: int = 101,
    *,
    side: str = "long",
    entry_price: float = 50_000.0,
    status: str = "open",
    highest_price: float | None = None,
    native_trailing_stop: bool = False,
    take_profit: float | None = None,
    stop_loss: float | None = None,
    trailing_status: str | None = None,
) -> MagicMock:
    trade = MagicMock()
    trade.id = trade_id
    trade.symbol = "BTC-USDT"
    trade.side = side
    trade.size = 0.1
    trade.entry_price = entry_price
    trade.highest_price = highest_price
    trade.status = status
    trade.demo_mode = True
    trade.native_trailing_stop = native_trailing_stop
    trade.take_profit = take_profit
    trade.stop_loss = stop_loss
    trade.trailing_status = trailing_status
    trade.trailing_atr_override = None
    trade.fees = 0.0
    trade.funding_paid = 0.0
    trade.entry_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    trade.metrics_snapshot = None
    trade.order_id = "ord-1"
    trade.close_order_id = None
    return trade


def _make_monitor(
    *,
    config=None,
    strategy=None,
    rsm=None,
    client=None,
    close_trade: AsyncMock | None = None,
    notifier: AsyncMock | None = None,
) -> PositionMonitor:
    cfg = config if config is not None else SimpleNamespace(
        name="TestBot",
        margin_mode="cross",
        pnl_alert_settings=None,
        user_id=7,
    )
    return PositionMonitor(
        bot_config_id=42,
        config_getter=lambda: cfg,
        strategy_getter=lambda: strategy,
        risk_state_manager_getter=lambda: rsm,
        client_factory=lambda demo_mode: client,
        close_trade=close_trade or AsyncMock(),
        notification_sender=notifier or AsyncMock(),
    )


class TestClassifyCloseHeuristic:
    def test_native_trailing_takes_precedence(self):
        trade = _make_trade(native_trailing_stop=True, take_profit=51_000.0)
        assert (
            PositionMonitor.classify_close_heuristic(trade, 51_000.0)
            == "TRAILING_STOP_NATIVE"
        )

    def test_take_profit_when_exit_near_tp(self):
        trade = _make_trade(take_profit=51_000.0)
        assert (
            PositionMonitor.classify_close_heuristic(trade, 51_000.0)
            == "TAKE_PROFIT_NATIVE"
        )

    def test_stop_loss_when_exit_near_sl(self):
        trade = _make_trade(stop_loss=49_000.0)
        assert (
            PositionMonitor.classify_close_heuristic(trade, 49_000.0)
            == "STOP_LOSS_NATIVE"
        )

    def test_external_close_unknown_fallback(self):
        trade = _make_trade()  # no TP, no SL
        assert (
            PositionMonitor.classify_close_heuristic(trade, 50_500.0)
            == "EXTERNAL_CLOSE_UNKNOWN"
        )

    def test_proximity_window_outside_tp(self):
        # 0.2% proximity window — 52_000 is way outside TP=51_000.
        trade = _make_trade(take_profit=51_000.0)
        assert (
            PositionMonitor.classify_close_heuristic(trade, 52_000.0)
            == "EXTERNAL_CLOSE_UNKNOWN"
        )


@pytest.mark.asyncio
class TestMonitor:
    async def test_clears_caches_when_no_open_trades(self):
        monitor = _make_monitor()
        monitor._trailing_stop_backoff[999] = datetime.now(timezone.utc)
        monitor._glitch_counter["old-key"] = 5

        scalars = MagicMock()
        scalars.all.return_value = []
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars

        session = MagicMock()
        session.execute = AsyncMock(return_value=exec_result)

        with patch("src.bot.components.position_monitor.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(return_value=session)
            gs.return_value.__aexit__ = AsyncMock(return_value=False)
            await monitor.monitor()

        assert monitor._trailing_stop_backoff == {}
        assert monitor._glitch_counter == {}

    async def test_prunes_stale_trackers(self):
        monitor = _make_monitor()
        monitor._trailing_stop_backoff[999] = datetime.now(timezone.utc)
        monitor._glitch_counter["stale:XRP"] = 2
        monitor._pnl_alerts_sent[999] = {"profit_percent_5.0"}

        live = _make_trade(trade_id=101)

        scalars = MagicMock()
        scalars.all.return_value = [live]
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars

        session = MagicMock()
        session.execute = AsyncMock(return_value=exec_result)
        session.commit = AsyncMock()

        async def _noop_check(_trade, _session):
            return

        with patch("src.bot.components.position_monitor.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(return_value=session)
            gs.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(monitor, "check_position", _noop_check):
                await monitor.monitor()

        assert 999 not in monitor._trailing_stop_backoff
        assert "stale:XRP" not in monitor._glitch_counter
        assert 999 not in monitor._pnl_alerts_sent

    async def test_parses_pnl_alert_settings_when_enabled(self):
        cfg = SimpleNamespace(
            name="TB",
            margin_mode="cross",
            user_id=7,
            pnl_alert_settings='{"enabled": true, "thresholds": [5.0], "direction": "both"}',
        )
        monitor = _make_monitor(config=cfg)

        live = _make_trade(trade_id=101)
        scalars = MagicMock()
        scalars.all.return_value = [live]
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars

        session = MagicMock()
        session.execute = AsyncMock(return_value=exec_result)

        async def _noop_check(_trade, _session):
            return

        with patch("src.bot.components.position_monitor.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(return_value=session)
            gs.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(monitor, "check_position", _noop_check):
                await monitor.monitor()

        assert monitor._pnl_alert_parsed is not None
        assert monitor._pnl_alert_parsed.get("enabled") is True

    async def test_ignores_pnl_alert_settings_when_disabled(self):
        cfg = SimpleNamespace(
            name="TB",
            margin_mode="cross",
            user_id=7,
            pnl_alert_settings='{"enabled": false, "thresholds": [5.0]}',
        )
        monitor = _make_monitor(config=cfg)

        live = _make_trade(trade_id=101)
        scalars = MagicMock()
        scalars.all.return_value = [live]
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars

        session = MagicMock()
        session.execute = AsyncMock(return_value=exec_result)

        async def _noop_check(_trade, _session):
            return

        with patch("src.bot.components.position_monitor.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(return_value=session)
            gs.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(monitor, "check_position", _noop_check):
                await monitor.monitor()

        assert monitor._pnl_alert_parsed is None

    async def test_ignores_malformed_pnl_alert_json(self):
        cfg = SimpleNamespace(
            name="TB",
            margin_mode="cross",
            user_id=7,
            pnl_alert_settings="not-valid-json",
        )
        monitor = _make_monitor(config=cfg)

        scalars = MagicMock()
        scalars.all.return_value = [_make_trade()]
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars

        session = MagicMock()
        session.execute = AsyncMock(return_value=exec_result)

        async def _noop_check(_trade, _session):
            return

        with patch("src.bot.components.position_monitor.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(return_value=session)
            gs.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(monitor, "check_position", _noop_check):
                await monitor.monitor()

        assert monitor._pnl_alert_parsed is None


@pytest.mark.asyncio
class TestMonitorSafe:
    async def test_swallows_exceptions(self):
        monitor = _make_monitor()

        async def _explode():
            raise RuntimeError("boom")

        with patch.object(monitor, "monitor", _explode):
            await monitor.monitor_safe()  # should NOT raise


@pytest.mark.asyncio
class TestConfirmPositionClosed:
    async def test_returns_true_when_position_gone_after_all_retries(self):
        client = MagicMock()
        client.get_position = AsyncMock(return_value=None)

        monitor = _make_monitor(client=client)
        trade = _make_trade()

        with patch("src.bot.components.position_monitor.asyncio.sleep", AsyncMock()):
            confirmed = await monitor.confirm_position_closed(trade, client)

        assert confirmed is True
        assert client.get_position.call_count == _POSITION_GONE_THRESHOLD

    async def test_returns_false_when_position_reappears(self):
        # First retry finds the position → glitch, must return False.
        client = MagicMock()
        client.get_position = AsyncMock(return_value=MagicMock(side="long"))

        monitor = _make_monitor(client=client)
        trade = _make_trade()

        with patch("src.bot.components.position_monitor.asyncio.sleep", AsyncMock()):
            confirmed = await monitor.confirm_position_closed(trade, client)

        assert confirmed is False
        assert monitor._glitch_counter[f"42:{trade.symbol}"] == 1

    async def test_returns_false_when_all_retries_raise(self):
        # Bug 1 guard: if every retry throws, we must NOT falsely confirm closure.
        client = MagicMock()
        client.get_position = AsyncMock(side_effect=RuntimeError("api down"))

        monitor = _make_monitor(client=client)
        trade = _make_trade()

        with patch("src.bot.components.position_monitor.asyncio.sleep", AsyncMock()):
            confirmed = await monitor.confirm_position_closed(trade, client)

        assert confirmed is False

    async def test_sends_notification_at_glitch_alert_threshold(self):
        client = MagicMock()
        client.get_position = AsyncMock(return_value=MagicMock(side="long"))

        notifier = AsyncMock()
        monitor = _make_monitor(client=client, notifier=notifier)
        trade = _make_trade()

        # Pre-load the glitch counter to (threshold - 1) so the next glitch hits.
        glitch_key = f"42:{trade.symbol}"
        monitor._glitch_counter[glitch_key] = _GLITCH_ALERT_THRESHOLD - 1

        with patch("src.bot.components.position_monitor.asyncio.sleep", AsyncMock()):
            await monitor.confirm_position_closed(trade, client)

        assert notifier.await_count == 1
        assert monitor._glitch_counter[glitch_key] == _GLITCH_ALERT_THRESHOLD


@pytest.mark.asyncio
class TestCheckPnlAlert:
    async def test_sends_profit_alert_once_per_threshold(self):
        notifier = AsyncMock()
        monitor = _make_monitor(notifier=notifier)
        monitor._pnl_alert_parsed = {
            "enabled": True,
            "direction": "both",
            "thresholds": [5.0],
        }

        trade = _make_trade()
        # +5% move: entry 50_000 long → price 52_500 = +5%.
        await monitor.check_pnl_alert(trade, 52_500.0)
        await monitor.check_pnl_alert(trade, 52_600.0)  # still above — must NOT resend

        assert notifier.await_count == 1
        sent_keys = monitor._pnl_alerts_sent[trade.id]
        assert any("profit" in k for k in sent_keys)

    async def test_sends_loss_alert_once(self):
        notifier = AsyncMock()
        monitor = _make_monitor(notifier=notifier)
        monitor._pnl_alert_parsed = {
            "enabled": True,
            "direction": "loss",
            "thresholds": [5.0],
        }

        trade = _make_trade()
        # -5% move: 50_000 long → 47_500 = -5%.
        await monitor.check_pnl_alert(trade, 47_500.0)
        await monitor.check_pnl_alert(trade, 47_400.0)

        assert notifier.await_count == 1

    async def test_direction_filter_suppresses_wrong_side(self):
        notifier = AsyncMock()
        monitor = _make_monitor(notifier=notifier)
        # direction=profit but trade is losing → no alert.
        monitor._pnl_alert_parsed = {
            "enabled": True,
            "direction": "profit",
            "thresholds": [5.0],
        }
        trade = _make_trade()
        await monitor.check_pnl_alert(trade, 47_500.0)

        assert notifier.await_count == 0

    async def test_returns_early_when_no_alert_config(self):
        notifier = AsyncMock()
        monitor = _make_monitor(notifier=notifier)
        monitor._pnl_alert_parsed = None

        await monitor.check_pnl_alert(_make_trade(), 60_000.0)
        assert notifier.await_count == 0

    async def test_handles_dict_threshold_with_dollar_mode(self):
        notifier = AsyncMock()
        monitor = _make_monitor(notifier=notifier)
        monitor._pnl_alert_parsed = {
            "enabled": True,
            "direction": "both",
            "thresholds": [{"value": 100.0, "mode": "dollar"}],
        }
        # long 0.1 @ 50_000 → +$100 abs when price moves to 51_000.
        trade = _make_trade()
        await monitor.check_pnl_alert(trade, 51_000.0)

        assert notifier.await_count == 1


@pytest.mark.asyncio
class TestCheckPosition:
    async def test_skips_when_no_client(self):
        monitor = _make_monitor(client=None)
        trade = _make_trade()
        session = MagicMock()
        # Should just return without raising.
        await monitor.check_position(trade, session)

    async def test_triggers_handle_closed_when_position_gone_and_confirmed(self):
        client = MagicMock()
        client.get_position = AsyncMock(return_value=None)

        close_trade = AsyncMock()
        monitor = _make_monitor(client=client, close_trade=close_trade)

        trade = _make_trade()
        session = MagicMock()

        with patch.object(monitor, "confirm_position_closed", AsyncMock(return_value=True)) as confirm, \
             patch.object(monitor, "handle_closed_position", AsyncMock()) as handle:
            await monitor.check_position(trade, session)

        assert confirm.await_count == 1
        assert handle.await_count == 1

    async def test_skips_handle_closed_when_confirmation_fails(self):
        client = MagicMock()
        client.get_position = AsyncMock(return_value=None)
        monitor = _make_monitor(client=client)
        trade = _make_trade()
        session = MagicMock()

        with patch.object(monitor, "confirm_position_closed", AsyncMock(return_value=False)) as confirm, \
             patch.object(monitor, "handle_closed_position", AsyncMock()) as handle:
            await monitor.check_position(trade, session)

        assert confirm.await_count == 1
        assert handle.await_count == 0


@pytest.mark.asyncio
class TestHandleClosedPosition:
    async def test_uses_rsm_when_available(self):
        client = MagicMock()
        client.get_close_fill_price = AsyncMock(return_value=51_000.0)
        client.get_ticker = AsyncMock(return_value=MagicMock(last_price=51_000.0))
        client.get_trade_total_fees = AsyncMock(return_value=0.5)
        client.get_funding_fees = AsyncMock(return_value=0.0)
        client._last_close_order_id = "close-1"

        rsm = MagicMock()
        rsm.classify_close = AsyncMock(return_value="TAKE_PROFIT_NATIVE")

        close_trade = AsyncMock()
        monitor = _make_monitor(client=client, rsm=rsm, close_trade=close_trade)

        trade = _make_trade()
        session = MagicMock()

        await monitor.handle_closed_position(trade, client, session)

        assert rsm.classify_close.await_count == 1
        assert close_trade.await_count == 1
        # First positional arg after trade is exit_price; the reason is the 3rd arg.
        args, _ = close_trade.call_args
        assert args[2] == "TAKE_PROFIT_NATIVE"

    async def test_falls_back_to_heuristic_when_rsm_raises(self):
        client = MagicMock()
        client.get_close_fill_price = AsyncMock(return_value=51_000.0)
        client.get_ticker = AsyncMock(return_value=MagicMock(last_price=51_000.0))
        client.get_trade_total_fees = AsyncMock(return_value=0.0)
        client.get_funding_fees = AsyncMock(return_value=0.0)
        client._last_close_order_id = None

        rsm = MagicMock()
        rsm.classify_close = AsyncMock(side_effect=RuntimeError("oops"))

        close_trade = AsyncMock()
        monitor = _make_monitor(client=client, rsm=rsm, close_trade=close_trade)
        # Trade has TP≈51_000 → heuristic should tag as TP.
        trade = _make_trade(take_profit=51_000.0)
        session = MagicMock()

        await monitor.handle_closed_position(trade, client, session)

        args, _ = close_trade.call_args
        assert args[2] == "TAKE_PROFIT_NATIVE"

    async def test_uses_heuristic_when_no_rsm(self):
        client = MagicMock()
        client.get_close_fill_price = AsyncMock(return_value=49_000.0)
        client.get_ticker = AsyncMock(return_value=MagicMock(last_price=49_000.0))
        client.get_trade_total_fees = AsyncMock(return_value=0.0)
        client.get_funding_fees = AsyncMock(return_value=0.0)
        client._last_close_order_id = None

        close_trade = AsyncMock()
        monitor = _make_monitor(client=client, rsm=None, close_trade=close_trade)
        trade = _make_trade(stop_loss=49_000.0)
        session = MagicMock()

        await monitor.handle_closed_position(trade, client, session)

        args, _ = close_trade.call_args
        assert args[2] == "STOP_LOSS_NATIVE"

    async def test_clears_trailing_backoff_for_closed_trade(self):
        client = MagicMock()
        client.get_close_fill_price = AsyncMock(return_value=51_000.0)
        client.get_ticker = AsyncMock(return_value=MagicMock(last_price=51_000.0))
        client.get_trade_total_fees = AsyncMock(return_value=0.0)
        client.get_funding_fees = AsyncMock(return_value=0.0)
        client._last_close_order_id = None

        monitor = _make_monitor(client=client, close_trade=AsyncMock())
        trade = _make_trade()
        monitor._trailing_stop_backoff[trade.id] = datetime.now(timezone.utc)

        await monitor.handle_closed_position(trade, client, MagicMock())
        assert trade.id not in monitor._trailing_stop_backoff
