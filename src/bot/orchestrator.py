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
from src.models.database import BotConfig, BotInstance, PendingTrade
from src.models.enums import BotStatus
from src.models.session import get_session
from src.strategy import StrategyRegistry  # noqa: F401 — package __init__ auto-registers all strategies
from src.constants import MAX_BOTS_PER_USER
from src.utils.logger import get_logger

logger = get_logger(__name__)


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

        logger.info("Orchestrator: Bot %s started", bot_config_id)

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

        logger.info("Orchestrator: Bot %s stopped", bot_config_id)

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

        # Mark any pending trades from a previous crash as orphaned
        await self._mark_orphaned_trades()

        # Check for position discrepancies between exchange and DB
        await self._reconcile_positions_on_startup()

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
                logger.error("Orchestrator: Failed to restore bot %s (%s): %s", config.id, config.name, e)
                failed += 1

        logger.info("Orchestrator: Restored %d bots, %d failed", restored, failed)

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

    async def shutdown_gracefully(self, grace_period: float = 20.0):
        """Gracefully stop all bots, waiting for in-flight trades.

        1. Sets shutdown flag on all workers (stops new trades immediately)
        2. Waits for in-flight operations to complete (with timeout)
        3. Logs warnings about open positions
        4. Then cleans up resources

        Args:
            grace_period: Max seconds to wait for in-flight operations per bot.
        """
        async with self._lock:
            running_workers = {
                bot_id: worker
                for bot_id, worker in self._workers.items()
                if worker.status == BotStatus.RUNNING
            }

            if not running_workers:
                logger.info("Orchestrator: No running bots to shut down")
            else:
                logger.info(
                    "Orchestrator: Graceful shutdown — stopping %d bot(s)",
                    len(running_workers),
                )

                # Phase 1: Set shutdown flag on ALL workers immediately
                for worker in running_workers.values():
                    worker._shutting_down = True

                # Phase 2: Graceful stop all workers concurrently (with timeout)
                async def _graceful_stop_one(bot_id: int, worker: BotWorker):
                    try:
                        open_positions = await worker.graceful_stop(
                            grace_period=grace_period,
                        )
                        if open_positions:
                            for pos in open_positions:
                                protection = []
                                if pos.get("has_tp"):
                                    protection.append("TP")
                                if pos.get("has_sl"):
                                    protection.append("SL")
                                prot_str = "+".join(protection) if protection else "NONE"
                                mode_str = "DEMO" if pos["demo_mode"] else "LIVE"
                                logger.warning(
                                    "Orchestrator: OPEN POSITION at shutdown — "
                                    "Bot %d | %s %s %s | size=%.6f entry=$%.2f | "
                                    "protection=%s",
                                    bot_id, pos["side"].upper(), pos["symbol"],
                                    mode_str, pos["size"], pos["entry_price"],
                                    prot_str,
                                )
                    except Exception as e:
                        logger.error(
                            "Orchestrator: Error during graceful stop of bot %d: %s",
                            bot_id, e,
                        )

                tasks = [
                    _graceful_stop_one(bot_id, worker)
                    for bot_id, worker in running_workers.items()
                ]
                await asyncio.gather(*tasks)

            # Mark all as not running in DB
            try:
                async with get_session() as session:
                    await session.execute(
                        update(BotInstance).where(
                            BotInstance.is_running.is_(True)
                        ).values(is_running=False, stopped_at=datetime.now(timezone.utc))
                    )
            except Exception as e:
                logger.error("Orchestrator: Error updating DB on shutdown: %s", e)

            # Shutdown shared scheduler
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)

            self._workers.clear()
            logger.info("Orchestrator: Graceful shutdown complete")

    async def shutdown_all(self):
        """Hard stop all running bots (fallback if graceful shutdown times out)."""
        async with self._lock:
            for bot_id in list(self._workers.keys()):
                worker = self._workers[bot_id]
                if worker.status == BotStatus.RUNNING:
                    try:
                        await worker.stop()
                    except Exception as e:
                        logger.error("Orchestrator: Error stopping bot %s: %s", bot_id, e)

            # Mark all as not running in DB
            try:
                async with get_session() as session:
                    await session.execute(
                        update(BotInstance).where(
                            BotInstance.is_running.is_(True)
                        ).values(is_running=False, stopped_at=datetime.now(timezone.utc))
                    )
            except Exception as e:
                logger.error("Orchestrator: Error updating DB on shutdown: %s", e)

            # Shutdown shared scheduler
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)

            self._workers.clear()
            logger.info("Orchestrator: All bots force-stopped")

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

    async def _mark_orphaned_trades(self):
        """Mark any pending trades from a previous crash as orphaned.

        Called once during startup. Trades stuck in 'pending' status mean
        the bot crashed mid-order — we mark them 'orphaned' so the user
        can see them and manually verify on the exchange.
        """
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(PendingTrade).where(PendingTrade.status == "pending")
                )
                orphaned = result.scalars().all()

                if not orphaned:
                    return

                now = datetime.now(timezone.utc)
                for trade in orphaned:
                    trade.status = "orphaned"
                    trade.resolved_at = now
                    trade.error_message = "Bot crashed or restarted while trade was in-flight"
                    logger.warning(
                        "Orchestrator: Orphaned pending trade #%d — bot=%d symbol=%s side=%s action=%s (created %s)",
                        trade.id, trade.bot_config_id, trade.symbol, trade.side, trade.action,
                        trade.created_at,
                    )

                logger.warning(
                    "Orchestrator: Marked %d pending trade(s) as orphaned — "
                    "check exchange positions manually",
                    len(orphaned),
                )
        except Exception as e:
            logger.error("Orchestrator: Failed to check orphaned trades: %s", e)

    async def _reconcile_positions_on_startup(self):
        """Compare exchange positions with DB open trades for each enabled bot.

        Logs warnings for any discrepancies but does NOT auto-close or modify
        anything. This is purely an alerting mechanism on startup so operators
        notice stale or untracked positions quickly.
        """
        from src.exchanges.factory import create_exchange_client
        from src.models.database import ExchangeConnection, TradeRecord
        from src.utils.encryption import decrypt_value

        try:
            async with get_session() as session:
                result = await session.execute(
                    select(BotConfig).where(BotConfig.is_enabled.is_(True))
                )
                enabled_configs = result.scalars().all()

                if not enabled_configs:
                    return

                for config in enabled_configs:
                    try:
                        # Load exchange connection for the bot owner
                        conn_result = await session.execute(
                            select(ExchangeConnection).where(
                                ExchangeConnection.user_id == config.user_id,
                                ExchangeConnection.exchange_type == config.exchange_type,
                            )
                        )
                        conn = conn_result.scalar_one_or_none()
                        if not conn:
                            continue

                        is_demo = config.mode in ("demo", "both")
                        api_key_enc = conn.demo_api_key_encrypted if is_demo else conn.api_key_encrypted
                        api_secret_enc = conn.demo_api_secret_encrypted if is_demo else conn.api_secret_encrypted
                        passphrase_enc = conn.demo_passphrase_encrypted if is_demo else conn.passphrase_encrypted

                        if not api_key_enc or not api_secret_enc:
                            continue

                        client = create_exchange_client(
                            exchange_type=config.exchange_type,
                            api_key=decrypt_value(api_key_enc),
                            api_secret=decrypt_value(api_secret_enc),
                            passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
                            demo_mode=is_demo,
                        )

                        try:
                            import asyncio
                            exchange_positions = await asyncio.wait_for(
                                client.get_open_positions(),
                                timeout=15.0,
                            )
                        except Exception as e:
                            logger.warning(
                                "Reconciliation: could not fetch positions for bot %d (%s): %s",
                                config.id, config.name, e,
                            )
                            continue
                        finally:
                            try:
                                await client.close()
                            except Exception:
                                pass

                        # Fetch open trades from DB for this bot
                        trades_result = await session.execute(
                            select(TradeRecord).where(
                                TradeRecord.bot_config_id == config.id,
                                TradeRecord.status == "open",
                            )
                        )
                        db_trades = list(trades_result.scalars().all())

                        # Build lookup maps by normalized symbol+side
                        def _normalize(symbol: str) -> str:
                            s = symbol.strip().lower()
                            for suffix in ("_umcbl", ":usdt", "-swap"):
                                s = s.replace(suffix, "")
                            for sep in ("/", "-", "_"):
                                s = s.replace(sep, "")
                            return s

                        exchange_keys = set()
                        for pos in exchange_positions:
                            if pos.size > 0:
                                exchange_keys.add(f"{_normalize(pos.symbol)}:{pos.side.lower()}")

                        db_keys = set()
                        for trade in db_trades:
                            db_keys.add(f"{_normalize(trade.symbol)}:{trade.side.lower()}")

                        untracked = exchange_keys - db_keys
                        phantom = db_keys - exchange_keys

                        if untracked:
                            logger.warning(
                                "Reconciliation: bot %d (%s) — %d UNTRACKED position(s) on exchange "
                                "(not in DB): %s",
                                config.id, config.name, len(untracked),
                                ", ".join(sorted(untracked)),
                            )
                        if phantom:
                            logger.warning(
                                "Reconciliation: bot %d (%s) — %d PHANTOM trade(s) in DB "
                                "(no matching exchange position): %s",
                                config.id, config.name, len(phantom),
                                ", ".join(sorted(phantom)),
                            )

                        if not untracked and not phantom:
                            matched = len(exchange_keys & db_keys)
                            if matched:
                                logger.info(
                                    "Reconciliation: bot %d (%s) — %d position(s) consistent",
                                    config.id, config.name, matched,
                                )

                    except Exception as e:
                        logger.error(
                            "Reconciliation: error checking bot %d (%s): %s",
                            config.id, config.name, e,
                        )

        except Exception as e:
            logger.error("Reconciliation: startup reconciliation failed: %s", e)

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

                # If worker has no config, fall back to DB lookup
                if config is None:
                    result2 = await session.execute(
                        select(BotConfig).where(BotConfig.id == bot_config_id)
                    )
                    config = result2.scalar_one_or_none()
                    if config is None:
                        logger.error(
                            "Orchestrator: Cannot update instance state — "
                            "no config found for bot_config_id=%s", bot_config_id
                        )
                        return

                if instance:
                    instance.is_running = is_running
                    instance.error_message = error_msg
                    if is_running:
                        instance.started_at = datetime.now(timezone.utc)
                        instance.stopped_at = None
                    else:
                        instance.stopped_at = datetime.now(timezone.utc)
                    instance.demo_mode = config.mode in ("demo", "both")
                else:
                    # Create new instance
                    instance = BotInstance(
                        user_id=config.user_id,
                        bot_config_id=bot_config_id,
                        exchange_type=config.exchange_type,
                        is_running=is_running,
                        demo_mode=config.mode in ("demo", "both"),
                        started_at=datetime.now(timezone.utc) if is_running else None,
                        error_message=error_msg,
                    )
                    session.add(instance)

        except Exception as e:
            logger.error("Orchestrator: DB state update error: %s", e)

    @staticmethod
    def _broadcast_event(user_id: int, event_type: str, data: dict) -> None:
        """Fire-and-forget WebSocket broadcast."""
        try:
            from src.api.websocket.manager import ws_manager
            asyncio.create_task(ws_manager.broadcast_to_user(user_id, event_type, data))
        except Exception as e:
            logger.debug("WS broadcast failed: %s", e)
