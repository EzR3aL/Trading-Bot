"""Periodic retry job for pending affiliate UID verifications.

When a user submits their affiliate UID, ``set_affiliate_uid`` tries to
auto-verify it via the admin's live exchange API. If the admin had no
live keys configured at that moment, or if the API call hiccupped, the
row is left with ``affiliate_verified = False``. This job picks up such
pending rows on a schedule and re-attempts verification.
"""

from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import select

from src.models.database import ExchangeConnection
from src.models.session import get_session
from src.services.config_service import get_admin_exchange_conn
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def _build_admin_client(admin_conn: ExchangeConnection, exchange_type: str):
    """Create a single exchange client from an admin connection."""
    from src.exchanges.factory import create_exchange_client

    return create_exchange_client(
        exchange_type=exchange_type,
        api_key=decrypt_value(admin_conn.api_key_encrypted),
        api_secret=decrypt_value(admin_conn.api_secret_encrypted),
        passphrase=(
            decrypt_value(admin_conn.passphrase_encrypted)
            if admin_conn.passphrase_encrypted
            else ""
        ),
        demo_mode=False,
    )


async def retry_pending_verifications() -> Dict:
    """Re-check all pending affiliate UID verifications.

    Returns a result dict with counts:
        {
            "checked": int,
            "newly_verified": int,
            "still_pending": int,
            "skipped_no_admin_conn": [exchange_type, ...],
        }
    """
    result: Dict = {
        "checked": 0,
        "newly_verified": 0,
        "still_pending": 0,
        "skipped_no_admin_conn": [],
    }

    async with get_session() as session:
        rows_result = await session.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.affiliate_uid.isnot(None),
                ExchangeConnection.affiliate_verified == False,  # noqa: E712
            )
        )
        pending: List[ExchangeConnection] = list(rows_result.scalars().all())

        # Group rows by exchange to share one admin client per exchange
        by_exchange: Dict[str, List[ExchangeConnection]] = {}
        for conn in pending:
            by_exchange.setdefault(conn.exchange_type, []).append(conn)

        for exchange_type, conns in by_exchange.items():
            try:
                admin_conn = await get_admin_exchange_conn(exchange_type, session)
            except Exception as e:
                logger.warning(
                    "Affiliate retry: failed to load admin conn for %s: %s",
                    exchange_type,
                    type(e).__name__,
                )
                result["skipped_no_admin_conn"].append(exchange_type)
                result["still_pending"] += len(conns)
                continue

            if admin_conn is None:
                logger.warning(
                    "Affiliate retry: no admin live connection configured "
                    "for %s — skipping %d pending row(s)",
                    exchange_type,
                    len(conns),
                )
                result["skipped_no_admin_conn"].append(exchange_type)
                result["still_pending"] += len(conns)
                continue

            try:
                client = await _build_admin_client(admin_conn, exchange_type)
            except Exception as e:
                logger.error(
                    "Affiliate retry: failed to build client for %s: %s",
                    exchange_type,
                    e,
                )
                result["skipped_no_admin_conn"].append(exchange_type)
                result["still_pending"] += len(conns)
                continue

            try:
                for conn in conns:
                    result["checked"] += 1
                    try:
                        ok = await client.check_affiliate_uid(conn.affiliate_uid)
                        if ok:
                            conn.affiliate_verified = True
                            conn.affiliate_verified_at = datetime.now(timezone.utc)
                            result["newly_verified"] += 1
                            logger.info(
                                "Affiliate retry: verified user %s uid=%s on %s",
                                conn.user_id,
                                conn.affiliate_uid,
                                exchange_type,
                            )
                        else:
                            result["still_pending"] += 1
                    except Exception as e:
                        result["still_pending"] += 1
                        logger.warning(
                            "Affiliate retry: row user_id=%s uid=%s on %s "
                            "raised %s — skipping",
                            conn.user_id,
                            conn.affiliate_uid,
                            exchange_type,
                            type(e).__name__,
                        )
            finally:
                try:
                    await client.close()
                except Exception:
                    pass

    logger.info(
        "Affiliate retry finished: checked=%d newly_verified=%d "
        "still_pending=%d skipped_no_admin_conn=%s",
        result["checked"],
        result["newly_verified"],
        result["still_pending"],
        result["skipped_no_admin_conn"],
    )
    return result
