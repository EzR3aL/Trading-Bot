"""Shared enums for type-safe status and type fields."""

from enum import Enum


class BotStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    STARTING = "starting"
    STOPPING = "stopping"


class ExchangeType(str, Enum):
    BITGET = "bitget"
    WEEX = "weex"
    HYPERLIQUID = "hyperliquid"
    BITUNIX = "bitunix"
    BINGX = "bingx"


# Derived constants — add new exchanges ONLY to ExchangeType above
EXCHANGE_NAMES: list[str] = [e.value for e in ExchangeType]
EXCHANGE_PATTERN: str = "^(" + "|".join(EXCHANGE_NAMES) + ")$"
CEX_EXCHANGES: list[str] = [e.value for e in ExchangeType if e != ExchangeType.HYPERLIQUID]
CEX_EXCHANGE_PATTERN: str = "^(" + "|".join(CEX_EXCHANGES) + ")$"
EXCHANGE_OR_ANY_PATTERN: str = "^(any|" + "|".join(EXCHANGE_NAMES) + ")$"


class TradeStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class TradeSide(str, Enum):
    LONG = "long"
    SHORT = "short"
