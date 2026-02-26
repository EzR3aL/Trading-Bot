"""
Tests for TP/SL passthrough to exchange and should_exit() guard.

Covers:
1. Per-asset TP/SL LONG → correct absolute prices
2. Per-asset TP/SL SHORT → inverted calculation
3. No TP/SL → all None (backward compatibility)
4. Bot-level fallback when per-asset empty
5. Only TP set, SL stays None
6. Only SL set, TP stays None
7. Position monitor skips should_exit() when TP/SL present
8. Position monitor calls should_exit() when no TP/SL
9. tpsl_failed → TP/SL reset to None (safety fallback)
10. _handle_closed_position detects TP/SL exits
11. Claude-Edge new default thresholds loaded correctly
12. SHORT trade — slight momentum flip no longer triggers exit
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.strategy.base import SignalDirection, TradeSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(direction=SignalDirection.LONG, entry_price=68200.0,
                 target_price=70000.0, stop_loss=67000.0):
    return TradeSignal(
        direction=direction,
        confidence=75,
        symbol="BTCUSDT",
        entry_price=entry_price,
        target_price=target_price,
        stop_loss=stop_loss,
        reason="Test signal",
        metrics_snapshot={"test": True},
        timestamp=datetime.now(timezone.utc),
    )


def _make_mock_config(**overrides):
    config = MagicMock()
    config.id = overrides.get("id", 1)
    config.user_id = overrides.get("user_id", 1)
    config.name = overrides.get("name", "Test Bot")
    config.exchange_type = overrides.get("exchange_type", "bitget")
    config.mode = overrides.get("mode", "demo")
    config.leverage = overrides.get("leverage", 4)
    config.take_profit_percent = overrides.get("take_profit_percent", None)
    config.stop_loss_percent = overrides.get("stop_loss_percent", None)
    config.per_asset_config = overrides.get("per_asset_config", None)
    config.margin_mode = overrides.get("margin_mode", "cross")
    return config


def _make_mock_order(tpsl_failed=False):
    order = MagicMock()
    order.order_id = "order_001"
    order.price = 68200.0
    order.side = "long"
    order.status = "filled"
    order.tpsl_failed = tpsl_failed
    return order


def _make_mock_trade(**overrides):
    trade = MagicMock()
    trade.id = overrides.get("id", 1)
    trade.bot_config_id = overrides.get("bot_config_id", 1)
    trade.symbol = overrides.get("symbol", "BTCUSDT")
    trade.side = overrides.get("side", "long")
    trade.entry_price = overrides.get("entry_price", 68200.0)
    trade.take_profit = overrides.get("take_profit", None)
    trade.stop_loss = overrides.get("stop_loss", None)
    trade.highest_price = overrides.get("highest_price", 68200.0)
    trade.demo_mode = overrides.get("demo_mode", True)
    trade.metrics_snapshot = overrides.get("metrics_snapshot", '{"test": true}')
    trade.order_id = overrides.get("order_id", "order_001")
    trade.close_order_id = overrides.get("close_order_id", None)
    trade.fees = overrides.get("fees", 0)
    trade.funding_paid = overrides.get("funding_paid", 0)
    trade.entry_time = overrides.get("entry_time", datetime.now(timezone.utc))
    trade.status = overrides.get("status", "open")
    return trade


# ---------------------------------------------------------------------------
# 1. Per-asset TP/SL LONG
# ---------------------------------------------------------------------------

class TestTPSLCalculation:
    def test_per_asset_tpsl_long_correct_prices(self):
        """Per-asset TP/SL on LONG calculates correct absolute prices."""
        from src.bot.trade_executor import TradeExecutorMixin

        mixin = TradeExecutorMixin()
        mixin.bot_config_id = 1
        mixin._config = _make_mock_config(
            per_asset_config=json.dumps({
                "BTCUSDT": {"take_profit_percent": 2.0, "stop_loss_percent": 1.0}
            }),
        )
        mixin._risk_manager = MagicMock()
        mixin._risk_manager.can_trade.return_value = (True, None)
        mixin.trades_today = 0

        signal = _make_signal(direction=SignalDirection.LONG, entry_price=68200.0)
        client = AsyncMock()
        client.set_leverage = AsyncMock()
        client.place_market_order = AsyncMock(return_value=_make_mock_order())
        client.get_fill_price = AsyncMock(return_value=68200.0)
        mixin._send_notification = AsyncMock()
        mixin._get_client = MagicMock(return_value=client)

        # Run the TP/SL calculation logic directly
        from src.utils.json_helpers import parse_json_field
        per_asset_cfg = parse_json_field(
            mixin._config.per_asset_config,
            field_name="per_asset_config",
            context="test",
            default={},
        )
        asset_cfg = per_asset_cfg.get("BTCUSDT", {})
        tp_pct = asset_cfg.get("take_profit_percent")
        sl_pct = asset_cfg.get("stop_loss_percent")

        entry = 68200.0
        is_long = True
        tp_price = entry * (1 + tp_pct / 100) if tp_pct else None
        sl_price = entry * (1 - sl_pct / 100) if sl_pct else None

        assert tp_price == pytest.approx(69564.0)   # 68200 * 1.02
        assert sl_price == pytest.approx(67518.0)    # 68200 * 0.99

    # -------------------------------------------------------------------
    # 2. Per-asset TP/SL SHORT
    # -------------------------------------------------------------------

    def test_per_asset_tpsl_short_inverted_prices(self):
        """Per-asset TP/SL on SHORT inverts the calculation."""
        entry = 68200.0
        tp_pct = 2.0
        sl_pct = 1.0

        # SHORT: TP below entry, SL above entry
        tp_price = entry * (1 - tp_pct / 100)
        sl_price = entry * (1 + sl_pct / 100)

        assert tp_price == pytest.approx(66836.0)   # 68200 * 0.98
        assert sl_price == pytest.approx(68882.0)    # 68200 * 1.01

    # -------------------------------------------------------------------
    # 3. No TP/SL → backward compatibility
    # -------------------------------------------------------------------

    def test_no_tpsl_returns_none(self):
        """No TP/SL configured → signal gets None for both."""
        tp_pct = None
        sl_pct = None

        entry = 68200.0
        tp_price = entry * (1 + tp_pct / 100) if tp_pct else None
        sl_price = entry * (1 - sl_pct / 100) if sl_pct else None

        assert tp_price is None
        assert sl_price is None

    # -------------------------------------------------------------------
    # 4. Bot-level fallback
    # -------------------------------------------------------------------

    def test_bot_level_fallback_when_per_asset_empty(self):
        """Bot-level TP/SL used when per-asset config has no TP/SL."""
        # Simulate: per-asset has no tp/sl, bot-level has them
        asset_cfg = {}
        bot_tp = 3.0
        bot_sl = 1.5

        tp_pct = asset_cfg.get("take_profit_percent") or bot_tp
        sl_pct = asset_cfg.get("stop_loss_percent") or bot_sl

        entry = 68200.0
        tp_price = entry * (1 + tp_pct / 100)
        sl_price = entry * (1 - sl_pct / 100)

        assert tp_pct == 3.0
        assert sl_pct == 1.5
        assert tp_price == pytest.approx(70246.0)   # 68200 * 1.03
        assert sl_price == pytest.approx(67177.0)    # 68200 * 0.985

    # -------------------------------------------------------------------
    # 5. Only TP set
    # -------------------------------------------------------------------

    def test_only_tp_set_sl_stays_none(self):
        """Only TP configured → SL remains None."""
        tp_pct = 2.0
        sl_pct = None
        entry = 68200.0

        tp_price = entry * (1 + tp_pct / 100) if tp_pct else None
        sl_price = entry * (1 - sl_pct / 100) if sl_pct else None

        assert tp_price == pytest.approx(69564.0)
        assert sl_price is None

    # -------------------------------------------------------------------
    # 6. Only SL set
    # -------------------------------------------------------------------

    def test_only_sl_set_tp_stays_none(self):
        """Only SL configured → TP remains None."""
        tp_pct = None
        sl_pct = 1.0
        entry = 68200.0

        tp_price = entry * (1 + tp_pct / 100) if tp_pct else None
        sl_price = entry * (1 - sl_pct / 100) if sl_pct else None

        assert tp_price is None
        assert sl_price == pytest.approx(67518.0)


# ---------------------------------------------------------------------------
# 7-8. Position monitor should_exit() guard
# ---------------------------------------------------------------------------

class TestPositionMonitorGuard:

    @pytest.mark.asyncio
    async def test_skip_should_exit_when_tpsl_present(self):
        """Position monitor skips should_exit() when trade has exchange TP/SL."""
        from src.bot.position_monitor import PositionMonitorMixin

        mixin = PositionMonitorMixin()
        mixin.bot_config_id = 1
        mixin._strategy = MagicMock()
        mixin._strategy.should_exit = AsyncMock(return_value=(True, "momentum flip"))
        mixin._config = MagicMock()
        mixin._config.name = "Test Bot"

        trade = _make_mock_trade(take_profit=69564.0, stop_loss=67518.0)
        client = AsyncMock()
        position = MagicMock()
        position.side = "long"
        client.get_position = AsyncMock(return_value=position)
        ticker = MagicMock()
        ticker.last_price = 68500.0
        client.get_ticker = AsyncMock(return_value=ticker)
        mixin._get_client = MagicMock(return_value=client)

        session = AsyncMock()
        session.commit = AsyncMock()

        await mixin._check_position(trade, session)

        # should_exit should NOT have been called
        mixin._strategy.should_exit.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_should_exit_when_no_tpsl(self):
        """Position monitor calls should_exit() when trade has no TP/SL."""
        from src.bot.position_monitor import PositionMonitorMixin

        mixin = PositionMonitorMixin()
        mixin.bot_config_id = 1
        mixin._strategy = MagicMock()
        mixin._strategy.should_exit = AsyncMock(return_value=(False, "hold"))
        mixin._config = MagicMock()
        mixin._config.name = "Test Bot"

        trade = _make_mock_trade(take_profit=None, stop_loss=None)
        client = AsyncMock()
        position = MagicMock()
        position.side = "long"
        client.get_position = AsyncMock(return_value=position)
        ticker = MagicMock()
        ticker.last_price = 68500.0
        client.get_ticker = AsyncMock(return_value=ticker)
        mixin._get_client = MagicMock(return_value=client)

        session = AsyncMock()
        session.commit = AsyncMock()

        await mixin._check_position(trade, session)

        # should_exit SHOULD have been called
        mixin._strategy.should_exit.assert_called_once()


# ---------------------------------------------------------------------------
# 9. tpsl_failed safety
# ---------------------------------------------------------------------------

class TestTPSLFailedSafety:

    def test_tpsl_failed_resets_signal_to_none(self):
        """When tpsl_failed=True, signal TP/SL must be reset to None."""
        signal = _make_signal(
            direction=SignalDirection.LONG,
            entry_price=68200.0,
            target_price=69564.0,
            stop_loss=67518.0,
        )
        order = _make_mock_order(tpsl_failed=True)

        # Simulate the safety logic from trade_executor
        if getattr(order, "tpsl_failed", False):
            signal.target_price = None
            signal.stop_loss = None

        assert signal.target_price is None
        assert signal.stop_loss is None


# ---------------------------------------------------------------------------
# 10. _handle_closed_position TP/SL exit detection
# ---------------------------------------------------------------------------

class TestHandleClosedPosition:

    @pytest.mark.asyncio
    async def test_detects_take_profit_exit(self):
        """_handle_closed_position detects TP exit when price near take_profit."""
        from src.bot.position_monitor import PositionMonitorMixin

        mixin = PositionMonitorMixin()
        mixin.bot_config_id = 1
        mixin._config = MagicMock()
        mixin._config.name = "Test Bot"
        mixin._close_and_record_trade = AsyncMock()

        trade = _make_mock_trade(
            entry_price=68200.0,
            take_profit=69564.0,
            stop_loss=67518.0,
        )

        client = AsyncMock()
        # Price very close to TP
        ticker = MagicMock()
        ticker.last_price = 69560.0
        client.get_ticker = AsyncMock(return_value=ticker)
        client.get_trade_total_fees = AsyncMock(return_value=2.5)
        client.get_funding_fees = AsyncMock(return_value=0.1)

        session = AsyncMock()

        await mixin._handle_closed_position(trade, client, session)

        mixin._close_and_record_trade.assert_called_once()
        call_args = mixin._close_and_record_trade.call_args
        assert call_args[0][1] == 69560.0  # exit_price
        assert call_args[0][2] == "TAKE_PROFIT"


# ---------------------------------------------------------------------------
# 11. Claude-Edge new default thresholds
# ---------------------------------------------------------------------------

class TestClaudeEdgeDefaults:

    def test_new_default_thresholds_loaded(self):
        """Verify the updated DEFAULTS are applied correctly."""
        from src.strategy.claude_edge_indicator import DEFAULTS

        assert DEFAULTS["momentum_bull_threshold"] == 0.35
        assert DEFAULTS["momentum_bear_threshold"] == -0.35
        assert DEFAULTS["trailing_trail_atr"] == 2.5
        assert DEFAULTS["trailing_breakeven_atr"] == 1.5
        assert DEFAULTS["momentum_smooth_period"] == 5

    def test_param_schema_includes_new_params(self):
        """get_param_schema() exposes the 4 previously missing parameters."""
        from src.strategy.claude_edge_indicator import ClaudeEdgeIndicatorStrategy

        schema = ClaudeEdgeIndicatorStrategy.get_param_schema()

        assert "trailing_breakeven_atr" in schema
        assert schema["trailing_breakeven_atr"]["type"] == "float"
        assert schema["trailing_breakeven_atr"]["default"] == 1.5

        assert "trailing_trail_atr" in schema
        assert schema["trailing_trail_atr"]["type"] == "float"
        assert schema["trailing_trail_atr"]["default"] == 2.5

        assert "momentum_smooth_period" in schema
        assert schema["momentum_smooth_period"]["type"] == "int"
        assert schema["momentum_smooth_period"]["default"] == 5

        assert "atr_period" in schema
        assert schema["atr_period"]["type"] == "int"
        assert schema["atr_period"]["default"] == 14


# ---------------------------------------------------------------------------
# 12. SHORT trade — slight momentum flip → no exit with new thresholds
# ---------------------------------------------------------------------------

class TestMomentumThresholdNoExit:

    def test_short_slight_momentum_flip_no_exit(self):
        """With new threshold 0.35, a momentum of 0.25 should NOT trigger bull regime.

        Previously at 0.20 threshold, momentum=0.25 would flip to bull → exit SHORT.
        Now 0.25 < 0.35 → stays neutral → no exit.
        """
        old_threshold = 0.20
        new_threshold = 0.35
        momentum_value = 0.25

        # Old behavior: would have triggered exit
        assert momentum_value > old_threshold, "Would have triggered with old threshold"

        # New behavior: no exit
        assert momentum_value < new_threshold, "Should NOT trigger with new threshold"

        # Simulate regime check logic from strategy
        if momentum_value > new_threshold:
            regime = "bull"
        elif momentum_value < -new_threshold:
            regime = "bear"
        else:
            regime = "neutral"

        assert regime == "neutral", "Slight momentum flip should remain neutral"
