"""Exchange connection CRUD, testing, and connectivity status endpoints."""

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.config import ExchangeConnectionUpdate
from src.auth.dependencies import get_current_user
from src.errors import (
    ERR_CONNECTION_FAILED,
    ERR_INVALID_ETH_ADDRESS,
    ERR_INVALID_HEX_KEY,
    ERR_NO_API_KEYS,
    ERR_NO_API_KEYS_FOR,
    ERR_NO_CONNECTION_FOR,
    ERR_NO_DEMO_API_KEYS,
    ERR_NO_LIVE_API_KEYS,
)
from src.models.database import ExchangeConnection, User
from src.models.enums import EXCHANGE_PATTERN
from src.models.session import get_db
from src.services.config_service import (
    EXCHANGE_PING_URLS,
    conn_to_response,
    get_or_create_config,
    get_user_connections,
    ping_service,
)
from src.utils.circuit_breaker import circuit_registry
from src.utils.encryption import decrypt_value, encrypt_value
from src.utils.logger import get_logger
from src.api.rate_limit import limiter

_logger = get_logger(__name__)

router = APIRouter()

# ── Exchange Connection CRUD ─────────────────────────────────────────


@router.get("/exchange-connections")
async def get_exchange_connections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all exchange connections for the user."""
    connections = await get_user_connections(user.id, db)
    return {"connections": [conn_to_response(c) for c in connections]}


@router.put("/exchange-connections/{exchange_type}")
@limiter.limit("5/minute")
async def upsert_exchange_connection(
    request: Request,
    data: ExchangeConnectionUpdate,
    exchange_type: str = Path(pattern=EXCHANGE_PATTERN),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update API keys for a specific exchange."""
    # Validate Hyperliquid wallet address / private key format
    if exchange_type == "hyperliquid":
        _HEX_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
        _HEX_KEY = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
        for addr_field, label in [
            (data.api_key, "Wallet address"),
            (data.demo_api_key, "Testnet wallet address"),
        ]:
            if addr_field and not _HEX_ADDR.match(addr_field):
                raise HTTPException(
                    status_code=400,
                    detail=ERR_INVALID_ETH_ADDRESS.format(label=label),
                )
        for key_field, label in [
            (data.api_secret, "Private key"),
            (data.demo_api_secret, "Testnet private key"),
        ]:
            if key_field and not _HEX_KEY.match(key_field):
                raise HTTPException(
                    status_code=400,
                    detail=ERR_INVALID_HEX_KEY.format(label=label),
                )

    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == exchange_type,
        )
    )
    conn = result.scalar_one_or_none()
    is_new = conn is None

    if not conn:
        conn = ExchangeConnection(user_id=user.id, exchange_type=exchange_type)
        db.add(conn)

    # For Hyperliquid: detect wallet change and reset approval flags.
    # The API key IS the wallet address, so if it changes, approvals are invalid.
    if exchange_type == "hyperliquid" and not is_new:
        wallet_changed = False
        if data.api_key and conn.api_key_encrypted:
            old_key = decrypt_value(conn.api_key_encrypted)
            if old_key.lower() != data.api_key.lower():
                wallet_changed = True
        if data.demo_api_key and conn.demo_api_key_encrypted:
            old_demo = decrypt_value(conn.demo_api_key_encrypted)
            if old_demo.lower() != data.demo_api_key.lower():
                wallet_changed = True
        if wallet_changed:
            conn.builder_fee_approved = False
            conn.builder_fee_approved_at = None
            conn.referral_verified = False
            conn.referral_verified_at = None
            _logger.info(
                f"Hyperliquid wallet changed for user {user.id} — "
                f"reset builder_fee_approved and referral_verified"
            )

    if data.api_key:
        conn.api_key_encrypted = encrypt_value(data.api_key)
    if data.api_secret:
        conn.api_secret_encrypted = encrypt_value(data.api_secret)
    if data.passphrase:
        conn.passphrase_encrypted = encrypt_value(data.passphrase)
    if data.demo_api_key:
        conn.demo_api_key_encrypted = encrypt_value(data.demo_api_key)
    if data.demo_api_secret:
        conn.demo_api_secret_encrypted = encrypt_value(data.demo_api_secret)
    if data.demo_passphrase:
        conn.demo_passphrase_encrypted = encrypt_value(data.demo_passphrase)

    from src.utils.event_logger import log_event
    await log_event("config_changed", f"Exchange connection '{exchange_type}' updated", user_id=user.id)

    # Flush to get conn.id for new connections
    await db.flush()

    from src.utils.config_audit import log_config_change
    await log_config_change(
        user_id=user.id, entity_type="exchange_connection", entity_id=conn.id,
        action="create" if is_new else "update",
        new_data={"exchange_type": exchange_type, **data.model_dump(exclude_unset=True)},
    )

    return {"status": "ok", "message": f"{exchange_type} API keys updated"}


