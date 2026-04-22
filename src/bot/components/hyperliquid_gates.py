"""Hyperliquid pre-flight gate checks (ARCH-H1 Phase 1 PR-2, #277).

Extracted from ``HyperliquidGatesMixin`` so gate logic is composition-owned
and independently testable. The mixin is kept as a thin proxy until the
Phase 1 finalize PR removes all mixin shims.

The gate methods return a ``GateResult`` value object rather than mutating
worker state directly. The mixin proxy is the single place that translates
failures into ``self.error_message`` / ``self.status = "error"`` — which
preserves the existing external behavior with zero callsite changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select as sa_select

from src.exchanges.base import ExchangeClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class GateResult:
    """Result of a single gate check.

    ``ok=True`` means the gate passed; the bot may proceed.
    ``ok=False`` plus ``error_message`` means the bot is blocked and the
    user-visible reason is ``error_message``.
    """

    ok: bool
    error_message: Optional[str] = None

    @classmethod
    def passed(cls) -> "GateResult":
        return cls(ok=True)

    @classmethod
    def blocked(cls, message: str) -> "GateResult":
        return cls(ok=False, error_message=message)


class HyperliquidGates:
    """Owns Hyperliquid-specific pre-flight gate checks."""

    def __init__(
        self,
        bot_config_id: int,
        config_getter: Callable[[], Optional[Any]],
    ) -> None:
        self._bot_config_id = bot_config_id
        self._get_config = config_getter

    async def check_referral(self, client: ExchangeClient, db) -> GateResult:
        """HARD gate: block bot start unless user is referred via our affiliate link.

        Always enforced when HL_REFERRAL_CODE is set. Checks DB flag first
        (fast path), then live HL API, persists the verified flag to DB.
        """
        from src.utils.settings import get_hl_config
        hl_cfg = await get_hl_config()
        referral_code = hl_cfg["referral_code"]
        if not referral_code:
            return GateResult.passed()

        log_prefix = f"[Bot:{self._bot_config_id}]"

        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient

            if not isinstance(client, HyperliquidClient):
                return GateResult.passed()

            config = self._get_config()
            from src.models.database import ExchangeConnection
            result = await db.execute(
                sa_select(ExchangeConnection).where(
                    ExchangeConnection.user_id == config.user_id,
                    ExchangeConnection.exchange_type == "hyperliquid",
                )
            )
            conn = result.scalar_one_or_none()

            if conn and conn.referral_verified:
                logger.info(f"{log_prefix} Referral verified (DB flag)")
                return GateResult.passed()

            info = await client.get_referral_info()
            referred_by = None
            if info:
                referred_by = info.get("referredBy") or info.get("referred_by")

            if referred_by:
                referrer_code = None
                if isinstance(referred_by, dict):
                    referrer_code = referred_by.get("code") or referred_by.get("referralCode")
                elif isinstance(referred_by, str):
                    referrer_code = referred_by

                builder_address = hl_cfg.get("builder_address", "")
                if referrer_code and referral_code:
                    code_match = str(referrer_code).lower() == str(referral_code).lower()
                    addr_match = (
                        builder_address
                        and str(referrer_code).lower() == str(builder_address).lower()
                    )
                    if not code_match and not addr_match:
                        logger.warning(f"{log_prefix} Wrong referrer: {referrer_code}")
                        return GateResult.blocked(
                            f"Dein Account wurde über einen anderen Referral-Code registriert. "
                            f"Bitte nutze unseren Link: "
                            f"https://app.hyperliquid.xyz/join/{referral_code}"
                        )

                if conn:
                    conn.referral_verified = True
                    conn.referral_verified_at = datetime.now(timezone.utc)
                    await db.commit()
                logger.info(f"{log_prefix} User is referred (by {referred_by}), saved to DB")
                return GateResult.passed()

            link = f"https://app.hyperliquid.xyz/join/{referral_code}"
            msg = (
                f"Referral erforderlich: Bitte registriere dich über {link} "
                f"bevor du Hyperliquid Bots nutzen kannst."
            )
            logger.warning(f"{log_prefix} {msg}")
            return GateResult.blocked(msg)
        except Exception as e:
            logger.warning(f"{log_prefix} Referral check failed: {e}")
            return GateResult.blocked(
                f"Referral-Prüfung fehlgeschlagen. Bitte versuche es erneut. "
                f"Falls das Problem bestehen bleibt, registriere dich über "
                f"https://app.hyperliquid.xyz/join/{referral_code}"
            )

    async def check_builder_approval(self, client: ExchangeClient, db) -> GateResult:
        """HARD gate: block bot start if builder fee not approved on mainnet.

        Builder fee approvals only exist on mainnet. Demo (testnet) bots skip
        the builder fee in orders, but mainnet approval is still enforced so
        switching to live mode works without surprises.
        """
        log_prefix = f"[Bot:{self._bot_config_id}]"
        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient

            if not isinstance(client, HyperliquidClient):
                return GateResult.passed()
            if not client.builder_config:
                return GateResult.passed()

            config = self._get_config()
            from src.models.database import ExchangeConnection
            result = await db.execute(
                sa_select(ExchangeConnection).where(
                    ExchangeConnection.user_id == config.user_id,
                    ExchangeConnection.exchange_type == "hyperliquid",
                )
            )
            conn = result.scalar_one_or_none()

            if conn and conn.builder_fee_approved:
                logger.info(f"{log_prefix} Builder fee approved (DB flag)")
                return GateResult.passed()

            if client.demo_mode and conn:
                from src.services.config_service import create_hl_mainnet_read_client
                mainnet_client = create_hl_mainnet_read_client(conn)
                approved = await mainnet_client.check_builder_fee_approval(
                    builder_address=client.builder_config["b"],
                )
            else:
                approved = await client.check_builder_fee_approval()

            if approved is not None and approved >= client.builder_config["f"]:
                if conn:
                    conn.builder_fee_approved = True
                    conn.builder_fee_approved_at = datetime.now(timezone.utc)
                    await db.commit()
                logger.info(f"{log_prefix} Builder fee approved (on-chain verified)")
                return GateResult.passed()

            logger.warning(f"{log_prefix} Builder fee NOT approved — bot start blocked")
            return GateResult.blocked(
                "Builder Fee nicht genehmigt. Bitte genehmige die Builder Fee "
                "auf der Website unter 'Meine Bots' bevor du einen Hyperliquid Bot starten kannst."
            )

        except Exception as e:
            logger.warning(f"{log_prefix} Builder approval check failed: {e}")
            return GateResult.blocked(f"Builder Fee Prüfung fehlgeschlagen: {e}")

    async def check_wallet(self, client: ExchangeClient) -> GateResult:
        """HARD gate: block bot start if Hyperliquid wallet is not usable.

        Checks that the wallet exists, is funded, and API wallet is authorized.
        Unexpected errors fail open (return passed) to avoid blocking users on
        transient issues.
        """
        log_prefix = f"[Bot:{self._bot_config_id}]"
        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient

            if not isinstance(client, HyperliquidClient):
                return GateResult.passed()

            result = await client.validate_wallet()

            if result["valid"]:
                logger.info(
                    "%s Wallet validation passed: balance=$%.2f wallet=%s",
                    log_prefix, result["balance"], result["main_wallet"][:10],
                )
                return GateResult.passed()

            logger.warning("%s Wallet validation failed: %s", log_prefix, result["error"][:100])
            return GateResult.blocked(result["error"])

        except Exception as e:
            logger.warning("%s Wallet validation check failed: %s", log_prefix, e)
            return GateResult.passed()

    async def check_affiliate_uid(self, db) -> GateResult:
        """HARD gate: block bot start if affiliate UID verification is required
        but the user has not verified their UID yet.

        Checks the ``AffiliateLink.uid_required`` flag for the exchange and
        verifies that ``ExchangeConnection.affiliate_verified`` is True.
        Unexpected errors fail open to avoid blocking users.
        """
        log_prefix = f"[Bot:{self._bot_config_id}]"
        try:
            from src.models.database import AffiliateLink, ExchangeConnection

            config = self._get_config()
            exchange_type = getattr(config, "exchange_type", None)
            if not exchange_type:
                return GateResult.passed()

            result = await db.execute(
                sa_select(AffiliateLink).where(
                    AffiliateLink.exchange_type == exchange_type,
                    AffiliateLink.is_active.is_(True),
                    AffiliateLink.uid_required.is_(True),
                )
            )
            affiliate_link = result.scalar_one_or_none()

            if not affiliate_link:
                return GateResult.passed()

            result = await db.execute(
                sa_select(ExchangeConnection).where(
                    ExchangeConnection.user_id == config.user_id,
                    ExchangeConnection.exchange_type == exchange_type,
                )
            )
            conn = result.scalar_one_or_none()

            if conn and conn.affiliate_verified:
                logger.info(f"{log_prefix} Affiliate UID verified (DB flag)")
                return GateResult.passed()

            logger.warning(f"{log_prefix} Affiliate UID not verified — bot start blocked")
            return GateResult.blocked(
                f"Affiliate UID-Verifizierung erforderlich für {exchange_type}. "
                f"Bitte gib deine UID unter 'Affiliate Links' ein und verifiziere sie, "
                f"bevor du einen Bot starten kannst."
            )

        except Exception as e:
            logger.warning(f"{log_prefix} Affiliate UID check failed: {e}")
            return GateResult.passed()
