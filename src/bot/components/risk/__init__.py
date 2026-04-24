"""Risk-state components (ARCH-H2 Phase 0 scaffolding, issue #326).

Phase 1 will extract ``DailyStatsAggregator``, ``TradeGate``,
``AlertThrottler``, ``RiskStatePersistence`` out of
``src/risk/risk_manager.py`` (DailyStats + ``can_trade`` + persistence)
and the alert-dedupe state currently inlined in
``src/bot/bot_worker.py`` (``_risk_alerts_sent`` + midnight reset) into
the Protocols declared here. Phase 2 rewires ``RiskManager`` as a
façade and removes the alert-dedupe state from ``BotWorker``.

Only scaffolding (Protocols + deps dataclass + empty module stubs)
lives here today. No behaviour change. See the Phase 0/1/2 split in
the issue for details.
"""
from src.bot.components.risk.alert_throttler import AlertThrottler
from src.bot.components.risk.daily_stats import DailyStats, DailyStatsAggregator
from src.bot.components.risk.protocols import (
    AlertThrottlerProtocol,
    DailyStatsAggregatorProtocol,
    RiskComponentDeps,
    RiskStatePersistenceProtocol,
    TradeGateProtocol,
)

__all__ = [
    "DailyStatsAggregatorProtocol",
    "TradeGateProtocol",
    "AlertThrottlerProtocol",
    "RiskStatePersistenceProtocol",
    "RiskComponentDeps",
    "AlertThrottler",
    "DailyStats",
    "DailyStatsAggregator",
]
