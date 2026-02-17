"""
Unit tests for the Telegram Notifier.

Tests cover:
- Initialization (bot_token, chat_id, API URL construction)
- Async context manager (__aenter__, __aexit__)
- _send_message (success, API errors, network failures, timeout)
- send_trade_entry (long/short, optional fields, message content)
- send_trade_exit (profit/loss, PnL formatting, optional fields)
- send_error (with/without context)
- send_bot_status (started/stopped/unknown statuses, with/without details)
- send_test_message (content verification)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.notifications.telegram_notifier import TelegramNotifier, TELEGRAM_API_BASE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_notifier(bot_token="123456:ABC-DEF", chat_id="987654321"):
    """Create a TelegramNotifier with test credentials."""
    return TelegramNotifier(bot_token=bot_token, chat_id=chat_id)


def _mock_aiohttp_success(response_status=200):
    """Build a fully mocked aiohttp.ClientSession that returns the given status.

    Returns (mock_session_class, mock_response) so tests can inspect the response
    or override behavior.
    """
    mock_response = AsyncMock()
    mock_response.status = response_status
    mock_response.text = AsyncMock(return_value="OK")
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_class = MagicMock(return_value=mock_session)
    return mock_session_class, mock_response


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

class TestTelegramNotifierInit:
    """Tests for TelegramNotifier initialization."""

    def test_stores_bot_token(self):
        # Arrange / Act
        notifier = _make_notifier(bot_token="my-token")

        # Assert
        assert notifier.bot_token == "my-token"

    def test_stores_chat_id(self):
        # Arrange / Act
        notifier = _make_notifier(chat_id="12345")

        # Assert
        assert notifier.chat_id == "12345"

    def test_api_url_contains_token(self):
        # Arrange / Act
        notifier = _make_notifier(bot_token="111:AAA-BBB")

        # Assert
        assert notifier._api_url == "https://api.telegram.org/bot111:AAA-BBB"

    def test_api_url_matches_constant_format(self):
        # Arrange
        token = "999:ZZZ-YYY"

        # Act
        notifier = _make_notifier(bot_token=token)

        # Assert
        expected = TELEGRAM_API_BASE.format(token=token)
        assert notifier._api_url == expected


# ---------------------------------------------------------------------------
# Async context manager tests
# ---------------------------------------------------------------------------

class TestAsyncContextManager:
    """Tests for __aenter__ and __aexit__ methods."""

    async def test_aenter_returns_self(self):
        # Arrange
        notifier = _make_notifier()

        # Act
        async with notifier as ctx:
            # Assert
            assert ctx is notifier

    async def test_aexit_does_not_raise(self):
        # Arrange
        notifier = _make_notifier()

        # Act / Assert - should not raise
        async with notifier:
            pass

    async def test_context_manager_works_with_exception(self):
        """__aexit__ should not suppress exceptions."""
        # Arrange
        notifier = _make_notifier()

        # Act / Assert
        with pytest.raises(ValueError, match="deliberate"):
            async with notifier:
                raise ValueError("deliberate")


# ---------------------------------------------------------------------------
# _send_message tests
# ---------------------------------------------------------------------------

class TestSendMessage:
    """Tests for _send_message method."""

    async def test_returns_true_on_200_response(self):
        # Arrange
        notifier = _make_notifier()
        mock_session_cls, _ = _mock_aiohttp_success(200)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier._send_message("Hello")

        # Assert
        assert result is True

    async def test_posts_to_correct_url(self):
        # Arrange
        notifier = _make_notifier(bot_token="tok123")
        mock_session_cls, _ = _mock_aiohttp_success(200)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            await notifier._send_message("Test")

        # Assert
        mock_session = mock_session_cls.return_value.__aenter__.return_value
        call_args = mock_session.post.call_args
        url = call_args[0][0]
        assert url == f"{notifier._api_url}/sendMessage"

    async def test_sends_correct_payload(self):
        # Arrange
        notifier = _make_notifier(chat_id="42")
        mock_session_cls, _ = _mock_aiohttp_success(200)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            await notifier._send_message("Hello World", parse_mode="Markdown")

        # Assert
        mock_session = mock_session_cls.return_value.__aenter__.return_value
        call_kwargs = mock_session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["chat_id"] == "42"
        assert payload["text"] == "Hello World"
        assert payload["parse_mode"] == "Markdown"

    async def test_default_parse_mode_is_html(self):
        # Arrange
        notifier = _make_notifier()
        mock_session_cls, _ = _mock_aiohttp_success(200)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            await notifier._send_message("Test")

        # Assert
        mock_session = mock_session_cls.return_value.__aenter__.return_value
        call_kwargs = mock_session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["parse_mode"] == "HTML"

    async def test_returns_false_on_non_200_response(self):
        # Arrange
        notifier = _make_notifier()
        mock_session_cls, mock_response = _mock_aiohttp_success(400)
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier._send_message("Test")

        # Assert
        assert result is False

    async def test_returns_false_on_401_unauthorized(self):
        # Arrange
        notifier = _make_notifier()
        mock_session_cls, mock_response = _mock_aiohttp_success(401)
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Unauthorized")

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier._send_message("Test")

        # Assert
        assert result is False

    async def test_returns_false_on_500_server_error(self):
        # Arrange
        notifier = _make_notifier()
        mock_session_cls, mock_response = _mock_aiohttp_success(500)
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier._send_message("Test")

        # Assert
        assert result is False

    async def test_returns_false_on_network_exception(self):
        # Arrange
        notifier = _make_notifier()
        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=ConnectionError("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls = MagicMock(return_value=mock_session)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier._send_message("Test")

        # Assert
        assert result is False

    async def test_returns_false_on_timeout_exception(self):
        # Arrange
        notifier = _make_notifier()
        import asyncio
        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=asyncio.TimeoutError())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls = MagicMock(return_value=mock_session)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier._send_message("Test")

        # Assert
        assert result is False

    async def test_returns_false_on_generic_exception(self):
        # Arrange
        notifier = _make_notifier()
        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=RuntimeError("Something unexpected"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls = MagicMock(return_value=mock_session)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier._send_message("Test")

        # Assert
        assert result is False

    async def test_logs_warning_on_api_error(self):
        # Arrange
        notifier = _make_notifier()
        mock_session_cls, mock_response = _mock_aiohttp_success(403)
        mock_response.status = 403
        mock_response.text = AsyncMock(return_value="Forbidden")

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            with patch("src.notifications.telegram_notifier.logger") as mock_logger:
                await notifier._send_message("Test")

        # Assert
        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "403" in warning_msg
        assert "Forbidden" in warning_msg

    async def test_logs_error_on_exception(self):
        # Arrange
        notifier = _make_notifier()
        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=OSError("Network down"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls = MagicMock(return_value=mock_session)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            with patch("src.notifications.telegram_notifier.logger") as mock_logger:
                await notifier._send_message("Test")

        # Assert
        mock_logger.error.assert_called_once()
        error_msg = mock_logger.error.call_args[0][0]
        assert "Network down" in error_msg

    async def test_sets_timeout_of_10_seconds(self):
        # Arrange
        notifier = _make_notifier()
        mock_session_cls, _ = _mock_aiohttp_success(200)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            await notifier._send_message("Test")

        # Assert
        mock_session = mock_session_cls.return_value.__aenter__.return_value
        call_kwargs = mock_session.post.call_args
        timeout = call_kwargs.kwargs.get("timeout") or call_kwargs[1].get("timeout")
        assert timeout is not None
        assert timeout.total == 10


# ---------------------------------------------------------------------------
# send_trade_entry tests
# ---------------------------------------------------------------------------

class TestSendTradeEntry:
    """Tests for send_trade_entry method."""

    async def test_long_trade_returns_true_on_success(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        result = await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
        )

        # Assert
        assert result is True
        notifier._send_message.assert_awaited_once()

    async def test_short_trade_returns_true_on_success(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        result = await notifier.send_trade_entry(
            symbol="ETHUSDT", side="short",
            entry_price=3500.0, position_size=0.5,
        )

        # Assert
        assert result is True

    async def test_long_trade_message_contains_green_emoji(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "\U0001f7e2" in message  # green circle emoji

    async def test_short_trade_message_contains_red_emoji(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="short",
            entry_price=95000.0, position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "\U0001f534" in message  # red circle emoji

    async def test_message_contains_symbol(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="SOLUSDT", side="long",
            entry_price=150.0, position_size=1.0,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "SOLUSDT" in message

    async def test_message_contains_direction_uppercase(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "LONG" in message

    async def test_message_contains_entry_price(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95123.45, position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "95123.45" in message

    async def test_message_contains_position_size(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.05,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "0.05" in message

    async def test_message_contains_leverage(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
            leverage=10,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "10x" in message

    async def test_default_leverage_is_1(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "1x" in message

    async def test_message_includes_strategy_when_provided(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
            strategy="LiquidationHunter",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "LiquidationHunter" in message
        assert "Strategy" in message

    async def test_message_excludes_strategy_when_empty(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
            strategy="",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Strategy" not in message

    async def test_message_includes_take_profit_when_provided(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
            take_profit=97000.0,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Take Profit" in message
        assert "97000.0" in message

    async def test_message_excludes_take_profit_when_none(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
            take_profit=None,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Take Profit" not in message

    async def test_message_includes_stop_loss_when_provided(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
            stop_loss=93000.0,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Stop Loss" in message
        assert "93000.0" in message

    async def test_message_excludes_stop_loss_when_none(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
            stop_loss=None,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Stop Loss" not in message

    async def test_message_contains_timestamp(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "UTC" in message

    async def test_message_contains_trade_opened_header(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Trade Opened" in message

    async def test_returns_false_when_send_fails(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=False)

        # Act
        result = await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
        )

        # Assert
        assert result is False

    async def test_side_is_case_insensitive(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="Long",
            entry_price=95000.0, position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "LONG" in message
        assert "\U0001f7e2" in message  # green for long

    async def test_accepts_extra_kwargs(self):
        """send_trade_entry accepts **kwargs without error."""
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act / Assert - should not raise
        result = await notifier.send_trade_entry(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, position_size=0.01,
            extra_field="extra_value",
        )
        assert result is True

    async def test_message_with_all_optional_fields(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_entry(
            symbol="BTCUSDT", side="short",
            entry_price=95000.0, position_size=0.01,
            leverage=20, strategy="RSI_Divergence",
            take_profit=93000.0, stop_loss=96000.0,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "SHORT" in message
        assert "95000.0" in message
        assert "0.01" in message
        assert "20x" in message
        assert "RSI_Divergence" in message
        assert "93000.0" in message
        assert "96000.0" in message


# ---------------------------------------------------------------------------
# send_trade_exit tests
# ---------------------------------------------------------------------------

class TestSendTradeExit:
    """Tests for send_trade_exit method."""

    async def test_profitable_exit_returns_true(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        result = await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            position_size=0.01,
        )

        # Assert
        assert result is True

    async def test_profitable_exit_uses_checkmark_emoji(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "\u2705" in message  # checkmark for profit

    async def test_losing_exit_uses_x_emoji(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=94000.0,
            pnl=-10.0, pnl_percent=-1.05,
            position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "\u274c" in message  # x-mark for loss

    async def test_zero_pnl_uses_checkmark_emoji(self):
        """Zero PnL (breakeven) should use checkmark emoji (pnl >= 0)."""
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=95000.0,
            pnl=0.0, pnl_percent=0.0,
            position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "\u2705" in message

    async def test_message_contains_trade_closed_header(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="ETHUSDT", side="short",
            entry_price=3500.0, exit_price=3400.0,
            pnl=10.0, pnl_percent=2.86,
            position_size=0.1,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Trade Closed" in message
        assert "ETHUSDT" in message

    async def test_message_contains_pnl_with_sign(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.50, pnl_percent=1.05,
            position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "+10.50 USDT" in message
        assert "+1.05%" in message

    async def test_negative_pnl_has_no_plus_sign(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=94000.0,
            pnl=-20.00, pnl_percent=-2.10,
            position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "-20.00 USDT" in message
        assert "-2.10%" in message
        assert "+-" not in message  # no double sign

    async def test_message_contains_entry_and_exit_prices(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=94000.0, exit_price=96500.0,
            pnl=25.0, pnl_percent=2.66,
            position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "94000.0" in message
        assert "96500.0" in message

    async def test_message_contains_leverage(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            position_size=0.01, leverage=5,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "5x" in message

    async def test_message_includes_strategy_when_provided(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            position_size=0.01, strategy="MyStrategy",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Strategy" in message
        assert "MyStrategy" in message

    async def test_message_excludes_strategy_when_empty(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            position_size=0.01, strategy="",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Strategy" not in message

    async def test_message_includes_duration_when_provided(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            position_size=0.01, duration="2h 30m",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Duration" in message
        assert "2h 30m" in message

    async def test_message_excludes_duration_when_empty(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            position_size=0.01, duration="",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Duration" not in message

    async def test_message_contains_timestamp(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            position_size=0.01,
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "UTC" in message

    async def test_returns_false_when_send_fails(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=False)

        # Act
        result = await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            position_size=0.01,
        )

        # Assert
        assert result is False

    async def test_accepts_extra_kwargs(self):
        """send_trade_exit accepts **kwargs without error."""
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act / Assert - should not raise
        result = await notifier.send_trade_exit(
            symbol="BTCUSDT", side="long",
            entry_price=95000.0, exit_price=96000.0,
            pnl=10.0, pnl_percent=1.05,
            position_size=0.01, unknown_param="value",
        )
        assert result is True


# ---------------------------------------------------------------------------
# send_error tests
# ---------------------------------------------------------------------------

class TestSendError:
    """Tests for send_error method."""

    async def test_basic_error_returns_true(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        result = await notifier.send_error(error_message="Something went wrong")

        # Assert
        assert result is True

    async def test_message_contains_bot_error_header(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_error(error_message="API timeout")

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Bot Error" in message

    async def test_message_contains_error_message(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_error(error_message="Connection refused to exchange")

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Connection refused to exchange" in message

    async def test_message_includes_context_when_provided(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_error(
            error_message="Rate limit exceeded",
            context="Fetching BTCUSDT orderbook",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Context" in message
        assert "Fetching BTCUSDT orderbook" in message

    async def test_message_excludes_context_when_empty(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_error(error_message="Timeout", context="")

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Context" not in message

    async def test_message_excludes_context_when_default(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_error(error_message="Timeout")

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Context" not in message

    async def test_message_contains_warning_emoji(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_error(error_message="Error occurred")

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "\u26a0\ufe0f" in message  # warning emoji

    async def test_message_contains_timestamp(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_error(error_message="Error")

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "UTC" in message

    async def test_returns_false_when_send_fails(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=False)

        # Act
        result = await notifier.send_error(error_message="Error")

        # Assert
        assert result is False

    async def test_accepts_extra_kwargs(self):
        """send_error accepts **kwargs without error."""
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act / Assert
        result = await notifier.send_error(
            error_message="Error",
            extra_key="extra_value",
        )
        assert result is True


# ---------------------------------------------------------------------------
# send_bot_status tests
# ---------------------------------------------------------------------------

class TestSendBotStatus:
    """Tests for send_bot_status method."""

    async def test_started_status_returns_true(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        result = await notifier.send_bot_status(
            bot_name="TradingBot", status="started",
        )

        # Assert
        assert result is True

    async def test_started_status_uses_play_emoji(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_bot_status(
            bot_name="TradingBot", status="started",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "\u25b6\ufe0f" in message  # play button emoji

    async def test_stopped_status_uses_stop_emoji(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_bot_status(
            bot_name="TradingBot", status="stopped",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "\u23f9\ufe0f" in message  # stop button emoji

    async def test_unknown_status_uses_info_emoji(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_bot_status(
            bot_name="TradingBot", status="paused",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "\u2139\ufe0f" in message  # info emoji

    async def test_message_contains_bot_name(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_bot_status(
            bot_name="MyBot-Alpha", status="started",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "MyBot-Alpha" in message

    async def test_message_contains_status_title_case(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_bot_status(
            bot_name="Bot1", status="started",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Started" in message

    async def test_message_includes_details_when_provided(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_bot_status(
            bot_name="Bot1", status="started",
            details="Running on BTCUSDT and ETHUSDT",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Details" in message
        assert "Running on BTCUSDT and ETHUSDT" in message

    async def test_message_excludes_details_when_empty(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_bot_status(
            bot_name="Bot1", status="started", details="",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Details" not in message

    async def test_message_excludes_details_when_default(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_bot_status(
            bot_name="Bot1", status="started",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Details" not in message

    async def test_message_contains_timestamp(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_bot_status(
            bot_name="Bot1", status="started",
        )

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "UTC" in message

    async def test_returns_false_when_send_fails(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=False)

        # Act
        result = await notifier.send_bot_status(
            bot_name="Bot1", status="started",
        )

        # Assert
        assert result is False

    async def test_accepts_extra_kwargs(self):
        """send_bot_status accepts **kwargs without error."""
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act / Assert
        result = await notifier.send_bot_status(
            bot_name="Bot1", status="started",
            extra_param="extra",
        )
        assert result is True


# ---------------------------------------------------------------------------
# send_test_message tests
# ---------------------------------------------------------------------------

class TestSendTestMessage:
    """Tests for send_test_message method."""

    async def test_returns_true_on_success(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        result = await notifier.send_test_message()

        # Assert
        assert result is True

    async def test_message_contains_test_header(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_test_message()

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "Telegram Notification Test" in message

    async def test_message_contains_success_confirmation(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_test_message()

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "configured correctly" in message

    async def test_message_contains_checkmark_emoji(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_test_message()

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "\u2705" in message

    async def test_message_contains_timestamp(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=True)

        # Act
        await notifier.send_test_message()

        # Assert
        message = notifier._send_message.call_args[0][0]
        assert "UTC" in message

    async def test_returns_false_when_send_fails(self):
        # Arrange
        notifier = _make_notifier()
        notifier._send_message = AsyncMock(return_value=False)

        # Act
        result = await notifier.send_test_message()

        # Assert
        assert result is False


# ---------------------------------------------------------------------------
# Integration-style tests (end-to-end through _send_message mock)
# ---------------------------------------------------------------------------

class TestEndToEndWithMockedHttp:
    """Tests that verify full flow from public method to HTTP call."""

    async def test_trade_entry_sends_http_post(self):
        """Verify that send_trade_entry actually triggers an HTTP POST."""
        # Arrange
        notifier = _make_notifier(bot_token="test-token", chat_id="12345")
        mock_session_cls, mock_response = _mock_aiohttp_success(200)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier.send_trade_entry(
                symbol="BTCUSDT", side="long",
                entry_price=95000.0, position_size=0.01,
            )

        # Assert
        assert result is True
        mock_session = mock_session_cls.return_value.__aenter__.return_value
        mock_session.post.assert_called_once()

        call_args = mock_session.post.call_args
        url = call_args[0][0]
        assert "test-token" in url
        assert "sendMessage" in url

        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["chat_id"] == "12345"
        assert "BTCUSDT" in payload["text"]

    async def test_trade_exit_sends_http_post(self):
        """Verify that send_trade_exit actually triggers an HTTP POST."""
        # Arrange
        notifier = _make_notifier(bot_token="exit-token", chat_id="99999")
        mock_session_cls, _ = _mock_aiohttp_success(200)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier.send_trade_exit(
                symbol="ETHUSDT", side="short",
                entry_price=3500.0, exit_price=3400.0,
                pnl=10.0, pnl_percent=2.86,
                position_size=0.1,
            )

        # Assert
        assert result is True
        mock_session = mock_session_cls.return_value.__aenter__.return_value
        payload = mock_session.post.call_args.kwargs.get("json") or mock_session.post.call_args[1].get("json")
        assert payload["chat_id"] == "99999"
        assert "ETHUSDT" in payload["text"]
        assert "Trade Closed" in payload["text"]

    async def test_error_notification_sends_http_post(self):
        """Verify that send_error actually triggers an HTTP POST."""
        # Arrange
        notifier = _make_notifier()
        mock_session_cls, _ = _mock_aiohttp_success(200)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier.send_error(
                error_message="Critical failure",
                context="Main loop",
            )

        # Assert
        assert result is True
        mock_session = mock_session_cls.return_value.__aenter__.return_value
        payload = mock_session.post.call_args.kwargs.get("json") or mock_session.post.call_args[1].get("json")
        assert "Critical failure" in payload["text"]
        assert "Main loop" in payload["text"]

    async def test_network_failure_does_not_raise(self):
        """Network failure should return False, not raise."""
        # Arrange
        notifier = _make_notifier()
        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=ConnectionError("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls = MagicMock(return_value=mock_session)

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier.send_trade_entry(
                symbol="BTCUSDT", side="long",
                entry_price=95000.0, position_size=0.01,
            )

        # Assert
        assert result is False

    async def test_invalid_token_api_error_does_not_raise(self):
        """Invalid token causing a 401 should return False, not raise."""
        # Arrange
        notifier = _make_notifier(bot_token="invalid-token")
        mock_session_cls, mock_response = _mock_aiohttp_success(401)
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value='{"ok":false,"error_code":401,"description":"Unauthorized"}')

        # Act
        with patch("src.notifications.telegram_notifier.aiohttp.ClientSession", mock_session_cls):
            result = await notifier.send_test_message()

        # Assert
        assert result is False
