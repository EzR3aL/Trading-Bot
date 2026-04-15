"""Base interface for affiliate revenue fetchers.

Each adapter pulls commission/referral/affiliate data from an exchange
and returns a list of (date, amount_usd) tuples. The coordinator then
upserts these into the revenue_entries table.

Adapters should be idempotent — re-running for the same date range
must produce identical entries (the DB UNIQUE constraint will reject
duplicates and the coordinator handles the resulting error).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class DailyRevenue:
    """One day's commission for one exchange."""
    day: date
    amount_usd: float


@dataclass
class FetchResult:
    """Outcome of a single adapter run."""
    exchange: str
    status: str  # "ok" | "error" | "unsupported" | "not_configured"
    rows: list[DailyRevenue] = field(default_factory=list)
    error: Optional[str] = None


class AffiliateAdapter:
    """Subclass and override fetch()."""

    exchange: str = "unknown"
    revenue_type: str = "affiliate"

    async def fetch(self, since: date, until: date) -> FetchResult:
        """Fetch daily revenue between since and until (inclusive)."""
        raise NotImplementedError
