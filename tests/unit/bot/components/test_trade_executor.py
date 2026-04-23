"""Unit tests for the extracted TradeExecutor component (#72, ARCH-H1 Phase 1 PR-5).

These tests pin the behavior of ``src.bot.components.trade_executor.TradeExecutor``
in isolation (i.e. without going through the BotWorker / mixin). The full
integration path is covered by the existing ``tests/integration/test_tpsl_flow.py``
and the pre-existing BotWorker unit tests, which continue to exercise the
mixin proxy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.components.trade_executor import (
    TradeExecutor,
    _is_fatal_error,
    _make_user_friendly,
)
from src.exceptions import OrderError
from src.strategy import TradeSignal
from src.strategy.base import SignalDirection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    symbol: str = "BTCUSDT",
    direction: SignalDirection = SignalDirection.LONG,
    entry_price: float = 50000.0,
    target_price: float | None = 52000.0,
    stop_loss: float | None = 48000.0,
    confidence: int = 80,
) -> TradeSignal:
    return TradeSignal(
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        target_price=target_price,
        stop_loss=stop_loss,
        confidence=confidence,
        reason="unit-test",
        metrics_snapshot={},
        timestamp=datetime.now(timezone.utc),
    )


def _make_config(**overrides) -> MagicMock:
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


def _make_risk_manager(can_trade: tuple[bool, str] = (True, "")) -> MagicMock:
    rm = MagicMock()
    rm.can_trade.return_value = can_trade
    rm.calculate_position_size.return_value = (200.0, 0.004)
    return rm


def _make_order(
    order_id: str = "ord-1",
    price: float = 50000.0,
    tpsl_failed: bool = False,
) -> MagicMock:
    order = MagicMock()
    order.order_id = order_id
    order.price = price
    order.tpsl_failed = tpsl_failed
    return order


def _make_executor(
    *,
    config: MagicMock | None = None,
    risk_manager: MagicMock | None = None,
    close_trade: AsyncMock | None = None,
    notification_sender: AsyncMock | None = None,
    client: MagicMock | None = None,
    on_trade_opened: MagicMock | None = None,
    on_fatal_error: MagicMock | None = None,
) -> tuple[TradeExecutor, dict]:
    """Build a TradeExecutor with mocked dependencies + return the mocks bag."""
    config = config or _make_config()
    risk_manager = risk_manager or _make_risk_manager()
    close_trade = close_trade or AsyncMock()
    notification_sender = notification_sender or AsyncMock()
    on_trade_opened = on_trade_opened or MagicMock()
    on_fatal_error = on_fatal_error or MagicMock()

    ex = TradeExecutor(
        bot_config_id=7,
        config_getter=lambda: config,
        risk_manager_getter=lambda: risk_manager,
        close_trade=close_trade,
        notification_sender=notification_sender,
        client_getter=lambda: client,
        on_trade_opened=on_trade_opened,
        on_fatal_error=on_fatal_error,
    )
    return ex, {
        "config": config,
        "risk_manager": risk_manager,
        "close_trade": close_trade,
        "notification_sender": notification_sender,
        "client": client,
        "on_trade_opened": on_trade_opened,
        "on_fatal_error": on_fatal_error,
    }


def _session_ctx() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# Free-standing helpers
# ---------------------------------------------------------------------------


class TestErrorClassifiers:
    def test_make_user_friendly_hyperliquid_wallet(self):
        raw = "User or API Wallet 0xabcdef1234567890abcdef does not exist"
        friendly = _make_user_friendly(raw)
        assert "Hyperliquid-Wallet" in friendly
        assert "0xabcdef" in friendly

    def test_make_user_friendly_rate_limit(self):
        assert "Zu viele Anfragen" in _make_user_friendly("429 Too Many Requests")

    def test_make_user_friendly_unknown_returns_raw(self):
        raw = "Totally unrecognized error message"
        assert _make_user_friendly(raw) == raw

    def test_is_fatal_detects_invalid_api_key(self):
        assert _is_fatal_error("Invalid API key") is True

    def test_is_fatal_ignores_transient_errors(self):
        assert _is_fatal_error("network timeout") is False


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecute:
    async def test_skips_when_entry_price_invalid(self):
        ex, mocks = _make_executor()
        mock_client = AsyncMock()
        signal = _make_signal(entry_price=0)

        await ex.execute(signal, mock_client, demo_mode=True)

        mock_client.place_market_order.assert_not_awaited()
        mocks["on_trade_opened"].assert_not_called()

    async def test_skips_when_risk_manager_denies(self):
        rm = _make_risk_manager(can_trade=(False, "daily loss limit hit"))
        ex, mocks = _make_executor(risk_manager=rm)

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(available=1000)

        await ex.execute(_make_signal(), mock_client, demo_mode=True)

        mock_client.place_market_order.assert_not_awaited()
        mocks["on_trade_opened"].assert_not_called()

    async def test_skips_when_position_too_small(self):
        rm = _make_risk_manager()
        rm.calculate_position_size.return_value = (3.0, 0.00003)  # < $5 minimum
        ex, mocks = _make_executor(risk_manager=rm)

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(available=10)

        await ex.execute(_make_signal(), mock_client, demo_mode=True)

        mock_client.place_market_order.assert_not_awaited()
        mocks["on_trade_opened"].assert_not_called()

    async def test_skips_when_set_leverage_fails(self):
        ex, mocks = _make_executor()
        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(available=1000)
        mock_client.set_leverage = AsyncMock(return_value=False)

        with patch("src.bot.components.trade_executor.get_session", return_value=_session_ctx()):
            await ex.execute(_make_signal(), mock_client, demo_mode=True)

        mock_client.place_market_order.assert_not_awaited()
        mocks["on_trade_opened"].assert_not_called()

    async def test_places_order_and_fires_on_trade_opened(self):
        ex, mocks = _make_executor()
        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(available=1000)
        mock_client.set_leverage = AsyncMock(return_value=True)
        mock_client.place_market_order = AsyncMock(return_value=_make_order())
        mock_client.get_fill_price = AsyncMock(return_value=50123.0)

        with patch("src.bot.components.trade_executor.get_session", return_value=_session_ctx()):
            await ex.execute(_make_signal(), mock_client, demo_mode=True)

        mock_client.place_market_order.assert_awaited_once()
        mocks["risk_manager"].record_trade_entry.assert_called_once()
        mocks["on_trade_opened"].assert_called_once()
        # Notification lambda is dispatched
        mocks["notification_sender"].assert_awaited()

    async def test_order_error_triggers_notify_and_resolve_pending(self):
        ex, mocks = _make_executor()
        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(available=1000)
        mock_client.set_leverage = AsyncMock(return_value=True)
        mock_client.place_market_order = AsyncMock(side_effect=OrderError("bitget", "API rate limit"))

        ex.notify_trade_failure = AsyncMock()
        ex.resolve_pending_trade = AsyncMock()

        with patch("src.bot.components.trade_executor.get_session", return_value=_session_ctx()):
            await ex.execute(_make_signal(), mock_client, demo_mode=True)

        ex.notify_trade_failure.assert_awaited_once()
        ex.resolve_pending_trade.assert_awaited_once()
        assert "API rate limit" in ex.notify_trade_failure.await_args[0][2]

    async def test_minimum_amount_order_error_does_not_notify(self):
        ex, mocks = _make_executor()
        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(available=1000)
        mock_client.set_leverage = AsyncMock(return_value=True)
        mock_client.place_market_order = AsyncMock(
            side_effect=OrderError("bitget", "minimum amount not met")
        )

        ex.notify_trade_failure = AsyncMock()
        ex.resolve_pending_trade = AsyncMock()

        with patch("src.bot.components.trade_executor.get_session", return_value=_session_ctx()):
            await ex.execute(_make_signal(), mock_client, demo_mode=True)

        ex.notify_trade_failure.assert_not_awaited()
        ex.resolve_pending_trade.assert_awaited_once()

    async def test_neutral_signal_is_skipped_before_placing(self):
        ex, mocks = _make_executor()
        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(available=1000)
        mock_client.set_leverage = AsyncMock(return_value=True)

        await ex.execute(
            _make_signal(direction=SignalDirection.NEUTRAL),
            mock_client,
            demo_mode=True,
        )

        mock_client.place_market_order.assert_not_awaited()
        mocks["on_trade_opened"].assert_not_called()

    async def test_asset_budget_mode_computes_size_from_budget(self):
        ex, mocks = _make_executor(config=_make_config(leverage=2))
        mock_client = AsyncMock()
        mock_client.set_leverage = AsyncMock(return_value=True)
        mock_client.place_market_order = AsyncMock(return_value=_make_order())
        mock_client.get_fill_price = AsyncMock(return_value=50000.0)

        with patch("src.bot.components.trade_executor.get_session", return_value=_session_ctx()):
            await ex.execute(_make_signal(), mock_client, demo_mode=True, asset_budget=100.0)

        # 95% of 100 USDT margin * 2x leverage / 50000 entry = 0.0038
        call = mock_client.place_market_order.await_args
        assert call.kwargs["size"] == pytest.approx(0.0038, rel=1e-3)

    async def test_tp_sl_override_from_caller_is_preserved(self):
        # Caller TP/SL always wins over config percentages — self-managed
        # strategies rely on this.
        ex, _ = _make_executor(config=_make_config(take_profit_percent=5, stop_loss_percent=5))
        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(available=1000)
        mock_client.set_leverage = AsyncMock(return_value=True)
        mock_client.place_market_order = AsyncMock(return_value=_make_order())
        mock_client.get_fill_price = AsyncMock(return_value=50000.0)

        caller_tp = 55555.0
        caller_sl = 44444.0
        with patch("src.bot.components.trade_executor.get_session", return_value=_session_ctx()):
            await ex.execute(
                _make_signal(target_price=caller_tp, stop_loss=caller_sl),
                mock_client,
                demo_mode=True,
            )

        call = mock_client.place_market_order.await_args
        assert call.kwargs["take_profit"] == caller_tp
        assert call.kwargs["stop_loss"] == caller_sl


# ---------------------------------------------------------------------------
# notify_trade_failure()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNotifyTradeFailure:
    async def test_sends_risk_alert_with_friendly_message(self):
        ex, mocks = _make_executor()
        captured = {}

        async def capture(fn, **kwargs):
            captured["fn"] = fn
            captured["kwargs"] = kwargs

        mocks["notification_sender"].side_effect = capture

        with patch("src.bot.components.trade_executor.asyncio.create_task"), \
             patch.dict("sys.modules", {"src.api.websocket.manager": MagicMock()}):
            await ex.notify_trade_failure(
                _make_signal(), "LIVE", "429 Too Many Requests",
            )

        assert "fn" in captured
        notifier = MagicMock()
        notifier.send_risk_alert = AsyncMock()
        await captured["fn"](notifier)
        assert notifier.send_risk_alert.await_args.kwargs["alert_type"] == "TRADE_FAILED"
        assert "Zu viele Anfragen" in notifier.send_risk_alert.await_args.kwargs["message"]

    async def test_fatal_error_triggers_on_fatal_callback(self):
        ex, mocks = _make_executor()
        with patch("src.bot.components.trade_executor.asyncio.create_task"), \
             patch.dict("sys.modules", {"src.api.websocket.manager": MagicMock()}):
            await ex.notify_trade_failure(
                _make_signal(), "LIVE", "Invalid API key",
            )

        mocks["on_fatal_error"].assert_called_once()
        assert "API-Key" in mocks["on_fatal_error"].call_args[0][0]

    async def test_non_fatal_error_does_not_pause_bot(self):
        ex, mocks = _make_executor()
        with patch("src.bot.components.trade_executor.asyncio.create_task"), \
             patch.dict("sys.modules", {"src.api.websocket.manager": MagicMock()}):
            await ex.notify_trade_failure(
                _make_signal(), "LIVE", "Connection timeout",
            )

        mocks["on_fatal_error"].assert_not_called()


# ---------------------------------------------------------------------------
# Self-managed strategy wrappers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWrappers:
    async def test_execute_wrapper_returns_early_without_client(self):
        ex, _ = _make_executor(client=None)
        await ex.execute_wrapper(
            symbol="BTCUSDT",
            side="long",
            notional_usdt=100.0,
            leverage=2,
            reason="copy",
            bot_config_id=7,
        )
        # No exception, no-op

    async def test_execute_wrapper_returns_early_on_bad_ticker(self):
        client = AsyncMock()
        client.get_ticker = AsyncMock(side_effect=RuntimeError("no ticker"))
        ex, _ = _make_executor(client=client)

        # Should swallow the ticker error and return cleanly
        await ex.execute_wrapper(
            symbol="BTCUSDT",
            side="long",
            notional_usdt=100.0,
            leverage=2,
            reason="copy",
            bot_config_id=7,
        )

    async def test_close_by_strategy_dispatches_to_close_trade(self):
        close_trade = AsyncMock()
        client = AsyncMock()
        client.get_ticker = AsyncMock(return_value=MagicMock(last_price=100.5))
        ex, _ = _make_executor(close_trade=close_trade, client=client)

        trade = MagicMock()
        trade.symbol = "BTCUSDT"
        trade.entry_price = 100.0

        await ex.close_by_strategy(trade, reason="stop")

        close_trade.assert_awaited_once()
        kwargs = close_trade.await_args.kwargs
        assert kwargs["exit_price"] == pytest.approx(100.5)
        assert kwargs["exit_reason"] == "stop"
        assert kwargs["strategy_reason"] == "stop"
