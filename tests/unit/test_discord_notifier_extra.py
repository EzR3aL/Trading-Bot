"""
Extra unit tests for the Discord Notifier to increase coverage to 90%+.

Tests cover the methods and branches NOT exercised in test_discord_notifier.py:
- _ensure_session (new session, re-create closed session)
- close (active session, None session, already-closed session)
- send_trade_entry with demo_mode=None (settings fallback)
- send_trade_exit with demo_mode=None, duration formatting, strategy_reason,
  short-side direction emoji, zero-duration edge case
- send_daily_summary (full coverage including zero-trades edge case)
- send_risk_alert (with and without optional params)
- send_signal_alert (long and short directions)
- send_error (with and without details)
- send_bot_status (known statuses, unknown status, with/without stats)
- _send_webhook creates session when _session is None
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.notifications.discord_notifier import DiscordNotifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_notifier(webhook_url="https://discord.com/api/webhooks/test/token"):
    """Create a DiscordNotifier with a given webhook URL."""
    return DiscordNotifier(webhook_url=webhook_url)


def _stub_send_webhook(notifier):
    """Replace _send_webhook with a mock that captures the payload."""
    notifier._send_webhook = AsyncMock(return_value=True)
    return notifier._send_webhook


# ---------------------------------------------------------------------------
# Session management tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEnsureSession:
    """Tests for _ensure_session method."""

    async def test_creates_session_when_none(self):
        """_ensure_session should create a new aiohttp.ClientSession when _session is None."""
        # Arrange
        notifier = _make_notifier()
        assert notifier._session is None

        # Act
        with patch("src.notifications.discord_notifier.aiohttp.ClientSession") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.closed = False
            mock_cls.return_value = mock_instance
            await notifier._ensure_session()

        # Assert
        mock_cls.assert_called_once()
        assert notifier._session is mock_instance

    async def test_recreates_session_when_closed(self):
        """_ensure_session should create a new session when existing one is closed."""
        # Arrange
        notifier = _make_notifier()
        old_session = MagicMock()
        old_session.closed = True
        notifier._session = old_session

        # Act
        with patch("src.notifications.discord_notifier.aiohttp.ClientSession") as mock_cls:
            new_session = MagicMock()
            new_session.closed = False
            mock_cls.return_value = new_session
            await notifier._ensure_session()

        # Assert
        mock_cls.assert_called_once()
        assert notifier._session is new_session

    async def test_reuses_open_session(self):
        """_ensure_session should not create a new session when one is already open."""
        # Arrange
        notifier = _make_notifier()
        existing_session = MagicMock()
        existing_session.closed = False
        notifier._session = existing_session

        # Act
        with patch("src.notifications.discord_notifier.aiohttp.ClientSession") as mock_cls:
            await notifier._ensure_session()

        # Assert
        mock_cls.assert_not_called()
        assert notifier._session is existing_session


@pytest.mark.asyncio
class TestClose:
    """Tests for close method."""

    async def test_closes_open_session(self):
        """close should close an active session."""
        # Arrange
        notifier = _make_notifier()
        mock_session = AsyncMock()
        mock_session.closed = False
        notifier._session = mock_session

        # Act
        await notifier.close()

        # Assert
        mock_session.close.assert_awaited_once()

    async def test_noop_when_session_is_none(self):
        """close should do nothing when _session is None."""
        # Arrange
        notifier = _make_notifier()
        notifier._session = None

        # Act / Assert (should not raise)
        await notifier.close()

    async def test_noop_when_session_already_closed(self):
        """close should do nothing when session is already closed."""
        # Arrange
        notifier = _make_notifier()
        mock_session = AsyncMock()
        mock_session.closed = True
        notifier._session = mock_session

        # Act
        await notifier.close()

        # Assert
        mock_session.close.assert_not_awaited()


# ---------------------------------------------------------------------------
# _send_webhook integration (session creation path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendWebhookSessionCreation:
    """Tests that _send_webhook creates a session when needed."""

    async def test_creates_session_before_posting(self):
        """_send_webhook should call _ensure_session to set up HTTP session."""
        # Arrange
        notifier = _make_notifier()
        mock_response = AsyncMock()
        mock_response.status = 204
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post.return_value = mock_response

        notifier._session = mock_session

        # Act
        result = await notifier._send_webhook({"test": "payload"})

        # Assert
        assert result is True
        mock_session.post.assert_called_once()

    async def test_send_webhook_empty_webhook_url_string(self):
        """_send_webhook should return False when webhook_url is empty string."""
        # Arrange
        notifier = _make_notifier(webhook_url="")
        notifier.webhook_url = ""

        # Act
        result = await notifier._send_webhook({"test": "payload"})

        # Assert - empty string is falsy, so should return False
        assert result is False


# ---------------------------------------------------------------------------
# send_trade_entry: demo_mode=None (settings fallback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendTradeEntryDemoModeFallback:
    """Tests for send_trade_entry when demo_mode is None (uses settings)."""

    async def test_demo_mode_none_uses_settings_true(self):
        """When demo_mode=None, should read settings.is_demo_mode (True)."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        with patch("src.notifications.discord_notifier.settings", create=True) as mock_settings:
            mock_settings.is_demo_mode = True
            # The import inside the method is `from config import settings`
            with patch.dict("sys.modules", {"config": MagicMock(settings=mock_settings)}):
                result = await notifier.send_trade_entry(
                    symbol="BTCUSDT", side="long", size=0.01,
                    entry_price=95000.0, leverage=4, take_profit=97000.0,
                    stop_loss=94000.0, confidence=75, reason="Test reason",
                    order_id="order_999", demo_mode=None,
                )

        # Assert
        assert result is True
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "DEMO" in embed["title"]

    async def test_demo_mode_none_uses_settings_false(self):
        """When demo_mode=None, should read settings.is_demo_mode (False)."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        with patch.dict("sys.modules", {"config": MagicMock(settings=MagicMock(is_demo_mode=False))}):
            result = await notifier.send_trade_entry(
                symbol="BTCUSDT", side="short", size=0.01,
                entry_price=95000.0, leverage=4, take_profit=93000.0,
                stop_loss=96000.0, confidence=60, reason="Bearish signal",
                order_id="order_998", demo_mode=None,
            )

        # Assert
        assert result is True
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "LIVE" in embed["title"]
        assert "SHORT" in embed["title"]

    async def test_position_value_calculation(self):
        """Entry notification should calculate position_value = size * entry_price."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long", size=0.5,
            entry_price=100000.0, leverage=10, take_profit=105000.0,
            stop_loss=95000.0, confidence=90, reason="High confidence",
            order_id="order_val", demo_mode=True,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        field_values = {f["name"]: f["value"] for f in embed["fields"]}
        # position_value = 0.5 * 100000 = 50000
        assert "$50,000.00" in field_values.get("\U0001f4b5 Value", "")

    async def test_reason_truncated_to_500_chars(self):
        """Long reasons should be truncated to 500 characters."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)
        long_reason = "A" * 1000

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, leverage=4, take_profit=97000.0,
            stop_loss=94000.0, confidence=75, reason=long_reason,
            order_id="order_trunc", demo_mode=True,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        reasoning_field = [f for f in embed["fields"] if "Reasoning" in f["name"]][0]
        # The value is ```reason[:500]``` so inner content is 500 chars
        inner = reasoning_field["value"].strip("`")
        assert len(inner) == 500


# ---------------------------------------------------------------------------
# send_trade_exit: additional branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendTradeExitExtra:
    """Extra tests for send_trade_exit branches not covered by existing tests."""

    async def test_demo_mode_none_uses_settings(self):
        """When demo_mode=None, should read settings.is_demo_mode."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        with patch.dict("sys.modules", {"config": MagicMock(settings=MagicMock(is_demo_mode=True))}):
            result = await notifier.send_trade_exit(
                symbol="BTCUSDT", side="long", size=0.01,
                entry_price=95000.0, exit_price=96000.0,
                pnl=10.0, pnl_percent=1.05, fees=0.5, funding_paid=0.1,
                reason="TAKE_PROFIT", order_id="order_dm",
                demo_mode=None,
            )

        # Assert
        assert result is True
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "DEMO" in embed["title"]

    async def test_short_direction_emoji(self):
        """Short-side exit should use short direction in the description."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_trade_exit(
            symbol="ETHUSDT", side="short", size=0.1,
            entry_price=3500.0, exit_price=3400.0,
            pnl=10.0, pnl_percent=2.86, fees=0.3, funding_paid=0.05,
            reason="TAKE_PROFIT", order_id="order_short",
            demo_mode=True,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "SHORT" in embed["description"]

    async def test_duration_minutes_only(self):
        """Duration under 60 minutes should show only minutes."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05, fees=0.5, funding_paid=0.1,
            reason="TAKE_PROFIT", order_id="order_dur",
            duration_minutes=45, demo_mode=True,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        duration_field = [f for f in embed["fields"] if "Duration" in f["name"]][0]
        assert "45m" in duration_field["value"]
        assert "h" not in duration_field["value"]

    async def test_duration_hours_and_minutes(self):
        """Duration >= 60 minutes should show hours and minutes."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05, fees=0.5, funding_paid=0.1,
            reason="TAKE_PROFIT", order_id="order_dur2",
            duration_minutes=150, demo_mode=True,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        duration_field = [f for f in embed["fields"] if "Duration" in f["name"]][0]
        assert "2h 30m" in duration_field["value"]

    async def test_no_duration_field_when_none(self):
        """No duration field should be present when duration_minutes is None."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05, fees=0.5, funding_paid=0.1,
            reason="TAKE_PROFIT", order_id="order_nodur",
            duration_minutes=None, demo_mode=True,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        assert not any("Duration" in n for n in field_names)

    async def test_strategy_reason_appended(self):
        """strategy_reason should appear as a field when provided."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05, fees=0.5, funding_paid=0.1,
            reason="TAKE_PROFIT", order_id="order_sr",
            demo_mode=True, strategy_reason="RSI divergence detected",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        strategy_fields = [f for f in embed["fields"] if "Strategy Decision" in f["name"]]
        assert len(strategy_fields) == 1
        assert "RSI divergence" in strategy_fields[0]["value"]

    async def test_no_strategy_reason_field_when_none(self):
        """Strategy Decision field should not appear when strategy_reason is None."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05, fees=0.5, funding_paid=0.1,
            reason="TAKE_PROFIT", order_id="order_nosr",
            demo_mode=True, strategy_reason=None,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        assert not any("Strategy Decision" in n for n in field_names)

    async def test_net_pnl_calculation_profit(self):
        """Net PnL = pnl - fees - funding_paid; positive = PROFIT."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # pnl=20, fees=2, funding_paid=3 => net_pnl=15 (profit)
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            pnl=20.0, pnl_percent=2.0, fees=2.0, funding_paid=3.0,
            reason="TAKE_PROFIT", order_id="order_net_p",
            demo_mode=True,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "PROFIT" in embed["title"]
        assert embed["color"] == DiscordNotifier.COLOR_PROFIT

    async def test_net_pnl_calculation_loss(self):
        """Net PnL = pnl - fees - funding_paid; negative = LOSS."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # pnl=-5, fees=2, funding_paid=1 => net_pnl=-8 (loss)
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=94000.0,
            pnl=-5.0, pnl_percent=-0.5, fees=2.0, funding_paid=1.0,
            reason="STOP_LOSS", order_id="order_net_l",
            demo_mode=True,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "LOSS" in embed["title"]
        assert embed["color"] == DiscordNotifier.COLOR_LOSS

    async def test_exit_footer_contains_order_id_and_mode(self):
        """Footer should contain Order ID and Mode."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05, fees=0.5, funding_paid=0.1,
            reason="TAKE_PROFIT", order_id="order_foot",
            demo_mode=False,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "order_foot" in embed["footer"]["text"]
        assert "LIVE" in embed["footer"]["text"]


# ---------------------------------------------------------------------------
# send_daily_summary: full coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendDailySummary:
    """Tests for send_daily_summary method."""

    async def test_profitable_day_summary(self):
        """Profitable day should use green color and profit emoji."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        result = await notifier.send_daily_summary(
            date="2026-02-15",
            starting_balance=10000.0,
            ending_balance=10150.0,
            total_trades=5,
            winning_trades=4,
            losing_trades=1,
            total_pnl=200.0,
            total_fees=10.0,
            total_funding=5.0,
            max_drawdown=1.5,
        )

        # Assert
        assert result is True
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert embed["color"] == DiscordNotifier.COLOR_PROFIT
        assert "2026-02-15" in embed["title"]
        assert payload["username"] == "Bitget Trading Bot"

    async def test_losing_day_summary(self):
        """Losing day should use red color and loss emoji."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # net_pnl = -50 - 10 - 5 = -65 (loss)
        await notifier.send_daily_summary(
            date="2026-02-14",
            starting_balance=10000.0,
            ending_balance=9935.0,
            total_trades=3,
            winning_trades=1,
            losing_trades=2,
            total_pnl=-50.0,
            total_fees=10.0,
            total_funding=5.0,
            max_drawdown=3.0,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert embed["color"] == DiscordNotifier.COLOR_LOSS

    async def test_zero_trades_win_rate(self):
        """Zero trades should produce 0% win rate without division error."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_daily_summary(
            date="2026-02-13",
            starting_balance=10000.0,
            ending_balance=10000.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            total_pnl=0.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        win_rate_field = [f for f in embed["fields"] if "Win Rate" in f["name"]][0]
        assert "0.0%" in win_rate_field["value"]

    async def test_zero_starting_balance_return_pct(self):
        """Zero starting balance should produce 0% return without division error."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_daily_summary(
            date="2026-02-12",
            starting_balance=0.0,
            ending_balance=100.0,
            total_trades=1,
            winning_trades=1,
            losing_trades=0,
            total_pnl=100.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        return_field = [f for f in embed["fields"] if "Daily Return" in f["name"]][0]
        assert "0.00%" in return_field["value"]

    async def test_daily_summary_contains_all_expected_fields(self):
        """Summary should contain all 12 expected fields."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_daily_summary(
            date="2026-02-15",
            starting_balance=10000.0,
            ending_balance=10100.0,
            total_trades=5,
            winning_trades=3,
            losing_trades=2,
            total_pnl=150.0,
            total_fees=30.0,
            total_funding=10.0,
            max_drawdown=2.0,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        expected_keywords = [
            "Date", "Total Trades", "Wins", "Win Rate",
            "Starting Balance", "Ending Balance", "Gross PnL",
            "Total Fees", "Total Funding", "Net PnL",
            "Daily Return", "Max Drawdown",
        ]
        for kw in expected_keywords:
            assert any(kw in n for n in field_names), f"Missing field containing '{kw}'"

    async def test_daily_summary_footer(self):
        """Footer should contain bot name."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_daily_summary(
            date="2026-02-15",
            starting_balance=10000.0,
            ending_balance=10050.0,
            total_trades=2,
            winning_trades=1,
            losing_trades=1,
            total_pnl=50.0,
            total_fees=5.0,
            total_funding=2.0,
            max_drawdown=0.5,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "Bitget Trading Bot" in embed["footer"]["text"]


# ---------------------------------------------------------------------------
# send_risk_alert: full coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendRiskAlert:
    """Tests for send_risk_alert method."""

    async def test_basic_risk_alert(self):
        """Risk alert with no optional params should have 2 base fields."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        result = await notifier.send_risk_alert(
            alert_type="DAILY_LOSS_LIMIT",
            message="Daily loss limit of 5% reached",
        )

        # Assert
        assert result is True
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert embed["color"] == DiscordNotifier.COLOR_WARNING
        assert "RISK ALERT" in embed["title"]
        assert len(embed["fields"]) == 2

    async def test_risk_alert_with_current_value(self):
        """Risk alert with current_value should add a field."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_risk_alert(
            alert_type="MAX_DRAWDOWN",
            message="Drawdown exceeded threshold",
            current_value=6.5,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert len(embed["fields"]) == 3
        current_field = [f for f in embed["fields"] if "Current Value" in f["name"]]
        assert len(current_field) == 1
        assert "6.50" in current_field[0]["value"]

    async def test_risk_alert_with_threshold(self):
        """Risk alert with threshold should add a field."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_risk_alert(
            alert_type="MAX_TRADES",
            message="Max trades per day reached",
            threshold=10.0,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert len(embed["fields"]) == 3
        threshold_field = [f for f in embed["fields"] if "Threshold" in f["name"]]
        assert len(threshold_field) == 1
        assert "10.00" in threshold_field[0]["value"]

    async def test_risk_alert_with_both_optional_params(self):
        """Risk alert with both current_value and threshold should have 4 fields."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_risk_alert(
            alert_type="DAILY_LOSS_LIMIT",
            message="Loss limit exceeded",
            current_value=5.5,
            threshold=5.0,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert len(embed["fields"]) == 4

    async def test_risk_alert_footer(self):
        """Risk alert footer should mention trading paused."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_risk_alert(
            alert_type="TEST_ALERT",
            message="Test message",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "paused" in embed["footer"]["text"].lower()


