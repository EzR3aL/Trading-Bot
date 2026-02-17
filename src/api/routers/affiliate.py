"""Affiliate link CRUD endpoints (admin-managed, globally visible)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.schemas.affiliate import AffiliateLinkResponse, AffiliateLinkUpdate
from src.auth.dependencies import get_current_admin, get_current_user
from src.models.database import AffiliateLink, User
from src.models.session import get_db

router = APIRouter(prefix="/api/affiliate-links", tags=["affiliate"])

VALID_EXCHANGES = {"bitget", "weex", "hyperliquid"}


@router.get("", response_model=list[AffiliateLinkResponse])
async def list_affiliate_links(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all active affiliate links (any authenticated user)."""
    result = await db.execute(
        select(AffiliateLink).where(AffiliateLink.is_active == True)
    )
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
        raise HTTPException(status_code=404, detail="Affiliate link not found")

    await db.delete(link)
    return {"detail": "deleted"}
