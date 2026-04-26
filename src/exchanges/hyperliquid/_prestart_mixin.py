"""Pre-start gate checks for Hyperliquid (#ARCH-H2).

Runs the affiliate / referral / builder-fee / wallet validation gates
that ``BotWorker.initialize`` consults before letting an HL bot start.

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from src.exchanges.base import GateCheckResult
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HyperliquidPrestartMixin:
    """Pre-start gate checks (#ARCH-H2) used by :class:`HyperliquidClient`."""

    async def pre_start_checks(
        self,
        user_id: int,
        db: Optional[Any] = None,
    ) -> List["GateCheckResult"]:
        """Run Hyperliquid-specific pre-start gate checks (#ARCH-H2).

        Returns a list of ``GateCheckResult`` entries with ``ok=False`` for
        each gate that should block bot start:
          - ``referral`` — user is not referred via our affiliate code
          - ``builder_fee`` — builder fee approval missing on-chain
          - ``wallet`` — wallet is not usable (unfunded / unauthorized)

        Passing gates are omitted (empty list = all clear). The caller
        (``BotWorker.initialize``) maps failing results to ``self.error_message``
        and decides whether to abort.
        """
        from src.utils.settings import get_hl_config

        # Base gates (affiliate-UID) first — shared across exchanges.
        results: List[GateCheckResult] = list(
            await super().pre_start_checks(user_id=user_id, db=db)
        )
        hl_cfg = await get_hl_config()

        # ── Referral gate ────────────────────────────────────────────
        referral_code = hl_cfg.get("referral_code")
        if referral_code:
            conn = await self._load_exchange_connection(db, user_id)
            if conn and getattr(conn, "referral_verified", False):
                pass  # cached as verified
            else:
                try:
                    info = await self.get_referral_info()
                    referred_by = None
                    if info:
                        referred_by = info.get("referredBy") or info.get("referred_by")

                    if not referred_by:
                        link = f"https://app.hyperliquid.xyz/join/{referral_code}"
                        results.append(GateCheckResult(
                            key="referral", ok=False,
                            message=(
                                f"Referral erforderlich: Bitte registriere dich über {link} "
                                f"bevor du Hyperliquid Bots nutzen kannst."
                            ),
                        ))
                    else:
                        referrer_code = None
                        if isinstance(referred_by, dict):
                            referrer_code = (
                                referred_by.get("code") or referred_by.get("referralCode")
                            )
                        elif isinstance(referred_by, str):
                            referrer_code = referred_by

                        builder_address = hl_cfg.get("builder_address", "")
                        code_match = (
                            referrer_code
                            and str(referrer_code).lower() == str(referral_code).lower()
                        )
                        addr_match = (
                            referrer_code and builder_address
                            and str(referrer_code).lower() == str(builder_address).lower()
                        )
                        if not code_match and not addr_match:
                            results.append(GateCheckResult(
                                key="referral", ok=False,
                                message=(
                                    f"Dein Account wurde über einen anderen Referral-Code "
                                    f"registriert. Bitte nutze unseren Link: "
                                    f"https://app.hyperliquid.xyz/join/{referral_code}"
                                ),
                            ))
                        elif conn is not None and db is not None:
                            # Cache success so future starts skip the live call.
                            try:
                                conn.referral_verified = True
                                conn.referral_verified_at = datetime.now(timezone.utc)
                                await db.commit()
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"Hyperliquid referral check failed: {e}")
                    results.append(GateCheckResult(
                        key="referral", ok=False,
                        message=(
                            f"Referral-Prüfung fehlgeschlagen. Bitte versuche es erneut. "
                            f"Falls das Problem bestehen bleibt, registriere dich über "
                            f"https://app.hyperliquid.xyz/join/{referral_code}"
                        ),
                    ))

        # ── Builder-fee gate ─────────────────────────────────────────
        if self.builder_config:
            conn = await self._load_exchange_connection(db, user_id)
            if conn and getattr(conn, "builder_fee_approved", False):
                pass  # cached
            else:
                try:
                    if self.demo_mode and conn is not None:
                        from src.services.config_service import (
                            create_hl_mainnet_read_client,
                        )
                        mainnet_client = create_hl_mainnet_read_client(conn)
                        approved = await mainnet_client.check_builder_fee_approval(
                            builder_address=self.builder_config["b"],
                        )
                    else:
                        approved = await self.check_builder_fee_approval()

                    if approved is not None and approved >= self.builder_config["f"]:
                        if conn is not None and db is not None:
                            try:
                                conn.builder_fee_approved = True
                                conn.builder_fee_approved_at = datetime.now(timezone.utc)
                                await db.commit()
                            except Exception:
                                pass
                    else:
                        results.append(GateCheckResult(
                            key="builder_fee", ok=False,
                            message=(
                                "Builder Fee nicht genehmigt. Bitte genehmige die Builder "
                                "Fee auf der Website unter 'Meine Bots' bevor du einen "
                                "Hyperliquid Bot starten kannst."
                            ),
                        ))
                except Exception as e:
                    logger.warning(f"Hyperliquid builder approval check failed: {e}")
                    results.append(GateCheckResult(
                        key="builder_fee", ok=False,
                        message=f"Builder Fee Prüfung fehlgeschlagen: {e}",
                    ))

        # ── Wallet gate ──────────────────────────────────────────────
        try:
            wallet_result = await self.validate_wallet()
            if not wallet_result.get("valid", False):
                results.append(GateCheckResult(
                    key="wallet", ok=False,
                    message=wallet_result.get("error") or "Wallet-Validierung fehlgeschlagen.",
                ))
        except Exception as e:
            logger.warning(f"Hyperliquid wallet validation failed: {e}")
            # Fail open on unexpected errors (matches original behavior).

        return results

    @staticmethod
    async def _load_exchange_connection(db, user_id: int):
        """Load the Hyperliquid ExchangeConnection row for this user (or None)."""
        if db is None:
            return None
        try:
            from sqlalchemy import select as sa_select
            from src.models.database import ExchangeConnection
            result = await db.execute(
                sa_select(ExchangeConnection).where(
                    ExchangeConnection.user_id == user_id,
                    ExchangeConnection.exchange_type == "hyperliquid",
                )
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.debug(f"Could not load HL ExchangeConnection for user={user_id}: {e}")
            return None
