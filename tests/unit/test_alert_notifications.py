"""
Unit tests for alert notification formatting (Discord + Telegram).

Tests cover:
- Discord send_alert() embed construction
- Telegram send_alert() HTML message formatting
- Different alert types (price, strategy, portfolio)
- Symbol presence/absence
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_discord_notifier(webhook_url="https://discord.com/api/webhooks/test/token"):
    from src.notifications.discord_notifier import DiscordNotifier
    return DiscordNotifier(webhook_url=webhook_url)


def _make_telegram_notifier():
    from src.notifications.telegram_notifier import TelegramNotifier
    return TelegramNotifier(bot_token="test-token", chat_id="12345")


# ---------------------------------------------------------------------------
# Discord alert notification tests
# ---------------------------------------------------------------------------

class TestDiscordAlertNotification:
    """Tests for DiscordNotifier.send_alert()."""

    @pytest.mark.asyncio
    async def test_send_alert_constructs_embed(self):
        """send_alert builds a payload with the correct embed fields."""
        notifier = _make_discord_notifier()

        captured_payload = {}

        async def mock_send(payload):
            captured_payload.update(payload)
            return True

        notifier._send_webhook = mock_send

        result = await notifier.send_alert(
            alert_type="price",
            symbol="BTCUSDT",
            current_value=95000.0,
            threshold=90000.0,
            message="BTC price is $95,000 (above threshold $90,000)",
        )

        assert result is True
        assert "embeds" in captured_payload
        embed = captured_payload["embeds"][0]
        assert "PRICE" in embed["title"]
        assert embed["color"] == notifier.COLOR_ALERT

    @pytest.mark.asyncio
    async def test_send_alert_price_type_emoji(self):
        """Price alerts use the money emoji."""
        notifier = _make_discord_notifier()
        captured = {}

        async def mock_send(payload):
            captured.update(payload)
            return True

        notifier._send_webhook = mock_send

        await notifier.send_alert(
            alert_type="price",
            symbol="ETHUSDT",
            current_value=3500.0,
            threshold=3000.0,
            message="Test",
        )

        # Title should contain the money emoji for price alerts
        embed = captured["embeds"][0]
        assert "\U0001f4b0" in embed["title"] or "PRICE" in embed["title"]

    @pytest.mark.asyncio
    async def test_send_alert_strategy_type(self):
        """Strategy alerts use the brain emoji."""
        notifier = _make_discord_notifier()
        captured = {}

        async def mock_send(payload):
            captured.update(payload)
            return True

        notifier._send_webhook = mock_send

        await notifier.send_alert(
            alert_type="strategy",
            symbol=None,
            current_value=3.0,
            threshold=3.0,
            message="3 consecutive losses",
        )

        embed = captured["embeds"][0]
        assert "STRATEGY" in embed["title"]

    @pytest.mark.asyncio
    async def test_send_alert_portfolio_type(self):
        """Portfolio alerts use the chart emoji."""
        notifier = _make_discord_notifier()
        captured = {}

        async def mock_send(payload):
            captured.update(payload)
            return True

        notifier._send_webhook = mock_send

        await notifier.send_alert(
            alert_type="portfolio",
            symbol=None,
            current_value=5.0,
            threshold=3.0,
            message="Daily loss exceeds 3%",
        )

        embed = captured["embeds"][0]
        assert "PORTFOLIO" in embed["title"]

    @pytest.mark.asyncio
    async def test_send_alert_without_symbol(self):
        """When symbol is None, no symbol field is in the embed."""
        notifier = _make_discord_notifier()
        captured = {}

        async def mock_send(payload):
            captured.update(payload)
            return True

        notifier._send_webhook = mock_send

        await notifier.send_alert(
            alert_type="portfolio",
            symbol=None,
            current_value=5.0,
            threshold=3.0,
            message="Test",
        )

        embed = captured["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        # Symbol field should not be present when symbol is None
        symbol_fields = [n for n in field_names if "Symbol" in n]
        assert len(symbol_fields) == 0

    @pytest.mark.asyncio
    async def test_send_alert_with_symbol(self):
        """When symbol is set, a symbol field appears in the embed."""
        notifier = _make_discord_notifier()
        captured = {}

        async def mock_send(payload):
            captured.update(payload)
            return True

        notifier._send_webhook = mock_send

        await notifier.send_alert(
            alert_type="price",
            symbol="BTCUSDT",
            current_value=95000.0,
            threshold=90000.0,
            message="Test",
        )

        embed = captured["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        symbol_fields = [n for n in field_names if "Symbol" in n]
        assert len(symbol_fields) == 1

    @pytest.mark.asyncio
    async def test_color_is_alert_orange(self):
        """Alert embeds use the COLOR_ALERT (orange) color."""
        from src.notifications.discord_notifier import DiscordNotifier
        assert DiscordNotifier.COLOR_ALERT == 0xFF6600


# ---------------------------------------------------------------------------
# Telegram alert notification tests
# ---------------------------------------------------------------------------

class TestTelegramAlertNotification:
    """Tests for TelegramNotifier.send_alert()."""

    @pytest.mark.asyncio
    async def test_send_alert_calls_send_message(self):
        """send_alert composes and sends an HTML message."""
        notifier = _make_telegram_notifier()

        captured_text = []

        async def mock_send(text, parse_mode="HTML"):
            captured_text.append(text)
            return True

        notifier._send_message = mock_send

        result = await notifier.send_alert(
            alert_type="price",
            symbol="BTCUSDT",
            current_value=95000.0,
            threshold=90000.0,
            message="BTC price above threshold",
        )

        assert result is True
        assert len(captured_text) == 1
        text = captured_text[0]
        assert "PRICE" in text
        assert "BTCUSDT" in text

    @pytest.mark.asyncio
    async def test_send_alert_strategy_no_symbol(self):
        """Strategy alert without symbol omits the symbol line."""
        notifier = _make_telegram_notifier()
        captured = []

        async def mock_send(text, parse_mode="HTML"):
            captured.append(text)
            return True

        notifier._send_message = mock_send

        await notifier.send_alert(
            alert_type="strategy",
            symbol=None,
            current_value=3.0,
            threshold=3.0,
            message="Consecutive losses",
        )

        text = captured[0]
        assert "STRATEGY" in text
        # "Symbol:" line should not be present
        assert "Symbol:" not in text

    @pytest.mark.asyncio
    async def test_send_alert_includes_threshold(self):
        """Message includes both current value and threshold."""
        notifier = _make_telegram_notifier()
        captured = []

        async def mock_send(text, parse_mode="HTML"):
            captured.append(text)
            return True

        notifier._send_message = mock_send

        await notifier.send_alert(
            alert_type="portfolio",
            symbol=None,
            current_value=5.5,
            threshold=3.0,
            message="Loss exceeded",
        )

        text = captured[0]
        assert "5.50" in text
        assert "3.00" in text

    @pytest.mark.asyncio
    async def test_send_alert_portfolio_emoji(self):
        """Portfolio alerts use the chart emoji."""
        notifier = _make_telegram_notifier()
        captured = []

        async def mock_send(text, parse_mode="HTML"):
            captured.append(text)
            return True

        notifier._send_message = mock_send

        await notifier.send_alert(
            alert_type="portfolio",
            symbol=None,
            current_value=5.0,
            threshold=3.0,
            message="Test",
        )

        text = captured[0]
        # Chart emoji for portfolio
        assert "\U0001f4ca" in text
