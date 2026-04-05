"""
Unit tests for the WhatsApp Notifier.

Tests cover:
- Initialization and configuration
- Message payload construction
- Session management (context manager, _ensure_session)
- API response handling (success, errors, retries)
- All notification methods
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.notifications.whatsapp_notifier import WhatsAppNotifier, WHATSAPP_API_BASE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def notifier():
    """Create a WhatsAppNotifier with test credentials."""
    return WhatsAppNotifier(
        phone_number_id="123456789",
        access_token="test-access-token",
        recipient_number="491701234567",
    )


def _mock_response(status=200, json_data=None, text=""):
    """Create a mock aiohttp response."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.text = AsyncMock(return_value=text)
    mock_resp.json = AsyncMock(return_value=json_data or {})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

class TestWhatsAppNotifierInit:
    """Tests for WhatsAppNotifier initialization."""

    def test_stores_credentials(self):
        notifier = WhatsAppNotifier(
            phone_number_id="111",
            access_token="token",
            recipient_number="491701234567",
        )
        assert notifier.phone_number_id == "111"
        assert notifier.access_token == "token"
        assert notifier.recipient_number == "491701234567"

    def test_api_url_includes_phone_number_id(self):
        notifier = WhatsAppNotifier(
            phone_number_id="999",
            access_token="token",
            recipient_number="491701234567",
        )
        assert "999" in notifier._api_url
        assert notifier._api_url == WHATSAPP_API_BASE.format(phone_number_id="999")

    def test_session_starts_none(self):
        notifier = WhatsAppNotifier(
            phone_number_id="111",
            access_token="token",
            recipient_number="491701234567",
        )
        assert notifier._session is None


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------

class TestContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_aenter_creates_session(self, notifier):
        with patch("src.notifications.whatsapp_notifier.aiohttp.ClientSession") as mock_cls:
            mock_session = MagicMock()
            mock_cls.return_value = mock_session
            result = await notifier.__aenter__()
            assert result is notifier
            assert notifier._session is mock_session

    @pytest.mark.asyncio
    async def test_aexit_closes_session(self, notifier):
        mock_session = AsyncMock()
        mock_session.closed = False
        notifier._session = mock_session
        await notifier.__aexit__(None, None, None)
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aexit_does_nothing_if_no_session(self, notifier):
        notifier._session = None
        await notifier.__aexit__(None, None, None)  # Should not raise


# ---------------------------------------------------------------------------
# _ensure_session tests
# ---------------------------------------------------------------------------

class TestEnsureSession:
    """Tests for _ensure_session."""

    @pytest.mark.asyncio
    async def test_creates_session_if_none(self, notifier):
        assert notifier._session is None
        with patch("src.notifications.whatsapp_notifier.aiohttp.ClientSession") as mock_cls:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_cls.return_value = mock_session
            await notifier._ensure_session()
            assert notifier._session is mock_session

    @pytest.mark.asyncio
    async def test_does_nothing_if_session_exists(self, notifier):
        existing_session = MagicMock()
        existing_session.closed = False
        notifier._session = existing_session
        await notifier._ensure_session()
        assert notifier._session is existing_session


# ---------------------------------------------------------------------------
# _send_message tests
# ---------------------------------------------------------------------------

