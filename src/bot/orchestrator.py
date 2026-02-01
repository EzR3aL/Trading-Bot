"""
Multi-Tenant Bot Orchestrator.

Manages multiple isolated trading bot instances, each with their own:
- Credentials (API keys)
- Configuration (trading pairs, leverage, etc.)
- Risk manager (daily limits, PnL tracking)
- Trade history

Provides lifecycle management: start, stop, health monitoring.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, List, Any
from collections import defaultdict

from src.models.bot_instance import BotInstance, BotInstanceRepository, BotConfig
from src.models.multi_tenant_trade_db import MultiTenantTradeDatabase
from src.security.credential_manager import CredentialManager, DecryptedCredential
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BotStatus(Enum):
    """Bot instance status."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class BotHealth:
    """Health information for a bot instance."""
    status: BotStatus
    last_heartbeat: Optional[datetime]
    uptime_seconds: int
    trades_today: int
    daily_pnl: float
    open_positions: int
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "uptime_seconds": self.uptime_seconds,
            "trades_today": self.trades_today,
            "daily_pnl": self.daily_pnl,
            "open_positions": self.open_positions,
            "error_message": self.error_message,
        }


@dataclass
class RunningInstance:
    """State for a running bot instance."""
    bot_instance: BotInstance
    credential: DecryptedCredential
    status: BotStatus = BotStatus.STOPPED
    started_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    error_message: Optional[str] = None
    task: Optional[asyncio.Task] = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)

    # Isolated components (to be initialized on start)
    risk_manager: Any = None
    bitget_client: Any = None


