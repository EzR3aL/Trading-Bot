"""Placeholder for Phase 1 extraction of TradeGate. See issue #326.

The concrete TradeGate will own the branch logic currently in
``RiskManager.can_trade(symbol=None)`` — global vs. per-symbol, halted
sets, trade-count limits, loss-limit gating + ``_halt_trading`` side
effect, and the Profit Lock-In dynamic-limit calculation.

See ``src/bot/components/risk/protocols.py::TradeGateProtocol`` for the
Phase 1 contract.
"""

from __future__ import annotations
