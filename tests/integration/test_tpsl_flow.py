"""
Integration tests for the full TP/SL flow: trade open → monitor → close.

Unlike unit tests (mocked logic snippets), these tests exercise the actual
BotWorker._execute_trade() and _check_position() methods end-to-end with
realistic exchange mocks that track state across calls.

Scenarios:
1. LONG + per-asset TP/SL  → exchange receives correct prices → DB has TP/SL → monitor skips should_exit()
2. SHORT + per-asset TP/SL → inverted prices → monitor skips should_exit()
3. LONG + bot-level TP/SL  → fallback works → exchange receives prices
4. No TP/SL configured     → exchange gets None → monitor calls should_exit()
5. tpsl_failed              → TP/SL reset to None → DB records None → monitor calls should_exit()
6. Exchange closes at TP    → position gone → _handle_closed_position → exit_reason=TAKE_PROFIT
7. Exchange closes at SL    → position gone → _handle_closed_position → exit_reason=STOP_LOSS
8. Only TP set (no SL)     → partial TP/SL → monitor still skips should_exit()
"""

import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.bot.bot_worker import BotWorker
from src.strategy.base import SignalDirection, TradeSignal


# ---------------------------------------------------------------------------
# Realistic exchange mock — tracks orders, positions, TP/SL state
# ---------------------------------------------------------------------------

@dataclass
class MockPosition:
    symbol: str
    side: str
    size: float
    entry_price: float
    unrealized_pnl: float = 0.0


@dataclass
class MockTicker:
    last_price: float
    symbol: str = "BTCUSDT"


@dataclass
class MockOrder:
    order_id: str
    price: float
    side: str
    status: str = "filled"
    tpsl_failed: bool = False


@dataclass
class MockBalance:
    available: float = 10000.0
    total: float = 10000.0
    unrealized_pnl: float = 0.0


class FakeExchangeClient:
    """Stateful exchange mock that remembers placed orders and positions."""

    def __init__(self, *, current_price: float = 68200.0, tpsl_fails: bool = False):
        self.current_price = current_price
        self.tpsl_fails = tpsl_fails

        # State
        self.open_positions: dict[str, MockPosition] = {}
        self.placed_orders: list[dict] = []
        self.leverage_calls: list[tuple] = []
        self.tp_on_exchange: dict[str, Optional[float]] = {}
        self.sl_on_exchange: dict[str, Optional[float]] = {}

    async def get_account_balance(self):
        return MockBalance()

    async def set_leverage(self, symbol, leverage, margin_mode="cross"):
        self.leverage_calls.append((symbol, leverage, margin_mode))
        return True

    async def place_market_order(self, symbol, side, size, leverage,
                                  take_profit=None, stop_loss=None,
                                  margin_mode="cross"):
        order_id = f"ord_{len(self.placed_orders)+1:03d}"

        order_record = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "leverage": leverage,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "margin_mode": margin_mode,
        }
        self.placed_orders.append(order_record)

        # Store position
        self.open_positions[symbol] = MockPosition(
            symbol=symbol,
            side=side,
            size=size,
            entry_price=self.current_price,
        )

        failed = self.tpsl_fails and (take_profit is not None or stop_loss is not None)

        if not failed:
            self.tp_on_exchange[symbol] = take_profit
            self.sl_on_exchange[symbol] = stop_loss
        else:
            self.tp_on_exchange[symbol] = None
            self.sl_on_exchange[symbol] = None

        return MockOrder(
            order_id=order_id,
            price=self.current_price,
            side=side,
            tpsl_failed=failed,
        )

    async def get_fill_price(self, symbol, order_id):
        return self.current_price

    async def get_position(self, symbol):
        return self.open_positions.get(symbol)

    async def get_ticker(self, symbol):
        return MockTicker(last_price=self.current_price, symbol=symbol)

    async def close_position(self, symbol, side, margin_mode="cross"):
        self.open_positions.pop(symbol, None)

    async def get_trade_total_fees(self, symbol, entry_order_id, close_order_id=None):
        return 1.50

    async def get_funding_fees(self, symbol, start_time_ms, end_time_ms):
        return 0.05

    def remove_position(self, symbol):
        """Simulate exchange closing position via TP/SL trigger."""
        self.open_positions.pop(symbol, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides):
    config = MagicMock()
    config.id = overrides.get("id", 1)
    config.user_id = overrides.get("user_id", 1)
    config.name = overrides.get("name", "Integration Bot")
    config.description = ""
    config.strategy_type = overrides.get("strategy_type", "edge_indicator")
    config.exchange_type = overrides.get("exchange_type", "bitget")
    config.mode = overrides.get("mode", "demo")
    config.trading_pairs = json.dumps(["BTCUSDT"])
    config.leverage = overrides.get("leverage", 10)
    config.position_size_percent = 7.5
    config.max_trades_per_day = 5
    config.take_profit_percent = overrides.get("take_profit_percent", None)
    config.stop_loss_percent = overrides.get("stop_loss_percent", None)
    config.daily_loss_limit_percent = 5.0
    config.schedule_type = "interval"
    config.schedule_config = None
    config.strategy_params = None
    config.discord_webhook_url = None
    config.telegram_bot_token = None
    config.telegram_chat_id = None
    config.rotation_enabled = False
    config.rotation_interval_minutes = None
    config.rotation_start_time = None
    config.is_enabled = True
    config.per_asset_config = overrides.get("per_asset_config", None)
    config.margin_mode = overrides.get("margin_mode", "cross")
    return config


