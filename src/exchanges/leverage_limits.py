"""Static per-exchange max leverage lookup.

This is an APPROXIMATION used by the bot builder to give the user immediate
feedback when configuring a copy-trading bot. The exchange itself remains
the source of truth — at trade execution time, leverage that exceeds the
real exchange limit is caught and reported.

Numbers reflect public docs as of 2026-04. Update if the exchanges change them.
"""

from typing import Optional


class ExchangeNotSupported(ValueError):
    """Raised when an exchange has no leverage limits configured."""


# Per-exchange: per-symbol overrides + default fallback
_LIMITS: dict[str, dict[str, int]] = {
    "bitget": {
        "_default": 50,
        "BTCUSDT": 125,
        "ETHUSDT": 125,
        "SOLUSDT": 75,
    },
    "bingx": {
        "_default": 50,
        "BTC-USDT": 125,
        "ETH-USDT": 100,
    },
    "hyperliquid": {
        "_default": 25,
        "BTC": 50,
        "ETH": 50,
        "SOL": 20,
    },
    "bitunix": {
        "_default": 50,
        "BTCUSDT": 100,
    },
    "weex": {
        "_default": 50,
        "BTCUSDT": 100,
    },
}


def get_max_leverage(exchange: str, symbol: str) -> int:
    """Return the max leverage for a symbol on a given exchange.

    Falls back to the exchange's `_default` if the symbol is not in the
    override list. Raises `ExchangeNotSupported` for unknown exchanges.
    """
    table = _LIMITS.get(exchange.lower())
    if table is None:
        raise ExchangeNotSupported(f"No leverage limits configured for {exchange}")
    return table.get(symbol, table["_default"])


def get_supported_exchanges() -> list[str]:
    return sorted(_LIMITS.keys())
