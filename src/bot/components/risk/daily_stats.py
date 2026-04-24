"""Placeholder for Phase 1 extraction of DailyStatsAggregator. See issue #326.

The concrete aggregator will own the mutable ``DailyStats`` snapshot
currently held by ``RiskManager._daily_stats`` and expose:

* ``initialize_day(starting_balance)``
* ``get_daily_stats()``
* ``record_trade_entry(...)``
* ``record_trade_exit(...)``

See ``src/bot/components/risk/protocols.py::DailyStatsAggregatorProtocol``
for the Phase 1 contract. The characterization tests in
``tests/unit/bot/test_risk_state_manager_characterization.py`` freeze
the observable behaviour this implementation must preserve.
"""

from __future__ import annotations
