"""RiskStatePersistence component: DB truth-source I/O for DailyStats (#188).

Extracted from ``src.risk.risk_manager.RiskManager`` as part of ARCH-H2
Phase 1 PR-7 (issue #326). Owns the load / save / historical-read code
paths against the ``risk_stats`` table and NOTHING else — no business
logic, no gate evaluation, no aggregation. The ``RiskManager`` façade
delegates the three DB code paths to this component.

Contracts preserved from the pre-extraction implementation:

* ``load_stats`` strips the three ``@property`` fields
  (``net_pnl`` / ``return_percent`` / ``win_rate``) from the JSON blob
  BEFORE calling ``DailyStats(**data)`` — the snapshot was historically
  serialised with those derived values via ``DailyStats.to_dict``, and
  the dataclass does not accept them as ``__init__`` kwargs.
* All three methods swallow exceptions and log a warning; the bot must
  continue running without DB history rather than crash on a transient
  failure. ``load_stats`` returns ``None``, ``save_stats`` returns
  silently, ``get_historical_stats`` returns ``[]``.
* ``save_stats`` performs an upsert: UPDATE the existing row for
  ``(bot_config_id, date)`` if present, otherwise INSERT a new row.

See ``src/bot/components/risk/protocols.py::RiskStatePersistenceProtocol``
for the Phase 1 contract, and
``tests/unit/bot/test_risk_state_manager_characterization.py``
(``TestRiskStatePersistenceLoad`` + ``TestExceptionSwallowContracts``)
for the frozen observable behaviour this implementation must preserve.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.risk.risk_manager import DailyStats

logger = get_logger(__name__)

# ── Computed DailyStats @property fields ────────────────────────────────
# ``DailyStats.to_dict`` writes these three derived values into the JSON
# blob, but the dataclass ``__init__`` does not accept them. The load
# path MUST strip them before reconstruction. Extracted as a named
# constant so the contract is explicit (rather than an inline tuple).
_COMPUTED_DAILYSTATS_FIELDS: tuple[str, ...] = ("net_pnl", "return_percent", "win_rate")


class RiskStatePersistence:
    """DB truth-source for risk ``DailyStats`` snapshots.

    One instance per bot; shares the bot's ``bot_config_id`` + an async
    ``session_factory`` that yields a context-managed DB session. The
    component does NOT own ``DailyStats`` itself — it is called by the
    façade with the current snapshot, and hands snapshots back out on
    load. Fire-and-forget scheduling is the caller's responsibility.
    """

    def __init__(
        self,
        bot_config_id: Optional[int],
        session_factory: Optional[Callable[..., Any]],
        dailystats_cls: Optional[type] = None,
    ) -> None:
        """Build a persistence component.

        Args:
            bot_config_id: Target bot's ``bot_configs.id``. ``None`` means
                DB persistence is disabled (memory-only mode); all three
                methods short-circuit to their no-op returns.
            session_factory: Async-context-manager factory matching the
                ``src.models.session.get_session`` signature. ``None``
                also disables DB persistence.
            dailystats_cls: Injection hook for ``DailyStats`` (lets the
                load path be unit-tested without importing the real
                dataclass). Falls back to ``src.risk.risk_manager.DailyStats``
                at first-use to avoid an import cycle at module load.
        """
        self._bot_config_id = bot_config_id
        self._session_factory = session_factory
        self._dailystats_cls = dailystats_cls
        self._enabled = bot_config_id is not None and session_factory is not None

    @property
    def enabled(self) -> bool:
        """``True`` iff this component will actually touch the DB."""
        return self._enabled

    def _get_dailystats_cls(self) -> type:
        """Lazy lookup of the ``DailyStats`` class to avoid import cycles."""
        if self._dailystats_cls is not None:
            return self._dailystats_cls
        from src.risk.risk_manager import DailyStats as _DailyStats
        return _DailyStats

    async def load_stats(self) -> Optional["DailyStats"]:
        """Load today's snapshot from the ``risk_stats`` table.

        Returns ``None`` if DB persistence is disabled, no row exists
        for today, or any read raises. The caller is responsible for
        initialising a fresh ``DailyStats`` on ``None``.
        """
        if not self._enabled:
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        try:
            # Import lazily so test environments without SQLAlchemy can
            # still import this module; the guard matches the pre-refactor
            # behaviour in ``RiskManager``.
            from sqlalchemy import select
            from src.models.database import RiskStats

            async with self._session_factory() as session:
                result = await session.execute(
                    select(RiskStats).where(
                        RiskStats.bot_config_id == self._bot_config_id,
                        RiskStats.date == today,
                    )
                )
                row = result.scalar_one_or_none()
                if row is None:
                    return None

                data = json.loads(row.stats_json)
                # Strip derived @property fields so DailyStats(**data)
                # does not choke on unexpected kwargs. This mirrors the
                # pre-extraction behaviour exactly.
                for key in _COMPUTED_DAILYSTATS_FIELDS:
                    data.pop(key, None)

                dailystats_cls = self._get_dailystats_cls()
                stats = dailystats_cls(**data)
                logger.info(
                    "Loaded risk stats from DB: %d trades, PnL: $%.2f",
                    stats.trades_executed,
                    stats.net_pnl,
                )
                return stats
        except Exception as e:  # noqa: BLE001 — contract: swallow all, log warning
            logger.warning("Failed to load risk stats from DB: %s", e)
            return None

    async def save_stats(self, stats: "DailyStats") -> None:
        """Upsert ``stats`` into the ``risk_stats`` table.

        No-op when DB persistence is disabled or ``stats`` is ``None``.
        Swallows all exceptions and logs a warning; the in-memory
        ``DailyStats`` remains the source of truth for the running
        session, and the next successful write will resync the DB.
        """
        if not self._enabled or stats is None:
            return

        try:
            from sqlalchemy import select
            from src.models.database import RiskStats

            stats_dict = stats.to_dict()
            async with self._session_factory() as session:
                result = await session.execute(
                    select(RiskStats).where(
                        RiskStats.bot_config_id == self._bot_config_id,
                        RiskStats.date == stats.date,
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.stats_json = json.dumps(stats_dict)
                    existing.daily_pnl = stats.net_pnl
                    existing.trades_count = stats.trades_executed
                    existing.is_halted = stats.is_trading_halted
                else:
                    row = RiskStats(
                        bot_config_id=self._bot_config_id,
                        date=stats.date,
                        stats_json=json.dumps(stats_dict),
                        daily_pnl=stats.net_pnl,
                        trades_count=stats.trades_executed,
                        is_halted=stats.is_trading_halted,
                    )
                    session.add(row)
        except Exception as e:  # noqa: BLE001 — contract: swallow all, log warning
            logger.warning("Failed to save risk stats to DB: %s", e)

    async def get_historical_stats(self, days: int = 30) -> List[Dict]:
        """Return up to ``days`` days of parsed stats dicts, newest first.

        Returns ``[]`` when DB persistence is disabled or on any read
        error — callers (Reports / Dashboard) must tolerate an empty
        history gracefully.
        """
        if not self._enabled:
            return []

        try:
            from sqlalchemy import select
            from src.models.database import RiskStats

            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            async with self._session_factory() as session:
                result = await session.execute(
                    select(RiskStats)
                    .where(
                        RiskStats.bot_config_id == self._bot_config_id,
                        RiskStats.date >= cutoff,
                    )
                    .order_by(RiskStats.date.desc())
                )
                rows = result.scalars().all()
                return [json.loads(r.stats_json) for r in rows]
        except Exception as e:  # noqa: BLE001 — contract: swallow all, log warning
            logger.warning("Failed to load historical stats from DB: %s", e)
            return []
