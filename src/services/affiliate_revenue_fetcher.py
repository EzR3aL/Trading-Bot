"""Coordinator: runs all configured affiliate adapters every 6h and
upserts results into revenue_entries.

Credentials come from the admin user's `exchange_connections` rows —
no environment variables required. Hyperliquid uses the admin's wallet
address (stored in `api_key_encrypted`). Bitunix has no public API.

Idempotency: the (date, exchange, revenue_type) UNIQUE constraint
catches duplicates. Existing rows are updated in place when the new
amount differs (e.g. late-arriving settlements).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from src.models.database import AffiliateState, ExchangeConnection, RevenueEntry, User
from src.models.session import get_session
from src.utils.encryption import decrypt_value

from src.services.affiliate.base import AffiliateAdapter, FetchResult
from src.services.affiliate.bingx_fetcher import BingxAffiliateAdapter
from src.services.affiliate.bitget_fetcher import BitgetAffiliateAdapter
from src.services.affiliate.bitunix_fetcher import BitunixAffiliateAdapter
from src.services.affiliate.hyperliquid_fetcher import HyperliquidAffiliateAdapter
from src.services.affiliate.weex_fetcher import WeexAffiliateAdapter

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 7


async def _load_admin_credentials() -> dict[str, ExchangeConnection]:
    """Return {exchange_type: connection} for the first admin user with live keys.

    Falls back to demo keys when live keys are missing — helps during local
    development where only demo credentials exist.
    """
    async with get_session() as db:
        admin_ids = (await db.execute(
            select(User.id).where(User.role == "admin").order_by(User.id)
        )).scalars().all()

        creds: dict[str, ExchangeConnection] = {}
        for admin_id in admin_ids:
            rows = (await db.execute(
                select(ExchangeConnection).where(ExchangeConnection.user_id == admin_id)
            )).scalars().all()
            for conn in rows:
                # prefer live keys; fall back to demo if live missing
                has_live = bool(conn.api_key_encrypted and conn.api_secret_encrypted)
                has_demo = bool(conn.demo_api_key_encrypted and conn.demo_api_secret_encrypted)
                if conn.exchange_type not in creds and (has_live or has_demo):
                    creds[conn.exchange_type] = conn
        return creds


def _decrypt(value: Optional[str]) -> str:
    return decrypt_value(value) if value else ""


def _build_adapter(exchange_type: str, conn: Optional[ExchangeConnection]) -> AffiliateAdapter:
    """Build one adapter with credentials sourced from the admin connection."""
    if exchange_type == "bitunix":
        return BitunixAffiliateAdapter()

    if conn is None:
        # No admin connection configured → return unconfigured adapter so the
        # tile surfaces "nicht konfiguriert" without raising.
        if exchange_type == "bitget":
            return BitgetAffiliateAdapter(api_key="", api_secret="", passphrase="")
        if exchange_type == "weex":
            return WeexAffiliateAdapter(api_key="", api_secret="", passphrase="")
        if exchange_type == "hyperliquid":
            return HyperliquidAffiliateAdapter(referrer_address="")
        if exchange_type == "bingx":
            return BingxAffiliateAdapter(api_key="", api_secret="")

    # Prefer live, fall back to demo
    key = _decrypt(conn.api_key_encrypted) or _decrypt(conn.demo_api_key_encrypted)
    secret = _decrypt(conn.api_secret_encrypted) or _decrypt(conn.demo_api_secret_encrypted)
    passphrase = _decrypt(conn.passphrase_encrypted) or _decrypt(conn.demo_passphrase_encrypted)

    if exchange_type == "bitget":
        return BitgetAffiliateAdapter(api_key=key, api_secret=secret, passphrase=passphrase)
    if exchange_type == "weex":
        return WeexAffiliateAdapter(api_key=key, api_secret=secret, passphrase=passphrase)
    if exchange_type == "hyperliquid":
        # HL "api_key" is the wallet address (referrer).
        return HyperliquidAffiliateAdapter(referrer_address=key)
    if exchange_type == "bingx":
        # BingX agent API uses the same key/secret pair as trading when the
        # account has agent-tier activated.
        return BingxAffiliateAdapter(api_key=key, api_secret=secret)

    raise ValueError(f"Unknown exchange_type: {exchange_type}")


async def _build_adapters() -> list[AffiliateAdapter]:
    creds = await _load_admin_credentials()
    return [
        _build_adapter("bitget", creds.get("bitget")),
        _build_adapter("weex", creds.get("weex")),
        _build_adapter("hyperliquid", creds.get("hyperliquid")),
        _build_adapter("bingx", creds.get("bingx")),
        _build_adapter("bitunix", creds.get("bitunix")),
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

    adapters = await _build_adapters()
    summary: dict[str, dict] = {}
    for adapter in adapters:
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
