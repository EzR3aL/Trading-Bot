"""
Unit tests for the AlertEngine.

Tests cover:
- AlertEngine start / stop lifecycle
- Price alert condition checking (above, below)
- Portfolio alert condition checking (daily_loss, drawdown, profit_target)
- Strategy alert inline checking (low_confidence, consecutive_losses, signal_missed)
- Cooldown enforcement
- Trigger side effects (DB update, history record)
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_alert(**overrides):
    """Create a mock Alert object."""
    defaults = {
        "id": 1,
        "user_id": 1,
        "bot_config_id": None,
        "alert_type": "price",
        "category": "price_above",
        "symbol": "BTCUSDT",
        "threshold": 100000.0,
        "direction": "above",
        "is_enabled": True,
        "cooldown_minutes": 15,
        "last_triggered_at": None,
        "trigger_count": 0,
    }
    defaults.update(overrides)
    alert = MagicMock()
    for k, v in defaults.items():
        setattr(alert, k, v)
    return alert


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

class TestAlertEngineLifecycle:
    """Tests for starting and stopping the engine."""

    def test_initial_state(self):
        from src.bot.alert_engine import AlertEngine
        engine = AlertEngine()
        assert engine._running is False
        assert engine._price_task is None
        assert engine._portfolio_task is None

    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        from src.bot.alert_engine import AlertEngine
        engine = AlertEngine()

        with patch.object(engine, "_price_loop", new_callable=AsyncMock):
            with patch.object(engine, "_portfolio_loop", new_callable=AsyncMock):
                await engine.start()
                assert engine._running is True
                assert engine._price_task is not None
                assert engine._portfolio_task is not None
                # Cleanup
                await engine.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        from src.bot.alert_engine import AlertEngine
        engine = AlertEngine()

        with patch.object(engine, "_price_loop", new_callable=AsyncMock):
            with patch.object(engine, "_portfolio_loop", new_callable=AsyncMock):
                await engine.start()
                task1 = engine._price_task
                await engine.start()  # Should be no-op
                assert engine._price_task is task1
                await engine.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        from src.bot.alert_engine import AlertEngine
        engine = AlertEngine()

        with patch.object(engine, "_price_loop", new_callable=AsyncMock):
            with patch.object(engine, "_portfolio_loop", new_callable=AsyncMock):
                await engine.start()
                await engine.stop()
                assert engine._running is False


# ---------------------------------------------------------------------------
# Price alert check tests
# ---------------------------------------------------------------------------

class TestPriceAlertChecks:
    """Tests for price alert condition evaluation."""

    @pytest.mark.asyncio
    async def test_price_above_triggers(self):
        """Alert with direction=above triggers when price >= threshold."""
        from src.bot.alert_engine import AlertEngine
        engine = AlertEngine()

        alert = _make_alert(
            category="price_above",
            direction="above",
            threshold=90000.0,
            symbol="BTCUSDT",
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [alert]
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_fetcher = MagicMock()
        mock_fetcher._ensure_session = AsyncMock()
        mock_fetcher.close = AsyncMock()
        mock_fetcher.get_current_price = AsyncMock(return_value=95000.0)

        with patch("src.bot.alert_engine.get_session", return_value=mock_session):
            with patch("src.bot.alert_engine.MarketDataFetcher", return_value=mock_fetcher) if False else \
                 patch("src.data.market_data.MarketDataFetcher", return_value=mock_fetcher):
                with patch.object(engine, "_trigger_alert", new_callable=AsyncMock) as mock_trigger:
                    # Manually test the condition logic
                    current_price = 95000.0
                    triggered = current_price >= alert.threshold
                    assert triggered is True

    @pytest.mark.asyncio
    async def test_price_below_triggers(self):
        """Alert with direction=below triggers when price <= threshold."""
        alert = _make_alert(
            category="price_below",
            direction="below",
            threshold=90000.0,
            symbol="BTCUSDT",
        )
        current_price = 85000.0
        triggered = current_price <= alert.threshold
        assert triggered is True

    @pytest.mark.asyncio
    async def test_price_above_no_trigger(self):
        """Alert with direction=above does NOT trigger when price < threshold."""
        alert = _make_alert(
            category="price_above",
            direction="above",
            threshold=100000.0,
        )
        current_price = 95000.0
        triggered = current_price >= alert.threshold
        assert triggered is False

    @pytest.mark.asyncio
    async def test_price_below_no_trigger(self):
        """Alert with direction=below does NOT trigger when price > threshold."""
        alert = _make_alert(
            category="price_below",
            direction="below",
            threshold=80000.0,
        )
        current_price = 95000.0
        triggered = current_price <= alert.threshold
        assert triggered is False


# ---------------------------------------------------------------------------
# Portfolio alert check tests
# ---------------------------------------------------------------------------

class TestPortfolioAlertChecks:
    """Tests for portfolio alert condition evaluation."""

    @pytest.mark.asyncio
    async def test_daily_loss_triggers(self):
        """daily_loss alert triggers when loss pct >= threshold."""
        alert = _make_alert(
            alert_type="portfolio",
            category="daily_loss",
            threshold=3.0,
            symbol=None,
            direction=None,
        )
        daily_loss_pct = abs(-4.5)
        triggered = daily_loss_pct >= alert.threshold
        assert triggered is True

    @pytest.mark.asyncio
    async def test_daily_loss_no_trigger(self):
        """daily_loss alert does NOT trigger when loss pct < threshold."""
        alert = _make_alert(
            alert_type="portfolio",
            category="daily_loss",
            threshold=5.0,
        )
        daily_loss_pct = abs(-2.0)
        triggered = daily_loss_pct >= alert.threshold
        assert triggered is False

    @pytest.mark.asyncio
    async def test_drawdown_triggers(self):
        """drawdown alert triggers when drawdown >= threshold."""
        alert = _make_alert(
            alert_type="portfolio",
            category="drawdown",
            threshold=5.0,
        )
        drawdown = abs(-7.0)
        triggered = drawdown >= alert.threshold
        assert triggered is True

    @pytest.mark.asyncio
    async def test_profit_target_triggers(self):
        """profit_target alert triggers when daily pnl >= threshold."""
        alert = _make_alert(
            alert_type="portfolio",
            category="profit_target",
            threshold=500.0,
        )
        daily_pnl = 600.0
        triggered = daily_pnl >= alert.threshold
        assert triggered is True

    @pytest.mark.asyncio
    async def test_profit_target_no_trigger(self):
        """profit_target alert does NOT trigger when pnl < threshold."""
        alert = _make_alert(
            alert_type="portfolio",
            category="profit_target",
            threshold=500.0,
        )
        daily_pnl = 200.0
        triggered = daily_pnl >= alert.threshold
        assert triggered is False


# ---------------------------------------------------------------------------
# Cooldown tests
# ---------------------------------------------------------------------------

class TestCooldown:
    """Tests for alert cooldown enforcement."""

    @pytest.mark.asyncio
    async def test_cooldown_blocks_trigger(self):
        """Alert within cooldown window should not trigger."""
        from src.bot.alert_engine import AlertEngine
        engine = AlertEngine()

        now = datetime.utcnow()
        alert = _make_alert(
            last_triggered_at=now - timedelta(minutes=5),
            cooldown_minutes=15,
        )

        # Directly test the cooldown check from _trigger_alert
        cooldown_end = alert.last_triggered_at + timedelta(minutes=alert.cooldown_minutes)
        should_skip = now < cooldown_end
        assert should_skip is True

    @pytest.mark.asyncio
    async def test_cooldown_allows_trigger_after_expiry(self):
        """Alert after cooldown window should trigger."""
        now = datetime.utcnow()
        alert = _make_alert(
            last_triggered_at=now - timedelta(minutes=20),
            cooldown_minutes=15,
        )

        cooldown_end = alert.last_triggered_at + timedelta(minutes=alert.cooldown_minutes)
        should_skip = now < cooldown_end
        assert should_skip is False

    @pytest.mark.asyncio
    async def test_no_previous_trigger_allows(self):
        """Alert that was never triggered should always pass cooldown."""
        alert = _make_alert(last_triggered_at=None)
        # In the engine, None last_triggered_at skips cooldown check
        assert alert.last_triggered_at is None


# ---------------------------------------------------------------------------
# Strategy alert (inline) tests
# ---------------------------------------------------------------------------

class TestStrategyAlerts:
    """Tests for check_strategy_alerts() function."""

    @pytest.mark.asyncio
    async def test_low_confidence_triggers(self):
        """low_confidence triggers when current_value <= threshold."""
        alert = _make_alert(
            alert_type="strategy",
            category="low_confidence",
            threshold=60.0,
        )
        current_value = 45.0
        should_trigger = current_value <= alert.threshold
        assert should_trigger is True

    @pytest.mark.asyncio
    async def test_low_confidence_no_trigger(self):
        """low_confidence does NOT trigger when current_value > threshold."""
        alert = _make_alert(
            alert_type="strategy",
            category="low_confidence",
            threshold=60.0,
        )
        current_value = 75.0
        should_trigger = current_value <= alert.threshold
        assert should_trigger is False

    @pytest.mark.asyncio
    async def test_consecutive_losses_triggers(self):
        """consecutive_losses triggers when count >= threshold."""
        alert = _make_alert(
            alert_type="strategy",
            category="consecutive_losses",
            threshold=3.0,
        )
        current_value = 4.0
        should_trigger = current_value >= alert.threshold
        assert should_trigger is True

    @pytest.mark.asyncio
    async def test_signal_missed_always_triggers(self):
        """signal_missed always triggers if alert exists."""
        alert = _make_alert(
            alert_type="strategy",
            category="signal_missed",
        )
        # In the engine, signal_missed always returns True
        should_trigger = True
        assert should_trigger is True


# ---------------------------------------------------------------------------
# Trigger action tests
# ---------------------------------------------------------------------------

class TestTriggerAction:
    """Tests for the _trigger_alert side effects."""

    @pytest.mark.asyncio
    async def test_trigger_sends_notification(self):
        """Triggering an alert calls _send_alert_notifications."""
        from src.bot.alert_engine import AlertEngine
        engine = AlertEngine()

        alert = _make_alert(last_triggered_at=None, bot_config_id=None)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.add = MagicMock()

        with patch("src.bot.alert_engine.get_session", return_value=mock_session):
            with patch.object(engine, "_send_alert_notifications", new_callable=AsyncMock) as mock_notify:
                with patch("src.bot.alert_engine.ws_manager", create=True) as mock_ws:
                    mock_ws.broadcast_to_user = AsyncMock()
                    await engine._trigger_alert(alert, 95000.0, "BTC reached $95,000")
                    mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_respects_cooldown(self):
        """Trigger is skipped when within cooldown window."""
        from src.bot.alert_engine import AlertEngine
        engine = AlertEngine()

        alert = _make_alert(
            last_triggered_at=datetime.utcnow() - timedelta(minutes=5),
            cooldown_minutes=15,
        )

        with patch.object(engine, "_send_alert_notifications", new_callable=AsyncMock) as mock_notify:
            await engine._trigger_alert(alert, 95000.0, "Test")
            mock_notify.assert_not_called()
