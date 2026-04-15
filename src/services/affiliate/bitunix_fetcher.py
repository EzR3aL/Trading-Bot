"""Bitunix has no public affiliate/commission API.

Affiliate payouts are dashboard-only (settled daily 02:00 UTC). The
public OpenAPI spec at openapidoc.bitunix.com lists no affiliate,
referral, partner, commission, or rebate endpoints.

This stub adapter exists so the coordinator can return a uniform
"unsupported" status for the Bitunix tile in the admin UI.
"""
from __future__ import annotations

from datetime import date

from .base import AffiliateAdapter, FetchResult


class BitunixAffiliateAdapter(AffiliateAdapter):
    exchange = "bitunix"
    revenue_type = "affiliate"

    @property
    def configured(self) -> bool:
        return False

    async def fetch(self, since: date, until: date) -> FetchResult:
        return FetchResult(
            self.exchange,
            "unsupported",
            error="Bitunix bietet keine öffentliche Affiliate-API. Beträge müssen manuell aus dem Dashboard übernommen werden.",
        )
