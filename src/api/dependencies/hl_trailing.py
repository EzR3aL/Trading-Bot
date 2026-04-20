"""Dependency wiring for the :class:`HLTrailingEmulator` singleton (#216).

Hyperliquid has no native trailing-stop primitive, so the bot runs a
single per-process watchdog to emulate one. The singleton lives here
for the same reason :class:`RiskStateManager` does:

* **One watchdog per process** — multiple watchdogs would multiply HL
  read traffic without adding coverage. Bots + API both use the same
  singleton so the 2-Phase-Commit lock map in RSM is honoured.
* **Reuses the RSM factory chain** — credentials are decrypted once via
  ``get_risk_state_manager()``'s exchange factory. The emulator inherits
  it so there is no separate secret-handling code path.
"""

from __future__ import annotations

from typing import Optional

from src.api.dependencies.risk_state import (
    _make_exchange_client_factory,
    get_risk_state_manager,
)
from src.bot.hl_trailing_emulator import HLTrailingEmulator
from src.models.session import get_session

# Module-level singleton. Tests may swap it via set_hl_trailing_emulator.
_emulator: Optional[HLTrailingEmulator] = None


def get_hl_trailing_emulator() -> HLTrailingEmulator:
    """Return the process-wide :class:`HLTrailingEmulator` singleton.

    The emulator keeps internal state (running task, stop event). One
    instance per process is required — multiple would each open their
    own HL read channel and race on the same ``TradeRecord.highest_price``
    column.
    """
    global _emulator
    if _emulator is None:
        _emulator = HLTrailingEmulator(
            exchange_client_factory=_make_exchange_client_factory(),
            session_factory=get_session,
            risk_state_manager=get_risk_state_manager(),
        )
    return _emulator


def set_hl_trailing_emulator(emulator: Optional[HLTrailingEmulator]) -> None:
    """Override the singleton — intended for tests only."""
    global _emulator
    _emulator = emulator
