"""Bitget affiliate commission fetcher.

Endpoint: GET /api/v2/broker/customer-commissions
Auth: standard ACCESS-KEY/SIGN/PASSPHRASE/TIMESTAMP — the API key
must belong to a Bitget account that holds affiliate (KOL) status.

Default time-range when the caller omits start/end is "yesterday
00:00–23:59 UTC+8" — we always pass startTime/endTime explicitly.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Optional

import aiohttp

from .base import AffiliateAdapter, DailyRevenue, FetchResult

logger = logging.getLogger(__name__)

BITGET_BASE_URL = "https://api.bitget.com"
BITGET_PATH = "/api/v2/broker/customer-commissions"


def _sign(secret: str, ts: str, method: str, path: str, body: str) -> str:
    """Bitget HMAC-SHA256 signature, base64-encoded."""
    msg = f"{ts}{method.upper()}{path}{body}"
    digest = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _to_ms(d: date, end_of_day: bool = False) -> int:
    t = time.max if end_of_day else time.min
    return int(datetime.combine(d, t, tzinfo=timezone.utc).timestamp() * 1000)


class BitgetAffiliateAdapter(AffiliateAdapter):
    exchange = "bitget"
    revenue_type = "affiliate"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("BITGET_AFFILIATE_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("BITGET_AFFILIATE_API_SECRET", "")
        self.passphrase = passphrase or os.environ.get("BITGET_AFFILIATE_PASSPHRASE", "")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret and self.passphrase)

    async def fetch(self, since: date, until: date) -> FetchResult:
        if not self.configured:
            return FetchResult(self.exchange, "not_configured")

        params = {
            "startTime": str(_to_ms(since)),
            "endTime": str(_to_ms(until, end_of_day=True)),
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        request_path = f"{BITGET_PATH}?{query}"
        ts = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        sig = _sign(self.api_secret, ts, "GET", request_path, "")

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": sig,
            "ACCESS-PASSPHRASE": self.passphrase,
            "ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
                async with s.get(BITGET_BASE_URL + request_path, headers=headers) as r:
                    payload = await r.json()
        except Exception as exc:
            logger.warning("Bitget affiliate fetch failed: %s", exc)
            return FetchResult(self.exchange, "error", error=str(exc))

        if str(payload.get("code")) != "00000":
            msg = payload.get("msg") or "unknown"
            return FetchResult(self.exchange, "error", error=f"API code={payload.get('code')} msg={msg}")

        rows = payload.get("data", []) or []
        agg: dict[date, float] = defaultdict(float)
        for row in rows:
            ts_ms = row.get("cTime") or row.get("ts") or row.get("settleTime")
            amount = row.get("commission") or row.get("amount") or 0
            if ts_ms is None:
                continue
            try:
                day = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).date()
                agg[day] += float(amount)
            except (ValueError, TypeError):
                continue

        return FetchResult(
            self.exchange,
            "ok",
            rows=[DailyRevenue(day=d, amount_usd=round(amt, 6)) for d, amt in sorted(agg.items())],
        )
