"""Affiliate UID endpoints (user + admin management)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import select, func as sa_func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.config import AffiliateUidUpdate, AffiliateVerifyUpdate
from src.auth.dependencies import get_current_admin, get_current_user
from src.errors import ERR_AFFILIATE_UID_NOT_FOUND
from src.models.database import ExchangeConnection, User
from src.models.enums import CEX_EXCHANGE_PATTERN
from src.models.session import get_db
from src.services.config_service import get_admin_exchange_conn
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger
from src.api.rate_limit import limiter

_logger = get_logger(__name__)

router = APIRouter()


# ── User: set affiliate UID ─────────────────────────────────────────


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
        admin_conn = await get_admin_exchange_conn(exchange_type, db)
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
        _logger.warning(f"Affiliate UID auto-verify failed for user {user.id}: {type(e).__name__}")

    await db.flush()
    await db.commit()

    return {
        "uid": uid,
        "verified": verified,
        "message": "UID verifiziert." if verified else "UID gespeichert. Verifizierung ausstehend.",
    }


# ── Admin: affiliate UID management ─────────────────────────────────


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

    # Paginated query -- sort by exchange then newest first
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
