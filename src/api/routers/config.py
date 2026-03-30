"""User configuration endpoints (per-user settings)."""

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import select, func as sa_func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.config import (
    AffiliateUidUpdate,
    AffiliateVerifyUpdate,
    BuilderApprovalConfirm,
    ConfigResponse,
    ExchangeConnectionResponse,
    ExchangeConnectionUpdate,
    HLAdminSettingsUpdate,
    StrategyConfigUpdate,
    TradingConfigUpdate,
)
from src.auth.dependencies import get_current_admin, get_current_user
from src.errors import (
    ERR_AFFILIATE_UID_NOT_FOUND,
    ERR_BUILDER_FEE_NOT_FOUND,
    ERR_CONNECTION_FAILED,
    ERR_CONNECTION_TEST_FAILED,
    ERR_INVALID_BUILDER_ADDRESS,
    ERR_INVALID_REFERRAL_CODE,
    ERR_NO_API_KEYS,
    ERR_NO_API_KEYS_FOR,
    ERR_NO_DEMO_API_KEYS,
    ERR_NO_DEMO_API_KEYS_HL,
    ERR_NO_HL_CONNECTION,
    ERR_NO_HL_CONNECTION_PLAIN,
    ERR_NO_LIVE_API_KEYS,
    ERR_NO_LIVE_API_KEYS_HL,
    ERR_REFERRAL_CHECK_FAILED,
    ERR_REFERRAL_NOT_FOUND,
    ERR_REVENUE_SUMMARY_FAILED,
    ERR_INVALID_ETH_ADDRESS,
    ERR_INVALID_HEX_KEY,
    ERR_NO_CONNECTION_FOR,
)
from src.models.database import ExchangeConnection, TradeRecord, User, UserConfig
from src.models.session import get_db
from src.utils.circuit_breaker import circuit_registry
from src.api.rate_limit import limiter
from src.models.enums import CEX_EXCHANGE_PATTERN, EXCHANGE_PATTERN
from src.utils.encryption import decrypt_value, encrypt_value
from src.utils.logger import get_logger

_config_logger = get_logger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

EXCHANGE_PING_URLS: Dict[str, Dict[str, Any]] = {
    "bitget": {"label": "Bitget", "url": "https://api.bitget.com/api/v2/public/time"},
    "weex": {"label": "Weex", "url": "https://api.weex.com/api/v2/public/time"},
    "hyperliquid": {"label": "Hyperliquid", "url": "https://api.hyperliquid.xyz/info", "method": "POST", "json_body": {"type": "meta"}},
    "bitunix": {"label": "Bitunix", "url": "https://fapi.bitunix.com/api/v1/common/server_time"},
    "bingx": {"label": "BingX", "url": "https://open-api.bingx.com/openApi/swap/v2/server/time"},
}


async def _get_or_create_config(
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


async def _get_user_connections(
    user_id: int, db: AsyncSession
) -> List[ExchangeConnection]:
    """Get all exchange connections for a user."""
    result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user_id)
    )
    return list(result.scalars().all())


def _conn_to_response(conn: ExchangeConnection) -> ExchangeConnectionResponse:
    return ExchangeConnectionResponse(
        exchange_type=conn.exchange_type,
        api_keys_configured=bool(conn.api_key_encrypted),
        demo_api_keys_configured=bool(conn.demo_api_key_encrypted),
        affiliate_uid=getattr(conn, "affiliate_uid", None),
        affiliate_verified=getattr(conn, "affiliate_verified", None) if getattr(conn, "affiliate_uid", None) else None,
    )


@router.get("", response_model=ConfigResponse)
async def get_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's configuration."""
    config = await _get_or_create_config(user, db)
    connections = await _get_user_connections(user.id, db)

    trading = None
    if config.trading_config:
        trading = TradingConfigUpdate(**json.loads(config.trading_config))

    strategy = None
    if config.strategy_config:
        strategy = StrategyConfigUpdate(**json.loads(config.strategy_config))

    conn_responses = [_conn_to_response(c) for c in connections]

    # Deprecated fields for backward compat
    has_live_keys = bool(config.api_key_encrypted)
    has_demo_keys = bool(config.demo_api_key_encrypted)

    return ConfigResponse(
        trading=trading,
        strategy=strategy,
        connections=conn_responses,
        exchange_type=config.exchange_type,
        api_keys_configured=has_live_keys,
        demo_api_keys_configured=has_demo_keys,
    )