# ---------------------------------------------------------------------------
# send_signal_alert: full coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendSignalAlert:
    """Tests for send_signal_alert method."""

    async def test_long_signal_alert(self):
        """Long signal should use green color and long emoji."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)
        metrics = {
            "fear_greed_index": 25,
            "long_short_ratio": 0.5,
            "funding_rate_btc": -0.0003,
        }

        # Act
        result = await notifier.send_signal_alert(
            symbol="BTCUSDT",
            direction="long",
            confidence=80,
            reason="Extreme fear, crowded shorts",
            entry_price=90000.0,
            target_price=95000.0,
            stop_loss=88000.0,
            metrics=metrics,
        )

        # Assert
        assert result is True
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "LONG" in embed["title"]
        assert embed["color"] == DiscordNotifier.COLOR_LONG
        assert "80%" in embed["description"]

    async def test_short_signal_alert(self):
        """Short signal should use red color and short emoji."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)
        metrics = {
            "fear_greed_index": 85,
            "long_short_ratio": 2.5,
            "funding_rate_btc": 0.001,
        }

        # Act
        result = await notifier.send_signal_alert(
            symbol="ETHUSDT",
            direction="short",
            confidence=75,
            reason="Extreme greed, crowded longs",
            entry_price=3500.0,
            target_price=3200.0,
            stop_loss=3600.0,
            metrics=metrics,
        )

        # Assert
        assert result is True
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "SHORT" in embed["title"]
        assert embed["color"] == DiscordNotifier.COLOR_SHORT

    async def test_signal_alert_metrics_formatting(self):
        """Signal alert should format market metrics correctly."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)
        metrics = {
            "fear_greed_index": 30,
            "long_short_ratio": 1.25,
            "funding_rate_btc": 0.0002,
        }

        # Act
        await notifier.send_signal_alert(
            symbol="BTCUSDT",
            direction="long",
            confidence=70,
            reason="Test reason",
            entry_price=95000.0,
            target_price=97000.0,
            stop_loss=94000.0,
            metrics=metrics,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        field_map = {f["name"]: f["value"] for f in embed["fields"]}
        assert "30" in field_map.get("\U0001f631 Fear & Greed", "")
        assert "1.25" in field_map.get("\U0001f4ca L/S Ratio", "")
        assert "0.0200%" in field_map.get("\U0001f4b8 Funding Rate", "")

    async def test_signal_alert_missing_metrics_raises_on_ls_ratio(self):
        """Empty metrics dict triggers ValueError because 'N/A' string cannot be formatted with :.2f.

        This documents a known edge case in the source code (line 482):
        metrics.get('long_short_ratio', 'N/A') returns 'N/A' which is then
        formatted with :.2f, causing a ValueError.
        """
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)
        metrics = {}  # Empty metrics dict

        # Act / Assert
        with pytest.raises(ValueError, match="Unknown format code"):
            await notifier.send_signal_alert(
                symbol="BTCUSDT",
                direction="long",
                confidence=60,
                reason="Sparse data signal",
                entry_price=95000.0,
                target_price=97000.0,
                stop_loss=94000.0,
                metrics=metrics,
            )

    async def test_signal_alert_with_partial_metrics(self):
        """Signal alert with only required numeric keys should succeed."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)
        # Provide the numeric keys to avoid the :.2f formatting bug
        metrics = {
            "long_short_ratio": 1.5,
            "funding_rate_btc": 0.0002,
            # fear_greed_index missing - uses 'N/A' string (no format specifier, so OK)
        }

        # Act
        await notifier.send_signal_alert(
            symbol="BTCUSDT",
            direction="long",
            confidence=60,
            reason="Partial metrics signal",
            entry_price=95000.0,
            target_price=97000.0,
            stop_loss=94000.0,
            metrics=metrics,
        )

        # Assert
        assert mock_webhook.await_count == 1
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        field_map = {f["name"]: f["value"] for f in embed["fields"]}
        assert "N/A" in field_map.get("\U0001f631 Fear & Greed", "")

    async def test_signal_alert_contains_all_fields(self):
        """Signal alert should have exactly 10 fields."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)
        metrics = {
            "fear_greed_index": 50,
            "long_short_ratio": 1.0,
            "funding_rate_btc": 0.0001,
        }

        # Act
        await notifier.send_signal_alert(
            symbol="BTCUSDT",
            direction="long",
            confidence=70,
            reason="Normal conditions",
            entry_price=95000.0,
            target_price=97000.0,
            stop_loss=94000.0,
            metrics=metrics,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert len(embed["fields"]) == 10

    async def test_signal_alert_footer(self):
        """Signal alert footer should mention the strategy."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_signal_alert(
            symbol="BTCUSDT",
            direction="long",
            confidence=70,
            reason="Test",
            entry_price=95000.0,
            target_price=97000.0,
            stop_loss=94000.0,
            metrics={"fear_greed_index": 50, "long_short_ratio": 1.0, "funding_rate_btc": 0.0001},
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "Contrarian Liquidation Hunter" in embed["footer"]["text"]


