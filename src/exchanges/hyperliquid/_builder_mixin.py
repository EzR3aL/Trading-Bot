"""Builder-code, referral and affiliate queries for the Hyperliquid client.

Wraps the ``maxBuilderFee`` / ``referralState`` / ``userFees`` HL info-API
endpoints together with the EIP-712 signed ``approve_builder_fee`` flow.
The defense-in-depth fee validators (SEC-008) live in
``eip712_validator`` — this mixin only orchestrates the call.

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

from typing import Optional

from src.exchanges.hyperliquid.eip712_validator import (
    EIP712ValidationError,
    assert_builder_fee_tenths_bps,
    validate_approve_builder_fee,
)
from src.exchanges.hyperliquid.fees import calculate_builder_fee
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HyperliquidBuilderMixin:
    """Builder-code, referral, affiliate and fee-validation surface."""

    async def check_builder_fee_approval(
        self,
        user_address: str = None,
        builder_address: str = None,
    ) -> Optional[int]:
        """Check if user has approved builder fee for the configured builder.

        Args:
            user_address: Wallet to check. Defaults to ``self.wallet_address``.
            builder_address: Builder wallet whose approval to query. Defaults
                to ``self._builder["b"]`` when the client was initialized
                with builder kwargs. Callers that construct the client via
                ``create_hl_mainnet_read_client`` (which does not set
                ``self._builder``) **must** pass this explicitly, otherwise
                the method short-circuits to ``None`` without hitting HL.

        Returns:
            The max approved fee rate (int, tenths of basis points), or
            ``None`` if no approval exists or the builder address could
            not be resolved.
        """
        resolved_builder = (
            builder_address
            or (self._builder["b"] if self._builder else None)
        )
        if not resolved_builder:
            logger.debug(
                "check_builder_fee_approval called without a builder address — "
                "client has no self._builder and no explicit parameter",
            )
            return None

        addr = (user_address or self.wallet_address).lower()
        try:
            result = self._info_exec.post(
                "/info",
                {
                    "type": "maxBuilderFee",
                    "user": addr,
                    "builder": resolved_builder.lower(),
                },
            )
            if result is not None and int(result) > 0:
                return int(result)
            return None
        except Exception as e:
            logger.warning(f"Failed to check builder fee approval: {e}")
            return None

    async def approve_builder_fee(self, max_fee_rate: int = None) -> bool:
        """Approve builder fee for the configured builder address.

        Must be called once per user before builder fees can be charged.
        Uses the SDK's approve_builder_fee (EIP-712 signed).

        Defense-in-depth (SEC-008): both the integer fee and the wire-format
        percentage string are validated before signing. Historical incident:
        the fee was once computed 10x too high; the validators prevent a
        recurrence by refusing anything outside the HL documented range.
        """
        if not self._builder:
            logger.warning("No builder code configured, cannot approve")
            return False

        fee = max_fee_rate or self._builder["f"]
        # Hyperliquid API expects maxFeeRate as percentage string.
        # Internal fee is in tenths of basis points (e.g. 10 = 1bp = 0.01%).
        try:
            assert_builder_fee_tenths_bps(fee)
            fee_pct = f"{fee / 1000:.3f}%"
            validate_approve_builder_fee(
                builder=self._builder["b"],
                max_fee_rate=fee_pct,
                demo_mode=self.demo_mode,
                chain_id=self._expected_chain_id,
            )
        except EIP712ValidationError as e:
            logger.error(f"Builder-fee approval rejected by validator: {e}")
            return False

        try:
            self._exchange.approve_builder_fee(
                builder=self._builder["b"],
                max_fee_rate=fee_pct,
            )
            logger.info(
                f"Builder fee approved: builder={self._builder['b'][:10]}... maxFee={fee_pct}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to approve builder fee: {e}")
            return False

    async def get_referral_info(self, user_address: str = None) -> Optional[dict]:
        """Get referral state for a user (referred_by, referral_code, etc.)."""
        addr = (user_address or self.wallet_address).lower()
        try:
            result = self._info_exec.query_referral_state(addr)
            return result if isinstance(result, dict) else None
        except Exception as e:
            logger.warning(f"Failed to get referral info: {e}")
            return None

    async def get_user_state(self, user_address: str = None) -> Optional[dict]:
        """Raw ``user_state`` query — used for deposit / balance diagnostics.

        Returns the full HL response dict with ``marginSummary``,
        ``withdrawable``, ``assetPositions`` etc. Used by the referral
        verification flow to distinguish "wallet never deposited" from
        "wallet deposited but no referrer set".
        """
        addr = (user_address or self.wallet_address).lower()
        try:
            result = self._info_exec.user_state(addr)
            return result if isinstance(result, dict) else None
        except Exception as e:
            logger.warning(f"Failed to get user state: {e}")
            return None

    async def check_affiliate_uid(self, uid: str) -> bool:
        """Check if a wallet address has been referred via our referral code.

        For Hyperliquid, the 'uid' is the user's wallet address (0x...).
        Checks if `referred_by` is set in the referral state.
        """
        try:
            info = await self.get_referral_info(user_address=uid)
            if info and info.get("referred_by"):
                return True
            return False
        except Exception as e:
            logger.warning(f"Affiliate UID check failed for {uid}: {e}")
            return False

    async def get_user_fees(self, user_address: str = None) -> Optional[dict]:
        """Get user fee/volume tier info (includes trading volume data)."""
        addr = (user_address or self.wallet_address).lower()
        try:
            result = self._info_exec.user_fees(addr)
            return result if isinstance(result, dict) else None
        except Exception as e:
            logger.warning(f"Failed to get user fees: {e}")
            return None

    def calculate_builder_fee(
        self, entry_price: float, exit_price: float, size: float
    ) -> float:
        """Calculate builder fee earned for a round-trip trade.

        Both entry and exit orders carry the builder fee.
        Fee unit: f is in tenths of basis points.
        f=10 → 10 * 0.001% = 0.01% → 0.0001
        Divisor: 10 (tenths) * 10_000 (basis points) = 100_000
        """
        return calculate_builder_fee(self._builder, entry_price, exit_price, size)

    @property
    def builder_config(self) -> Optional[dict]:
        """Return current builder config or None."""
        return self._builder
