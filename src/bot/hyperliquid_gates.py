"""Hyperliquid pre-flight gate checks for BotWorker (thin proxy mixin).

Logic lives in ``src.bot.components.hyperliquid_gates.HyperliquidGates``.
This mixin is a compatibility shim so existing callsites in ``BotWorker``
(``self._check_referral_gate(...)`` etc.) stay unchanged during the ARCH-H1
composition migration. It will be removed in Phase 1 PR-6 (finalize).
"""

from src.exchanges.base import ExchangeClient


class HyperliquidGatesMixin:
    """Proxies gate-check calls to the composition-owned ``HyperliquidGates``
    component and translates results into the legacy error-state contract
    (``self.error_message`` / ``self.status = "error"`` on failure).
    """

    async def _check_referral_gate(self, client: ExchangeClient, db) -> bool:
        result = await self._hl_gates.check_referral(client, db)
        if not result.ok:
            self.error_message = result.error_message
            self.status = "error"
        return result.ok

    async def _check_builder_approval(self, client: ExchangeClient, db) -> bool:
        result = await self._hl_gates.check_builder_approval(client, db)
        if not result.ok:
            self.error_message = result.error_message
            self.status = "error"
        return result.ok

    async def _check_wallet_gate(self, client: ExchangeClient) -> bool:
        result = await self._hl_gates.check_wallet(client)
        if not result.ok:
            self.error_message = result.error_message
            self.status = "error"
        return result.ok

    async def _check_affiliate_uid_gate(self, db) -> bool:
        result = await self._hl_gates.check_affiliate_uid(db)
        if not result.ok:
            self.error_message = result.error_message
            self.status = "error"
        return result.ok
