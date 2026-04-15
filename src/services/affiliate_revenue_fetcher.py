"""Coordinator: runs all configured affiliate adapters every 6h and
upserts results into revenue_entries.

Idempotency: the (date, exchange, revenue_type) UNIQUE constraint
catches duplicates. We update existing rows in place when the new
amount differs (e.g. a day's commission gets settled in two batches).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from src.models.database import AffiliateState, RevenueEntry
from src.models.session import get_session

from src.services.affiliate.base import AffiliateAdapter, FetchResult
from src.services.affiliate.bingx_fetcher import BingxAffiliateAdapter
from src.services.affiliate.bitget_fetcher import BitgetAffiliateAdapter
from src.services.affiliate.bitunix_fetcher import BitunixAffiliateAdapter
from src.services.affiliate.hyperliquid_fetcher import HyperliquidAffiliateAdapter
from src.services.affiliate.weex_fetcher import WeexAffiliateAdapter

logger = logging.getLogger(__name__)

# Default sync window — covers late-arriving Bitget/Weex settlements
DEFAULT_LOOKBACK_DAYS = 7


def _build_adapters() -> list[AffiliateAdapter]:
    return [
        BitgetAffiliateAdapter(),
        WeexAffiliateAdapter(),
        HyperliquidAffiliateAdapter(),
        BingxAffiliateAdapter(),
        BitunixAffiliateAdapter(),
    ]


async def _persist_state(exchange: str, status: str, error: str | None) -> None:
    async with get_session() as db:
        row = (await db.execute(
            select(AffiliateState).where(AffiliateState.exchange == exchange)
        )).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if row is None:
            db.add(AffiliateState(
                exchange=exchange,
                cumulative_amount_usd=0.0,
                last_synced_at=now,
                last_status=status,
                last_error=error,
            ))
        else:
            row.last_synced_at = now
            row.last_status = status
            row.last_error = error
        await db.commit()


async def _upsert_rows(result: FetchResult) -> int:
    """Insert or update revenue_entries for one adapter result. Returns row count."""
    written = 0
    async with get_session() as db:
        for r in result.rows:
            existing = (await db.execute(
                select(RevenueEntry).where(
                    RevenueEntry.date == r.day,
                    RevenueEntry.exchange == result.exchange,
                    RevenueEntry.revenue_type == _revenue_type_for(result.exchange),
                )
            )).scalar_one_or_none()

            if existing is None:
                db.add(RevenueEntry(
                    date=r.day,
                    exchange=result.exchange,
                    revenue_type=_revenue_type_for(result.exchange),
                    amount_usd=r.amount_usd,
                    source="auto_import",
                ))
                written += 1
            elif abs((existing.amount_usd or 0) - r.amount_usd) > 1e-6:
                existing.amount_usd = r.amount_usd
                existing.source = "auto_import"
                written += 1
        await db.commit()
    return written


def _revenue_type_for(exchange: str) -> str:
    if exchange == "hyperliquid":
        return "referral"
    return "affiliate"


async def run_affiliate_fetch(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> dict:
    """Run all adapters and persist results. Returns a per-exchange summary."""
    until = date.today()
    since = until - timedelta(days=lookback_days)

    summary: dict[str, dict] = {}
    for adapter in _build_adapters():
        try:
            result = await adapter.fetch(since, until)
        except Exception as exc:
            logger.exception("Affiliate adapter %s crashed", adapter.exchange)
            result = FetchResult(adapter.exchange, "error", error=str(exc))

        try:
            written = await _upsert_rows(result) if result.status == "ok" else 0
            await _persist_state(adapter.exchange, result.status, result.error)
        except Exception:
            logger.exception("Affiliate persist failed for %s", adapter.exchange)
            written = 0

        summary[adapter.exchange] = {
            "status": result.status,
            "rows": len(result.rows),
            "written": written,
            "error": result.error,
        }
        logger.info(
            "Affiliate fetch %s: status=%s rows=%d written=%d err=%s",
            adapter.exchange, result.status, len(result.rows), written, result.error,
        )

    return summary
