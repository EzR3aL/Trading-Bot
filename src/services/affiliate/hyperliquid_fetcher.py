"""Hyperliquid referral fetcher.

POST https://api.hyperliquid.xyz/info  body={"type":"referral","user":"<addr>"}

Returns the lifetime cumulative reward in `referrerState.cumFeesRewardedToReferrer`.
We track the previous baseline in affiliate_state.cumulative_amount_usd and
write only the delta — attributed to today (since HL gives no per-day breakdown).
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

import aiohttp
from sqlalchemy import select

from src.models.database import AffiliateState
from src.models.session import get_session

from .base import AffiliateAdapter, DailyRevenue, FetchResult

logger = logging.getLogger(__name__)

HL_INFO_URL = "https://api.hyperliquid.xyz/info"


def _sum_referrer_rewards(payload: dict) -> float:
    """Sum cumFeesRewardedToReferrer across the referrer state structure."""
    state = payload.get("referrerState") or {}
    direct = state.get("cumFeesRewardedToReferrer")
    if direct is not None:
        try:
            return float(direct)
        except (TypeError, ValueError):
            pass
    total = 0.0
    for ref in state.get("referralStates", []) or []:
        try:
            total += float(ref.get("cumFeesRewardedToReferrer", 0))
        except (TypeError, ValueError):
            continue
    return total


class HyperliquidAffiliateAdapter(AffiliateAdapter):
    exchange = "hyperliquid"
    revenue_type = "referral"

    def __init__(self, referrer_address: Optional[str] = None):
        self.referrer_address = (referrer_address or os.environ.get("HL_REFERRER_ADDRESS", "")).strip()

    @property
    def configured(self) -> bool:
        return bool(self.referrer_address)

    async def fetch(self, since: date, until: date) -> FetchResult:
        if not self.configured:
            return FetchResult(self.exchange, "not_configured")

        body = {"type": "referral", "user": self.referrer_address}

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
                async with s.post(HL_INFO_URL, json=body) as r:
                    payload = await r.json()
        except Exception as exc:
            logger.warning("Hyperliquid referral fetch failed: %s", exc)
            return FetchResult(self.exchange, "error", error=str(exc))

        cumulative_now = _sum_referrer_rewards(payload)

        async with get_session() as db:
            row = (await db.execute(
                select(AffiliateState).where(AffiliateState.exchange == self.exchange)
            )).scalar_one_or_none()

            previous = float(row.cumulative_amount_usd) if row else 0.0
            delta = max(0.0, cumulative_now - previous)

            if row is None:
                db.add(AffiliateState(
                    exchange=self.exchange,
                    cumulative_amount_usd=cumulative_now,
                    last_synced_at=datetime.now(timezone.utc),
                    last_status="ok",
                ))
            else:
                row.cumulative_amount_usd = cumulative_now
                row.last_synced_at = datetime.now(timezone.utc)
                row.last_status = "ok"
                row.last_error = None
            await db.commit()

        if delta <= 0:
            return FetchResult(self.exchange, "ok", rows=[])

        today = until
        return FetchResult(
            self.exchange,
            "ok",
            rows=[DailyRevenue(day=today, amount_usd=round(delta, 6))],
        )
