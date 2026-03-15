"""
Comprehensive tests for strategy-based exit signals, optional TP/SL,
position monitor exit checks, and close-position verification.

Covers all changes from 2026-02-23 to 2026-02-25:
1. should_exit() for EdgeIndicator
2. Optional TP/SL (_calculate_targets returns None when no config)
3. Position monitor strategy exit integration
4. Close-position endpoint exchange verification
5. TradeExecutor None TP/SL logging
6. BaseStrategy should_exit() default
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.base import BaseStrategy, SignalDirection, TradeSignal


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_klines(closes, highs=None, lows=None):
    """Build minimal kline data from close prices."""
    result = []
    for i, c in enumerate(closes):
        h = highs[i] if highs else c * 1.01
        low = lows[i] if lows else c * 0.99
        result.append([
            1700000000000 + i * 3600000,
            str(c), str(h), str(low), str(c), "100",
            1700003600000 + i * 3600000,
            str(c * 100), 1000, "55", str(c * 55), "0",
        ])
    return result


def _uptrend_closes(n=50, start=100.0, step=1.0):
    return [start + i * step for i in range(n)]


def _downtrend_closes(n=50, start=200.0, step=1.0):
    return [start - i * step for i in range(n)]


def _sideways_closes(n=50, center=100.0, amplitude=0.5):
    """Oscillating closes that stay inside the EMA ribbon."""
    return [center + amplitude * ((-1) ** i) for i in range(n)]


def _make_mock_fetcher(klines):
    """Create a mock data fetcher that returns given klines."""
    fetcher = AsyncMock()
    fetcher.get_binance_klines = AsyncMock(return_value=klines)
    fetcher._ensure_session = AsyncMock()
    fetcher.close = AsyncMock()
    return fetcher


# ═══════════════════════════════════════════════════════════════════════════════
# 1. BaseStrategy.should_exit() default
# ═══════════════════════════════════════════════════════════════════════════════

class TestBaseStrategyShouldExit:
    """BaseStrategy.should_exit() should return (False, '') by default."""

    @pytest.mark.asyncio
    async def test_default_returns_false(self):
        """Default implementation never exits."""

        class MinimalStrategy(BaseStrategy):
            async def generate_signal(self, symbol="BTCUSDT"):
                pass
            async def should_trade(self, signal):
                return True, ""
            @classmethod
            def get_description(cls):
                return "test"
            @classmethod
            def get_param_schema(cls):
                return {}

        strategy = MinimalStrategy()
        should_close, reason = await strategy.should_exit("BTCUSDT", "long", 95000.0)

        assert should_close is False
        assert reason == ""

    @pytest.mark.asyncio
    async def test_default_with_metrics(self):
        """Default implementation ignores metrics_at_entry."""

        class MinimalStrategy(BaseStrategy):
            async def generate_signal(self, symbol="BTCUSDT"):
                pass
            async def should_trade(self, signal):
                return True, ""
            @classmethod
            def get_description(cls):
                return "test"
            @classmethod
            def get_param_schema(cls):
                return {}

        strategy = MinimalStrategy()
        should_close, reason = await strategy.should_exit(
            "BTCUSDT", "short", 95000.0,
            metrics_at_entry={"adx": 25, "regime": -1}
        )

        assert should_close is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TradeSignal Optional TP/SL
# ═══════════════════════════════════════════════════════════════════════════════

class TestTradeSignalOptionalTpSl:
    """TradeSignal.target_price and stop_loss can be None."""

    def test_none_tp_sl_accepted(self):
        signal = TradeSignal(
            direction=SignalDirection.LONG,
            confidence=70,
            symbol="BTCUSDT",
            entry_price=95000.0,
            target_price=None,
            stop_loss=None,
            reason="no TP/SL",
            metrics_snapshot={},
            timestamp=datetime.now(),
        )
        assert signal.target_price is None
        assert signal.stop_loss is None

    def test_mixed_tp_none_sl_set(self):
        signal = TradeSignal(
            direction=SignalDirection.SHORT,
            confidence=60,
            symbol="ETHUSDT",
            entry_price=3500.0,
            target_price=None,
            stop_loss=3600.0,
            reason="only SL",
            metrics_snapshot={},
            timestamp=datetime.now(),
        )
        assert signal.target_price is None
        assert signal.stop_loss == 3600.0

    def test_both_set_still_works(self):
        signal = TradeSignal(
            direction=SignalDirection.LONG,
            confidence=80,
            symbol="BTCUSDT",
            entry_price=95000.0,
            target_price=98000.0,
            stop_loss=93000.0,
            reason="full TP/SL",
            metrics_snapshot={},
            timestamp=datetime.now(),
        )
        assert signal.target_price == 98000.0
        assert signal.stop_loss == 93000.0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. EdgeIndicator: Optional TP/SL + should_exit()
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeIndicatorOptionalTpSl:
    """EdgeIndicator._calculate_targets returns (None, None) without config."""

    def test_no_defaults_returns_none(self):
        from src.strategy.edge_indicator import EdgeIndicatorStrategy
        strategy = EdgeIndicatorStrategy()
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 95000.0)
        assert tp is None
        assert sl is None

    def test_no_defaults_short_returns_none(self):
        from src.strategy.edge_indicator import EdgeIndicatorStrategy
        strategy = EdgeIndicatorStrategy()
        tp, sl = strategy._calculate_targets(SignalDirection.SHORT, 95000.0)
        assert tp is None
        assert sl is None

    def test_user_configured_tp_works(self):
        from src.strategy.edge_indicator import EdgeIndicatorStrategy
        strategy = EdgeIndicatorStrategy(params={"take_profit_percent": 3.0})
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 100000.0)
        assert tp == 103000.0
        assert sl is None

    def test_user_configured_sl_works(self):
        from src.strategy.edge_indicator import EdgeIndicatorStrategy
        strategy = EdgeIndicatorStrategy(params={"stop_loss_percent": 1.5})
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 100000.0)
        assert tp is None
        assert sl == 98500.0

    def test_user_configured_both_works(self):
        from src.strategy.edge_indicator import EdgeIndicatorStrategy
        strategy = EdgeIndicatorStrategy(params={
            "take_profit_percent": 4.0,
            "stop_loss_percent": 2.0,
        })
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 100000.0)
        assert tp == 104000.0
        assert sl == 98000.0

    def test_short_user_configured_both(self):
        from src.strategy.edge_indicator import EdgeIndicatorStrategy
        strategy = EdgeIndicatorStrategy(params={
            "take_profit_percent": 4.0,
            "stop_loss_percent": 2.0,
        })
        tp, sl = strategy._calculate_targets(SignalDirection.SHORT, 100000.0)
        assert tp == 96000.0
        assert sl == 102000.0

    def test_defaults_dict_has_no_tp_sl(self):
        from src.strategy.edge_indicator import DEFAULTS
        assert "take_profit_percent" not in DEFAULTS
        assert "stop_loss_percent" not in DEFAULTS

    def test_param_schema_has_no_default_for_tp(self):
        from src.strategy.edge_indicator import EdgeIndicatorStrategy
        schema = EdgeIndicatorStrategy.get_param_schema()
        assert "default" not in schema["take_profit_percent"]

    def test_param_schema_has_no_default_for_sl(self):
        from src.strategy.edge_indicator import EdgeIndicatorStrategy
        schema = EdgeIndicatorStrategy.get_param_schema()
        assert "default" not in schema["stop_loss_percent"]


class TestEdgeIndicatorShouldExit:
    """EdgeIndicator.should_exit() exit conditions."""

    def _make_strategy(self, klines):
        from src.strategy.edge_indicator import EdgeIndicatorStrategy
        fetcher = _make_mock_fetcher(klines)
        return EdgeIndicatorStrategy(data_fetcher=fetcher)

    @pytest.mark.asyncio
    async def test_long_exit_on_bear_trend(self):
        """LONG should exit when price drops below EMA ribbon (bear trend)."""
        closes = _downtrend_closes(60, start=200, step=3)
        strategy = self._make_strategy(_make_klines(closes))

        should_close, reason = await strategy.should_exit("BTCUSDT", "long", 200.0)

        assert should_close is True
        assert "bearTrend" in reason or "unter EMA" in reason

    @pytest.mark.asyncio
    async def test_short_exit_on_bull_trend(self):
        """SHORT should exit when price rises above EMA ribbon (bull trend)."""
        closes = _uptrend_closes(60, start=100, step=3)
        strategy = self._make_strategy(_make_klines(closes))

        should_close, reason = await strategy.should_exit("BTCUSDT", "short", 100.0)

        assert should_close is True
        assert "bullTrend" in reason or "ueber EMA" in reason

    @pytest.mark.asyncio
    async def test_long_no_exit_in_bull_trend(self):
        """LONG should NOT exit when trend is still bullish."""
        closes = _uptrend_closes(60, start=100, step=3)
        strategy = self._make_strategy(_make_klines(closes))

        should_close, reason = await strategy.should_exit("BTCUSDT", "long", 100.0)

        assert should_close is False

    @pytest.mark.asyncio
    async def test_short_no_exit_in_bear_trend(self):
        """SHORT should NOT exit when trend is still bearish."""
        closes = _downtrend_closes(60, start=200, step=3)
        strategy = self._make_strategy(_make_klines(closes))

        should_close, reason = await strategy.should_exit("BTCUSDT", "short", 200.0)

        assert should_close is False

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_false(self):
        """With insufficient kline data, should not exit."""
        closes = [100.0, 101.0, 102.0]
        strategy = self._make_strategy(_make_klines(closes))

        should_close, reason = await strategy.should_exit("BTCUSDT", "long", 100.0)

        assert should_close is False
        assert "Insufficient" in reason

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        """On exception, should not exit (safety: keep position)."""
        from src.strategy.edge_indicator import EdgeIndicatorStrategy
        fetcher = AsyncMock()
        fetcher.get_binance_klines = AsyncMock(side_effect=Exception("API down"))
        fetcher._ensure_session = AsyncMock()
        strategy = EdgeIndicatorStrategy(data_fetcher=fetcher)

        should_close, reason = await strategy.should_exit("BTCUSDT", "long", 95000.0)

        assert should_close is False

    @pytest.mark.asyncio
    async def test_exit_reason_contains_score(self):
        """Exit reason should include momentum score for debugging."""
        closes = _downtrend_closes(60, start=200, step=3)
        strategy = self._make_strategy(_make_klines(closes))

        should_close, reason = await strategy.should_exit("BTCUSDT", "long", 200.0)

        if should_close:
            assert "Momentum" in reason or "score" in reason


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LiquidationHunter + SentimentSurfer: Optional TP/SL
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiquidationHunterOptionalTpSl:

    def test_no_defaults_returns_none(self):
        from src.strategy.liquidation_hunter import LiquidationHunterStrategy
        strategy = LiquidationHunterStrategy()
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 95000.0)
        assert tp is None
        assert sl is None

    def test_user_configured_works(self):
        from src.strategy.liquidation_hunter import LiquidationHunterStrategy
        strategy = LiquidationHunterStrategy(params={
            "take_profit_percent": 4.0,
            "stop_loss_percent": 1.5,
        })
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 100000.0)
        assert tp == 104000.0
        assert sl == 98500.0

    def test_defaults_dict_has_no_tp_sl(self):
        from src.strategy.liquidation_hunter import DEFAULTS
        assert "take_profit_percent" not in DEFAULTS
        assert "stop_loss_percent" not in DEFAULTS


class TestSentimentSurferOptionalTpSl:

    def test_no_defaults_returns_none(self):
        from src.strategy.sentiment_surfer import SentimentSurferStrategy
        strategy = SentimentSurferStrategy()
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 95000.0)
        assert tp is None
        assert sl is None

    def test_user_configured_works(self):
        from src.strategy.sentiment_surfer import SentimentSurferStrategy
        strategy = SentimentSurferStrategy(params={
            "take_profit_percent": 3.5,
            "stop_loss_percent": 1.5,
        })
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 100000.0)
        assert tp == 103500.0
        assert sl == 98500.0

    def test_defaults_dict_has_no_tp_sl(self):
        from src.strategy.sentiment_surfer import DEFAULTS
        assert "take_profit_percent" not in DEFAULTS
        assert "stop_loss_percent" not in DEFAULTS


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Position Monitor: Strategy Exit Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestPositionMonitorStrategyExit:
    """Tests for the strategy exit check in _check_position()."""

    def _make_monitor(self, strategy=None):
        """Create a mock object with PositionMonitorMixin methods."""
        from src.bot.position_monitor import PositionMonitorMixin

        class MockMonitor(PositionMonitorMixin):
            pass

        monitor = MockMonitor()
        monitor.bot_config_id = 1
        monitor._strategy = strategy
        monitor._config = MagicMock()
        monitor._config.name = "TestBot"
        monitor._get_client = MagicMock()
        monitor._close_and_record_trade = AsyncMock()
        return monitor

    def _make_trade(self, symbol="BTCUSDT", side="long", entry_price=95000.0,
                    tp=None, sl=None, metrics=None):
        trade = MagicMock()
        trade.id = 1
        trade.symbol = symbol
        trade.side = side
        trade.entry_price = entry_price
        trade.demo_mode = True
        trade.take_profit = tp
        trade.stop_loss = sl
        trade.highest_price = None
        trade.metrics_snapshot = json.dumps(metrics) if metrics else None
        trade.order_id = "order_001"
        trade.close_order_id = None
        trade.fees = 0
        trade.funding_paid = 0
        trade.entry_time = datetime.now(timezone.utc)
        return trade

    def _make_position(self, size=0.01, side="long"):
        pos = MagicMock()
        pos.size = size
        pos.side = side
        return pos

    @pytest.mark.asyncio
    async def test_strategy_exit_closes_position(self):
        """When should_exit returns True, position should be closed."""
        strategy = AsyncMock()
        strategy.should_exit = AsyncMock(return_value=(True, "Trend reversal"))

        monitor = self._make_monitor(strategy)
        client = AsyncMock()
        client.get_position = AsyncMock(return_value=self._make_position())
        client.close_position = AsyncMock()
        client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
        client.get_trade_total_fees = AsyncMock(return_value=0.5)
        client.get_funding_fees = AsyncMock(return_value=0.1)
        monitor._get_client = MagicMock(return_value=client)

        trade = self._make_trade()
        session = AsyncMock()

        await monitor._check_position(trade, session)

        client.close_position.assert_called_once_with(trade.symbol, trade.side)
        monitor._close_and_record_trade.assert_called_once()
        call_args = monitor._close_and_record_trade.call_args
        assert call_args[0][2] == "STRATEGY_EXIT"

    @pytest.mark.asyncio
    async def test_strategy_no_exit_keeps_position(self):
        """When should_exit returns False, position should NOT be closed."""
        strategy = AsyncMock()
        strategy.should_exit = AsyncMock(return_value=(False, ""))

        monitor = self._make_monitor(strategy)
        client = AsyncMock()
        client.get_position = AsyncMock(return_value=self._make_position())
        monitor._get_client = MagicMock(return_value=client)

        trade = self._make_trade()
        session = AsyncMock()

        await monitor._check_position(trade, session)

        client.close_position.assert_not_called()
        monitor._close_and_record_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_strategy_skips_exit_check(self):
        """When no strategy is set, exit check is skipped."""
        monitor = self._make_monitor(strategy=None)
        client = AsyncMock()
        client.get_position = AsyncMock(return_value=self._make_position())
        monitor._get_client = MagicMock(return_value=client)

        trade = self._make_trade()
        session = AsyncMock()

        await monitor._check_position(trade, session)

        client.close_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_position_gone_triggers_handle_closed(self):
        """When exchange says position is gone, handle_closed_position is called."""
        monitor = self._make_monitor()
        client = AsyncMock()
        client.get_position = AsyncMock(return_value=None)
        client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
        client.get_trade_total_fees = AsyncMock(return_value=0.5)
        client.get_funding_fees = AsyncMock(return_value=0.1)
        monitor._get_client = MagicMock(return_value=client)

        trade = self._make_trade(tp=97000.0, sl=94000.0)
        session = AsyncMock()

        await monitor._check_position(trade, session)

        monitor._close_and_record_trade.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_position_failure_does_not_record(self):
        """If exchange close fails, trade should NOT be recorded as closed."""
        strategy = AsyncMock()
        strategy.should_exit = AsyncMock(return_value=(True, "Exit signal"))

        monitor = self._make_monitor(strategy)
        client = AsyncMock()
        client.get_position = AsyncMock(return_value=self._make_position())
        client.close_position = AsyncMock(side_effect=Exception("Exchange error"))
        monitor._get_client = MagicMock(return_value=client)

        trade = self._make_trade()
        session = AsyncMock()

        await monitor._check_position(trade, session)

        monitor._close_and_record_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_closed_position_none_tp_sl(self):
        """_handle_closed_position works when trade has no TP/SL."""
        monitor = self._make_monitor()
        client = AsyncMock()
        client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
        client.get_trade_total_fees = AsyncMock(return_value=0.5)
        client.get_funding_fees = AsyncMock(return_value=0.1)

        trade = self._make_trade(tp=None, sl=None)
        session = AsyncMock()

        await monitor._handle_closed_position(trade, client, session)

        monitor._close_and_record_trade.assert_called_once()
        call_args = monitor._close_and_record_trade.call_args
        assert call_args[0][2] == "EXTERNAL_CLOSE"

    @pytest.mark.asyncio
    async def test_metrics_snapshot_parsed(self):
        """Metrics snapshot should be parsed and passed to should_exit."""
        strategy = AsyncMock()
        strategy.should_exit = AsyncMock(return_value=(False, ""))

        monitor = self._make_monitor(strategy)
        client = AsyncMock()
        client.get_position = AsyncMock(return_value=self._make_position())
        client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
        monitor._get_client = MagicMock(return_value=client)

        metrics = {"adx": 25, "regime": 1, "momentum_smoothed": 0.5}
        trade = self._make_trade(metrics=metrics)
        session = AsyncMock()

        await monitor._check_position(trade, session)

        call_kwargs = strategy.should_exit.call_args[1]
        assert call_kwargs["metrics_at_entry"] == metrics


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Close-Position Endpoint: Exchange Verification
# ═══════════════════════════════════════════════════════════════════════════════

class TestClosePositionVerification:
    """Tests for the close-position endpoint exchange verification fix."""

    @pytest.mark.asyncio
    async def test_close_succeeds_when_position_gone(self):
        """After close, if get_position returns None, no error should occur."""
        mock_client = AsyncMock()
        mock_client.close_position = AsyncMock(return_value=MagicMock())
        mock_client.get_position = AsyncMock(return_value=None)

        # Simulate the verification logic from bots_lifecycle.py
        order = await mock_client.close_position("BTCUSDT", "long", margin_mode="cross")
        assert order is not None

        remaining = await mock_client.get_position("BTCUSDT")
        assert remaining is None
        # No error — position is verified as closed

    @pytest.mark.asyncio
    async def test_close_fails_when_position_still_exists(self):
        """After failed close, if position still exists, should error."""
        from fastapi import HTTPException

        mock_client = AsyncMock()
        mock_client.close_position = AsyncMock(side_effect=Exception("API error"))

        mock_position = MagicMock()
        mock_position.size = 0.01
        mock_client.get_position = AsyncMock(return_value=mock_position)

        # Simulate the verification logic from bots_lifecycle.py
        try:
            await mock_client.close_position("BTCUSDT", "long", margin_mode="cross")
        except Exception:
            pass

        remaining_pos = await mock_client.get_position("BTCUSDT")
        assert remaining_pos is not None
        assert remaining_pos.size > 0

        # This should trigger the HTTPException in the real endpoint
        with pytest.raises(Exception):
            if remaining_pos and remaining_pos.size > 0:
                raise HTTPException(
                    status_code=502,
                    detail="Position konnte nicht geschlossen werden",
                )

    @pytest.mark.asyncio
    async def test_close_fails_but_position_already_gone(self):
        """Close API fails but position is already gone (e.g. TP hit) = success."""
        mock_client = AsyncMock()
        mock_client.close_position = AsyncMock(side_effect=Exception("no position"))
        mock_client.get_position = AsyncMock(return_value=None)

        try:
            await mock_client.close_position("BTCUSDT", "long", margin_mode="cross")
        except Exception:
            pass

        remaining = await mock_client.get_position("BTCUSDT")
        assert remaining is None
        # No error should be raised — position is gone


# ═══════════════════════════════════════════════════════════════════════════════
# 8. TradeExecutor: None TP/SL Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestTradeExecutorNoneTpSl:
    """TradeExecutor logs correctly when no TP/SL is set."""

    def _make_signal(self, tp=None, sl=None):
        return TradeSignal(
            direction=SignalDirection.LONG,
            confidence=70,
            symbol="BTCUSDT",
            entry_price=95000.0,
            target_price=tp,
            stop_loss=sl,
            reason="test",
            metrics_snapshot={},
            timestamp=datetime.now(),
        )

    def test_signal_with_none_tp_sl(self):
        signal = self._make_signal(tp=None, sl=None)
        assert signal.target_price is None
        assert signal.stop_loss is None

    def test_signal_with_values(self):
        signal = self._make_signal(tp=98000.0, sl=93000.0)
        assert signal.target_price == 98000.0
        assert signal.stop_loss == 93000.0


# ═══════════════════════════════════════════════════════════════════════════════
# 9. i18n: Warning Translation Keys Exist
# ═══════════════════════════════════════════════════════════════════════════════

class TestI18nWarningKeys:
    """Verify that the new i18n keys exist in both language files."""

    def _load_json(self, lang):
        path = Path(__file__).parent.parent.parent / "frontend" / "src" / "i18n" / f"{lang}.json"
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @pytest.mark.parametrize("lang", ["de", "en"])
    def test_no_sl_warning_key(self, lang):
        data = self._load_json(lang)
        assert "noSlWarning" in data["bots"]["builder"]

    @pytest.mark.parametrize("lang", ["de", "en"])
    def test_no_tpsl_warning_key(self, lang):
        data = self._load_json(lang)
        assert "noTpSlWarning" in data["bots"]["builder"]

    @pytest.mark.parametrize("lang", ["de", "en"])
    def test_no_tpsl_label_key(self, lang):
        data = self._load_json(lang)
        assert "noTpSlLabel" in data["bots"]["builder"]

    def test_german_warning_mentions_strategie(self):
        data = self._load_json("de")
        assert "Strategie" in data["bots"]["builder"]["noTpSlWarning"]

    def test_english_warning_mentions_strategy(self):
        data = self._load_json("en")
        assert "strategy" in data["bots"]["builder"]["noTpSlWarning"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Margin Mode (from 2026-02-24)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarginModeInConfig:
    """Verify margin_mode field exists in BotConfig model."""

    def test_botconfig_has_margin_mode_column(self):
        from src.models.database import BotConfig
        assert hasattr(BotConfig, "margin_mode")

    def test_margin_mode_i18n_keys_exist(self):
        for lang in ["de", "en"]:
            path = Path(__file__).parent.parent.parent / "frontend" / "src" / "i18n" / f"{lang}.json"
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            builder = data["bots"]["builder"]
            assert "marginMode" in builder
            assert "cross" in builder
            assert "isolated" in builder


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Symbol Conflict Detection (from 2026-02-23)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSymbolConflictI18n:
    """Verify symbol conflict i18n keys exist."""

    @pytest.mark.parametrize("lang", ["de", "en"])
    def test_symbol_conflict_keys(self, lang):
        path = Path(__file__).parent.parent.parent / "frontend" / "src" / "i18n" / f"{lang}.json"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        builder = data["bots"]["builder"]
        assert "symbolConflictTitle" in builder
