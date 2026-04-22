"""Shared trade closing logic for position monitor and rotation manager (thin proxy mixin).

Logic lives in ``src.bot.components.trade_closer.TradeCloser``. This mixin
is a compatibility shim so existing callsites in ``BotWorker``
(``self._close_and_record_trade(...)``) stay unchanged during the ARCH-H1
composition migration. It will be removed in Phase 1 PR-6 (finalize).
"""

from typing import Optional

from src.models.database import TradeRecord


class TradeCloserMixin:
    """Proxies the close-and-record call to the composition-owned ``TradeCloser``."""

    async def _close_and_record_trade(
        self,
        trade: TradeRecord,
        exit_price: float,
        exit_reason: str,
        *,
        fees: Optional[float] = None,
        funding_paid: Optional[float] = None,
        builder_fee: Optional[float] = None,
        strategy_reason: Optional[str] = None,
    ) -> None:
        await self._trade_closer.close_and_record(
            trade,
            exit_price,
            exit_reason,
            fees=fees,
            funding_paid=funding_paid,
            builder_fee=builder_fee,
            strategy_reason=strategy_reason,
        )
