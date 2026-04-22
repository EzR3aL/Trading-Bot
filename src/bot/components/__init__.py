"""BotWorker component package (ARCH-H1, issue #266).

Target architecture: the five current mixins in ``src/bot/`` — TradeExecutor,
PositionMonitor, TradeCloser, HyperliquidGates, Notifications — become
composition-owned components on the ``BotWorker``. This package holds the
scaffolding (protocols + shared dependency dataclass) for that migration.

This PR is Phase 0 (scaffolding only). No component is extracted yet;
``BotWorker`` still inherits from the mixin classes. The full extraction
plan lives in ``Anleitungen/refactor_plan_bot_worker_composition.md``.
"""

from src.bot.components.deps import BotWorkerDeps
from src.bot.components.protocols import (
    NotifierProtocol,
    PositionMonitorProtocol,
    TradeCloserProtocol,
    TradeExecutorProtocol,
)

__all__ = [
    "BotWorkerDeps",
    "NotifierProtocol",
    "PositionMonitorProtocol",
    "TradeCloserProtocol",
    "TradeExecutorProtocol",
]
