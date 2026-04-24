"""Placeholder for Phase 1 extraction of RiskStatePersistence. See issue #326.

The concrete persistence component will own the DB truth-source logic
from Epic #188 currently in ``RiskManager.load_stats_from_db`` +
``RiskManager._save_stats_to_db`` — upsert-on-``risk_stats``-table, JSON
serialisation of the ``DailyStats`` snapshot, and the swallow-on-error
contract that lets a failing DB never break the in-memory bot.

See ``src/bot/components/risk/protocols.py::RiskStatePersistenceProtocol``
for the Phase 1 contract.
"""

from __future__ import annotations
