"""Weex affiliate commission fetcher.

Endpoint: GET /api/v3/rebate/affiliate/getAffiliateCommission
Auth: standard ACCESS-KEY/SIGN/TIMESTAMP/PASSPHRASE.

Range cap: max 3 months per request.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import aiohttp

from .base import AffiliateAdapter, DailyRevenue, FetchResult

logger = logging.getLogger(__name__)

WEEX_BASE_URL = "https://api-spot.weex.com"
WEEX_PATH = "/api/v3/rebate/affiliate/getAffiliateCommission"
WEEX_MAX_RANGE_DAYS = 90


def _sign(secret: str, ts: str, method: str, path: str, body: str) -> str:
    msg = f"{ts}{method.upper()}{path}{body}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _to_ms(d: date, end_of_day: bool = False) -> int:
    t = time.max if end_of_day else time.min
    return int(datetime.combine(d, t, tzinfo=timezone.utc).timestamp() * 1000)


class WeexAffiliateAdapter(AffiliateAdapter):
    exchange = "weex"
    revenue_type = "affiliate"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("WEEX_AFFILIATE_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("WEEX_AFFILIATE_API_SECRET", "")
        self.passphrase = passphrase or os.environ.get("WEEX_AFFILIATE_PASSPHRASE", "")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    async def fetch(self, since: date, until: date) -> FetchResult:
        if not self.configured:
            return FetchResult(self.exchange, "not_configured")

        # Clamp to 90-day window
        if (until - since).days > WEEX_MAX_RANGE_DAYS:
            since = until - timedelta(days=WEEX_MAX_RANGE_DAYS)

        agg: dict[date, float] = defaultdict(float)
        page = 1
        page_size = 200

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
                while True:
                    params = {
                        "startTime": str(_to_ms(since)),
                        "endTime": str(_to_ms(until, end_of_day=True)),
                        "pageNum": str(page),
                        "pageSize": str(page_size),
                    }
                    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
                    request_path = f"{WEEX_PATH}?{query}"
                    ts = str(int(datetime.now(timezone.utc).timestamp() * 1000))
                    sig = _sign(self.api_secret, ts, "GET", request_path, "")

                    headers = {
                        "ACCESS-KEY": self.api_key,
                        "ACCESS-SIGN": sig,
                        "ACCESS-TIMESTAMP": ts,
                        "ACCESS-PASSPHRASE": self.passphrase,
                        "Content-Type": "application/json",
                    }

                    async with s.get(WEEX_BASE_URL + request_path, headers=headers) as r:
                        payload = await r.json()

                    if str(payload.get("code")) not in ("0", "00000"):
                        return FetchResult(
                            self.exchange, "error",
                            error=f"API code={payload.get('code')} msg={payload.get('msg')}",
                        )

                    data = payload.get("data") or {}
                    rows = data.get("list") or data.get("rows") or []
                    for row in rows:
                        ts_ms = row.get("ts") or row.get("settleTime") or row.get("createTime")
                        amount = row.get("commission") or row.get("amount") or 0
                        if ts_ms is None:
                            continue
                        try:
                            day = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).date()
                            agg[day] += float(amount)
                        except (ValueError, TypeError):
                            continue

                    total_pages = int(data.get("pages") or 1)
                    if page >= total_pages or not rows:
                        break
                    page += 1
        except Exception as exc:
            logger.warning("Weex affiliate fetch failed: %s", exc)
            return FetchResult(self.exchange, "error", error=str(exc))

        return FetchResult(
            self.exchange,
            "ok",
            rows=[DailyRevenue(day=d, amount_usd=round(amt, 6)) for d, amt in sorted(agg.items())],
        )
