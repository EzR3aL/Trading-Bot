"""Trading strategy modules.

ARCH-H7: strategies auto-register on package import. Dropping a new file
into ``src/strategy/`` with a module-level ``StrategyRegistry.register(...)``
call is enough — no edits to ``orchestrator.py`` or this __init__ are
required. The loop below imports every sibling ``.py`` file (except the
base module, the registry entry point, and underscore-prefixed helpers);
import failures are logged but never abort package loading so a single
broken strategy cannot take the whole system down.
"""

import importlib
import pkgutil
from pathlib import Path

from .base import (
    BaseStrategy,
    SignalDirection,
    StrategyRegistry,
    TradeSignal,
    check_atr_trailing_stop,
)
from src.utils.logger import get_logger

_logger = get_logger(__name__)

# Files we must NOT auto-import: the registry base itself and the package
# __init__. Underscore-prefixed modules are treated as private helpers.
_SKIP_MODULES = {"base", "__init__"}

_package_dir = Path(__file__).resolve().parent

for _module_info in pkgutil.iter_modules([str(_package_dir)]):
    _name = _module_info.name
    if _name in _SKIP_MODULES or _name.startswith("_"):
        continue
    try:
        importlib.import_module(f"{__name__}.{_name}")
    except Exception as exc:  # noqa: BLE001 — strategy load must not block startup
        _logger.error("Strategy auto-register failed for %s: %s", _name, exc)


__all__ = [
    "BaseStrategy",
    "SignalDirection",
    "StrategyRegistry",
    "TradeSignal",
    "check_atr_trailing_stop",
]
