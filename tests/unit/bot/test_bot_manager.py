"""Tests for src/bot/bot_manager.py - BotManager simple (non-DB) methods."""

import pytest

from src.bot.bot_manager import BotManager


class TestBotManagerGetStatus:
    def test_get_status_no_bot(self):
        """get_status returns empty list when no bot exists."""
        manager = BotManager()
        statuses = manager.get_status(user_id=999)
        assert statuses == []

    def test_get_exchange_status_no_bot(self):
        """get_exchange_status returns default dict when no bot exists."""
        manager = BotManager()
        status = manager.get_exchange_status(user_id=999, exchange_type="bitget")
        assert status["is_running"] is False
        assert status["exchange_type"] == "bitget"
        assert status["demo_mode"] is True
        assert status["active_preset_id"] is None
        assert status["active_preset_name"] is None
        assert status["started_at"] is None


class TestBotManagerIsRunning:
    def test_is_running_no_bot(self):
        """is_running returns False when no bot has been registered."""
        manager = BotManager()
        assert manager.is_running(user_id=999) is False

    def test_is_running_specific_exchange(self):
        """is_running with exchange_type returns False when no bot registered."""
        manager = BotManager()
        assert manager.is_running(user_id=999, exchange_type="bitget") is False


class TestBotManagerStopBot:
    @pytest.mark.asyncio
    async def test_stop_bot_not_running(self):
        """stop_bot returns False when there is no bot running for the user."""
        manager = BotManager()
        result = await manager.stop_bot(user_id=999, exchange_type="bitget")
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_all_no_bots(self):
        """stop_all_for_user returns 0 when no bots are running."""
        manager = BotManager()
        result = await manager.stop_all_for_user(user_id=999)
        assert result == 0