def _make_signal(direction=SignalDirection.LONG, symbol="BTCUSDT",
                 entry_price=68200.0):
    return TradeSignal(
        direction=direction,
        confidence=80,
        symbol=symbol,
        entry_price=entry_price,
        target_price=None,
        stop_loss=None,
        reason="Integration test signal",
        metrics_snapshot={
            "momentum": 0.45,
            "adx": 28.0,
            "rsi": 55.0,
            "regime": "bull",
        },
        timestamp=datetime.now(timezone.utc),
    )


def _make_db_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    return session


def _mock_session_ctx(mock_session):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_trade_record_from_signal(signal, fill_price, leverage, tp, sl, **extra):
    """Build a mock TradeRecord as it would be saved after _execute_trade."""
    trade = MagicMock()
    trade.id = extra.get("id", 1)
    trade.bot_config_id = extra.get("bot_config_id", 1)
    trade.user_id = 1
    trade.symbol = signal.symbol
    trade.side = signal.direction.value
    trade.size = extra.get("size", 0.01)
    trade.entry_price = fill_price
    trade.take_profit = tp
    trade.stop_loss = sl
    trade.highest_price = fill_price
    trade.leverage = leverage
    trade.confidence = signal.confidence
    trade.reason = signal.reason
    trade.order_id = extra.get("order_id", "ord_001")
    trade.close_order_id = None
    trade.status = "open"
    trade.fees = 0
    trade.funding_paid = 0
    trade.builder_fee = 0
    trade.entry_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    trade.exit_time = None
    trade.exit_reason = None
    trade.demo_mode = True
    trade.exchange = "bitget"
    trade.metrics_snapshot = json.dumps(signal.metrics_snapshot)
    trade.native_trailing_stop = extra.get("native_trailing_stop", False)
    trade.trailing_atr_override = extra.get("trailing_atr_override", None)
    trade.trailing_status = extra.get("trailing_status", None)
    return trade


# ---------------------------------------------------------------------------
# Captured DB writes: intercept TradeRecord() to verify what gets persisted
# ---------------------------------------------------------------------------

class TradeRecordCapture:
    """Captures TradeRecord constructor calls to inspect persisted values."""

    def __init__(self):
        self.records: list[dict] = []

    def __call__(self, **kwargs):
        self.records.append(kwargs)
        return MagicMock(**kwargs)


# ===========================================================================
# Integration tests
# ===========================================================================

