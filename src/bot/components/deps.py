"""Shared dependency bundle for future BotWorker components (ARCH-H1).

When the mixins currently bundled in ``BotWorker`` are extracted to
standalone component classes (one per Phase 1-5 PR in the refactor plan),
each component will need access to the same handful of process-wide
singletons and per-bot handles — the exchange client, the DB session
factory, the risk-state manager, the event bus, and so on.

This dataclass exists so component ``__init__`` signatures can stay
stable across the multi-PR extraction: a component receives one
``BotWorkerDeps`` instance rather than 8-12 individual args. Today
nothing constructs one — it's scaffolding. Phase 1 (Notifier extract,
PR-3) will be the first real consumer.

Field semantics are deliberately conservative: each handle is ``Optional``
because the ``BotWorker`` construction flow currently resolves some deps
lazily (``_client`` only after DB lookup in ``start()``, ``_strategy``
after ``StrategyRegistry`` wiring). The composition refactor will tighten
this — but doing so in the scaffolding PR would break the "no behaviour
change" invariant for this step.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.exchanges.base import ExchangeClient
    from src.models.database import BotConfig


@dataclass
class BotWorkerDeps:
    """Shared state handed to each component on construction.

    Instances are owned by ``BotWorker`` — components MUST NOT mutate
    these fields. They may read. Writes to ``bot_config``-derived state
    (e.g. ``status``, ``error_message``) remain the sole responsibility
    of ``BotWorker`` itself; see the State-Ownership Matrix in
    ``Anleitungen/refactor_plan_bot_worker_composition.md``.
    """

    # Bot config snapshot. Immutable from the component's point of view.
    bot_config: Optional["BotConfig"] = None

    # Exchange client for this bot (resolved in BotWorker.start()).
    # Demo + live clients are held separately on BotWorker today; Phase 5
    # (TradeExecutor extract) will collapse to a single active client here.
    client: Optional["ExchangeClient"] = None

    # Per-symbol locks. Same dict instance as BotWorker._symbol_locks —
    # passed by reference so component and worker never fight over
    # separate lock maps.
    symbol_locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    # Per-user trade lock. Shared across all BotWorkers for the same user
    # to serialise order placement — must be the SAME asyncio.Lock instance
    # the orchestrator handed the worker, not a copy.
    user_trade_lock: Optional[asyncio.Lock] = None
