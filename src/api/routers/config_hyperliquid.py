"""Hyperliquid-specific config endpoints (builder code, referral, revenue)."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.config import BuilderApprovalConfirm, HLAdminSettingsUpdate
from src.auth.dependencies import get_current_admin, get_current_user
from src.errors import (
    ERR_BUILDER_FEE_NOT_FOUND,
    ERR_INVALID_BUILDER_ADDRESS,
    ERR_INVALID_REFERRAL_CODE,
    ERR_NO_HL_CONNECTION,
    ERR_NO_HL_CONNECTION_PLAIN,
    ERR_REFERRAL_CHECK_FAILED,
    ERR_REFERRAL_DEPOSIT_NEEDED,
    ERR_REFERRAL_ENTER_CODE_NEEDED,
    ERR_REFERRAL_WRONG_CODE,
    ERR_REVENUE_SUMMARY_FAILED,
)
from src.models.database import ExchangeConnection, TradeRecord, User
from src.models.session import get_db
from src.services.config_service import (
    async_none,
    create_hl_client,
    create_hl_mainnet_read_client,
)
from src.utils.logger import get_logger
from src.api.rate_limit import limiter

#: Hyperliquid's hard minimum deposit via the Arbitrum bridge. Any USDC below
#: this threshold is lost on deposit — we surface this in the UX so users
#: don't send dust and then wonder why the referral didn't register.
HL_MIN_DEPOSIT_USDC = 5.0

#: Required action returned by verify_referral so the frontend can render
#: concrete next-steps instead of a generic error string.
REFERRAL_ACTION_VERIFIED = "VERIFIED"
REFERRAL_ACTION_DEPOSIT_NEEDED = "DEPOSIT_NEEDED"
REFERRAL_ACTION_ENTER_CODE_MANUALLY = "ENTER_CODE_MANUALLY"
REFERRAL_ACTION_WRONG_REFERRER = "WRONG_REFERRER"


def _shorten_wallet(address: str) -> str:
    """Return ``0xABCD...1234`` for log/UI display."""
    if not address or len(address) < 10:
        return address or ""
    return f"{address[:6]}...{address[-4:]}"

_logger = get_logger(__name__)

router = APIRouter()


# ── Admin settings ──────────────────────────────────────────────────


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


# ── Builder config & approval ───────────────────────────────────────


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
    client = create_hl_client(conn, use_demo)
    approved_fee = None
    try:
        # Check with stored wallet address first, then signing wallet if different
        approved_fee = await client.check_builder_fee_approval()
        if approved_fee is None and signing_wallet:
            approved_fee = await client.check_builder_fee_approval(user_address=signing_wallet)
        # Retry once after short delay (propagation)
        if approved_fee is None:
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

    _logger.warning(
        f"Builder fee check failed: approved_fee={approved_fee}, "
        f"required={builder_fee}, no signing_wallet provided"
    )
    raise HTTPException(
        status_code=400,
        detail=ERR_BUILDER_FEE_NOT_FOUND,
    )


# ── Referral ────────────────────────────────────────────────────────


@router.post("/hyperliquid/verify-referral")
@limiter.limit("10/minute")
async def verify_referral(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User-facing: check referral via HL API and return structured diagnostics.

    Returns a JSON body with enough state for the frontend to render a
    concrete "what to do next" UI instead of a generic error. On success
    (``verified=True``), the user's connection is marked verified in DB.
    On failure, HTTP 400 is raised with a ``detail`` dict containing:

    - ``error``: localized message
    - ``required_action``: one of VERIFIED / DEPOSIT_NEEDED / ENTER_CODE_MANUALLY / WRONG_REFERRER
    - ``wallet_address``: the checksummed address that was checked
    - ``wallet_short``: ``0xABCD...1234`` for display
    - ``account_value_usd``: HL balance (float)
    - ``cum_volume_usd``: cumulative trading volume on HL (float)
    - ``referred_by``: the raw ``referredBy`` field from HL (may be null)
    - ``referral_code``: our configured code (e.g. TRADINGDEPARTMENT)
    - ``referral_link``: full https URL
    - ``min_deposit_usdc``: HL minimum deposit (5.0)
    - ``deposit_url``: HL Arbitrum bridge URL
    - ``enter_code_url``: HL referrals page URL

    Referral state always comes from MAINNET because Hyperliquid referrals
    do not exist on testnet. The user's demo_mode flag only affects the
    trading endpoint, not read-only referral/account diagnostics.
    """
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
        return {
            "verified": True,
            "required_action": REFERRAL_ACTION_VERIFIED,
            "message": "Kein Referral erforderlich.",
        }

    if conn.referral_verified:
        return {
            "verified": True,
            "required_action": REFERRAL_ACTION_VERIFIED,
            "message": "Bereits verifiziert.",
        }

    # Force MAINNET for all referral/account reads — referrals don't exist on testnet
    client = create_hl_mainnet_read_client(conn)
    wallet_address = client.wallet_address
    wallet_short = _shorten_wallet(wallet_address)
    try:
        referral_info = await client.get_referral_info()
        user_state = await client.get_user_state()
    finally:
        await client.close()

    # Extract wallet metrics
    account_value = 0.0
    if user_state and isinstance(user_state, dict):
        margin = user_state.get("marginSummary", {}) or {}
        try:
            account_value = float(margin.get("accountValue", 0) or 0)
        except (TypeError, ValueError):
            account_value = 0.0

    cum_volume = 0.0
    if referral_info and isinstance(referral_info, dict):
        try:
            cum_volume = float(referral_info.get("cumVlm", 0) or 0)
        except (TypeError, ValueError):
            cum_volume = 0.0

    referred_by = None
    if referral_info:
        referred_by = (
            referral_info.get("referredBy")
            or referral_info.get("referred_by")
        )

    # Build the base diagnostic payload that every branch returns
    diag = {
        "wallet_address": wallet_address,
        "wallet_short": wallet_short,
        "account_value_usd": round(account_value, 2),
        "cum_volume_usd": round(cum_volume, 2),
        "referred_by": referred_by,
        "referral_code": referral_code,
        "referral_link": f"https://app.hyperliquid.xyz/join/{referral_code}",
        "min_deposit_usdc": HL_MIN_DEPOSIT_USDC,
        "deposit_url": "https://app.hyperliquid.xyz/deposit",
        "enter_code_url": "https://app.hyperliquid.xyz/referrals",
    }

    # ── Case 1: No referrer set at all ────────────────────────────────
    if not referred_by:
        if account_value < HL_MIN_DEPOSIT_USDC:
            # Wallet has never deposited (or deposited less than minimum).
            # Without a deposit the referral can't bind via the link flow.
            raise HTTPException(
                status_code=400,
                detail={
                    **diag,
                    "required_action": REFERRAL_ACTION_DEPOSIT_NEEDED,
                    "error": ERR_REFERRAL_DEPOSIT_NEEDED.format(
                        wallet_short=wallet_short,
                        referral_code=referral_code,
                    ),
                },
            )
        # Wallet HAS a balance but no referrer — user must enter the code
        # manually on the HL referrals page.
        raise HTTPException(
            status_code=400,
            detail={
                **diag,
                "required_action": REFERRAL_ACTION_ENTER_CODE_MANUALLY,
                "error": ERR_REFERRAL_ENTER_CODE_NEEDED.format(
                    wallet_short=wallet_short,
                    account_value=account_value,
                    referral_code=referral_code,
                ),
            },
        )

    # ── Case 2: Has a referrer — verify it matches ours ───────────────
    # referred_by can be a dict {"referrer": "0x...", "code": "MYCODE"}
    # or a plain string (older API versions).
    referrer_code = None
    if isinstance(referred_by, dict):
        referrer_code = referred_by.get("code") or referred_by.get("referralCode")
    elif isinstance(referred_by, str):
        referrer_code = referred_by

    # Accept if referrer code matches OR if referrer address matches builder address
    builder_address = hl_cfg.get("builder_address", "")
    code_match = bool(
        referrer_code and str(referrer_code).lower() == str(referral_code).lower()
    )
    addr_match = bool(
        referrer_code
        and builder_address
        and str(referrer_code).lower() == str(builder_address).lower()
    )

    if not code_match and not addr_match:
        raise HTTPException(
            status_code=400,
            detail={
                **diag,
                "required_action": REFERRAL_ACTION_WRONG_REFERRER,
                "error": ERR_REFERRAL_WRONG_CODE.format(
                    wallet_short=wallet_short,
                    found_code=referrer_code or "unknown",
                    referral_code=referral_code,
                ),
            },
        )

    # ── Case 3: Verified successfully ─────────────────────────────────
    conn.referral_verified = True
    conn.referral_verified_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "verified": True,
        "required_action": REFERRAL_ACTION_VERIFIED,
        **diag,
    }


@router.get("/hyperliquid/referral-status")
async def get_referral_status(
    mode: Optional[Literal["live", "demo"]] = None,  # kept for backwards compat
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Check referral status (admin only).

    Always queries Hyperliquid **mainnet** — the ``mode`` query parameter is
    accepted for backwards compatibility but ignored, because Hyperliquid
    referrals do not exist on testnet.
    """
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

    try:
        client = create_hl_mainnet_read_client(conn)
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
    except HTTPException:  # pragma: no cover -- re-raise HTTP errors
        raise
    except Exception as e:
        _logger.error("Referral check failed: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=ERR_REFERRAL_CHECK_FAILED)


# ── Revenue summary ─────────────────────────────────────────────────


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
        client = create_hl_client(conn, use_demo)

        # Gather builder status, referral info, and fee tier in parallel
        approved_fee, referral_info, user_fees = await asyncio.gather(
            client.check_builder_fee_approval() if builder_address else async_none(),
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
    except HTTPException:  # pragma: no cover -- re-raise HTTP errors
        raise
    except Exception as e:
        _logger.error("Revenue summary failed: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=ERR_REVENUE_SUMMARY_FAILED)
