"""Affiliate / position-sizing helpers for the Bitget client.

Holds the broker-affiliate UID lookup and the legacy
``calculate_position_size`` convenience used by older callers. Methods
here expect the host class to expose ``_request`` (from
:class:`HTTPExchangeClientMixin`).

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

from src.utils.logger import get_logger

logger = get_logger(__name__)


class BitgetAffiliateMixin:
    """Affiliate / sizing helpers used by :class:`BitgetExchangeClient`."""

    async def check_affiliate_uid(self, uid: str) -> bool:
        """Check if a UID is in our affiliate referral list via Bitget Broker API.

        Uses GET /api/v2/broker/subaccounts with direct uid filter
        to verify the user signed up through our affiliate link.
        Falls back to commission endpoint if subaccounts endpoint is unavailable.
        """
        try:
            # Primary: broker subaccounts endpoint with uid filter
            result = await self._request(
                "GET",
                "/api/v2/broker/subaccounts",
                params={"uid": str(uid), "pageSize": "10", "pageNo": "1"},
            )
            items = result if isinstance(result, list) else result.get("list", [])
            for item in items:
                if str(item.get("uid", "")) == str(uid):
                    return True
            # If no match via subaccounts, try commission endpoint as fallback
            if not items:
                result = await self._request(
                    "GET",
                    "/api/v2/broker/customer-commissions",
                    params={"uid": str(uid)},
                )
                items = result if isinstance(result, list) else result.get("list", [])
                return len(items) > 0
            return False
        except Exception as e:
            logger.warning(f"Affiliate UID check failed for {uid}: {e}")
            return False

    def calculate_position_size(
        self, balance: float, price: float, risk_percent: float, leverage: int,
    ) -> float:
        """Calculate position size based on risk parameters."""
        risk_amount = balance * (risk_percent / 100)
        position_value = risk_amount * leverage
        return round(position_value / price, 6)