@pytest.mark.asyncio
class TestTPSLIntegrationFlow:

    # -----------------------------------------------------------------------
    # 1. LONG + per-asset TP/SL → full flow
    # -----------------------------------------------------------------------

    async def test_long_per_asset_tpsl_full_flow(self):
        """LONG with per-asset TP=3%, SL=1.5%:
        - exchange receives correct absolute prices
        - DB records TP/SL on the trade
        - position monitor skips should_exit()
        """
        exchange = FakeExchangeClient(current_price=68200.0)
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config(
            per_asset_config=json.dumps({
                "BTCUSDT": {"take_profit_percent": 3.0, "stop_loss_percent": 1.5}
            }),
        )
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, None)
        worker.trades_today = 0
        worker._send_notification = AsyncMock()

        signal = _make_signal(direction=SignalDirection.LONG, entry_price=68200.0)
        db_capture = TradeRecordCapture()
        mock_session = _make_db_session()

        with patch("src.bot.components.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.components.trade_executor.TradeRecord", db_capture):
            await worker._execute_trade(signal, exchange, demo_mode=True, asset_budget=500.0)

        # 1. Exchange received correct TP/SL prices
        assert len(exchange.placed_orders) == 1
        order = exchange.placed_orders[0]

        expected_tp = 68200.0 * 1.03   # 70246.0
        expected_sl = 68200.0 * 0.985  # 67177.0

        assert order["take_profit"] == pytest.approx(expected_tp, rel=1e-6)
        assert order["stop_loss"] == pytest.approx(expected_sl, rel=1e-6)

        # 2. DB record has TP/SL
        assert len(db_capture.records) == 1
        db_trade = db_capture.records[0]
        assert db_trade["take_profit"] == pytest.approx(expected_tp, rel=1e-6)
        assert db_trade["stop_loss"] == pytest.approx(expected_sl, rel=1e-6)

        # 3. Position monitor skips should_exit()
        trade_record = _make_trade_record_from_signal(
            signal, 68200.0, 10, tp=expected_tp, sl=expected_sl,
        )
        worker._strategy = MagicMock()
        worker._strategy.should_exit = AsyncMock(return_value=(True, "fake exit"))
        worker._strategy._p = {"trailing_stop_enabled": False}
        worker._get_client = MagicMock(return_value=exchange)

        monitor_session = AsyncMock()
        monitor_session.commit = AsyncMock()
        await worker._check_position(trade_record, monitor_session)

        # should_exit must NOT have been called
        worker._strategy.should_exit.assert_not_called()

    # -----------------------------------------------------------------------
    # 2. SHORT + per-asset TP/SL → inverted prices
    # -----------------------------------------------------------------------

    async def test_short_per_asset_tpsl_inverted(self):
        """SHORT with TP=2%, SL=1%:
        - TP = entry * (1 - 0.02) = below entry
        - SL = entry * (1 + 0.01) = above entry
        """
        exchange = FakeExchangeClient(current_price=68200.0)
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config(
            per_asset_config=json.dumps({
                "BTCUSDT": {"take_profit_percent": 2.0, "stop_loss_percent": 1.0}
            }),
        )
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, None)
        worker.trades_today = 0
        worker._send_notification = AsyncMock()

        signal = _make_signal(direction=SignalDirection.SHORT, entry_price=68200.0)
        mock_session = _make_db_session()

        with patch("src.bot.components.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, exchange, demo_mode=True, asset_budget=500.0)

        order = exchange.placed_orders[0]
        expected_tp = 68200.0 * 0.98   # 66836.0
        expected_sl = 68200.0 * 1.01   # 68882.0

        assert order["take_profit"] == pytest.approx(expected_tp, rel=1e-6)
        assert order["stop_loss"] == pytest.approx(expected_sl, rel=1e-6)
        assert order["side"] == "short"

    # -----------------------------------------------------------------------
    # 3. LONG + bot-level TP/SL fallback
    # -----------------------------------------------------------------------

    async def test_long_bot_level_tpsl_fallback(self):
        """No per-asset TP/SL → falls back to bot-level take_profit_percent/stop_loss_percent."""
        exchange = FakeExchangeClient(current_price=68200.0)
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config(
            take_profit_percent=4.0,
            stop_loss_percent=2.0,
            per_asset_config=None,
        )
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, None)
        worker.trades_today = 0
        worker._send_notification = AsyncMock()

        signal = _make_signal(direction=SignalDirection.LONG, entry_price=68200.0)
        mock_session = _make_db_session()

        with patch("src.bot.components.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, exchange, demo_mode=True, asset_budget=500.0)

        order = exchange.placed_orders[0]
        assert order["take_profit"] == pytest.approx(68200.0 * 1.04, rel=1e-6)  # 70928.0
        assert order["stop_loss"] == pytest.approx(68200.0 * 0.98, rel=1e-6)    # 66836.0

    # -----------------------------------------------------------------------
    # 4. No TP/SL → exchange gets None → monitor calls should_exit()
    # -----------------------------------------------------------------------

    async def test_no_tpsl_exchange_gets_none_monitor_calls_should_exit(self):
        """Without any TP/SL config, exchange gets None and should_exit() runs."""
        exchange = FakeExchangeClient(current_price=68200.0)
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config(
            take_profit_percent=None,
            stop_loss_percent=None,
            per_asset_config=None,
        )
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, None)
        worker.trades_today = 0
        worker._send_notification = AsyncMock()

        signal = _make_signal(direction=SignalDirection.LONG, entry_price=68200.0)
        db_capture = TradeRecordCapture()
        mock_session = _make_db_session()

        with patch("src.bot.components.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.components.trade_executor.TradeRecord", db_capture):
            await worker._execute_trade(signal, exchange, demo_mode=True, asset_budget=500.0)

        # Exchange received None for both
        order = exchange.placed_orders[0]
        assert order["take_profit"] is None
        assert order["stop_loss"] is None

        # DB also has None
        assert db_capture.records[0]["take_profit"] is None
        assert db_capture.records[0]["stop_loss"] is None

        # Monitor calls should_exit()
        trade_record = _make_trade_record_from_signal(
            signal, 68200.0, 10, tp=None, sl=None,
        )
        worker._strategy = MagicMock()
        worker._strategy.should_exit = AsyncMock(return_value=(False, "hold"))
        worker._get_client = MagicMock(return_value=exchange)

        monitor_session = AsyncMock()
        monitor_session.commit = AsyncMock()
        await worker._check_position(trade_record, monitor_session)

        worker._strategy.should_exit.assert_called_once()

    # -----------------------------------------------------------------------
    # 5. tpsl_failed → safety fallback
    # -----------------------------------------------------------------------

    async def test_tpsl_failed_resets_to_none_and_monitor_calls_should_exit(self):
        """When exchange can't set TP/SL, they reset to None → should_exit() active."""
        exchange = FakeExchangeClient(current_price=68200.0, tpsl_fails=True)
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config(
            per_asset_config=json.dumps({
                "BTCUSDT": {"take_profit_percent": 3.0, "stop_loss_percent": 1.5}
            }),
        )
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, None)
        worker.trades_today = 0
        worker._send_notification = AsyncMock()

        signal = _make_signal(direction=SignalDirection.LONG, entry_price=68200.0)
        db_capture = TradeRecordCapture()
        mock_session = _make_db_session()

        with patch("src.bot.components.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.components.trade_executor.TradeRecord", db_capture):
            await worker._execute_trade(signal, exchange, demo_mode=True, asset_budget=500.0)

        # Exchange got TP/SL in the order, but tpsl_failed → reset
        order = exchange.placed_orders[0]
        assert order["take_profit"] is not None  # was sent to place_market_order
        assert order["stop_loss"] is not None

        # But DB records None because of tpsl_failed safety
        assert db_capture.records[0]["take_profit"] is None
        assert db_capture.records[0]["stop_loss"] is None

        # Monitor should call should_exit() as fallback
        trade_record = _make_trade_record_from_signal(
            signal, 68200.0, 10, tp=None, sl=None,
        )
        worker._strategy = MagicMock()
        worker._strategy.should_exit = AsyncMock(return_value=(False, "hold"))
        worker._get_client = MagicMock(return_value=exchange)

        monitor_session = AsyncMock()
        monitor_session.commit = AsyncMock()
        await worker._check_position(trade_record, monitor_session)

        worker._strategy.should_exit.assert_called_once()

    # -----------------------------------------------------------------------
    # 6. Exchange closes at TP → TAKE_PROFIT exit
    # -----------------------------------------------------------------------

    async def test_exchange_tp_hit_detected_as_take_profit(self):
        """Position closed by exchange at TP → _handle_closed_position → TAKE_PROFIT."""
        tp_price = 70246.0   # 68200 * 1.03
        sl_price = 67177.0   # 68200 * 0.985

        # Exchange has no position (TP was hit, position closed)
        exchange = FakeExchangeClient(current_price=tp_price)

        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config()
        worker._risk_manager = MagicMock()
        worker._send_notification = AsyncMock()
        worker._close_and_record_trade = AsyncMock()
        worker._get_client = MagicMock(return_value=exchange)

        trade_record = _make_trade_record_from_signal(
            _make_signal(), 68200.0, 10, tp=tp_price, sl=sl_price,
        )

        session = AsyncMock()

        # Position gone → _handle_closed_position
        await worker._handle_closed_position(trade_record, exchange, session)

        worker._close_and_record_trade.assert_called_once()
        call_args = worker._close_and_record_trade.call_args
        exit_price = call_args[0][1]
        exit_reason = call_args[0][2]

        assert exit_price == pytest.approx(tp_price, rel=1e-6)
        # #193 taxonomy: TAKE_PROFIT → TAKE_PROFIT_NATIVE (exchange-side TP trigger).
        assert exit_reason == "TAKE_PROFIT_NATIVE"

    # -----------------------------------------------------------------------
    # 7. Exchange closes at SL → STOP_LOSS_NATIVE exit
    # -----------------------------------------------------------------------

    async def test_exchange_sl_hit_detected_as_stop_loss(self):
        """Position closed by exchange at SL → _handle_closed_position → STOP_LOSS_NATIVE."""
        tp_price = 70246.0
        sl_price = 67177.0

        exchange = FakeExchangeClient(current_price=sl_price)

        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config()
        worker._risk_manager = MagicMock()
        worker._send_notification = AsyncMock()
        worker._close_and_record_trade = AsyncMock()
        worker._get_client = MagicMock(return_value=exchange)

        trade_record = _make_trade_record_from_signal(
            _make_signal(), 68200.0, 10, tp=tp_price, sl=sl_price,
        )

        session = AsyncMock()
        await worker._handle_closed_position(trade_record, exchange, session)

        call_args = worker._close_and_record_trade.call_args
        exit_reason = call_args[0][2]
        # #193 taxonomy: STOP_LOSS → STOP_LOSS_NATIVE (exchange-side SL trigger).
        assert exit_reason == "STOP_LOSS_NATIVE"

    # -----------------------------------------------------------------------
    # 8. Only TP set → monitor still skips should_exit()
    # -----------------------------------------------------------------------

    async def test_only_tp_set_monitor_skips_should_exit(self):
        """With only TP (no SL), should_exit() is still skipped — user accepts risk."""
        exchange = FakeExchangeClient(current_price=68200.0)
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config(
            per_asset_config=json.dumps({
                "BTCUSDT": {"take_profit_percent": 3.0}
            }),
        )
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, None)
        worker.trades_today = 0
        worker._send_notification = AsyncMock()

        signal = _make_signal(direction=SignalDirection.LONG, entry_price=68200.0)
        db_capture = TradeRecordCapture()
        mock_session = _make_db_session()

        with patch("src.bot.components.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.components.trade_executor.TradeRecord", db_capture):
            await worker._execute_trade(signal, exchange, demo_mode=True, asset_budget=500.0)

        # TP set, SL is None
        order = exchange.placed_orders[0]
        assert order["take_profit"] == pytest.approx(68200.0 * 1.03, rel=1e-6)
        assert order["stop_loss"] is None

        db_trade = db_capture.records[0]
        assert db_trade["take_profit"] == pytest.approx(68200.0 * 1.03, rel=1e-6)
        assert db_trade["stop_loss"] is None

        # Monitor: TP is set → skip should_exit()
        trade_record = _make_trade_record_from_signal(
            signal, 68200.0, 10,
            tp=db_trade["take_profit"], sl=None,
        )
        worker._strategy = MagicMock()
        worker._strategy.should_exit = AsyncMock(return_value=(True, "would exit"))
        worker._strategy._p = {"trailing_stop_enabled": False}
        worker._get_client = MagicMock(return_value=exchange)

        monitor_session = AsyncMock()
        monitor_session.commit = AsyncMock()
        await worker._check_position(trade_record, monitor_session)

        worker._strategy.should_exit.assert_not_called()


