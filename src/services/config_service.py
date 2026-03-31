"""Shared helpers for config sub-routers.

Centralises DB lookups and response builders so that
config_exchange, config_trading, config_hyperliquid and
config_affiliate can import them without circular dependencies.
"""

from typing import Any, Dict, List, Optional

import aiohttp
import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.config import ExchangeConnectionResponse
from src.models.database import ExchangeConnection, User, UserConfig
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Exchange ping URLs ──────────────────────────────────────────────

EXCHANGE_PING_URLS: Dict[str, Dict[str, Any]] = {
    "bitget": {"label": "Bitget", "url": "https://api.bitget.com/api/v2/public/time"},
    "weex": {"label": "Weex", "url": "https://api.weex.com/api/v2/public/time"},
    "hyperliquid": {"label": "Hyperliquid", "url": "https://api.hyperliquid.xyz/info", "method": "POST", "json_body": {"type": "meta"}},
    "bitunix": {"label": "Bitunix", "url": "https://fapi.bitunix.com/api/v1/common/server_time"},
    "bingx": {"label": "BingX", "url": "https://open-api.bingx.com/openApi/swap/v2/server/time"},
}


# ── DB helpers ──────────────────────────────────────────────────────

async def get_or_create_config(
    user: User, db: AsyncSession
) -> UserConfig:
    """Get user config or create a default one."""
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        config = UserConfig(user_id=user.id, exchange_type="bitget")
        db.add(config)
        await db.flush()
        await db.refresh(config)
    return config


async def get_user_connections(
    user_id: int, db: AsyncSession
) -> List[ExchangeConnection]:
    """Get all exchange connections for a user."""
    result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user_id)
    )
    return list(result.scalars().all())


def conn_to_response(conn: ExchangeConnection) -> ExchangeConnectionResponse:
    """Convert an ExchangeConnection to its API response model."""
    return ExchangeConnectionResponse(
        exchange_type=conn.exchange_type,
        api_keys_configured=bool(conn.api_key_encrypted),
        demo_api_keys_configured=bool(conn.demo_api_key_encrypted),
        affiliate_uid=getattr(conn, "affiliate_uid", None),
        affiliate_verified=getattr(conn, "affiliate_verified", None) if getattr(conn, "affiliate_uid", None) else None,
    )


async def get_admin_exchange_conn(exchange_type: str, db: AsyncSession):
    """Get the first admin user's live exchange connection for affiliate API calls."""
    result = await db.execute(
        select(ExchangeConnection).join(User).where(
            User.role == "admin",
            ExchangeConnection.exchange_type == exchange_type,
            ExchangeConnection.api_key_encrypted.isnot(None),
        ).limit(1)
    )
    return result.scalar_one_or_none()


# ── Ping helper ─────────────────────────────────────────────────────

async def ping_service(
    session: aiohttp.ClientSession,
    url: str,
    method: str = "GET",
    json_body: Optional[Dict] = None,
    timeout: float = 3.0,
) -> Dict[str, Any]:
    """Ping a URL and return status + latency."""
    start = time.monotonic()
    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        if method == "POST":  # pragma: no cover -- POST health check
            req = session.post(url, json=json_body or {}, timeout=client_timeout)
        else:
            req = session.get(url, timeout=client_timeout)
        async with req as resp:
            latency_ms = round((time.monotonic() - start) * 1000)
            return {"reachable": resp.status < 500, "status_code": resp.status, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000)
        return {"reachable": False, "status_code": None, "latency_ms": latency_ms, "error": type(e).__name__}


# ── Hyperliquid client helper ───────────────────────────────────────

def create_hl_client(conn: ExchangeConnection, use_demo: bool):
    """Create a temporary HyperliquidClient from stored credentials."""
    from src.errors import ERR_NO_DEMO_API_KEYS_HL, ERR_NO_LIVE_API_KEYS_HL
    from src.exchanges.factory import create_exchange_client

    if use_demo:
        if not conn.demo_api_key_encrypted:  # pragma: no cover -- HL key validation
            raise HTTPException(status_code=400, detail=ERR_NO_DEMO_API_KEYS_HL)
        return create_exchange_client(
            exchange_type="hyperliquid",
            api_key=decrypt_value(conn.demo_api_key_encrypted),
            api_secret=decrypt_value(conn.demo_api_secret_encrypted),
            demo_mode=True,
        )
    else:
        if not conn.api_key_encrypted:  # pragma: no cover -- HL key validation
            raise HTTPException(status_code=400, detail=ERR_NO_LIVE_API_KEYS_HL)
        return create_exchange_client(
            exchange_type="hyperliquid",
            api_key=decrypt_value(conn.api_key_encrypted),
            api_secret=decrypt_value(conn.api_secret_encrypted),
            demo_mode=False,
        )


async def async_none():
    """Helper that returns None for asyncio.gather when a task is skipped."""
    return None