class MultiTenantOrchestrator:
    """
    Orchestrates multiple trading bot instances.

    Each instance runs in isolation with its own:
    - API credentials
    - Trading configuration
    - Risk management state
    - Trade tracking

    Usage:
        orchestrator = MultiTenantOrchestrator()
        await orchestrator.initialize()

        # Start a bot for a user
        await orchestrator.start_instance(bot_instance_id, user_id)

        # Check status
        health = await orchestrator.get_instance_health(bot_instance_id, user_id)

        # Stop gracefully
        await orchestrator.stop_instance(bot_instance_id, user_id)
    """

    def __init__(self, db_path: str = "data/trades.db"):
        """
        Initialize the orchestrator.

        Args:
            db_path: Path to the database file
        """
        self.db_path = db_path
        self._instances: Dict[int, RunningInstance] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

        # Repositories
        self._bot_repo = BotInstanceRepository(db_path)
        self._trade_db = MultiTenantTradeDatabase(db_path)
        self._cred_manager = CredentialManager(db_path)

        # Background tasks
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize the orchestrator and restore running instances."""
        if self._initialized:
            return

        logger.info("Initializing MultiTenantOrchestrator...")

        # Initialize trade database
        await self._trade_db.initialize()

        # Restore instances that were running before shutdown
        running = await self._bot_repo.get_running()
        for instance in running:
            # Mark as stopped since we just started
            await self._bot_repo.set_running(instance.id, False)
            logger.info(f"Marked bot instance {instance.id} as stopped (from previous run)")

        # Start background tasks
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        self._initialized = True
        logger.info("MultiTenantOrchestrator initialized")

    async def shutdown(self) -> None:
        """Gracefully shutdown all running instances."""
        logger.info("Shutting down MultiTenantOrchestrator...")

        # Stop all running instances
        async with self._lock:
            instance_ids = list(self._instances.keys())

        for instance_id in instance_ids:
            try:
                instance = self._instances.get(instance_id)
                if instance:
                    await self._stop_instance_internal(instance)
            except Exception as e:
                logger.error(f"Error stopping instance {instance_id}: {e}")

        # Cancel background tasks
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()

        logger.info("MultiTenantOrchestrator shutdown complete")

    async def start_instance(self, instance_id: int, user_id: int) -> bool:
        """
        Start a bot instance.

        Args:
            instance_id: Bot instance ID
            user_id: User ID (for verification)

        Returns:
            True if started successfully

        Raises:
            ValueError: If instance not found or already running
        """
        async with self._lock:
            # Check if already running
            if instance_id in self._instances:
                existing = self._instances[instance_id]
                if existing.status in (BotStatus.RUNNING, BotStatus.STARTING):
                    raise ValueError(f"Bot instance {instance_id} is already running")

            # Get bot instance
            bot_instance = await self._bot_repo.get_by_id(instance_id, user_id)
            if not bot_instance:
                raise ValueError(f"Bot instance {instance_id} not found")

            # Get credentials
            credential = await self._cred_manager.get_credential(
                bot_instance.credential_id, user_id
            )
            if not credential:
                raise ValueError(f"Credentials for instance {instance_id} not found")

            # Create running instance
            running = RunningInstance(
                bot_instance=bot_instance,
                credential=credential,
                status=BotStatus.STARTING,
                started_at=datetime.now(),
                last_heartbeat=datetime.now(),
            )
            self._instances[instance_id] = running

        try:
            # Initialize isolated components
            await self._initialize_instance_components(running)

            # Start the trading loop
            running.task = asyncio.create_task(
                self._run_instance(running)
            )

            # Update database
            await self._bot_repo.set_running(instance_id, True)
            await self._bot_repo.update_heartbeat(instance_id)

            running.status = BotStatus.RUNNING
            logger.info(f"Started bot instance {instance_id} for user {user_id}")

            return True

        except Exception as e:
            running.status = BotStatus.ERROR
            running.error_message = str(e)
            logger.error(f"Failed to start bot instance {instance_id}: {e}")
            raise

    async def stop_instance(self, instance_id: int, user_id: int, force: bool = False) -> bool:
        """
        Stop a bot instance.

        Args:
            instance_id: Bot instance ID
            user_id: User ID (for verification)
            force: If True, forcefully stop without waiting for graceful shutdown

        Returns:
            True if stopped successfully
        """
        async with self._lock:
            if instance_id not in self._instances:
                # Check if it exists in DB
                bot_instance = await self._bot_repo.get_by_id(instance_id, user_id)
                if not bot_instance:
                    raise ValueError(f"Bot instance {instance_id} not found")
                # Already stopped
                return True

            running = self._instances[instance_id]

            # Verify ownership
            if running.bot_instance.user_id != user_id:
                raise ValueError(f"Bot instance {instance_id} not found")

        await self._stop_instance_internal(running, force)
        return True

    async def _stop_instance_internal(self, running: RunningInstance, force: bool = False) -> None:
        """Internal method to stop an instance."""
        instance_id = running.bot_instance.id
        running.status = BotStatus.STOPPING

        logger.info(f"Stopping bot instance {instance_id}...")

        # Signal the trading loop to stop
        running.stop_event.set()

        if running.task and not running.task.done():
            if force:
                running.task.cancel()
            else:
                # Wait for graceful shutdown (max 30 seconds)
                try:
                    await asyncio.wait_for(running.task, timeout=30)
                except asyncio.TimeoutError:
                    logger.warning(f"Bot instance {instance_id} did not stop gracefully, forcing...")
                    running.task.cancel()

        # Clean up resources
        if running.bitget_client:
            try:
                await running.bitget_client.close()
            except Exception as e:
                logger.warning(f"Error closing bitget client: {e}")

        # Update database
        await self._bot_repo.set_running(instance_id, False)

        # Remove from instances
        async with self._lock:
            if instance_id in self._instances:
                del self._instances[instance_id]

        running.status = BotStatus.STOPPED
        logger.info(f"Stopped bot instance {instance_id}")

    async def get_instance_health(self, instance_id: int, user_id: int) -> BotHealth:
        """
        Get health information for a bot instance.

        Args:
            instance_id: Bot instance ID
            user_id: User ID (for verification)

        Returns:
            BotHealth object with current status
        """
        # Check if running
        running = self._instances.get(instance_id)

        if running and running.bot_instance.user_id == user_id:
            # Get runtime stats
            uptime = 0
            if running.started_at:
                uptime = int((datetime.now() - running.started_at).total_seconds())

            trades_today = await self._trade_db.count_trades_today(user_id)
            today = datetime.now().strftime("%Y-%m-%d")
            daily_pnl = await self._trade_db.get_daily_pnl(user_id, today)
            open_positions = len(await self._trade_db.get_open_trades(user_id))

            return BotHealth(
                status=running.status,
                last_heartbeat=running.last_heartbeat,
                uptime_seconds=uptime,
                trades_today=trades_today,
                daily_pnl=daily_pnl,
                open_positions=open_positions,
                error_message=running.error_message,
            )

        # Not running, get from database
        bot_instance = await self._bot_repo.get_by_id(instance_id, user_id)
        if not bot_instance:
            raise ValueError(f"Bot instance {instance_id} not found")

        trades_today = await self._trade_db.count_trades_today(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        daily_pnl = await self._trade_db.get_daily_pnl(user_id, today)

        return BotHealth(
            status=BotStatus.STOPPED,
            last_heartbeat=bot_instance.last_heartbeat,
            uptime_seconds=0,
            trades_today=trades_today,
            daily_pnl=daily_pnl,
            open_positions=0,
        )

    async def get_user_instances(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Get all bot instances for a user with their status.

        Args:
            user_id: User ID

        Returns:
            List of instance info dictionaries
        """
        instances = await self._bot_repo.get_by_user(user_id)
        result = []

        for inst in instances:
            info = inst.to_dict()

            # Add runtime status
            running = self._instances.get(inst.id)
            if running and running.bot_instance.user_id == user_id:
                info["runtime_status"] = running.status.value
                info["uptime_seconds"] = int(
                    (datetime.now() - running.started_at).total_seconds()
                ) if running.started_at else 0
            else:
                info["runtime_status"] = BotStatus.STOPPED.value
                info["uptime_seconds"] = 0

            result.append(info)

        return result

    async def _initialize_instance_components(self, running: RunningInstance) -> None:
        """Initialize isolated components for a bot instance."""
        from src.risk.risk_manager import RiskManager
        from src.api.bitget_client import BitgetClient

        config = running.bot_instance.config
        credential = running.credential

        # Create isolated risk manager
        running.risk_manager = RiskManager(
            max_trades_per_day=config.max_trades_per_day,
            daily_loss_limit_percent=config.daily_loss_limit_percent,
        )

        # Create Bitget client with user's credentials
        running.bitget_client = BitgetClient(
            api_key=credential.api_key,
            api_secret=credential.api_secret,
            passphrase=credential.passphrase,
            demo_mode=(credential.credential_type == "demo"),
        )

        logger.info(f"Initialized components for bot instance {running.bot_instance.id}")

    async def _run_instance(self, running: RunningInstance) -> None:
        """
        Main trading loop for a bot instance.

        This is a simplified version - in production, this would
        include the full strategy execution, position monitoring, etc.
        """
        instance_id = running.bot_instance.id
        user_id = running.bot_instance.user_id
        config = running.bot_instance.config

        logger.info(f"Bot instance {instance_id} trading loop started")
        logger.info(f"  Trading pairs: {config.trading_pairs}")
        logger.info(f"  Leverage: {config.leverage}x")

        try:
            while not running.stop_event.is_set():
                # Update heartbeat
                running.last_heartbeat = datetime.now()
                await self._bot_repo.update_heartbeat(instance_id)

                # Check if we can trade
                can_trade, reason = running.risk_manager.can_trade()
                if not can_trade:
                    logger.debug(f"Instance {instance_id} cannot trade: {reason}")

                # Main trading logic would go here:
                # 1. Fetch market data
                # 2. Run strategy
                # 3. Execute trades if signal
                # 4. Monitor open positions

                # For now, just heartbeat
                await asyncio.sleep(30)  # Check every 30 seconds

        except asyncio.CancelledError:
            logger.info(f"Bot instance {instance_id} trading loop cancelled")
        except Exception as e:
            running.status = BotStatus.ERROR
            running.error_message = str(e)
            logger.error(f"Bot instance {instance_id} error: {e}")
            raise
        finally:
            logger.info(f"Bot instance {instance_id} trading loop ended")

    async def _heartbeat_loop(self) -> None:
        """Background task to update heartbeats and check for stale instances."""
        while True:
            try:
                await asyncio.sleep(60)  # Every minute

                for instance_id, running in list(self._instances.items()):
                    if running.status == BotStatus.RUNNING:
                        # Check for stale heartbeat
                        if running.last_heartbeat:
                            age = datetime.now() - running.last_heartbeat
                            if age > timedelta(minutes=5):
                                logger.warning(
                                    f"Bot instance {instance_id} heartbeat stale ({age})"
                                )
                                running.status = BotStatus.ERROR
                                running.error_message = "Heartbeat timeout"

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")

    async def _cleanup_loop(self) -> None:
        """Background task to clean up stopped instances."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes

                async with self._lock:
                    to_remove = []
                    for instance_id, running in self._instances.items():
                        if running.status == BotStatus.STOPPED:
                            to_remove.append(instance_id)

                    for instance_id in to_remove:
                        del self._instances[instance_id]
                        logger.debug(f"Cleaned up stopped instance {instance_id}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")


# Global orchestrator instance
_orchestrator: Optional[MultiTenantOrchestrator] = None


async def get_orchestrator() -> MultiTenantOrchestrator:
    """Get or create the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MultiTenantOrchestrator()
        await _orchestrator.initialize()
    return _orchestrator
