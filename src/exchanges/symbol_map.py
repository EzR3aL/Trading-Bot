"""Symbol normalization between different exchange formats."""

# Each exchange has its own symbol format for futures:
# Bitget:       "BTCUSDT" (with productType=USDT-FUTURES)
# Weex:         "BTCUSDT" (client transforms to cmt_btcusdt / cmt_btcsusdt for demo)
# Hyperliquid:  "BTC"
# Bitunix:      "BTCUSDT"
# BingX:        "BTC-USDT"

SYMBOL_MAP = {
    "bitget": {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "XRP": "XRPUSDT",
        "DOGE": "DOGEUSDT",
        "ADA": "ADAUSDT",
        "AVAX": "AVAXUSDT",
        "LINK": "LINKUSDT",
        "DOT": "DOTUSDT",
        "MATIC": "MATICUSDT",
    },
    "weex": {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "XRP": "XRPUSDT",
        "DOGE": "DOGEUSDT",
        "ADA": "ADAUSDT",
        "AVAX": "AVAXUSDT",
        "LINK": "LINKUSDT",
        "DOT": "DOTUSDT",
        "MATIC": "MATICUSDT",
    },
    "hyperliquid": {
        "BTC": "BTC",
        "ETH": "ETH",
        "SOL": "SOL",
        "XRP": "XRP",
        "DOGE": "DOGE",
        "ADA": "ADA",
        "AVAX": "AVAX",
        "LINK": "LINK",
        "DOT": "DOT",
        "MATIC": "MATIC",
    },
    "bitunix": {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "XRP": "XRPUSDT",
        "DOGE": "DOGEUSDT",
        "ADA": "ADAUSDT",
        "AVAX": "AVAXUSDT",
        "LINK": "LINKUSDT",
        "DOT": "DOTUSDT",
        "MATIC": "MATICUSDT",
    },
    "bingx": {
        "BTC": "BTC-USDT",
        "ETH": "ETH-USDT",
        "SOL": "SOL-USDT",
        "XRP": "XRP-USDT",
        "DOGE": "DOGE-USDT",
        "ADA": "ADA-USDT",
        "AVAX": "AVAX-USDT",
        "LINK": "LINK-USDT",
        "DOT": "DOT-USDT",
        "MATIC": "MATIC-USDT",
    },
}


def normalize_symbol(exchange_symbol: str, exchange: str) -> str:
    """
    Convert an exchange-specific symbol to normalized base format (e.g. "BTC").

    Args:
        exchange_symbol: Exchange-specific format (e.g. "BTCUSDT", "BTC/USDT:USDT")
        exchange: Exchange name ("bitget", "weex", "hyperliquid")

    Returns:
        Normalized base symbol (e.g. "BTC")
    """
    exchange_map = SYMBOL_MAP.get(exchange, {})
    # Reverse lookup
    for base, ex_sym in exchange_map.items():
        if ex_sym == exchange_symbol:
            return base

    # Fallback: try to strip common suffixes
    if exchange in ("bitget", "bitunix"):
        return exchange_symbol.replace("USDT", "")
    elif exchange == "weex":
        return exchange_symbol.replace("USDT", "")
    elif exchange == "hyperliquid":
        return exchange_symbol.replace("USDT", "").replace("-USDT", "")
    elif exchange == "bingx":
        return exchange_symbol.split("-")[0]

    return exchange_symbol


def to_exchange_symbol(base_symbol: str, exchange: str) -> str:
    """
    Convert a normalized base symbol to exchange-specific format.

    Args:
        base_symbol: Normalized symbol (e.g. "BTC" or "BTCUSDT")
        exchange: Exchange name

    Returns:
        Exchange-specific symbol format
    """
    # Strip USDT suffix if present to get base
    base = base_symbol.replace("USDT", "").replace("/USDT:USDT", "")

    exchange_map = SYMBOL_MAP.get(exchange, {})
    if base in exchange_map:
        return exchange_map[base]

    # Fallback: construct based on exchange convention
    if exchange in ("bitget", "bitunix"):
        return f"{base}USDT"
    elif exchange == "weex":
        return f"{base}USDT"
    elif exchange == "hyperliquid":
        return base
    elif exchange == "bingx":
        return f"{base}-USDT"

    return base_symbol


def get_supported_symbols(exchange: str) -> list:
    """Get list of supported symbols for an exchange."""
    return list(SYMBOL_MAP.get(exchange, {}).keys())