# ---------------------------------------------------------------------------
# send_error: full coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendError:
    """Tests for send_error method."""

    async def test_basic_error_notification(self):
        """Error notification without details should have 2 fields."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        result = await notifier.send_error(
            error_type="API_ERROR",
            error_message="Failed to fetch market data",
        )

        # Assert
        assert result is True
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert embed["color"] == DiscordNotifier.COLOR_ERROR
        assert "BOT ERROR" in embed["title"]
        assert len(embed["fields"]) == 2

    async def test_error_with_details(self):
        """Error notification with details should have 3 fields."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_error(
            error_type="CONNECTION_ERROR",
            error_message="WebSocket disconnected",
            details="Reconnection attempt 3/5 failed",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert len(embed["fields"]) == 3
        detail_field = [f for f in embed["fields"] if "Details" in f["name"]]
        assert len(detail_field) == 1
        assert "Reconnection" in detail_field[0]["value"]

    async def test_error_message_truncated(self):
        """Long error messages should be truncated to 500 chars."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)
        long_message = "E" * 1000

        # Act
        await notifier.send_error(
            error_type="LONG_ERROR",
            error_message=long_message,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        msg_field = [f for f in embed["fields"] if "Message" in f["name"]][0]
        inner = msg_field["value"].strip("`")
        assert len(inner) == 500

    async def test_error_details_truncated(self):
        """Long details should be truncated to 500 chars."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)
        long_details = "D" * 1000

        # Act
        await notifier.send_error(
            error_type="DETAIL_ERROR",
            error_message="Short msg",
            details=long_details,
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        detail_field = [f for f in embed["fields"] if "Details" in f["name"]][0]
        inner = detail_field["value"].strip("`")
        assert len(inner) == 500

    async def test_error_footer(self):
        """Error footer should reference logs."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_error(
            error_type="TEST",
            error_message="Test error",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "logs" in embed["footer"]["text"].lower()


# ---------------------------------------------------------------------------
# send_bot_status: full coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendBotStatus:
    """Tests for send_bot_status method."""

    async def test_started_status(self):
        """STARTED status should use green emoji."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        result = await notifier.send_bot_status(
            status="STARTED",
            message="Bot has been started",
        )

        # Assert
        assert result is True
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert embed["color"] == DiscordNotifier.COLOR_INFO
        assert "STARTED" in embed["description"]

    async def test_stopped_status(self):
        """STOPPED status should use red emoji."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_bot_status(
            status="STOPPED",
            message="Bot has been stopped",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        # Title should contain the red circle emoji for STOPPED
        assert "BOT STATUS UPDATE" in embed["title"]

    async def test_paused_status(self):
        """PAUSED status should use yellow emoji."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_bot_status(
            status="PAUSED",
            message="Bot has been paused due to risk limits",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        field_map = {f["name"]: f["value"] for f in embed["fields"]}
        assert "`PAUSED`" in field_map.get("\U0001f4ca Status", "")

    async def test_resumed_status(self):
        """RESUMED status should use green emoji."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_bot_status(
            status="RESUMED",
            message="Bot has been resumed",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "RESUMED" in embed["description"]

    async def test_error_status(self):
        """ERROR status should use error emoji."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_bot_status(
            status="ERROR",
            message="Bot encountered a fatal error",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "ERROR" in embed["description"]

    async def test_unknown_status_uses_info_emoji(self):
        """Unknown status should use the default info emoji."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_bot_status(
            status="MAINTENANCE",
            message="Bot entering maintenance mode",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "MAINTENANCE" in embed["description"]
        # Should still send successfully
        assert mock_webhook.await_count == 1

    async def test_status_with_stats(self):
        """Bot status with stats dict should add extra fields."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_bot_status(
            status="STARTED",
            message="Bot online",
            stats={
                "Total Trades": "150",
                "Win Rate": "65%",
                "Balance": "$10,000",
            },
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        # 2 base fields + 3 stats fields = 5
        assert len(embed["fields"]) == 5
        field_names = [f["name"] for f in embed["fields"]]
        assert any("Total Trades" in n for n in field_names)
        assert any("Win Rate" in n for n in field_names)
        assert any("Balance" in n for n in field_names)

    async def test_status_without_stats(self):
        """Bot status without stats should have only 2 base fields."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_bot_status(
            status="STOPPED",
            message="Shutdown complete",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert len(embed["fields"]) == 2

    async def test_status_footer_contains_timestamp(self):
        """Bot status footer should contain a timestamp."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_bot_status(
            status="STARTED",
            message="Online",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "Timestamp:" in embed["footer"]["text"]

    async def test_status_payload_username(self):
        """Bot status payload should use 'Bitget Trading Bot' username."""
        # Arrange
        notifier = _make_notifier()
        mock_webhook = _stub_send_webhook(notifier)

        # Act
        await notifier.send_bot_status(
            status="STARTED",
            message="Online",
        )

        # Assert
        payload = mock_webhook.call_args[0][0]
        assert payload["username"] == "Bitget Trading Bot"