@router.put("/trading")
@limiter.limit("10/minute")
async def update_trading_config(
    request: Request,
    data: TradingConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update trading parameters."""
    config = await _get_or_create_config(user, db)
    config.trading_config = json.dumps(data.model_dump())
    return {"status": "ok", "message": "Trading config updated"}


@router.put("/strategy")
@limiter.limit("10/minute")
async def update_strategy_config(
    request: Request,
    data: StrategyConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update strategy thresholds."""
    config = await _get_or_create_config(user, db)
    config.strategy_config = json.dumps(data.model_dump())
    return {"status": "ok", "message": "Strategy config updated"}


# ── Exchange Connection CRUD ─────────────────────────────────────────


@router.get("/exchange-connections")
async def get_exchange_connections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all exchange connections for the user."""
    connections = await _get_user_connections(user.id, db)
    return {"connections": [_conn_to_response(c) for c in connections]}


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
        from src.utils.encryption import decrypt_value
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
            _config_logger.info(
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
        _config_logger.error("Exchange connection test failed: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=ERR_CONNECTION_FAILED)


# ── Affiliate UID ───────────────────────────────────────────────────


@router.put("/exchange-connections/{exchange_type}/affiliate-uid")
@limiter.limit("10/minute")
async def set_affiliate_uid(
    request: Request,
    data: AffiliateUidUpdate,
    exchange_type: str = Path(pattern=CEX_EXCHANGE_PATTERN),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User sets their exchange UID; auto-verify via affiliate API."""
    uid = data.uid

    # Get or create user's exchange connection
    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == exchange_type,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        conn = ExchangeConnection(user_id=user.id, exchange_type=exchange_type)
        db.add(conn)

    conn.affiliate_uid = uid
    conn.affiliate_verified = False
    conn.affiliate_verified_at = None

    # Try auto-verify via admin's API keys
    verified = False
    try:
        admin_conn = await _get_admin_exchange_conn(exchange_type, db)
        if admin_conn:
            from src.exchanges.factory import create_exchange_client
            client = create_exchange_client(
                exchange_type=exchange_type,
                api_key=decrypt_value(admin_conn.api_key_encrypted),
                api_secret=decrypt_value(admin_conn.api_secret_encrypted),
                passphrase=decrypt_value(admin_conn.passphrase_encrypted) if admin_conn.passphrase_encrypted else "",
                demo_mode=False,
            )
            verified = await client.check_affiliate_uid(uid)
            await client.close()

            if verified:
                conn.affiliate_verified = True
                conn.affiliate_verified_at = datetime.now(timezone.utc)
    except Exception as e:
        _config_logger.warning(f"Affiliate UID auto-verify failed for user {user.id}: {type(e).__name__}")

    await db.flush()
    await db.commit()

    return {
        "uid": uid,
        "verified": verified,
        "message": "UID verifiziert." if verified else "UID gespeichert. Verifizierung ausstehend.",
    }


async def _get_admin_exchange_conn(exchange_type: str, db: AsyncSession):
    """Get the first admin user's live exchange connection for affiliate API calls."""
    result = await db.execute(
        select(ExchangeConnection).join(User).where(
            User.role == "admin",
            ExchangeConnection.exchange_type == exchange_type,
            ExchangeConnection.api_key_encrypted.isnot(None),
        ).limit(1)
    )
    return result.scalar_one_or_none()


# ── Connection Status (Ping) ────────────────────────────────────────


async def _ping_service(
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
        if method == "POST":  # pragma: no cover — POST health check
            req = session.post(url, json=json_body or {}, timeout=client_timeout)
        else:
            req = session.get(url, timeout=client_timeout)
        async with req as resp:
            latency_ms = round((time.monotonic() - start) * 1000)
            return {"reachable": resp.status < 500, "status_code": resp.status, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000)
        return {"reachable": False, "status_code": None, "latency_ms": latency_ms, "error": type(e).__name__}


@router.get("/connections")
async def get_connections_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check connectivity to all external data sources and services."""
    await _get_or_create_config(user, db)  # ensure config exists (side effect)
    user_connections = await _get_user_connections(user.id, db)

    # Build data source services dynamically from registry
    from src.data.data_source_registry import DATA_SOURCES, PROVIDER_HEALTH_URLS

    services: Dict[str, Dict[str, Any]] = {}

    # One ping per unique external provider (avoid redundant requests)
    pinged_providers: Dict[str, str] = {}  # provider -> service key
    for ds in DATA_SOURCES:
        if ds.provider == "Calculated":
            # No external dependency — always reachable
            services[f"ds_{ds.id}"] = {
                "label": ds.name, "type": "data_source",
                "category": ds.category, "provider": ds.provider,
                "url": None, "shared_with": None,
            }
            continue

        health_url = PROVIDER_HEALTH_URLS.get(ds.provider)
        if not health_url:  # pragma: no cover — unknown provider skip
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
            _ping_service(
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
        if isinstance(ping_result, Exception):  # pragma: no cover — gather error
            ping_results_map[svc_name] = {"reachable": False, "error": str(ping_result)}
        else:
            ping_results_map[svc_name] = ping_result

    results: Dict[str, Any] = {}
    for svc_name in services:
        svc = services[svc_name]
        is_configured = svc.get("configured", True)

        if not is_configured:
            # Unconfigured exchanges — skip ping, show as not configured
            ping_data: Dict[str, Any] = {"reachable": False, "latency_ms": None}
        elif svc.get("url") is None:
            # Calculated sources — always reachable
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


# ── Hyperliquid Builder Code & Referral ────────────────────────────


@router.get("/hyperliquid/admin-settings")
async def get_hl_admin_settings(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: get current builder config (DB values + ENV fallback indicator)."""
    from src.utils.settings import get_hl_config
    from src.models.database import SystemSetting

    config = await get_hl_config()

    # Check which values come from DB vs ENV
    db_keys = await db.execute(
        select(SystemSetting.key, SystemSetting.value).where(
            SystemSetting.key.in_(["HL_BUILDER_ADDRESS", "HL_BUILDER_FEE", "HL_REFERRAL_CODE"])
        )
    )
    db_values = {row.key: row.value for row in db_keys.all()}

    return {
        "builder_address": config["builder_address"],
        "builder_fee": config["builder_fee"],
        "referral_code": config["referral_code"],
        "sources": {
            "builder_address": "db" if db_values.get("HL_BUILDER_ADDRESS") else "env" if config["builder_address"] else "none",
            "builder_fee": "db" if db_values.get("HL_BUILDER_FEE") else "env" if config["builder_fee"] else "none",
            "referral_code": "db" if db_values.get("HL_REFERRAL_CODE") else "env" if config["referral_code"] else "none",
        },
    }


@router.put("/hyperliquid/admin-settings")
@limiter.limit("10/minute")
async def update_hl_admin_settings(
    request: Request,
    data: HLAdminSettingsUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: update builder address, fee, referral code."""
    import re as _re
    from src.models.database import SystemSetting

    builder_address = (data.builder_address or "").strip()
    builder_fee = data.builder_fee
    referral_code = (data.referral_code or "").strip()

    # Validate builder address (empty = clear, otherwise must be 0x + 40 hex)
    if builder_address and not _re.match(r"^0x[0-9a-fA-F]{40}$", builder_address):
        raise HTTPException(status_code=400, detail=ERR_INVALID_BUILDER_ADDRESS)

    # Validate referral code (alphanumeric, max 50 chars)
    if referral_code and not _re.match(r"^[a-zA-Z0-9_-]+$", referral_code):
        raise HTTPException(status_code=400, detail=ERR_INVALID_REFERRAL_CODE)

    # Upsert each setting
    settings = {
        "HL_BUILDER_ADDRESS": builder_address,
        "HL_BUILDER_FEE": str(builder_fee) if builder_fee is not None else "",
        "HL_REFERRAL_CODE": referral_code,
    }

    for key, value in settings.items():
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(SystemSetting(key=key, value=value, updated_at=datetime.now(timezone.utc)))

    return {"status": "ok", "message": "Hyperliquid settings updated"}


def _create_hl_client(conn: ExchangeConnection, use_demo: bool):
    """Helper: create a temporary HyperliquidClient from stored credentials."""
    from src.exchanges.factory import create_exchange_client

    if use_demo:
        if not conn.demo_api_key_encrypted:  # pragma: no cover — HL key validation
            raise HTTPException(status_code=400, detail=ERR_NO_DEMO_API_KEYS_HL)
        return create_exchange_client(
            exchange_type="hyperliquid",
            api_key=decrypt_value(conn.demo_api_key_encrypted),
            api_secret=decrypt_value(conn.demo_api_secret_encrypted),
            demo_mode=True,
        )
    else:
        if not conn.api_key_encrypted:  # pragma: no cover — HL key validation
            raise HTTPException(status_code=400, detail=ERR_NO_LIVE_API_KEYS_HL)
        return create_exchange_client(
            exchange_type="hyperliquid",
            api_key=decrypt_value(conn.api_key_encrypted),
            api_secret=decrypt_value(conn.api_secret_encrypted),
            demo_mode=False,
        )


@router.get("/hyperliquid/builder-config")
async def get_builder_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get builder fee config for frontend wallet signing (public, all users)."""
    from src.exchanges.hyperliquid.constants import DEFAULT_BUILDER_FEE

    from src.utils.settings import get_hl_config
    hl_cfg = await get_hl_config()
    builder_address = hl_cfg["builder_address"]
    if not builder_address:
        return {"builder_configured": False}

    builder_fee = hl_cfg["builder_fee"] or DEFAULT_BUILDER_FEE
    # maxFeeRate for Hyperliquid API: percentage string
    # builder_fee is in tenths of basis points (e.g. 10 = 1bp = 0.01%)
    max_fee_rate = f"{builder_fee / 1000:.3f}%"

    # Check if user has HL connection and approval status
    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == "hyperliquid",
        )
    )
    conn = result.scalar_one_or_none()

    referral_code = hl_cfg["referral_code"]

    # Admins bypass all affiliate/referral gates
    is_admin = user.role == "admin"
    referral_required = bool(referral_code)
    referral_verified = True if is_admin else (getattr(conn, "referral_verified", False) if conn else False)
    builder_fee_approved = True if is_admin else (getattr(conn, "builder_fee_approved", False) if conn else False)

    return {
        "builder_configured": True,
        "builder_address": builder_address,
        "builder_fee": builder_fee,
        "max_fee_rate": max_fee_rate,
        "chain_id": 42161,
        "testnet_chain_id": 421614,
        "has_hl_connection": conn is not None,
        "builder_fee_approved": builder_fee_approved,
        "needs_approval": False if is_admin else (conn is not None and not builder_fee_approved),
        "referral_code": referral_code,
        "referral_required": referral_required,
        "referral_verified": referral_verified,
        "needs_referral": False if is_admin else (referral_required and not referral_verified),
    }


@router.post("/hyperliquid/confirm-builder-approval")
@limiter.limit("10/minute")
async def confirm_builder_approval(
    request: Request,
    data: BuilderApprovalConfirm = BuilderApprovalConfirm(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """After frontend wallet signing, verify approval on-chain and record in DB."""
    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == "hyperliquid",
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=400, detail=ERR_NO_HL_CONNECTION_PLAIN)

    # Frontend may pass the browser wallet address that actually signed
    signing_wallet = (data.wallet_address or "").strip().lower() or None

    from src.utils.settings import get_hl_config
    hl_cfg = await get_hl_config()
    builder_fee = hl_cfg["builder_fee"] or 10

    # Verify approval on-chain via Hyperliquid API
    use_demo = bool(conn.demo_api_key_encrypted and not conn.api_key_encrypted)
    client = _create_hl_client(conn, use_demo)
    approved_fee = None
    try:
        # Check with stored wallet address first, then signing wallet if different
        approved_fee = await client.check_builder_fee_approval()
        if approved_fee is None and signing_wallet:
            approved_fee = await client.check_builder_fee_approval(user_address=signing_wallet)
        # Retry once after short delay (propagation)
        if approved_fee is None:
            import asyncio
            await asyncio.sleep(2)
            approved_fee = await client.check_builder_fee_approval()
            if approved_fee is None and signing_wallet:
                approved_fee = await client.check_builder_fee_approval(user_address=signing_wallet)
    finally:
        await client.close()

    if approved_fee is not None and approved_fee >= builder_fee:
        conn.builder_fee_approved = True
        conn.builder_fee_approved_at = datetime.now(timezone.utc)
        await db.commit()
        return {"status": "ok", "approved_max_fee": approved_fee}

    # Final retry with longer delay for on-chain propagation
    if signing_wallet:
        import asyncio
        await asyncio.sleep(5)
        try:
            approved_fee = await client.check_builder_fee_approval(user_address=signing_wallet)
        except Exception:
            pass
        if approved_fee is not None and approved_fee >= builder_fee:
            conn.builder_fee_approved = True
            conn.builder_fee_approved_at = datetime.now(timezone.utc)
            await db.commit()
            return {"status": "ok", "approved_max_fee": approved_fee}

    _config_logger.warning(
        f"Builder fee check failed: approved_fee={approved_fee}, "
        f"required={builder_fee}, no signing_wallet provided"
    )
    raise HTTPException(
        status_code=400,
        detail=ERR_BUILDER_FEE_NOT_FOUND,
    )


@router.post("/hyperliquid/verify-referral")
@limiter.limit("10/minute")
async def verify_referral(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User-facing: check referral via HL API and save result to DB."""
    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == "hyperliquid",
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=400, detail=ERR_NO_HL_CONNECTION)

    from src.utils.settings import get_hl_config
    hl_cfg = await get_hl_config()
    referral_code = hl_cfg["referral_code"]
    if not referral_code:
        return {"verified": True, "message": "Kein Referral erforderlich."}

    if conn.referral_verified:
        return {"verified": True, "message": "Bereits verifiziert."}

    use_demo = bool(conn.demo_api_key_encrypted and not conn.api_key_encrypted)
    client = _create_hl_client(conn, use_demo)
    try:
        referral_info = await client.get_referral_info()
    finally:
        await client.close()

    referred_by = None
    if referral_info:
        referred_by = referral_info.get("referredBy") or referral_info.get("referred_by")

    if not referred_by:
        raise HTTPException(
            status_code=400,
            detail=ERR_REFERRAL_NOT_FOUND.format(referral_code=referral_code),
        )

    # Verify the referrer matches our configured referral code.
    # referred_by can be a dict {"referrer": "0x...", "code": "MYCODE"} or a string.
    referrer_code = None
    if isinstance(referred_by, dict):
        referrer_code = referred_by.get("code") or referred_by.get("referralCode")
    elif isinstance(referred_by, str):
        # Some API versions return just the address or code as string
        referrer_code = referred_by

    # Match against configured referral code (case-insensitive)
    if referrer_code and referral_code:
        # Accept if referrer code matches OR if referrer address matches builder address
        builder_address = hl_cfg.get("builder_address", "")
        code_match = str(referrer_code).lower() == str(referral_code).lower()
        addr_match = (
            builder_address
            and str(referrer_code).lower() == str(builder_address).lower()
        )
        if not code_match and not addr_match:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Dein Account wurde ueber einen anderen Referral-Code registriert. "
                    f"Bitte nutze unseren Link: "
                    f"https://app.hyperliquid.xyz/join/{referral_code}"
                ),
            )

    conn.referral_verified = True
    conn.referral_verified_at = datetime.now(timezone.utc)
    await db.commit()
    return {"verified": True, "referred_by": referred_by}


@router.get("/hyperliquid/referral-status")
async def get_referral_status(
    mode: Optional[Literal["live", "demo"]] = None,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Check referral status (admin only)."""
    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == "hyperliquid",
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=400, detail=ERR_NO_HL_CONNECTION_PLAIN)

    from src.utils.settings import get_hl_config
    hl_cfg = await get_hl_config()
    referral_code = hl_cfg["referral_code"]
    use_demo = mode == "demo" if mode else bool(conn.demo_api_key_encrypted)

    try:
        client = _create_hl_client(conn, use_demo)
        referral_info = await client.get_referral_info()
        await client.close()

        referred_by = None
        if referral_info:
            referred_by = referral_info.get("referredBy") or referral_info.get("referred_by")

        return {
            "referral_code_configured": bool(referral_code),
            "referral_code": referral_code if referral_code else None,
            "user_referred": referred_by is not None,
            "referred_by": referred_by,
            "referral_link": f"https://app.hyperliquid.xyz/join/{referral_code}" if referral_code else None,
        }
    except HTTPException:  # pragma: no cover — re-raise HTTP errors
        raise
    except Exception as e:
        _config_logger.error("Referral check failed: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=ERR_REFERRAL_CHECK_FAILED)


@router.get("/hyperliquid/revenue-summary")
async def get_revenue_summary(
    mode: Optional[Literal["live", "demo"]] = None,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get combined builder code + referral revenue overview (admin only)."""
    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == "hyperliquid",
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=400, detail=ERR_NO_HL_CONNECTION_PLAIN)

    from src.utils.settings import get_hl_config
    hl_cfg = await get_hl_config()
    builder_address = hl_cfg["builder_address"]
    referral_code = hl_cfg["referral_code"]
    use_demo = mode == "demo" if mode else bool(conn.demo_api_key_encrypted)

    try:
        client = _create_hl_client(conn, use_demo)

        # Gather builder status, referral info, and fee tier in parallel
        approved_fee, referral_info, user_fees = await asyncio.gather(
            client.check_builder_fee_approval() if builder_address else _async_none(),
            client.get_referral_info(),
            client.get_user_fees(),
        )
        await client.close()

        from src.exchanges.hyperliquid.constants import DEFAULT_BUILDER_FEE

        builder_fee = hl_cfg["builder_fee"] or DEFAULT_BUILDER_FEE

        referred_by = None
        if referral_info:
            referred_by = referral_info.get("referredBy") or referral_info.get("referred_by")

        # Query trade-based builder fee earnings from DB
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import func as sqlfunc

        _closed = sqlfunc.coalesce(TradeRecord.exit_time, TradeRecord.entry_time)
        since_30d = datetime.now(timezone.utc) - timedelta(days=30)
        trade_stats = await db.execute(
            select(
                sqlfunc.count().label("total_trades"),
                sqlfunc.sum(TradeRecord.builder_fee).label("total_builder_fees"),
            ).where(
                TradeRecord.user_id == user.id,
                TradeRecord.status == "closed",
                TradeRecord.exchange == "hyperliquid",
                _closed >= since_30d,
            )
        )
        stats_row = trade_stats.one()

        return {
            "builder": {
                "configured": bool(builder_address),
                "address": builder_address[:10] + "..." if builder_address else None,
                "fee_rate": builder_fee,
                "fee_percent": f"{builder_fee / 1000:.3f}%",
                "user_approved": approved_fee is not None if builder_address else None,
            },
            "referral": {
                "configured": bool(referral_code),
                "code": referral_code or None,
                "user_referred": referred_by is not None,
                "link": f"https://app.hyperliquid.xyz/join/{referral_code}" if referral_code else None,
            },
            "user_fees": user_fees,
            "earnings": {
                "total_builder_fees_30d": stats_row.total_builder_fees or 0,
                "trades_with_builder_fee": stats_row.total_trades or 0,
                "monthly_estimate": stats_row.total_builder_fees or 0,
            },
        }
    except HTTPException:  # pragma: no cover — re-raise HTTP errors
        raise
    except Exception as e:
        _config_logger.error("Revenue summary failed: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=ERR_REVENUE_SUMMARY_FAILED)


async def _async_none():
    """Helper that returns None for asyncio.gather when a task is skipped."""
    return None


# ── Admin: Affiliate UID management ────────────────────────────────


@router.get("/admin/affiliate-uids")
async def list_affiliate_uids(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=5, le=100),
    search: str = Query("", max_length=100),
    status: str = Query("all", pattern="^(all|pending|verified)$"),
):
    """Admin: Paginated list of users who submitted an affiliate UID."""
    base = (
        select(ExchangeConnection, User.username)
        .join(User)
        .where(ExchangeConnection.affiliate_uid.isnot(None))
    )

    # Filter by status
    if status == "pending":
        base = base.where(ExchangeConnection.affiliate_verified == False)  # noqa: E712
    elif status == "verified":
        base = base.where(ExchangeConnection.affiliate_verified == True)  # noqa: E712

    # Search by username or UID
    if search.strip():
        term = f"%{search.strip()}%"
        base = base.where(
            or_(
                User.username.ilike(term),
                ExchangeConnection.affiliate_uid.ilike(term),
            )
        )

    # Count total
    count_q = select(sa_func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Stats (always unfiltered)
    stats_base = (
        select(ExchangeConnection)
        .where(ExchangeConnection.affiliate_uid.isnot(None))
    )
    total_all = (await db.execute(
        select(sa_func.count()).select_from(stats_base.subquery())
    )).scalar() or 0
    verified_count = (await db.execute(
        select(sa_func.count()).select_from(
            stats_base.where(ExchangeConnection.affiliate_verified == True).subquery()  # noqa: E712
        )
    )).scalar() or 0
    pending_count = total_all - verified_count

    # Paginated query — sort by exchange then newest first
    offset = (page - 1) * per_page
    result = await db.execute(
        base.order_by(
            ExchangeConnection.exchange_type.asc(),
            ExchangeConnection.created_at.desc(),
        )
        .offset(offset)
        .limit(per_page)
    )
    rows = result.all()

    # Exchanges without affiliate API require manual admin verification
    MANUAL_VERIFY_EXCHANGES = {"bitunix"}

    return {
        "items": [
            {
                "connection_id": conn.id,
                "user_id": conn.user_id,
                "username": username,
                "exchange_type": conn.exchange_type,
                "affiliate_uid": conn.affiliate_uid,
                "affiliate_verified": conn.affiliate_verified,
                "affiliate_verified_at": (
                    conn.affiliate_verified_at.isoformat()
                    if conn.affiliate_verified_at
                    else None
                ),
                "submitted_at": (
                    conn.created_at.isoformat()
                    if conn.created_at
                    else None
                ),
                "updated_at": (
                    conn.updated_at.isoformat()
                    if conn.updated_at
                    else None
                ),
                "verify_method": (
                    "manual"
                    if conn.exchange_type in MANUAL_VERIFY_EXCHANGES
                    else "auto"
                ),
            }
            for conn, username in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, -(-total // per_page)),
        "stats": {
            "total": total_all,
            "verified": verified_count,
            "pending": pending_count,
        },
    }


@router.put("/admin/affiliate-uids/{connection_id}/verify")
@limiter.limit("10/minute")
async def verify_affiliate_uid(
    connection_id: int,
    request: Request,
    data: AffiliateVerifyUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: Manually verify or reject an affiliate UID."""
    verified = data.verified

    result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.id == connection_id)
    )
    conn = result.scalar_one_or_none()
    if not conn or not conn.affiliate_uid:
        raise HTTPException(status_code=404, detail=ERR_AFFILIATE_UID_NOT_FOUND)

    conn.affiliate_verified = verified
    conn.affiliate_verified_at = datetime.now(timezone.utc) if verified else None

    return {
        "connection_id": conn.id,
        "affiliate_uid": conn.affiliate_uid,
        "affiliate_verified": conn.affiliate_verified,
    }
