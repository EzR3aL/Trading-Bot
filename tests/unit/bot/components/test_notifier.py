"""Unit tests for ``src.bot.components.notifier.Notifier``.

Part of ARCH-H1 Phase 1 PR-1 (issue #274). Verifies the extracted
Notifier component in isolation — no BotWorker involvement.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from src.bot.components.notifier import Notifier, _channel_name  # noqa: E402


def _make_config(
    *,
    user_id: int = 42,
    discord_webhook_url: str | None = None,
    telegram_bot_token: str | None = None,
    telegram_chat_id: str | None = None,
):
    cfg = MagicMock()
    cfg.user_id = user_id
    cfg.discord_webhook_url = discord_webhook_url
    cfg.telegram_bot_token = telegram_bot_token
    cfg.telegram_chat_id = telegram_chat_id
    return cfg


class TestChannelName:
    """Channel-name derivation from notifier class."""

    def test_discord(self):
        obj = MagicMock()
        obj.__class__.__name__ = "DiscordNotifier"
        assert _channel_name(obj) == "discord"

    def test_telegram(self):
        obj = MagicMock()
        obj.__class__.__name__ = "TelegramNotifier"
        assert _channel_name(obj) == "telegram"

    def test_unknown(self):
        obj = MagicMock()
        obj.__class__.__name__ = "MysteryNotifier"
        assert _channel_name(obj) == "unknown"


class TestGetDiscordNotifier:
    """Discord webhook loading."""

    async def test_no_config_returns_none(self):
        notifier = Notifier(bot_config_id=1, config_getter=lambda: None)
        assert await notifier.get_discord_notifier() is None

    async def test_no_webhook_returns_none(self):
        cfg = _make_config(discord_webhook_url=None)
        notifier = Notifier(bot_config_id=1, config_getter=lambda: cfg)
        assert await notifier.get_discord_notifier() is None

    async def test_returns_discord_when_configured(self):
        cfg = _make_config(discord_webhook_url="encrypted_url")
        notifier = Notifier(bot_config_id=1, config_getter=lambda: cfg)
        with patch(
            "src.bot.components.notifier.decrypt_value",
            return_value="https://discord.com/webhook/abc",
        ):
            result = await notifier.get_discord_notifier()
        assert result is not None

    async def test_decrypt_error_returns_none(self):
        cfg = _make_config(discord_webhook_url="encrypted_url")
        notifier = Notifier(bot_config_id=1, config_getter=lambda: cfg)
        with patch(
            "src.bot.components.notifier.decrypt_value",
            side_effect=Exception("boom"),
        ):
            result = await notifier.get_discord_notifier()
        assert result is None


class TestGetNotifiers:
    """Aggregate notifier loading (Discord + Telegram)."""

    async def test_empty_when_nothing_configured(self):
        notifier = Notifier(bot_config_id=1, config_getter=lambda: _make_config())
        assert await notifier.get_notifiers() == []

    async def test_only_discord_when_telegram_missing(self):
        cfg = _make_config(discord_webhook_url="enc_url")
        notifier = Notifier(bot_config_id=1, config_getter=lambda: cfg)
        with patch(
            "src.bot.components.notifier.decrypt_value", return_value="https://hook"
        ):
            result = await notifier.get_notifiers()
        assert len(result) == 1

    async def test_both_when_both_configured(self):
        cfg = _make_config(
            discord_webhook_url="enc_webhook",
            telegram_bot_token="enc_token",
            telegram_chat_id="123456",
        )
        notifier = Notifier(bot_config_id=1, config_getter=lambda: cfg)

        mock_tg_cls = MagicMock(return_value=MagicMock())
        with patch(
            "src.bot.components.notifier.decrypt_value", return_value="decrypted"
        ), patch(
            "src.notifications.telegram_notifier.TelegramNotifier", mock_tg_cls
        ):
            result = await notifier.get_notifiers()
        assert len(result) == 2

    async def test_telegram_exception_handled(self):
        cfg = _make_config(
            telegram_bot_token="enc_token", telegram_chat_id="123456"
        )
        notifier = Notifier(bot_config_id=1, config_getter=lambda: cfg)
        with patch(
            "src.bot.components.notifier.decrypt_value",
            side_effect=Exception("decrypt boom"),
        ):
            result = await notifier.get_notifiers()
        assert result == []


class TestSendNotification:
    """Dispatch loop behaviour."""

    async def test_dispatches_to_each_notifier(self):
        cfg = _make_config()
        notifier = Notifier(bot_config_id=1, config_getter=lambda: cfg)

        n1 = AsyncMock()
        n1.__aenter__ = AsyncMock(return_value=n1)
        n1.__aexit__ = AsyncMock(return_value=False)
        n1.__class__.__name__ = "DiscordNotifier"

        n2 = AsyncMock()
        n2.__aenter__ = AsyncMock(return_value=n2)
        n2.__aexit__ = AsyncMock(return_value=False)
        n2.__class__.__name__ = "TelegramNotifier"

        send_fn = AsyncMock()
        with patch(
            "src.bot.components.notifier.log_notification", new=AsyncMock()
        ):
            await notifier.send_notification(
                send_fn, event_type="trade_entry", notifiers=[n1, n2]
            )

        assert send_fn.await_count == 2

    async def test_per_notifier_error_is_isolated(self):
        cfg = _make_config()
        notifier = Notifier(bot_config_id=1, config_getter=lambda: cfg)

        bad = AsyncMock()
        bad.__aenter__ = AsyncMock(return_value=bad)
        bad.__aexit__ = AsyncMock(return_value=False)
        bad.__class__.__name__ = "DiscordNotifier"

        good = AsyncMock()
        good.__aenter__ = AsyncMock(return_value=good)
        good.__aexit__ = AsyncMock(return_value=False)
        good.__class__.__name__ = "TelegramNotifier"

        call_log = []

        async def send_fn(n):
            call_log.append(n)
            if n is bad:
                raise Exception("Discord down")

        with patch(
            "src.bot.components.notifier.log_notification", new=AsyncMock()
        ):
            await notifier.send_notification(
                send_fn, event_type="trade_entry", notifiers=[bad, good]
            )

        assert len(call_log) == 2  # good still called after bad

    async def test_loads_notifiers_when_none_passed(self):
        """If caller does not inject notifiers, component loads them itself."""
        cfg = _make_config(discord_webhook_url="enc_url")
        notifier = Notifier(bot_config_id=1, config_getter=lambda: cfg)

        send_fn = AsyncMock()
        injected = AsyncMock()
        injected.__aenter__ = AsyncMock(return_value=injected)
        injected.__aexit__ = AsyncMock(return_value=False)
        injected.__class__.__name__ = "DiscordNotifier"

        with patch.object(
            notifier, "get_notifiers", AsyncMock(return_value=[injected])
        ), patch(
            "src.bot.components.notifier.log_notification", new=AsyncMock()
        ):
            await notifier.send_notification(send_fn, event_type="test")

        send_fn.assert_awaited_once_with(injected)

    async def test_no_user_id_skips_logging(self):
        cfg = _make_config(user_id=None)
        notifier = Notifier(bot_config_id=1, config_getter=lambda: cfg)

        n = AsyncMock()
        n.__aenter__ = AsyncMock(return_value=n)
        n.__aexit__ = AsyncMock(return_value=False)
        n.__class__.__name__ = "DiscordNotifier"

        send_fn = AsyncMock()
        log_mock = AsyncMock()
        with patch("src.bot.components.notifier.log_notification", log_mock):
            await notifier.send_notification(send_fn, notifiers=[n])

        log_mock.assert_not_called()
