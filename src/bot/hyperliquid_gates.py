"""Hyperliquid-specific checks for BotWorker (mixin)."""

from datetime import datetime, timezone

from src.exchanges.base import ExchangeClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HyperliquidGatesMixin:
    """Mixin providing Hyperliquid gate checks for BotWorker."""

    async def _check_referral_gate(self, client: ExchangeClient, db) -> bool:
        """HARD gate: block bot start unless user is referred via our affiliate link.

        Always enforced when HL_REFERRAL_CODE is set.
        Checks DB flag first (fast path), then live HL API, saves result to DB.
        Returns True if OK to proceed, False if blocked.
        """
        from src.utils.settings import get_hl_config
        hl_cfg = await get_hl_config()
        referral_code = hl_cfg["referral_code"]
        if not referral_code:
            return True

        log_prefix = f"[Bot:{self.bot_config_id}]"

        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient

            if not isinstance(client, HyperliquidClient):
                return True

            # Check DB flag first (fast path)
            from src.models.database import ExchangeConnection
            from sqlalchemy import select as sa_select
            result = await db.execute(
                sa_select(ExchangeConnection).where(
                    ExchangeConnection.user_id == self._config.user_id,
                    ExchangeConnection.exchange_type == "hyperliquid",
                )
            )
            conn = result.scalar_one_or_none()

            if conn and conn.referral_verified:
                logger.info(f"{log_prefix} Referral verified (DB flag)")
                return True

            # Live check via HL API
            info = await client.get_referral_info()
            referred_by = None
            if info:
                referred_by = info.get("referredBy") or info.get("referred_by")

            if referred_by:
                # Save to DB so API-level checks work
                if conn:
                    conn.referral_verified = True
                    conn.referral_verified_at = datetime.now(timezone.utc)
                    await db.commit()
                logger.info(f"{log_prefix} User is referred (by {referred_by}), saved to DB")
                return True

            link = f"https://app.hyperliquid.xyz/join/{referral_code}"
            self.error_message = (
                f"Referral erforderlich: Bitte registriere dich ueber {link} "
                f"bevor du Hyperliquid Bots nutzen kannst."
            )
            self.status = "error"
            logger.warning(f"{log_prefix} {self.error_message}")
            return False
        except Exception as e:
            logger.warning(f"{log_prefix} Referral check failed: {e}")
            self.error_message = (
                f"Referral-Pruefung fehlgeschlagen. Bitte versuche es erneut. "
                f"Falls das Problem bestehen bleibt, registriere dich ueber "
                f"https://app.hyperliquid.xyz/join/{referral_code}"
            )
            self.status = "error"
            return False

    async def _check_builder_approval(self, client: ExchangeClient, db) -> bool:
        """HARD gate: block bot start if builder fee not approved.

        Returns True if OK to proceed, False if blocked.
        """
        log_prefix = f"[Bot:{self.bot_config_id}]"
        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient

            if not isinstance(client, HyperliquidClient):
                return True
            if not client.builder_config:
                return True

            # Check DB flag first (fast path)
            from src.models.database import ExchangeConnection
            from sqlalchemy import select as sa_select
            result = await db.execute(
                sa_select(ExchangeConnection).where(
                    ExchangeConnection.user_id == self._config.user_id,
                    ExchangeConnection.exchange_type == "hyperliquid",
                )
            )
            conn = result.scalar_one_or_none()

            if conn and conn.builder_fee_approved:
                logger.info(f"{log_prefix} Builder fee approved (DB flag)")
                return True

            # Fallback: verify on-chain
            approved = await client.check_builder_fee_approval()
            if approved is not None and approved >= client.builder_config["f"]:
                if conn:
                    conn.builder_fee_approved = True
                    conn.builder_fee_approved_at = datetime.now(timezone.utc)
                    await db.commit()
                logger.info(f"{log_prefix} Builder fee approved (on-chain verified)")
                return True

            # NOT APPROVED — block bot start
            self.error_message = (
                "Builder Fee nicht genehmigt. Bitte genehmige die Builder Fee "
                "auf der Website unter 'Meine Bots' bevor du einen Hyperliquid Bot starten kannst."
            )
            self.status = "error"
            logger.warning(f"{log_prefix} Builder fee NOT approved — bot start blocked")
            return False

        except Exception as e:
            logger.warning(f"{log_prefix} Builder approval check failed: {e}")
            self.error_message = f"Builder Fee Pruefung fehlgeschlagen: {e}"
            self.status = "error"
            return False

    async def _check_affiliate_uid_gate(self, db) -> bool:
        """HARD gate: block bot start if affiliate UID verification is required
        but the user has not verified their UID yet.

        Checks the AffiliateLink.uid_required flag for the exchange and verifies
        that ExchangeConnection.affiliate_verified is True.
        Returns True if OK to proceed, False if blocked.
        """
        log_prefix = f"[Bot:{self.bot_config_id}]"
        try:
            from src.models.database import AffiliateLink, ExchangeConnection
            from sqlalchemy import select as sa_select

            exchange_type = getattr(self._config, "exchange_type", None)
            if not exchange_type:
                return True

            # Check if this exchange has an active affiliate link with uid_required
            result = await db.execute(
                sa_select(AffiliateLink).where(
                    AffiliateLink.exchange_type == exchange_type,
                    AffiliateLink.is_active.is_(True),
                    AffiliateLink.uid_required.is_(True),
                )
            )
            affiliate_link = result.scalar_one_or_none()

            if not affiliate_link:
                # No UID requirement for this exchange
                return True

            # Check if user has verified their affiliate UID
            result = await db.execute(
                sa_select(ExchangeConnection).where(
                    ExchangeConnection.user_id == self._config.user_id,
                    ExchangeConnection.exchange_type == exchange_type,
                )
            )
            conn = result.scalar_one_or_none()

            if conn and conn.affiliate_verified:
                logger.info(f"{log_prefix} Affiliate UID verified (DB flag)")
                return True

            # NOT VERIFIED — block bot start
            self.error_message = (
                f"Affiliate UID-Verifizierung erforderlich fuer {exchange_type}. "
                f"Bitte gib deine UID unter 'Affiliate Links' ein und verifiziere sie, "
                f"bevor du einen Bot starten kannst."
            )
            self.status = "error"
            logger.warning(f"{log_prefix} Affiliate UID not verified — bot start blocked")
            return False

        except Exception as e:
            logger.warning(f"{log_prefix} Affiliate UID check failed: {e}")
            # Fail open on unexpected errors to avoid blocking users
            return True
