"""Affiliate link CRUD endpoints (admin-managed, globally visible)."""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.schemas.affiliate import AffiliateLinkResponse, AffiliateLinkUpdate
from src.auth.dependencies import get_current_admin, get_current_user
from src.models.database import AffiliateLink, ExchangeConnection, User
from src.models.session import get_db

router = APIRouter(prefix="/api/affiliate-links", tags=["affiliate"])

VALID_EXCHANGES = {"bitget", "weex", "hyperliquid"}

# UID format validators per exchange
_UID_VALIDATORS = {
    "bitget": re.compile(r"^\d+$"),           # numeric only
    "weex": re.compile(r"^[A-Za-z0-9]+$"),    # alphanumeric
}


class VerifyUIDRequest(BaseModel):
    exchange_type: str
    uid: str


@router.get("", response_model=list[AffiliateLinkResponse])
async def list_affiliate_links(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List affiliate links. Admins see all (including inactive), users see only active."""
    query = select(AffiliateLink)
    if user.role != "admin":
        query = query.where(AffiliateLink.is_active.is_(True))
    result = await db.execute(query)
    return [AffiliateLinkResponse.model_validate(link) for link in result.scalars().all()]


@router.put("/{exchange}", response_model=AffiliateLinkResponse)
@limiter.limit("5/minute")
async def upsert_affiliate_link(
    request: Request,
    exchange: str,
    data: AffiliateLinkUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create or update affiliate link for an exchange (admin only)."""
    if exchange not in VALID_EXCHANGES:
        raise HTTPException(status_code=400, detail=f"Invalid exchange: {exchange}")

    result = await db.execute(
        select(AffiliateLink).where(AffiliateLink.exchange_type == exchange)
    )
    link = result.scalar_one_or_none()

    if link:
        link.affiliate_url = str(data.affiliate_url)
        link.label = data.label
        link.is_active = data.is_active
        link.uid_required = data.uid_required
    else:
        link = AffiliateLink(
            exchange_type=exchange,
            affiliate_url=str(data.affiliate_url),
            label=data.label,
            is_active=data.is_active,
            uid_required=data.uid_required,
        )
        db.add(link)

    await db.flush()
    return AffiliateLinkResponse.model_validate(link)


@router.delete("/{exchange}")
@limiter.limit("5/minute")
async def delete_affiliate_link(
    request: Request,
    exchange: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete affiliate link for an exchange (admin only)."""
    result = await db.execute(
        select(AffiliateLink).where(AffiliateLink.exchange_type == exchange)
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Affiliate-Link nicht gefunden")

    await db.delete(link)
    return {"detail": "deleted"}


@router.post("/verify-uid")
@limiter.limit("10/minute")
async def verify_uid(
    request: Request,
    data: VerifyUIDRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify a user's UID for an affiliate-linked exchange.

    Validates UID format (Bitget: numeric only, Weex: alphanumeric)
    and marks the ExchangeConnection as affiliate-verified.
    """
    exchange = data.exchange_type.lower()
    uid = data.uid.strip()

    if exchange not in VALID_EXCHANGES:
        raise HTTPException(status_code=400, detail=f"Invalid exchange: {exchange}")

    if not uid:
        raise HTTPException(status_code=400, detail="UID must not be empty")

    # Validate UID format per exchange
    validator = _UID_VALIDATORS.get(exchange)
    if validator and not validator.match(uid):
        if exchange == "bitget":
            raise HTTPException(
                status_code=422,
                detail="Bitget UID muss rein numerisch sein",
            )
        elif exchange == "weex":
            raise HTTPException(
                status_code=422,
                detail="Weex UID muss alphanumerisch sein",
            )

    # Find or create ExchangeConnection for this user + exchange
    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == exchange,
        )
    )
    conn = result.scalar_one_or_none()

    if not conn:
        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type=exchange,
        )
        db.add(conn)

    conn.affiliate_uid = uid
    conn.affiliate_verified = True
    conn.affiliate_verified_at = datetime.now(timezone.utc)

    await db.flush()

    return {
        "exchange_type": exchange,
        "uid": uid,
        "affiliate_verified": True,
        "affiliate_verified_at": conn.affiliate_verified_at.isoformat(),
    }
