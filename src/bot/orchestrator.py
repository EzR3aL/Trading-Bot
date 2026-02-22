"""
BotOrchestrator: Supervisor that manages all BotWorker instances.

Responsibilities:
- Start/stop/restart individual bots
- Restore running bots on server restart
- Health monitoring and auto-restart on failure
- Provide status overview for API/frontend
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from src.bot.bot_worker import BotWorker
from src.models.database import BotConfig, BotInstance
from src.models.enums import BotStatus
from src.models.session import get_session
from src.strategy import StrategyRegistry  # noqa: F401 — triggers registration
from src.strategy.liquidation_hunter import LiquidationHunterStrategy  # noqa: F401 — registers strategy
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Maximum number of bots per user
MAX_BOTS_PER_USER = 10


class BotOrchestrator:
    """
    Supervisor that manages all BotWorker instances.

    Each bot is an asyncio-based worker identified by its bot_config_id.
    The orchestrator handles lifecycle, recovery, and status reporting.
    """

    def __init__(self):
        self._workers: Dict[int, BotWorker] = {}  # bot_config_id -> BotWorker
        self._lock = asyncio.Lock()
        self._scheduler = AsyncIOScheduler()  # Shared scheduler for all bots
        # Per-user locks for atomic risk-check-then-trade execution.
        # Prevents concurrent trades from bypassing daily loss limits.
        self._user_trade_locks: Dict[int, asyncio.Lock] = {}

    async def start_bot(self, bot_config_id: int) -> bool:
        """
        Start a bot by its config ID.

        Returns:
            True if started successfully
        """
        async with self._lock:
            return await self._start_bot_locked(bot_config_id)

    async def _start_bot_locked(self, bot_config_id: int) -> bool:
        """Internal: start bot while holding lock."""
        # Check if already running
        if bot_config_id in self._workers and self._workers[bot_config_id].status == BotStatus.RUNNING:
            raise ValueError(f"Bot {bot_config_id} is already running")

        # Enforce per-user bot limit
        async with get_session() as session:
            result = await session.execute(
                select(BotConfig).where(BotConfig.id == bot_config_id)
            )
            config = result.scalar_one_or_none()
            if config:
                user_bot_count = sum(
                    1 for w in self._workers.values()
                    if w.config and w.config.user_id == config.user_id
                    and w.status == BotStatus.RUNNING
                )
                if user_bot_count >= MAX_BOTS_PER_USER:
                    raise ValueError(
                        f"Maximum of {MAX_BOTS_PER_USER} bots per user reached"
                    )

        # Ensure shared scheduler is running
        if not self._scheduler.running:
            self._scheduler.start()

        # Resolve user_id for the per-user trade lock
        user_trade_lock = None
        if config:
            user_trade_lock = self.get_user_trade_lock(config.user_id)

        # Create and initialize worker with shared scheduler + per-user trade lock
        worker = BotWorker(
            bot_config_id,
            scheduler=self._scheduler,
            user_trade_lock=user_trade_lock,
        )
        success = await worker.initialize()

        if not success:
            # Record error in DB
            await self._update_instance_state(bot_config_id, False, worker.error_message)
            raise ValueError(worker.error_message or "Bot initialization failed")

        # Start the worker
        await worker.start()
        self._workers[bot_config_id] = worker

        # Record running state in DB
        await self._update_instance_state(bot_config_id, True)

        logger.info(f"Orchestrator: Bot {bot_config_id} started")

        # Broadcast event via WebSocket
        self._broadcast_event(
            worker.config.user_id,
            "bot_started",
            {"bot_id": bot_config_id, "status": worker.get_status_dict()},
        )

        return True

    async def stop_bot(self, bot_config_id: int) -> bool:
        """
        Stop a running bot.

        Returns:
            True if stopped successfully
        """
        async with self._lock:
            return await self._stop_bot_locked(bot_config_id)

    async def _stop_bot_locked(self, bot_config_id: int) -> bool:
        """Internal: stop bot while holding lock."""
        worker = self._workers.get(bot_config_id)
        if not worker or worker.status != "running":
            return False

        user_id = worker.config.user_id if worker.config else None

        await worker.stop()
        del self._workers[bot_config_id]

        # Update DB
        await self._update_instance_state(bot_config_id, False)

        logger.info(f"Orchestrator: Bot {bot_config_id} stopped")

        # Broadcast event via WebSocket
        if user_id is not None:
            self._broadcast_event(
                user_id, "bot_stopped", {"bot_id": bot_config_id}
            )

        return True

    async def restart_bot(self, bot_config_id: int) -> bool:
        """Stop and start a bot."""
        async with self._lock:
            # Stop if running
            if bot_config_id in self._workers:
                await self._stop_bot_locked(bot_config_id)

            # Start fresh
            return await self._start_bot_locked(bot_config_id)

    async def restore_on_startup(self):
        """
        Restore bots that were running before server shutdown.

        Called during FastAPI lifespan startup (before API accepts requests).
        The per-iteration lock acquisition is safe because no concurrent
        start_bot() calls can occur until lifespan startup completes.
        """
        logger.info("Orchestrator: Restoring bots from database...")

        # Start shared scheduler if not already running
        if not self._scheduler.running:
            self._scheduler.start()

        async with get_session() as session:
            # Find all enabled bot configs
            result = await session.execute(
                select(BotConfig).where(BotConfig.is_enabled.is_(True))
            )
            enabled_configs = result.scalars().all()

        restored = 0
        failed = 0

        for config in enabled_configs:
            try:
                async with self._lock:
                    success = await self._start_bot_locked(config.id)
                if success:
                    restored += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Orchestrator: Failed to restore bot {config.id} ({config.name}): {e}")
                failed += 1

        logger.info(f"Orchestrator: Restored {restored} bots, {failed} failed")

    async def stop_all_for_user(self, user_id: int) -> int:
        """Stop all bots for a specific user."""
        async with self._lock:
            stopped = 0
            for bot_id, worker in list(self._workers.items()):
                if worker.config and worker.config.user_id == user_id:
                    if worker.status == BotStatus.RUNNING:
                        await self._stop_bot_locked(bot_id)
                        stopped += 1
            return stopped

    async def shutdown_all(self):
        """Gracefully stop all running bots (called on app shutdown)."""
        async with self._lock:
            for bot_id in list(self._workers.keys()):
                worker = self._workers[bot_id]
                if worker.status == BotStatus.RUNNING:
                    try:
                        await worker.stop()
                    except Exception as e:
                        logger.error(f"Orchestrator: Error stopping bot {bot_id}: {e}")

            # Mark all as not running in DB
            try:
                async with get_session() as session:
                    await session.execute(
                        update(BotInstance).where(
                            BotInstance.is_running.is_(True)
                        ).values(is_running=False, stopped_at=datetime.now(timezone.utc))
                    )
            except Exception as e:
                logger.error(f"Orchestrator: Error updating DB on shutdown: {e}")

            # Shutdown shared scheduler
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)

            self._workers.clear()
            logger.info("Orchestrator: All bots shut down")

    def get_status(self, user_id: int) -> List[dict]:
        """Get status of all bots for a user."""
        statuses = []
        for worker in self._workers.values():
            if worker.config and worker.config.user_id == user_id:
                statuses.append(worker.get_status_dict())
        return statuses

    def get_bot_status(self, bot_config_id: int) -> Optional[dict]:
        """Get status of a specific bot."""
        worker = self._workers.get(bot_config_id)
        if worker:
            return worker.get_status_dict()
        return None

    def is_running(self, bot_config_id: int) -> bool:
        """Check if a specific bot is running."""
        worker = self._workers.get(bot_config_id)
        return worker is not None and worker.status == BotStatus.RUNNING

    def get_running_count(self, user_id: int) -> int:
        """Count running bots for a user."""
        return sum(
            1 for w in self._workers.values()
            if w.config and w.config.user_id == user_id and w.status == BotStatus.RUNNING
        )

    def get_user_trade_lock(self, user_id: int) -> asyncio.Lock:
        """Get a per-user lock for atomic risk-check-then-trade execution.

        Multiple bots for the same user share this lock so that concurrent
        trades cannot bypass the daily loss limit. The lock is created lazily.
        """
        if user_id not in self._user_trade_locks:
            self._user_trade_locks[user_id] = asyncio.Lock()
        return self._user_trade_locks[user_id]

    async def _update_instance_state(self, bot_config_id: int, is_running: bool, error_msg: Optional[str] = None):
        """Update or create BotInstance record in database."""
        try:
            async with get_session() as session:
                # Find existing instance for this bot config
                result = await session.execute(
                    select(BotInstance).where(
                        BotInstance.bot_config_id == bot_config_id,
                    )
                )
                instance = result.scalar_one_or_none()

                worker = self._workers.get(bot_config_id)
                config = worker.config if worker else None

                if instance:
                    instance.is_running = is_running
                    instance.error_message = error_msg
                    if is_running:
                        instance.started_at = datetime.now(timezone.utc)
                        instance.stopped_at = None
                    else:
                        instance.stopped_at = datetime.now(timezone.utc)
                    if config:
                        instance.demo_mode = config.mode in ("demo", "both")
                else:
                    # Create new instance
                    instance = BotInstance(
                        user_id=config.user_id if config else 0,
                        bot_config_id=bot_config_id,
                        exchange_type=config.exchange_type if config else "unknown",
                        is_running=is_running,
                        demo_mode=config.mode in ("demo", "both") if config else True,
                        started_at=datetime.now(timezone.utc) if is_running else None,
                        error_message=error_msg,
                    )
                    session.add(instance)

        except Exception as e:
            logger.error(f"Orchestrator: DB state update error: {e}")

    @staticmethod
    def _broadcast_event(user_id: int, event_type: str, data: dict) -> None:
        """Fire-and-forget WebSocket broadcast."""
        try:
            from src.api.websocket.manager import ws_manager
            asyncio.create_task(ws_manager.broadcast_to_user(user_id, event_type, data))
        except Exception as e:
            logger.debug("WS broadcast failed: %s", e)