@pytest.mark.asyncio
class TestTPSLExampleTrades:
    """Concrete example trades with real BTC prices to verify TP/SL math."""

    async def test_example_long_btc_68200_tp3_sl1_5(self):
        """LONG BTC @ $68,200 with TP=3%, SL=1.5%:
        - TP = $68,200 * 1.03 = $70,246.00
        - SL = $68,200 * 0.985 = $67,177.00
        - Risk:Reward = 1:2 (risking $1,023 for $2,046)
        """
        exchange = FakeExchangeClient(current_price=68200.0)
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config(
            per_asset_config=json.dumps({
                "BTCUSDT": {"take_profit_percent": 3.0, "stop_loss_percent": 1.5}
            }),
        )
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, None)
        worker.trades_today = 0
        worker._send_notification = AsyncMock()

        signal = _make_signal(direction=SignalDirection.LONG, entry_price=68200.0)
        mock_session = _make_db_session()

        with patch("src.bot.components.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, exchange, demo_mode=True, asset_budget=1000.0)

        order = exchange.placed_orders[0]
        tp = order["take_profit"]
        sl = order["stop_loss"]
        entry = 68200.0

        # Verify exact prices
        assert tp == pytest.approx(70246.0, rel=1e-6)
        assert sl == pytest.approx(67177.0, rel=1e-6)

        # Verify risk:reward ratio ≈ 1:2
        reward = tp - entry                     # 2046.0
        risk = entry - sl                       # 1023.0
        rr_ratio = reward / risk
        assert rr_ratio == pytest.approx(2.0, rel=1e-6)

    async def test_example_short_btc_68200_tp2_sl1(self):
        """SHORT BTC @ $68,200 with TP=2%, SL=1%:
        - TP = $68,200 * 0.98 = $66,836.00 (below entry)
        - SL = $68,200 * 1.01 = $68,882.00 (above entry)
        - Risk:Reward = 1:2
        """
        exchange = FakeExchangeClient(current_price=68200.0)
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config(
            per_asset_config=json.dumps({
                "BTCUSDT": {"take_profit_percent": 2.0, "stop_loss_percent": 1.0}
            }),
        )
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, None)
        worker.trades_today = 0
        worker._send_notification = AsyncMock()

        signal = _make_signal(direction=SignalDirection.SHORT, entry_price=68200.0)
        mock_session = _make_db_session()

        with patch("src.bot.components.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, exchange, demo_mode=True, asset_budget=1000.0)

        order = exchange.placed_orders[0]
        tp = order["take_profit"]
        sl = order["stop_loss"]
        entry = 68200.0

        assert tp == pytest.approx(66836.0, rel=1e-6)
        assert sl == pytest.approx(68882.0, rel=1e-6)

        # SHORT: reward = entry - tp, risk = sl - entry
        reward = entry - tp                     # 1364.0
        risk = sl - entry                       # 682.0
        rr_ratio = reward / risk
        assert rr_ratio == pytest.approx(2.0, rel=1e-6)

    async def test_example_long_btc_budget_sizing_with_leverage(self):
        """LONG BTC @ $68,200 with $1000 budget, 10x leverage:
        - Usable margin = $1000 * 0.95 = $950
        - Position notional = $950 * 10 = $9500
        - Position size = $9500 / $68,200 ≈ 0.139296 BTC
        """
        exchange = FakeExchangeClient(current_price=68200.0)
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config(
            leverage=10,
            per_asset_config=json.dumps({
                "BTCUSDT": {"take_profit_percent": 3.0, "stop_loss_percent": 1.5}
            }),
        )
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, None)
        worker.trades_today = 0
        worker._send_notification = AsyncMock()

        signal = _make_signal(direction=SignalDirection.LONG, entry_price=68200.0)
        mock_session = _make_db_session()

        with patch("src.bot.components.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, exchange, demo_mode=True, asset_budget=1000.0)

        order = exchange.placed_orders[0]
        expected_size = (1000.0 * 0.95 * 10) / 68200.0
        assert order["size"] == pytest.approx(expected_size, rel=1e-4)
        assert order["leverage"] == 10

    async def test_example_full_lifecycle_open_monitor_close(self):
        """Full lifecycle: open trade → monitor skips exit → TP hit → closed as TAKE_PROFIT.

        Step 1: Open LONG @ $68,200 with TP=3%
        Step 2: Price at $68,500 — monitor sees position, skips should_exit()
        Step 3: Price hits $70,246 — exchange closes position
        Step 4: Monitor sees position gone → _handle_closed_position → TAKE_PROFIT
        """
        # Step 1: Open trade
        exchange = FakeExchangeClient(current_price=68200.0)
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_config(
            per_asset_config=json.dumps({
                "BTCUSDT": {"take_profit_percent": 3.0, "stop_loss_percent": 1.5}
            }),
        )
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, None)
        worker.trades_today = 0
        worker._send_notification = AsyncMock()
        worker._strategy = MagicMock()
        worker._strategy.should_exit = AsyncMock(return_value=(True, "would exit"))
        worker._strategy._p = {"trailing_stop_enabled": False}

        signal = _make_signal(direction=SignalDirection.LONG, entry_price=68200.0)
        db_capture = TradeRecordCapture()
        mock_session = _make_db_session()

        with patch("src.bot.components.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.components.trade_executor.TradeRecord", db_capture):
            await worker._execute_trade(signal, exchange, demo_mode=True, asset_budget=1000.0)

        tp_price = db_capture.records[0]["take_profit"]
        sl_price = db_capture.records[0]["stop_loss"]
        assert tp_price == pytest.approx(70246.0, rel=1e-6)

        # Step 2: Price moves to $68,500 — monitor checks, position still open
        exchange.current_price = 68500.0
        trade_record = _make_trade_record_from_signal(
            signal, 68200.0, 10, tp=tp_price, sl=sl_price,
        )
        worker._get_client = MagicMock(return_value=exchange)

        monitor_session = AsyncMock()
        monitor_session.commit = AsyncMock()
        await worker._check_position(trade_record, monitor_session)

        # should_exit NOT called (TP/SL on exchange)
        worker._strategy.should_exit.assert_not_called()

        # Step 3: Price hits TP — exchange removes position
        exchange.current_price = 70246.0
        exchange.remove_position("BTCUSDT")

        # Step 4: Monitor sees position gone → handle closed
        worker._close_and_record_trade = AsyncMock()
        await worker._check_position(trade_record, monitor_session)

        # _handle_closed_position was triggered (position is None)
        worker._close_and_record_trade.assert_called_once()
        call_args = worker._close_and_record_trade.call_args
        exit_price = call_args[0][1]
        exit_reason = call_args[0][2]

        assert exit_price == pytest.approx(70246.0, rel=1e-6)
        # #193 taxonomy: legacy TAKE_PROFIT → TAKE_PROFIT_NATIVE.
        assert exit_reason == "TAKE_PROFIT_NATIVE"
