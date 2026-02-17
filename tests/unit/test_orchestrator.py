"""Tests for the BotOrchestrator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.orchestrator import BotOrchestrator, MAX_BOTS_PER_USER


class TestBotOrchestratorInit:
    """Tests for orchestrator initialization."""

    def test_init_empty(self):
        orch = BotOrchestrator()
        assert orch._workers == {}

    def test_max_bots_per_user_constant(self):
        assert MAX_BOTS_PER_USER == 10


class TestIsRunning:
    """Tests for is_running method."""

    def test_not_running_when_empty(self):
        orch = BotOrchestrator()
        assert orch.is_running(1) is False

    def test_running_when_worker_exists(self):
        orch = BotOrchestrator()
        mock_worker = MagicMock()
        mock_worker.status = "running"
        orch._workers[1] = mock_worker
        assert orch.is_running(1) is True

    def test_not_running_when_stopped(self):
        orch = BotOrchestrator()
        mock_worker = MagicMock()
        mock_worker.status = "stopped"
        orch._workers[1] = mock_worker
        assert orch.is_running(1) is False


class TestGetRunningCount:
    """Tests for get_running_count method."""

    def test_zero_when_empty(self):
        orch = BotOrchestrator()
        assert orch.get_running_count(user_id=1) == 0

    def test_counts_only_user_bots(self):
        orch = BotOrchestrator()
        w1 = MagicMock()
        w1.config = MagicMock(user_id=1)
        w1.status = "running"
        w2 = MagicMock()
        w2.config = MagicMock(user_id=2)
        w2.status = "running"
        w3 = MagicMock()
        w3.config = MagicMock(user_id=1)
        w3.status = "stopped"
        orch._workers = {10: w1, 20: w2, 30: w3}
        assert orch.get_running_count(user_id=1) == 1
        assert orch.get_running_count(user_id=2) == 1


class TestGetBotStatus:
    """Tests for get_bot_status method."""

    def test_returns_none_when_not_found(self):
        orch = BotOrchestrator()
        assert orch.get_bot_status(999) is None

    def test_returns_status_dict(self):
        orch = BotOrchestrator()
        mock_worker = MagicMock()
        mock_worker.get_status_dict.return_value = {"status": "running", "id": 1}
        orch._workers[1] = mock_worker
        result = orch.get_bot_status(1)
        assert result == {"status": "running", "id": 1}


class TestGetStatus:
    """Tests for get_status method (per-user)."""

    def test_empty_for_unknown_user(self):
        orch = BotOrchestrator()
        assert orch.get_status(user_id=999) == []

    def test_filters_by_user(self):
        orch = BotOrchestrator()
        w1 = MagicMock()
        w1.config = MagicMock(user_id=1)
        w1.get_status_dict.return_value = {"id": 10}
        w2 = MagicMock()
        w2.config = MagicMock(user_id=2)
        w2.get_status_dict.return_value = {"id": 20}
        orch._workers = {10: w1, 20: w2}
        result = orch.get_status(user_id=1)
        assert len(result) == 1
        assert result[0]["id"] == 10


class TestStartBot:
    """Tests for start_bot method."""

    @pytest.mark.asyncio
    async def test_start_already_running_raises(self):
        orch = BotOrchestrator()
        mock_worker = MagicMock()
        mock_worker.status = "running"
        orch._workers[1] = mock_worker
        with pytest.raises(ValueError, match="already running"):
            await orch.start_bot(1)

    @pytest.mark.asyncio
    async def test_start_initialization_failure_raises(self):
        orch = BotOrchestrator()
        with patch("src.bot.orchestrator.BotWorker") as MockWorker:
            worker_instance = AsyncMock()
            worker_instance.initialize = AsyncMock(return_value=False)
            worker_instance.error_message = "Config not found"
            worker_instance.status = "stopped"
            MockWorker.return_value = worker_instance
            with patch.object(orch, "_update_instance_state", new_callable=AsyncMock):
                with pytest.raises(ValueError, match="Config not found"):
                    await orch.start_bot(1)


class TestStopBot:
    """Tests for stop_bot method."""

    @pytest.mark.asyncio
    async def test_stop_not_running_returns_false(self):
        orch = BotOrchestrator()
        result = await orch.stop_bot(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_running_bot(self):
        orch = BotOrchestrator()
        mock_worker = AsyncMock()
        mock_worker.status = "running"
        mock_worker.stop = AsyncMock()
        orch._workers[1] = mock_worker
        with patch.object(orch, "_update_instance_state", new_callable=AsyncMock):
            result = await orch.stop_bot(1)
        assert result is True
        mock_worker.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_stopped_worker_returns_false(self):
        orch = BotOrchestrator()
        mock_worker = MagicMock()
        mock_worker.status = "stopped"
        orch._workers[1] = mock_worker
        result = await orch.stop_bot(1)
        assert result is False


class TestStartBotSuccess:
    """Tests for successful bot start."""

    @pytest.mark.asyncio
    async def test_start_bot_success(self):
        orch = BotOrchestrator()
        with patch("src.bot.orchestrator.BotWorker") as MockWorker:
            worker_instance = AsyncMock()
            worker_instance.initialize = AsyncMock(return_value=True)
            worker_instance.start = AsyncMock()
            worker_instance.status = "running"
            MockWorker.return_value = worker_instance
            with patch.object(orch, "_update_instance_state", new_callable=AsyncMock) as mock_update:
                result = await orch.start_bot(1)
        assert result is True
        assert 1 in orch._workers
        worker_instance.start.assert_called_once()
        mock_update.assert_called_once_with(1, True)


class TestRestartBot:
    """Tests for restart_bot method."""

    @pytest.mark.asyncio
    async def test_restart_stops_then_starts(self):
        orch = BotOrchestrator()
        # Pre-add a running worker whose status changes to "stopped" after stop()
        old_worker = AsyncMock()
        old_worker.status = "running"

        async def fake_stop():
            old_worker.status = "stopped"

        old_worker.stop = AsyncMock(side_effect=fake_stop)
        orch._workers[1] = old_worker

        with patch("src.bot.orchestrator.BotWorker") as MockWorker:
            new_worker = AsyncMock()
            new_worker.initialize = AsyncMock(return_value=True)
            new_worker.start = AsyncMock()
            new_worker.status = "running"
            MockWorker.return_value = new_worker
            with patch.object(orch, "_update_instance_state", new_callable=AsyncMock):
                result = await orch.restart_bot(1)
        assert result is True
        old_worker.stop.assert_called_once()
        new_worker.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_without_existing_worker(self):
        orch = BotOrchestrator()
        with patch("src.bot.orchestrator.BotWorker") as MockWorker:
            worker_instance = AsyncMock()
            worker_instance.initialize = AsyncMock(return_value=True)
            worker_instance.start = AsyncMock()
            worker_instance.status = "running"
            MockWorker.return_value = worker_instance
            with patch.object(orch, "_update_instance_state", new_callable=AsyncMock):
                result = await orch.restart_bot(1)
        assert result is True


class TestRestoreOnStartup:
    """Tests for restore_on_startup method."""

    @pytest.mark.asyncio
    async def test_restore_enabled_bots(self):
        orch = BotOrchestrator()
        mock_config1 = MagicMock(id=10, name="Bot1")
        mock_config2 = MagicMock(id=20, name="Bot2")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_config1, mock_config2]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.orchestrator.get_session", return_value=mock_session):
            with patch.object(orch, "_start_bot_locked", new_callable=AsyncMock, return_value=True) as mock_start:
                await orch.restore_on_startup()
        assert mock_start.call_count == 2

    @pytest.mark.asyncio
    async def test_restore_handles_failure(self):
        orch = BotOrchestrator()
        mock_config = MagicMock(id=10, name="FailBot")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_config]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.orchestrator.get_session", return_value=mock_session):
            with patch.object(orch, "_start_bot_locked", new_callable=AsyncMock, side_effect=Exception("init fail")):
                await orch.restore_on_startup()
        # Should not crash, failure is logged

    @pytest.mark.asyncio
    async def test_restore_no_enabled_bots(self):
        orch = BotOrchestrator()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.orchestrator.get_session", return_value=mock_session):
            await orch.restore_on_startup()
        assert len(orch._workers) == 0


class TestStopAllForUser:
    """Tests for stop_all_for_user method."""

    @pytest.mark.asyncio
    async def test_stops_all_user_bots(self):
        orch = BotOrchestrator()
        w1 = AsyncMock()
        w1.config = MagicMock(user_id=1)
        w1.status = "running"
        w1.stop = AsyncMock()
        w2 = AsyncMock()
        w2.config = MagicMock(user_id=1)
        w2.status = "running"
        w2.stop = AsyncMock()
        w3 = AsyncMock()
        w3.config = MagicMock(user_id=2)
        w3.status = "running"
        orch._workers = {10: w1, 20: w2, 30: w3}

        with patch.object(orch, "_update_instance_state", new_callable=AsyncMock):
            count = await orch.stop_all_for_user(1)
        assert count == 2

    @pytest.mark.asyncio
    async def test_stops_none_for_unknown_user(self):
        orch = BotOrchestrator()
        count = await orch.stop_all_for_user(999)
        assert count == 0


class TestShutdownAll:
    """Tests for shutdown_all method."""

    @pytest.mark.asyncio
    async def test_shutdown_stops_all_workers(self):
        orch = BotOrchestrator()
        w1 = AsyncMock()
        w1.status = "running"
        w1.stop = AsyncMock()
        w2 = AsyncMock()
        w2.status = "stopped"
        orch._workers = {1: w1, 2: w2}

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.orchestrator.get_session", return_value=mock_session):
            await orch.shutdown_all()
        w1.stop.assert_called_once()
        assert len(orch._workers) == 0

    @pytest.mark.asyncio
    async def test_shutdown_handles_worker_stop_error(self):
        orch = BotOrchestrator()
        w1 = AsyncMock()
        w1.status = "running"
        w1.stop = AsyncMock(side_effect=Exception("stop error"))
        orch._workers = {1: w1}

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.orchestrator.get_session", return_value=mock_session):
            await orch.shutdown_all()
        assert len(orch._workers) == 0

    @pytest.mark.asyncio
    async def test_shutdown_handles_db_error(self):
        orch = BotOrchestrator()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.orchestrator.get_session", return_value=mock_session):
            await orch.shutdown_all()
        assert len(orch._workers) == 0


class TestUpdateInstanceState:
    """Tests for _update_instance_state method."""

    @pytest.mark.asyncio
    async def test_update_existing_instance_running(self):
        orch = BotOrchestrator()
        mock_worker = MagicMock()
        mock_worker.config = MagicMock(mode="demo", user_id=1)
        orch._workers[1] = mock_worker

        mock_instance = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_instance

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.orchestrator.get_session", return_value=mock_session):
            await orch._update_instance_state(1, True)
        assert mock_instance.is_running is True
        assert mock_instance.stopped_at is None

    @pytest.mark.asyncio
    async def test_update_existing_instance_stopped(self):
        orch = BotOrchestrator()
        mock_worker = MagicMock()
        mock_worker.config = MagicMock(mode="live", user_id=1)
        orch._workers[1] = mock_worker

        mock_instance = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_instance

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.orchestrator.get_session", return_value=mock_session):
            await orch._update_instance_state(1, False, "some error")
        assert mock_instance.is_running is False
        assert mock_instance.error_message == "some error"

    @pytest.mark.asyncio
    async def test_create_new_instance(self):
        orch = BotOrchestrator()
        mock_worker = MagicMock()
        mock_worker.config = MagicMock(mode="both", user_id=5, exchange_type="bitget")
        orch._workers[1] = mock_worker

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.orchestrator.get_session", return_value=mock_session):
            await orch._update_instance_state(1, True)
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_instance_db_error_handled(self):
        orch = BotOrchestrator()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("DB fail"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.orchestrator.get_session", return_value=mock_session):
            await orch._update_instance_state(1, True)
        # Should not raise — error is logged
