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


class TradeStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class TradeSide(str, Enum):
    LONG = "long"
    SHORT = "short"
