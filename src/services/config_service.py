"""Shared helpers and read-handler service for config sub-routers.

Centralises DB lookups and response builders so that
config_exchange, config_trading, config_hyperliquid and
config_affiliate can import them without circular dependencies.

ARCH-C1 Phase 3 PR-1 (#289) adds a second layer on top of the original
helpers: FastAPI-free handler functions that the thin router adapters
delegate to. The extracted handlers are pure reads (no mutations, no
external API calls), returning plain dicts that the router projects onto
Pydantic response models.
"""

import json
from typing import Any, Dict, List, Optional

import aiohttp
import time

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.config import ExchangeConnectionResponse
from src.models.database import ConfigChangeLog, ExchangeConnection, User, UserConfig
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


def create_hl_mainnet_read_client(conn: ExchangeConnection):
    """Create a mainnet-only HyperliquidClient for read-only queries.

    Hyperliquid referrals and account state live on mainnet regardless of
    whether the user is running in demo (testnet) mode. For reads like
    ``get_referral_info`` / ``get_user_state`` we must always query mainnet.

    Uses whichever credentials the user has (preferring live, falling back
    to demo wallet address + secret since the EVM address is the same on
    mainnet and testnet).
    """
    from src.errors import ERR_NO_HL_CONNECTION
    from src.exchanges.factory import create_exchange_client

    if conn.api_key_encrypted:
        api_key = decrypt_value(conn.api_key_encrypted)
        api_secret = decrypt_value(conn.api_secret_encrypted)
    elif conn.demo_api_key_encrypted:
        api_key = decrypt_value(conn.demo_api_key_encrypted)
        api_secret = decrypt_value(conn.demo_api_secret_encrypted)
    else:
        raise HTTPException(status_code=400, detail=ERR_NO_HL_CONNECTION)

    return create_exchange_client(
        exchange_type="hyperliquid",
        api_key=api_key,
        api_secret=api_secret,
        demo_mode=False,  # force mainnet — referrals don't exist on testnet
    )


async def async_none():
    """Helper that returns None for asyncio.gather when a task is skipped."""
    return None


# ── Read-handler service functions (ARCH-C1 Phase 3 PR-1, #289) ─────
#
# These handler-level helpers are called by thin router adapters. They
# stay FastAPI-free: no Depends, no HTTPException, no Request. The
# router parses query params, calls the service, and maps the returned
# plain dict onto a Pydantic response model.


async def get_user_config_response(
    user: User, db: AsyncSession
) -> Dict[str, Any]:
    """Build the ``GET /api/config/`` response payload for a user.

    Reads (and lazily creates) the user's ``UserConfig`` row plus all
    of their ``ExchangeConnection`` rows, then assembles the shape
    the router wraps in ``ConfigResponse``. Returns ``connections`` as
    already-projected ``ExchangeConnectionResponse`` models because the
    existing ``conn_to_response`` helper produces them directly and the
    router just needs to forward the list.

    Behavior preserved verbatim from the pre-extract handler — same
    JSON-decoded ``trading_config`` / ``strategy_config`` shape, same
    deprecated ``api_keys_configured`` / ``demo_api_keys_configured``
    flags derived from the legacy ``UserConfig`` columns.
    """
    config = await get_or_create_config(user, db)
    connections = await get_user_connections(user.id, db)

    trading: Optional[Dict[str, Any]] = None
    if config.trading_config:
        trading = json.loads(config.trading_config)

    strategy: Optional[Dict[str, Any]] = None
    if config.strategy_config:
        strategy = json.loads(config.strategy_config)

    return {
        "trading": trading,
        "strategy": strategy,
        "connections": [conn_to_response(c) for c in connections],
        "exchange_type": config.exchange_type,
        "api_keys_configured": bool(config.api_key_encrypted),
        "demo_api_keys_configured": bool(config.demo_api_key_encrypted),
    }


async def list_exchange_connections(
    user: User, db: AsyncSession
) -> Dict[str, List[ExchangeConnectionResponse]]:
    """Return the ``GET /api/config/exchange-connections`` payload.

    Thin wrapper around ``get_user_connections`` that projects each row
    through ``conn_to_response`` and wraps the list under the
    ``connections`` key expected by the frontend.
    """
    connections = await get_user_connections(user.id, db)
    return {"connections": [conn_to_response(c) for c in connections]}


async def list_config_changes(
    user: User,
    db: AsyncSession,
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    action: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """Return the paginated config-change audit trail for a user.

    Mirrors ``GET /api/config-changes/`` exactly — same filter semantics
    (user-scoped, optional ``entity_type`` / ``entity_id`` / ``action``),
    same ``created_at DESC`` ordering, same page-size bounds (validation
    stays on the router via ``Query(..., ge=1, le=100)`` regex / bounds).

    The ``changes`` blob is decoded from JSON; malformed rows surface as
    ``None`` rather than raising, matching the pre-extract behavior.
    """
    filters = [ConfigChangeLog.user_id == user.id]
    if entity_type:
        filters.append(ConfigChangeLog.entity_type == entity_type)
    if entity_id is not None:
        filters.append(ConfigChangeLog.entity_id == entity_id)
    if action:
        filters.append(ConfigChangeLog.action == action)

    count_result = await db.execute(
        select(func.count(ConfigChangeLog.id)).where(*filters)
    )
    total = count_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await db.execute(
        select(ConfigChangeLog)
        .where(*filters)
        .order_by(ConfigChangeLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    logs = result.scalars().all()

    items: List[Dict[str, Any]] = []
    for log in logs:
        changes: Optional[Dict[str, Any]] = None
        if log.changes:
            try:
                changes = json.loads(log.changes)
            except (json.JSONDecodeError, TypeError):
                changes = None
        items.append({
            "id": log.id,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "action": log.action,
            "changes": changes,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