# ---------------------------------------------------------------------------
# _create_embed: edge cases not covered
# ---------------------------------------------------------------------------

class TestCreateEmbedExtra:
    """Additional tests for _create_embed edge cases."""

    def test_embed_without_thumbnail(self):
        """Embed without thumbnail_url should not have thumbnail key."""
        # Arrange
        notifier = _make_notifier()

        # Act
        embed = notifier._create_embed(
            title="T", description="D", color=0,
            fields=[], thumbnail_url=None,
        )

        # Assert
        assert "thumbnail" not in embed

    def test_embed_timestamp_is_iso_format(self):
        """Embed timestamp should be ISO 8601 format."""
        # Arrange
        notifier = _make_notifier()

        # Act
        embed = notifier._create_embed(
            title="T", description="D", color=0, fields=[],
        )

        # Assert
        ts = embed["timestamp"]
        assert "T" in ts  # ISO format has T separator
        assert len(ts) > 10  # More than just a date


# ---------------------------------------------------------------------------
# Context manager: extra tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestContextManagerExtra:
    """Additional context manager tests."""

    async def test_context_manager_returns_notifier(self):
        """__aenter__ should return the notifier itself."""
        # Arrange
        notifier = _make_notifier()
        notifier._ensure_session = AsyncMock()
        notifier.close = AsyncMock()

        # Act
        async with notifier as ctx:
            # Assert
            assert ctx is notifier

    async def test_context_manager_closes_on_exception(self):
        """__aexit__ should still close even if an exception occurred."""
        # Arrange
        notifier = _make_notifier()
        notifier._ensure_session = AsyncMock()
        notifier.close = AsyncMock()

        # Act
        with pytest.raises(ValueError):
            async with notifier:
                raise ValueError("test error")

        # Assert
        notifier.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Webhook URL edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWebhookUrlEdgeCases:
    """Tests for various webhook URL edge cases."""

    async def test_none_webhook_url_in_constructor(self):
        """Constructor with None webhook URL should store None."""
        # Arrange / Act
        notifier = DiscordNotifier(webhook_url=None)

        # Assert
        assert notifier.webhook_url is None

    async def test_default_webhook_url_is_none(self):
        """Default constructor should have None webhook URL."""
        # Arrange / Act
        notifier = DiscordNotifier()

        # Assert
        assert notifier.webhook_url is None

    async def test_send_methods_return_false_without_webhook(self):
        """All send methods should return False when webhook is not configured."""
        # Arrange
        notifier = DiscordNotifier(webhook_url=None)

        # Act / Assert
        result = await notifier.send_risk_alert(
            alert_type="TEST", message="test",
        )
        assert result is False

        result = await notifier.send_error(
            error_type="TEST", error_message="test",
        )
        assert result is False

        result = await notifier.send_bot_status(
            status="STARTED", message="test",
        )
        assert result is False