@router.delete("/exchange-connections/{exchange_type}")
@limiter.limit("5/minute")
async def delete_exchange_connection(
    request: Request,
    exchange_type: str = Path(pattern=EXCHANGE_PATTERN),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete API keys for a specific exchange."""
    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == exchange_type,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail=ERR_NO_CONNECTION_FOR.format(name=exchange_type))

    conn_id = conn.id
    await db.delete(conn)

    from src.utils.config_audit import log_config_change
    await log_config_change(
        user_id=user.id, entity_type="exchange_connection", entity_id=conn_id,
        action="delete", old_data={"exchange_type": exchange_type},
    )

    return {"status": "ok", "message": f"{exchange_type} connection deleted"}


@router.post("/exchange-connections/{exchange_type}/test")
@limiter.limit("3/minute")
async def test_exchange_connection(
    request: Request,
    exchange_type: str = Path(pattern=EXCHANGE_PATTERN),
    mode: Optional[Literal["live", "demo"]] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test connection for a specific exchange."""
    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == exchange_type,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=400, detail=ERR_NO_API_KEYS_FOR.format(exchange_type=exchange_type))

    if mode == "live":
        if not conn.api_key_encrypted:
            raise HTTPException(status_code=400, detail=ERR_NO_LIVE_API_KEYS)
        use_demo = False
    elif mode == "demo":
        if not conn.demo_api_key_encrypted:
            raise HTTPException(status_code=400, detail=ERR_NO_DEMO_API_KEYS)
        use_demo = True
    else:
        if not conn.api_key_encrypted and not conn.demo_api_key_encrypted:
            raise HTTPException(status_code=400, detail=ERR_NO_API_KEYS)
        use_demo = bool(conn.demo_api_key_encrypted)

    try:
        from src.exchanges.factory import create_exchange_client

        if use_demo:
            client = create_exchange_client(
                exchange_type=exchange_type,
                api_key=decrypt_value(conn.demo_api_key_encrypted),
                api_secret=decrypt_value(conn.demo_api_secret_encrypted),
                passphrase=decrypt_value(conn.demo_passphrase_encrypted) if conn.demo_passphrase_encrypted else "",
                demo_mode=True,
            )
        else:
            client = create_exchange_client(
                exchange_type=exchange_type,
                api_key=decrypt_value(conn.api_key_encrypted),
                api_secret=decrypt_value(conn.api_secret_encrypted),
                passphrase=decrypt_value(conn.passphrase_encrypted) if conn.passphrase_encrypted else "",
                demo_mode=False,
            )

        balance = await client.get_account_balance()
        await client.close()

        return {
            "status": "ok",
            "exchange": exchange_type,
            "balance": balance.total,
            "currency": balance.currency,
            "mode": "demo" if use_demo else "live",
        }
    except Exception as e:
        _logger.error("Exchange connection test failed: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=ERR_CONNECTION_FAILED)


# ── Connection Status (Ping) ────────────────────────────────────────


@router.get("/connections")
async def get_connections_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check connectivity to all external data sources and services."""
    await get_or_create_config(user, db)  # ensure config exists (side effect)
    user_connections = await get_user_connections(user.id, db)

    # Build data source services dynamically from registry
    from src.data.data_source_registry import DATA_SOURCES, PROVIDER_HEALTH_URLS

    services: Dict[str, Dict[str, Any]] = {}

    # One ping per unique external provider (avoid redundant requests)
    pinged_providers: Dict[str, str] = {}  # provider -> service key
    for ds in DATA_SOURCES:
        if ds.provider == "Calculated":
            # No external dependency -- always reachable
            services[f"ds_{ds.id}"] = {
                "label": ds.name, "type": "data_source",
                "category": ds.category, "provider": ds.provider,
                "url": None, "shared_with": None,
            }
            continue

        health_url = PROVIDER_HEALTH_URLS.get(ds.provider)
        if not health_url:  # pragma: no cover -- unknown provider skip
            continue

        if ds.provider in pinged_providers:
            # Share ping result with the first source from this provider
            services[f"ds_{ds.id}"] = {
                "label": ds.name, "type": "data_source",
                "category": ds.category, "provider": ds.provider,
                "url": health_url, "shared_with": pinged_providers[ds.provider],
            }
        else:
            pinged_providers[ds.provider] = f"ds_{ds.id}"
            services[f"ds_{ds.id}"] = {
                "label": ds.name, "type": "data_source",
                "category": ds.category, "provider": ds.provider,
                "url": health_url, "shared_with": None,
            }

    # Add exchange pings for all supported exchanges (configured + unconfigured)
    configured_exchanges = {c.exchange_type for c in user_connections}
    for ex_type, ping_info in EXCHANGE_PING_URLS.items():
        services[f"exchange_{ex_type}"] = {
            "label": ping_info["label"],
            "type": "exchange",
            "url": ping_info["url"],
            "method": ping_info.get("method", "GET"),
            "json_body": ping_info.get("json_body"),
            "configured": ex_type in configured_exchanges,
        }

    # Collect services that need actual pinging (unique URLs only, skip unconfigured exchanges)
    services_to_ping = [
        n for n in services
        if services[n].get("url")
        and not services[n].get("shared_with")
        and services[n].get("configured", True)  # skip unconfigured exchanges
    ]

    # Ping all in parallel (GDELT gets extra timeout)
    async with aiohttp.ClientSession() as http:
        coros = [
            ping_service(
                http, services[n]["url"],
                method=services[n].get("method", "GET"),
                json_body=services[n].get("json_body"),
                timeout=5.0 if "GDELT" in services[n].get("provider", "") else 3.0,
            )
            for n in services_to_ping
        ]
        pings = await asyncio.gather(*coros, return_exceptions=True)

    # Store ping results by service key
    ping_results_map: Dict[str, Dict[str, Any]] = {}
    for svc_name, ping_result in zip(services_to_ping, pings):
        if isinstance(ping_result, Exception):  # pragma: no cover -- gather error
            ping_results_map[svc_name] = {"reachable": False, "error": str(ping_result)}
        else:
            ping_results_map[svc_name] = ping_result

    results: Dict[str, Any] = {}
    for svc_name in services:
        svc = services[svc_name]
        is_configured = svc.get("configured", True)

        if not is_configured:
            # Unconfigured exchanges -- skip ping, show as not configured
            ping_data: Dict[str, Any] = {"reachable": False, "latency_ms": None}
        elif svc.get("url") is None:
            # Calculated sources -- always reachable
            ping_data = {"reachable": True, "latency_ms": 0}
        elif svc.get("shared_with"):
            # Reuse ping from the first source of the same provider
            ping_data = ping_results_map.get(svc["shared_with"], {"reachable": False, "error": "no ping"})
        else:
            ping_data = ping_results_map.get(svc_name, {"reachable": False, "error": "no ping"})

        result_entry: Dict[str, Any] = {
            "label": svc["label"],
            "type": svc["type"],
            "category": svc.get("category", ""),
            "provider": svc.get("provider", ""),
            **ping_data,
        }
        if not is_configured:
            result_entry["configured"] = False
        results[svc_name] = result_entry

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": results,
        "circuit_breakers": circuit_registry.get_all_statuses(),
    }
