"""Tests for src/bot/bot_manager.py - BotManager simple (non-DB) methods."""

import pytest

from src.bot.bot_manager import BotManager


class TestBotManagerGetStatus:
    def test_get_status_no_bot(self):
        """get_status returns a default dict with is_running=False when no bot exists."""
        manager = BotManager()
        status = manager.get_status(user_id=999)
        assert status["is_running"] is False
        assert status["exchange_type"] is None
        assert status["demo_mode"] is True
        assert status["active_preset_id"] is None
        assert status["active_preset_name"] is None
        assert status["started_at"] is None


class TestBotManagerIsRunning:
    def test_is_running_no_bot(self):
        """is_running returns False when no bot has been registered."""
        manager = BotManager()
        assert manager.is_running(user_id=999) is False


class TestBotManagerStopBot:
    @pytest.mark.asyncio
    async def test_stop_bot_not_running(self):
        """stop_bot returns False when there is no bot running for the user."""
        manager = BotManager()
        result = await manager.stop_bot(user_id=999)
        assert result is False
