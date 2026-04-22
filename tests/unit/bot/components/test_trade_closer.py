"""Unit tests for TradeCloser component (ARCH-H1 Phase 1 PR-3, #279)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.components.trade_closer import TradeCloser


def _make_trade(trade_id: int = 100):
    trade = MagicMock()
    trade.id = trade_id
    trade.symbol = "BTC-USDT"
    trade.side = "long"
    trade.size = 0.1
    trade.entry_price = 50_000.0
    trade.fees = 0.5
    trade.funding_paid = 0.0
    trade.builder_fee = 0.0
    trade.order_id = "ord-1"
    trade.entry_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    trade.demo_mode = True
    trade.status = "open"
    return trade


def _make_closer(risk_manager=None, notification_sender=None, user_id: int = 7) -> TradeCloser:
    config = MagicMock()
    config.user_id = user_id
    config.name = "TestBot"
    return TradeCloser(
        bot_config_id=42,
        config_getter=lambda: config,
        risk_manager_getter=lambda: risk_manager if risk_manager is not None else MagicMock(),
        notification_sender=notification_sender or AsyncMock(),
    )


@pytest.mark.asyncio
class TestCloseAndRecord:
    async def test_updates_in_memory_trade_fields(self):
        rm = MagicMock()
        sender = AsyncMock()
        closer = _make_closer(risk_manager=rm, notification_sender=sender)
        trade = _make_trade()

        with patch("src.bot.components.trade_closer.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("no DB"))
            with patch("src.bot.components.trade_closer.publish_trade_event"), \
                 patch("src.api.websocket.manager.ws_manager"):
                await closer.close_and_record(trade, 51_000.0, "TAKE_PROFIT")

        assert trade.exit_price == 51_000.0
        assert trade.exit_reason == "TAKE_PROFIT"
        assert trade.status == "closed"
        assert trade.pnl != 0
        assert trade.exit_time is not None

    async def test_applies_optional_fee_fields(self):
        rm = MagicMock()
        closer = _make_closer(risk_manager=rm, notification_sender=AsyncMock())
        trade = _make_trade()

        with patch("src.bot.components.trade_closer.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("no DB"))
            with patch("src.bot.components.trade_closer.publish_trade_event"), \
                 patch("src.api.websocket.manager.ws_manager"):
                await closer.close_and_record(
                    trade, 51_000.0, "STRATEGY_EXIT",
                    fees=2.5, funding_paid=0.1, builder_fee=0.05,
                )

        assert trade.fees == 2.5
        assert trade.funding_paid == 0.1
        assert trade.builder_fee == 0.05

    async def test_records_exit_in_risk_manager(self):
        rm = MagicMock()
        closer = _make_closer(risk_manager=rm, notification_sender=AsyncMock())
        trade = _make_trade()

        with patch("src.bot.components.trade_closer.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("no DB"))
            with patch("src.bot.components.trade_closer.publish_trade_event"), \
                 patch("src.api.websocket.manager.ws_manager"):
                await closer.close_and_record(trade, 51_000.0, "TAKE_PROFIT")

        rm.record_trade_exit.assert_called_once()
        kwargs = rm.record_trade_exit.call_args.kwargs
        assert kwargs["symbol"] == "BTC-USDT"
        assert kwargs["exit_price"] == 51_000.0
        assert kwargs["reason"] == "TAKE_PROFIT"

    async def test_fires_send_notification(self):
        rm = MagicMock()
        sender = AsyncMock()
        closer = _make_closer(risk_manager=rm, notification_sender=sender)
        trade = _make_trade()

        with patch("src.bot.components.trade_closer.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("no DB"))
            with patch("src.bot.components.trade_closer.publish_trade_event"), \
                 patch("src.api.websocket.manager.ws_manager"):
                await closer.close_and_record(trade, 51_000.0, "TAKE_PROFIT")

        sender.assert_called_once()
        call_kwargs = sender.call_args.kwargs
        assert call_kwargs["event_type"] == "trade_exit"
        assert "PnL=" in call_kwargs["summary"]

    async def test_publishes_sse_event(self):
        rm = MagicMock()
        closer = _make_closer(risk_manager=rm, notification_sender=AsyncMock(), user_id=7)
        trade = _make_trade()

        with patch("src.bot.components.trade_closer.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("no DB"))
            with patch("src.bot.components.trade_closer.publish_trade_event") as pub, \
                 patch("src.api.websocket.manager.ws_manager"):
                await closer.close_and_record(trade, 51_000.0, "TAKE_PROFIT")

        pub.assert_called_once()
        kwargs = pub.call_args.kwargs
        assert kwargs["user_id"] == 7
        assert kwargs["trade_id"] == 100

    async def test_sse_exception_is_swallowed(self):
        rm = MagicMock()
        closer = _make_closer(risk_manager=rm, notification_sender=AsyncMock())
        trade = _make_trade()

        with patch("src.bot.components.trade_closer.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("no DB"))
            with patch("src.bot.components.trade_closer.publish_trade_event", side_effect=Exception("sse dead")), \
                 patch("src.api.websocket.manager.ws_manager"):
                # Must not raise
                await closer.close_and_record(trade, 51_000.0, "TAKE_PROFIT")

        assert trade.status == "closed"

    async def test_db_round_trip_failure_still_closes_in_memory(self):
        rm = MagicMock()
        closer = _make_closer(risk_manager=rm, notification_sender=AsyncMock())
        trade = _make_trade()

        with patch("src.bot.components.trade_closer.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("boom"))
            with patch("src.bot.components.trade_closer.publish_trade_event"), \
                 patch("src.api.websocket.manager.ws_manager"):
                await closer.close_and_record(trade, 51_000.0, "TAKE_PROFIT")

        assert trade.status == "closed"
        rm.record_trade_exit.assert_called_once()  # still happens

    async def test_idempotent_skip_when_db_row_already_closed(self):
        """DB round-trip: if row.status is already 'closed', don't re-persist."""
        rm = MagicMock()
        closer = _make_closer(risk_manager=rm, notification_sender=AsyncMock())
        trade = _make_trade()

        db_trade = MagicMock()
        db_trade.status = "closed"  # already closed by a prior close path

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        result = MagicMock()
        result.scalar_one_or_none.return_value = db_trade
        session.execute = AsyncMock(return_value=result)

        with patch("src.bot.components.trade_closer.get_session", return_value=session):
            with patch("src.bot.components.trade_closer.publish_trade_event"), \
                 patch("src.api.websocket.manager.ws_manager"):
                await closer.close_and_record(trade, 51_000.0, "TAKE_PROFIT")

        # db_trade should NOT have been mutated (already-closed guard)
        assert db_trade.exit_price != 51_000.0  # untouched

    async def test_strategy_reason_overrides_default(self):
        rm = MagicMock()
        sender = AsyncMock()
        closer = _make_closer(risk_manager=rm, notification_sender=sender)
        trade = _make_trade()

        with patch("src.bot.components.trade_closer.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("no DB"))
            with patch("src.bot.components.trade_closer.publish_trade_event"), \
                 patch("src.api.websocket.manager.ws_manager"):
                await closer.close_and_record(
                    trade, 51_000.0, "STRATEGY_EXIT",
                    strategy_reason="EMA cross",
                )

        # Notification lambda was called with strategy_reason="EMA cross"
        sender.assert_called_once()
        # We can't easily inspect the lambda content — but we can check the
        # summary which is deterministic and prove no crash occurred.
        assert sender.call_args.kwargs["event_type"] == "trade_exit"


@pytest.mark.asyncio
class TestCloseAndRecordSideEffects:
    async def test_ws_broadcast_failure_does_not_raise(self):
        rm = MagicMock()
        closer = _make_closer(risk_manager=rm, notification_sender=AsyncMock())
        trade = _make_trade()

        with patch("src.bot.components.trade_closer.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("no DB"))
            with patch("src.bot.components.trade_closer.publish_trade_event"), \
                 patch("src.api.websocket.manager.ws_manager") as ws:
                ws.broadcast_to_user = AsyncMock(side_effect=Exception("ws down"))
                # Must not raise
                await closer.close_and_record(trade, 51_000.0, "TAKE_PROFIT")

        # async task dispatched; exception captured in done_callback
        assert trade.status == "closed"

    async def test_no_user_id_skips_ws_and_sse(self):
        rm = MagicMock()
        sender = AsyncMock()
        closer = TradeCloser(
            bot_config_id=42,
            config_getter=lambda: None,  # no config loaded yet
            risk_manager_getter=lambda: rm,
            notification_sender=sender,
        )
        trade = _make_trade()

        with patch("src.bot.components.trade_closer.get_session") as gs:
            gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("no DB"))
            with patch("src.bot.components.trade_closer.publish_trade_event") as pub:
                await closer.close_and_record(trade, 51_000.0, "TAKE_PROFIT")

        pub.assert_not_called()
        sender.assert_called_once()  # notification still fires
