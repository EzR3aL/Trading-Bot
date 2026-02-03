"""Factory for creating exchange client and websocket instances."""

from src.exchanges.base import ExchangeClient, ExchangeWebSocket


def create_exchange_client(
    exchange_type: str,
    api_key: str,
    api_secret: str,
    passphrase: str = "",
    demo_mode: bool = True,
    **kwargs,
) -> ExchangeClient:
    """
    Create an exchange client instance.

    Args:
        exchange_type: Exchange identifier ('bitget', 'weex', 'hyperliquid')
        api_key: API key
        api_secret: API secret
        passphrase: API passphrase (required for Bitget)
        demo_mode: Whether to use demo/paper trading
        **kwargs: Additional exchange-specific parameters

    Returns:
        ExchangeClient instance

    Raises:
        ValueError: If exchange type is not supported
    """
    if exchange_type == "bitget":
        from src.exchanges.bitget.client import BitgetExchangeClient
        return BitgetExchangeClient(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
            **kwargs,
        )
    elif exchange_type == "weex":
        from src.exchanges.weex.client import WeexClient
        return WeexClient(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
            **kwargs,
        )
    elif exchange_type == "hyperliquid":
        from src.exchanges.hyperliquid.client import HyperliquidClient
        return HyperliquidClient(
            api_key=api_key,
            api_secret=api_secret,
            demo_mode=demo_mode,
            **kwargs,
        )
    else:
        raise ValueError(
            f"Unsupported exchange: '{exchange_type}'. "
            f"Supported: bitget, weex, hyperliquid"
        )


def create_exchange_websocket(
    exchange_type: str,
    api_key: str = "",
    api_secret: str = "",
    passphrase: str = "",
    demo_mode: bool = True,
    **kwargs,
) -> ExchangeWebSocket:
    """
    Create an exchange websocket instance.

    Args:
        exchange_type: Exchange identifier
        api_key: API key (for authenticated channels)
        api_secret: API secret
        passphrase: API passphrase
        demo_mode: Whether to use demo mode
        **kwargs: Additional parameters

    Returns:
        ExchangeWebSocket instance

    Raises:
        ValueError: If exchange type is not supported
    """
    if exchange_type == "bitget":
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        return BitgetExchangeWebSocket(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
            **kwargs,
        )
    elif exchange_type == "weex":
        from src.exchanges.weex.websocket import WeexWebSocket
        return WeexWebSocket(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
            **kwargs,
        )
    elif exchange_type == "hyperliquid":
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        return HyperliquidWebSocket(
            api_key=api_key,
            api_secret=api_secret,
            demo_mode=demo_mode,
            **kwargs,
        )
    else:
        raise ValueError(
            f"Unsupported exchange: '{exchange_type}'. "
            f"Supported: bitget, weex, hyperliquid"
        )


def get_supported_exchanges() -> list:
    """Return list of supported exchange identifiers."""
    return ["bitget", "weex", "hyperliquid"]


def get_exchange_info(exchange_type: str) -> dict:
    """Return metadata about an exchange."""
    info = {
        "bitget": {
            "name": "bitget",
            "display_name": "Bitget",
            "supports_demo": True,
            "auth_type": "hmac_sha256_passphrase",
            "api_style": "rest_v2",
            "requires_passphrase": True,
        },
        "weex": {
            "name": "weex",
            "display_name": "Weex",
            "supports_demo": True,
            "auth_type": "hmac_sha256",
            "api_style": "rest",
            "requires_passphrase": True,
        },
        "hyperliquid": {
            "name": "hyperliquid",
            "display_name": "Hyperliquid",
            "supports_demo": True,
            "auth_type": "eth_wallet",
            "api_style": "json_rpc",
            "requires_passphrase": False,
        },
    }
    if exchange_type not in info:
        raise ValueError(f"Unknown exchange: {exchange_type}")
    return info[exchange_type]
