"""BingX agent commission fetcher.

Endpoint: GET /openApi/agent/v1/asset/commissionDataList
Auth: X-BX-APIKEY header + HMAC-SHA256 hex signature on the full query string
(same scheme as the trading API). Account must hold agent/broker scope —
standard trading keys do NOT have access; the agent role is granted by
BingX out-of-band (Telegram contact: SAJAD | BingX).

Optional X-SOURCE-KEY header for broker-tier identification.

Configure via environment variables:
  BINGX_AGENT_API_KEY=
  BINGX_AGENT_API_SECRET=
  BINGX_AGENT_SOURCE_KEY=    # optional broker source key
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Optional

import aiohttp

from .base import AffiliateAdapter, DailyRevenue, FetchResult

logger = logging.getLogger(__name__)

BINGX_BASE_URL = "https://open-api.bingx.com"
BINGX_PATH = "/openApi/agent/v1/asset/commissionDataList"


def _sign(secret: str, query_string: str) -> str:
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def _to_ms(d: date, end_of_day: bool = False) -> int:
    t = time.max if end_of_day else time.min
    return int(datetime.combine(d, t, tzinfo=timezone.utc).timestamp() * 1000)


class BingxAffiliateAdapter(AffiliateAdapter):
    exchange = "bingx"
    revenue_type = "affiliate"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        source_key: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("BINGX_AGENT_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("BINGX_AGENT_API_SECRET", "")
        self.source_key = source_key or os.environ.get("BINGX_AGENT_SOURCE_KEY", "")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    async def fetch(self, since: date, until: date) -> FetchResult:
        if not self.configured:
            return FetchResult(self.exchange, "not_configured")

        params = {
            "startTime": _to_ms(since),
            "endTime": _to_ms(until, end_of_day=True),
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
        query = urllib.parse.urlencode(sorted(params.items()))
        sig = _sign(self.api_secret, query)
        url = f"{BINGX_BASE_URL}{BINGX_PATH}?{query}&signature={sig}"

        headers = {"X-BX-APIKEY": self.api_key}
        if self.source_key:
            headers["X-SOURCE-KEY"] = self.source_key

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
                async with s.get(url, headers=headers) as r:
                    payload = await r.json()
        except Exception as exc:
            logger.warning("BingX agent commission fetch failed: %s", exc)
            return FetchResult(self.exchange, "error", error=str(exc))

        if str(payload.get("code")) not in ("0", "00000"):
            return FetchResult(
                self.exchange, "error",
                error=f"API code={payload.get('code')} msg={payload.get('msg')}",
            )

        data = payload.get("data") or {}
        rows = data.get("list") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        rows = rows or []

        agg: dict[date, float] = defaultdict(float)
        for row in rows:
            ts_ms = row.get("commissionTime") or row.get("settleTime") or row.get("ts") or row.get("time")
            amount = row.get("commission") or row.get("commissionAmount") or row.get("amount") or 0
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
