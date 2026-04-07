"""Factory for creating exchange client and websocket instances."""

from src.exchanges.base import ExchangeClient, ExchangeWebSocket
from src.exchanges.rate_limiter import ExchangeRateLimiter
from src.models.enums import ExchangeType
from src.utils.logger import get_logger

logger = get_logger(__name__)


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
    try:
        exchange = ExchangeType(exchange_type.lower().strip())
    except ValueError:
        raise ValueError(
            f"Unsupported exchange: '{exchange_type}'. "
            f"Supported: {', '.join(e.value for e in ExchangeType)}"
        )

    # Shared rate limiter per exchange type
    rate_limiter = ExchangeRateLimiter.get(exchange.value)

    if exchange == ExchangeType.BITGET:
        from src.exchanges.bitget.client import BitgetExchangeClient
        return BitgetExchangeClient(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
            rate_limiter=rate_limiter,
            **kwargs,
        )
    elif exchange == ExchangeType.WEEX:
        from src.exchanges.weex.client import WeexClient
        return WeexClient(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
            rate_limiter=rate_limiter,
            **kwargs,
        )
    elif exchange == ExchangeType.HYPERLIQUID:
        from src.exchanges.hyperliquid.client import HyperliquidClient
        return HyperliquidClient(
            api_key=api_key,
            api_secret=api_secret,
            demo_mode=demo_mode,
            rate_limiter=rate_limiter,
            **kwargs,
        )
    elif exchange == ExchangeType.BITUNIX:
        from src.exchanges.bitunix.client import BitunixClient
        return BitunixClient(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
            rate_limiter=rate_limiter,
            **kwargs,
        )
    elif exchange == ExchangeType.BINGX:
        from src.exchanges.bingx.client import BingXClient
        return BingXClient(
            api_key=api_key,
            api_secret=api_secret,
            demo_mode=demo_mode,
            rate_limiter=rate_limiter,
            **kwargs,
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
    try:
        exchange = ExchangeType(exchange_type.lower().strip())
    except ValueError:
        raise ValueError(
            f"Unsupported exchange: '{exchange_type}'. "
            f"Supported: {', '.join(e.value for e in ExchangeType)}"
        )

    if exchange == ExchangeType.BITGET:
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        return BitgetExchangeWebSocket(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
            **kwargs,
        )
    elif exchange == ExchangeType.WEEX:
        from src.exchanges.weex.websocket import WeexWebSocket
        return WeexWebSocket(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
            **kwargs,
        )
    elif exchange == ExchangeType.HYPERLIQUID:
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        return HyperliquidWebSocket(
            api_key=api_key,
            api_secret=api_secret,
            demo_mode=demo_mode,
            **kwargs,
        )
    elif exchange == ExchangeType.BITUNIX:
        from src.exchanges.bitunix.websocket import BitunixWebSocket
        return BitunixWebSocket(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
            **kwargs,
        )
    elif exchange == ExchangeType.BINGX:
        from src.exchanges.bingx.websocket import BingXWebSocket
        return BingXWebSocket(
            api_key=api_key,
            api_secret=api_secret,
            demo_mode=demo_mode,
            **kwargs,
        )


def get_supported_exchanges() -> list:
    """Return list of supported exchange identifiers."""
    return [e.value for e in ExchangeType]


#: Exchanges whose demo/paper environment can be accessed with the user's
#: **live** API credentials via a request header or a separate endpoint URL
#: (so we don't need separate demo keys to be stored).
#:
#: - Bitget: ``paptrading: 1`` header on the live API
#: - BingX: ``VST`` virtual simulated trading uses the same key on a
#:   separate base URL
#:
#: For exchanges NOT in this set (Hyperliquid, Weex, Bitunix), a demo client
#: can only be built when dedicated demo credentials are stored in the
#: connection row.
_EXCHANGES_WITH_HEADER_BASED_DEMO = {"bitget", "bingx"}


async def get_all_user_clients(
    user_id: int, db,
) -> list[tuple[str, bool, ExchangeClient]]:
    """Load all ExchangeConnections for a user and create client instances.

    Fix for #141: a user can run a bot in demo mode against a connection
    that only stores live credentials (on Bitget the same live key activates
    the paper-trading environment via a header). Previously the factory
    created exactly one client per exchange — picking live if present —
    which left demo trades invisible to the portfolio endpoint.

    Now every (connection, mode) combination that can be built from the
    stored credentials produces a client:

    - ``conn.api_key_encrypted`` present → live client for this exchange
    - ``conn.demo_api_key_encrypted`` present → demo client
    - ``conn.api_key_encrypted`` present **and** exchange is in
      ``_EXCHANGES_WITH_HEADER_BASED_DEMO`` → also a demo client using the
      live key (Bitget ``paptrading`` header, BingX VST)

    Args:
        user_id: User ID
        db: AsyncSession

    Returns:
        A list of ``(exchange_type, demo_mode, client)`` tuples. Empty if
        the user has no usable credentials on any connection.
    """
    from sqlalchemy import select
    from src.models.database import ExchangeConnection
    from src.utils.encryption import decrypt_value

    result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user_id)
    )
    connections = result.scalars().all()

    clients: list[tuple[str, bool, ExchangeClient]] = []

    def _try_create(
        conn: ExchangeConnection,
        demo_mode: bool,
        key_enc: str | None,
        secret_enc: str | None,
        passphrase_enc: str | None,
    ) -> None:
        if not key_enc or not secret_enc:
            return
        try:
            client = create_exchange_client(
                exchange_type=conn.exchange_type,
                api_key=decrypt_value(key_enc),
                api_secret=decrypt_value(secret_enc),
                passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
                demo_mode=demo_mode,
            )
            clients.append((conn.exchange_type, demo_mode, client))
        except Exception as e:  # pragma: no cover — exchange-specific init errors
            logger.warning(
                f"Failed to initialize {conn.exchange_type} "
                f"({'demo' if demo_mode else 'live'}): {e}"
            )

    for conn in connections:
        # Live client (one per connection that has live credentials)
        _try_create(
            conn,
            demo_mode=False,
            key_enc=conn.api_key_encrypted,
            secret_enc=conn.api_secret_encrypted,
            passphrase_enc=conn.passphrase_encrypted,
        )

        # Demo client from dedicated demo credentials (if stored)
        _try_create(
            conn,
            demo_mode=True,
            key_enc=conn.demo_api_key_encrypted,
            secret_enc=conn.demo_api_secret_encrypted,
            passphrase_enc=conn.demo_passphrase_encrypted,
        )

        # Demo client from LIVE credentials for exchanges that support
        # header-based paper trading (Bitget, BingX). Only create if no
        # demo client was built from dedicated demo credentials above.
        if (
            conn.exchange_type in _EXCHANGES_WITH_HEADER_BASED_DEMO
            and conn.api_key_encrypted
            and not conn.demo_api_key_encrypted
        ):
            _try_create(
                conn,
                demo_mode=True,
                key_enc=conn.api_key_encrypted,
                secret_enc=conn.api_secret_encrypted,
                passphrase_enc=conn.passphrase_encrypted,
            )

    return clients


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
            "supports_demo": False,
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
        "bitunix": {
            "name": "bitunix",
            "display_name": "Bitunix",
            "supports_demo": False,
            "auth_type": "hmac_sha256",
            "api_style": "rest",
            "requires_passphrase": True,
        },
        "bingx": {
            "name": "bingx",
            "display_name": "BingX",
            "supports_demo": True,
            "auth_type": "hmac_sha256",
            "api_style": "rest",
            "requires_passphrase": False,
        },
    }
    if exchange_type not in info:
        raise ValueError(f"Unknown exchange: {exchange_type}")
    return info[exchange_type]
