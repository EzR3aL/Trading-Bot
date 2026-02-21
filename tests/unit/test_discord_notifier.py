"""
Unit tests for the Discord Notifier.

Tests cover:
- Webhook payload construction
- Embed formatting (trade entry, trade exit)
- Session management (context manager)
- Error handling (network failures, missing webhook URL)
- Color codes for different trade directions
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_notifier(webhook_url="https://discord.com/api/webhooks/test/token"):
    """Create a DiscordNotifier directly (no module-level settings to mock)."""
    from src.notifications.discord_notifier import DiscordNotifier
    return DiscordNotifier(webhook_url=webhook_url)


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

class TestDiscordNotifierInit:
    """Tests for DiscordNotifier initialization."""

    def test_uses_provided_webhook_url(self):
        notifier = _make_notifier("https://discord.com/api/webhooks/123/abc")
        assert notifier.webhook_url == "https://discord.com/api/webhooks/123/abc"

    def test_session_starts_none(self):
        notifier = _make_notifier()
        assert notifier._session is None


# ---------------------------------------------------------------------------
# Embed creation tests
# ---------------------------------------------------------------------------

class TestCreateEmbed:
    """Tests for _create_embed helper."""

    def test_embed_has_required_fields(self):
        notifier = _make_notifier()
        embed = notifier._create_embed(
            title="Test Title",
            description="Test Description",
            color=0x00FF00,
            fields=[],
        )
        assert embed["title"] == "Test Title"
        assert embed["description"] == "Test Description"
        assert embed["color"] == 0x00FF00
        assert "timestamp" in embed

    def test_embed_with_footer(self):
        notifier = _make_notifier()
        embed = notifier._create_embed(
            title="T", description="D", color=0, fields=[],
            footer="Some footer",
        )
        assert embed["footer"]["text"] == "Some footer"

    def test_embed_without_footer(self):
        notifier = _make_notifier()
        embed = notifier._create_embed(
            title="T", description="D", color=0, fields=[],
        )
        assert "footer" not in embed

    def test_embed_with_thumbnail(self):
        notifier = _make_notifier()
        embed = notifier._create_embed(
            title="T", description="D", color=0, fields=[],
            thumbnail_url="https://example.com/image.png",
        )
        assert embed["thumbnail"]["url"] == "https://example.com/image.png"

    def test_embed_with_fields(self):
        notifier = _make_notifier()
        fields = [
            {"name": "Field1", "value": "Value1", "inline": True},
            {"name": "Field2", "value": "Value2", "inline": False},
        ]
        embed = notifier._create_embed(
            title="T", description="D", color=0, fields=fields,
        )
        assert len(embed["fields"]) == 2
        assert embed["fields"][0]["name"] == "Field1"


# ---------------------------------------------------------------------------
# Webhook sending tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendWebhook:
    """Tests for _send_webhook method."""

    async def test_returns_false_when_no_webhook_url(self):
        notifier = _make_notifier(webhook_url=None)
        notifier.webhook_url = None
        result = await notifier._send_webhook({"test": "payload"})
        assert result is False

    async def test_returns_true_on_204_response(self):
        notifier = _make_notifier()
        mock_response = AsyncMock()
        mock_response.status = 204
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post.return_value = mock_response

        notifier._session = mock_session

        result = await notifier._send_webhook({"test": "data"})
        assert result is True

    async def test_returns_false_on_error_response(self):
        notifier = _make_notifier()
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        notifier._session = mock_session

        result = await notifier._send_webhook({"test": "data"})
        assert result is False

    async def test_returns_false_on_network_error(self):
        notifier = _make_notifier()
        mock_session = AsyncMock()
        mock_session.post.side_effect = Exception("Connection refused")

        notifier._session = mock_session

        result = await notifier._send_webhook({"test": "data"})
        assert result is False


# ---------------------------------------------------------------------------
# Trade entry notification tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendTradeEntry:
    """Tests for send_trade_entry method."""

    async def test_sends_long_trade_entry(self):
        notifier = _make_notifier()
        notifier._send_webhook = AsyncMock(return_value=True)

        result = await notifier.send_trade_entry(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            take_profit=97000.0,
            stop_loss=94000.0,
            confidence=75,
            reason="Strong bullish signal",
            order_id="order_123",
            demo_mode=True,
        )

        assert result is True
        notifier._send_webhook.assert_awaited_once()

        payload = notifier._send_webhook.call_args[0][0]
        assert "embeds" in payload
        embed = payload["embeds"][0]
        assert "LONG" in embed["title"]
        assert "BTCUSDT" in embed["title"]
        assert "DEMO" in embed["title"]
        assert embed["color"] == notifier.COLOR_LONG

    async def test_sends_short_trade_entry(self):
        notifier = _make_notifier()
        notifier._send_webhook = AsyncMock(return_value=True)

        await notifier.send_trade_entry(
            symbol="ETHUSDT",
            side="short",
            size=0.5,
            entry_price=3500.0,
            leverage=10,
            take_profit=3300.0,
            stop_loss=3600.0,
            confidence=80,
            reason="Bearish signal",
            order_id="order_456",
            demo_mode=False,
        )

        payload = notifier._send_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert "SHORT" in embed["title"]
        assert "LIVE" in embed["title"]
        assert embed["color"] == notifier.COLOR_SHORT

    async def test_entry_contains_required_fields(self):
        notifier = _make_notifier()
        notifier._send_webhook = AsyncMock(return_value=True)

        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, leverage=4, take_profit=97000.0,
            stop_loss=94000.0, confidence=75, reason="Test",
            order_id="order_789", demo_mode=True,
        )

        payload = notifier._send_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]

        assert any("Mode" in n for n in field_names)
        assert any("Asset" in n for n in field_names)
        assert any("Entry Price" in n for n in field_names)
        assert any("Leverage" in n for n in field_names)
        assert any("Take Profit" in n for n in field_names)
        assert any("Stop Loss" in n for n in field_names)
        assert any("Confidence" in n for n in field_names)


# ---------------------------------------------------------------------------
# Trade exit notification tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendTradeExit:
    """Tests for send_trade_exit method."""

    async def test_sends_profitable_exit(self):
        notifier = _make_notifier()
        notifier._send_webhook = AsyncMock(return_value=True)

        result = await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            fees=0.5, funding_paid=0.1,
            reason="TAKE_PROFIT", order_id="order_123",
            duration_minutes=120, demo_mode=True,
        )

        assert result is True
        notifier._send_webhook.assert_awaited_once()

        payload = notifier._send_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert embed["color"] == notifier.COLOR_PROFIT

    async def test_sends_losing_exit(self):
        notifier = _make_notifier()
        notifier._send_webhook = AsyncMock(return_value=True)

        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=94000.0,
            pnl=-10.0, pnl_percent=-1.05,
            fees=0.5, funding_paid=0.1,
            reason="STOP_LOSS", order_id="order_456",
            demo_mode=False,
        )

        payload = notifier._send_webhook.call_args[0][0]
        embed = payload["embeds"][0]
        assert embed["color"] == notifier.COLOR_LOSS


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestContextManager:
    """Tests for async context manager behavior."""

    async def test_context_manager_creates_and_closes_session(self):
        notifier = _make_notifier()
        notifier._ensure_session = AsyncMock()
        notifier.close = AsyncMock()

        async with notifier:
            notifier._ensure_session.assert_awaited_once()

        notifier.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Color constant tests
# ---------------------------------------------------------------------------

class TestColorConstants:
    """Tests for embed color constants."""

    def test_long_color_is_green(self):
        notifier = _make_notifier()
        assert notifier.COLOR_LONG == 0x00FF00

    def test_short_color_is_red(self):
        notifier = _make_notifier()
        assert notifier.COLOR_SHORT == 0xFF0000

    def test_info_color_is_blue(self):
        notifier = _make_notifier()
        assert notifier.COLOR_INFO == 0x0099FF