class TestSendMessage:
    """Tests for _send_message."""

    @pytest.mark.asyncio
    async def test_successful_send_returns_true(self, notifier):
        mock_resp = _mock_response(status=200)
        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.closed = False
        notifier._session = mock_session

        result = await notifier._send_message("Hello")
        assert result is True

    @pytest.mark.asyncio
    async def test_client_error_returns_false(self, notifier):
        mock_resp = _mock_response(status=400, text="Bad request")
        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.closed = False
        notifier._session = mock_session

        result = await notifier._send_message("Hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_payload_structure(self, notifier):
        mock_resp = _mock_response(status=200)
        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.closed = False
        notifier._session = mock_session

        await notifier._send_message("Test message")

        call_kwargs = mock_session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["messaging_product"] == "whatsapp"
        assert payload["to"] == "491701234567"
        assert payload["type"] == "text"
        assert payload["text"]["body"] == "Test message"


# ---------------------------------------------------------------------------
# Notification method tests
# ---------------------------------------------------------------------------

class TestNotificationMethods:
    """Tests for all notification methods."""

    @pytest.fixture(autouse=True)
    def setup_notifier(self, notifier):
        """Mock _send_message for all notification method tests."""
        self.notifier = notifier
        self.notifier._send_message = AsyncMock(return_value=True)

    @pytest.mark.asyncio
    async def test_send_trade_entry_long(self):
        result = await self.notifier.send_trade_entry(
            symbol="BTCUSDT",
            side="long",
            entry_price=95000.0,
            size=0.1,
            leverage=10,
            strategy="LLM Signal",
        )
        assert result is True
        msg = self.notifier._send_message.call_args[0][0]
        assert "BTCUSDT" in msg
        assert "LONG" in msg
        assert "95000" in msg

    @pytest.mark.asyncio
    async def test_send_trade_entry_short(self):
        result = await self.notifier.send_trade_entry(
            symbol="ETHUSDT",
            side="short",
            entry_price=3500.0,
            size=1.0,
        )
        assert result is True
        msg = self.notifier._send_message.call_args[0][0]
        assert "SHORT" in msg

    @pytest.mark.asyncio
    async def test_send_trade_exit(self):
        result = await self.notifier.send_trade_exit(
            symbol="BTCUSDT",
            side="long",
            entry_price=95000.0,
            exit_price=96000.0,
            pnl=100.0,
            pnl_percent=1.05,
            size=0.1,
            leverage=10,
            fees=5.0,
            funding=2.0,
        )
        assert result is True
        msg = self.notifier._send_message.call_args[0][0]
        assert "BTCUSDT" in msg
        assert "96000" in msg
        assert "Fees" in msg
        assert "Net PnL" in msg

    @pytest.mark.asyncio
    async def test_send_daily_summary(self):
        result = await self.notifier.send_daily_summary(
            bot_name="Test Bot",
            date="2026-03-03",
            starting_balance=10000.0,
            ending_balance=10100.0,
            total_trades=5,
            winning_trades=3,
            gross_pnl=120.0,
            fees=15.0,
            funding=5.0,
        )
        assert result is True
        msg = self.notifier._send_message.call_args[0][0]
        assert "Daily Summary" in msg
        assert "Test Bot" in msg

    @pytest.mark.asyncio
    async def test_send_risk_alert(self):
        result = await self.notifier.send_risk_alert(
            alert_type="max_drawdown",
            message="Drawdown exceeds limit",
            current_value=12.5,
            threshold=10.0,
        )
        assert result is True
        msg = self.notifier._send_message.call_args[0][0]
        assert "Risk Alert" in msg

    @pytest.mark.asyncio
    async def test_send_bot_status(self):
        result = await self.notifier.send_bot_status(
            bot_name="Alpha Bot",
            status="started",
        )
        assert result is True
        msg = self.notifier._send_message.call_args[0][0]
        assert "Alpha Bot" in msg
        assert "Started" in msg

    @pytest.mark.asyncio
    async def test_send_alert(self):
        result = await self.notifier.send_alert(
            alert_type="price",
            symbol="BTCUSDT",
            current_value=95000.0,
            threshold=94000.0,
            message="Price crossed threshold",
        )
        assert result is True
        msg = self.notifier._send_message.call_args[0][0]
        assert "BTCUSDT" in msg

    @pytest.mark.asyncio
    async def test_send_error(self):
        result = await self.notifier.send_error(
            error_message="Connection timeout",
            context="Fetching ticker data",
        )
        assert result is True
        msg = self.notifier._send_message.call_args[0][0]
        assert "Connection timeout" in msg

    @pytest.mark.asyncio
    async def test_send_test_message(self):
        result = await self.notifier.send_test_message()
        assert result is True
        msg = self.notifier._send_message.call_args[0][0]
        assert "Test" in msg
