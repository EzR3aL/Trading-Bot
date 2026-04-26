"""Trading operations for the Hyperliquid client.

Order placement, leverage, close, cancel and position-level TP/SL — both
setting and per-leg cancellation — for :class:`HyperliquidClient`. Methods
here use the SDK Exchange wrapped in :class:`SafeExchange` (host attribute
``self._exchange``) and route through ``self._cb_call``.

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from src.exchanges.hyperliquid._helpers import _parse_order_response
from src.exchanges.hyperliquid.fees import DEFAULT_SLIPPAGE
from src.exchanges.hyperliquid.signing import HyperliquidClientError, _derive_cloid
from src.exchanges.types import Order
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HyperliquidTradeMixin:
    """Trading-side operations used by :class:`HyperliquidClient`."""

    async def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> bool:
        coin = self._normalize_symbol(symbol)
        try:
            result = await self._cb_call(self._exchange.update_leverage, leverage=leverage, name=coin, is_cross=(margin_mode == "cross"))
            # Check for error in response (API returns {'status': 'err', ...} instead of raising)
            if isinstance(result, dict) and result.get("status") == "err":
                err_response = result.get("response", str(result))
                logger.error(f"Hyperliquid set_leverage rejected for {coin}: {err_response}")
                raise HyperliquidClientError(err_response)
            logger.info(f"Hyperliquid leverage set to {leverage}x for {coin}")
            return True
        except HyperliquidClientError:
            raise  # Re-raise to trade_executor for user-friendly handling
        except Exception as e:
            logger.warning(f"Hyperliquid set_leverage failed for {coin}: {e}")
            return False

    @staticmethod
    def _derive_cloid(client_order_id: str):
        """Derive a Hyperliquid Cloid (16 bytes hex) from a free-form id.

        Thin wrapper around :func:`signing._derive_cloid` kept as a static
        method on the class so existing call sites
        (``HyperliquidClient._derive_cloid(...)``) and tests continue to
        resolve unchanged.
        """
        return _derive_cloid(client_order_id)

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float,
        leverage: int,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        margin_mode: str = "cross",
        client_order_id: Optional[str] = None,
    ) -> Order:
        coin = self._normalize_symbol(symbol)
        is_buy = side.lower() == "long"

        # Round size to szDecimals to avoid 'float_to_wire causes rounding' error
        sz_decimals = self._get_sz_decimals(coin)
        size = round(size, sz_decimals)

        # Set leverage first
        await self.set_leverage(coin, leverage, margin_mode=margin_mode)

        logger.info(
            f"Hyperliquid market_open: {coin} {'BUY' if is_buy else 'SELL'} "
            f"size={size} leverage={leverage}x wallet={self._wallet.address[:10]}..."
        )

        # Place market order via SDK (handles EIP-712 signing + slippage)
        # Builder fee only on mainnet — testnet has no approval state
        builder_kwargs = {"builder": self._builder} if self._builder and not self.demo_mode else {}
        # Idempotency: derive a 16-byte Cloid from the caller-supplied id so
        # retries after transient errors hit the same logical order (#ARCH-C2).
        cloid_kwargs: Dict[str, Any] = {}
        if client_order_id:
            try:
                cloid_kwargs["cloid"] = self._derive_cloid(client_order_id)
            except Exception as exc:
                logger.warning(
                    f"Hyperliquid: could not derive cloid from '{client_order_id}': {exc}"
                )
        result = await self._cb_call(
            self._exchange.market_open,
            name=coin,
            is_buy=is_buy,
            sz=size,
            slippage=DEFAULT_SLIPPAGE,
            **cloid_kwargs,
            **builder_kwargs,
        )

        # Parse response
        order_status = _parse_order_response(result)
        order_id = order_status.get("oid", "hl-unknown")
        fill_price = float(order_status.get("avgPx", 0))

        logger.info(f"Hyperliquid order placed: oid={order_id}, avgPx={fill_price}")

        # Place TP/SL trigger orders and track failures
        tpsl_failed = False
        if take_profit is not None:
            if not await self._place_trigger_order(coin, not is_buy, size, take_profit, "tp"):
                tpsl_failed = True
        if stop_loss is not None:
            if not await self._place_trigger_order(coin, not is_buy, size, stop_loss, "sl"):
                tpsl_failed = True

        return Order(
            order_id=str(order_id),
            symbol=coin,
            side=side,
            size=size,
            price=fill_price,
            status="filled",
            exchange="hyperliquid",
            leverage=leverage,
            take_profit=take_profit,
            stop_loss=stop_loss,
            tpsl_failed=tpsl_failed,
        )

    def _get_sz_decimals(self, coin: str) -> int:
        """Get size decimal precision for a coin from Hyperliquid meta endpoint."""
        try:
            meta = self._info_exec.meta()
            for asset_info in meta.get("universe", []):
                if asset_info.get("name") == coin:
                    return int(asset_info.get("szDecimals", 0))
        except Exception as e:
            logger.debug(f"Could not fetch szDecimals for {coin}: {e}")
        return 2  # safe default

    def _get_tick_size(self, coin: str) -> float:
        """Get price tick size from Hyperliquid meta_and_asset_ctxs.

        HL uses 5 significant figures for prices. We derive a tick size
        from the current mark price to ensure TP/SL trigger prices are valid.
        """
        try:
            ctx = self._info_exec.meta_and_asset_ctxs()
            if isinstance(ctx, list) and len(ctx) >= 2:
                meta_universe = ctx[0].get("universe", [])
                asset_ctxs = ctx[1]
                for i, asset_info in enumerate(meta_universe):
                    if asset_info.get("name") == coin and i < len(asset_ctxs):
                        mark_px = float(asset_ctxs[i].get("markPx", 0))
                        if mark_px > 0:
                            # HL uses 5 significant figures for prices
                            magnitude = math.floor(math.log10(mark_px))
                            return 10 ** (magnitude - 4)  # 5 sig figs
        except Exception as e:
            logger.debug(f"Could not fetch tick size for {coin}: {e}")
        return 0.01  # safe default

    @staticmethod
    def _round_price(price: float, tick_size: float) -> float:
        """Round price to the nearest tick size (5 significant figures for HL)."""
        if tick_size <= 0:
            return price
        if tick_size >= 1:
            return round(round(price / tick_size) * tick_size)
        decimals = max(0, -int(math.floor(math.log10(tick_size))))
        return round(round(price / tick_size) * tick_size, decimals)

    async def _place_trigger_order(
        self, coin: str, is_buy: bool, size: float, trigger_px: float, tpsl: str,
    ) -> bool:
        """Place a TP or SL trigger order (reduce-only).

        Returns True on success, False on failure or validation skip.

        is_buy is the CLOSE direction (opposite of position side):
        - Long position -> is_buy=False (sell to close)
        - Short position -> is_buy=True (buy to close)
        """
        # Validate trigger price against current market
        try:
            ticker = await self.get_ticker(coin)
            market_px = ticker.last_price
            if market_px > 0:
                # For closing a long (is_buy=False): TP above market, SL below
                # For closing a short (is_buy=True): TP below market, SL above
                if tpsl == "tp":
                    if not is_buy and trigger_px <= market_px:
                        logger.warning(
                            f"Hyperliquid TP trigger for {coin}: price {trigger_px} must be above "
                            f"market {market_px} for long position. Skipping."
                        )
                        return False
                    if is_buy and trigger_px >= market_px:
                        logger.warning(
                            f"Hyperliquid TP trigger for {coin}: price {trigger_px} must be below "
                            f"market {market_px} for short position. Skipping."
                        )
                        return False
                elif tpsl == "sl":
                    if not is_buy and trigger_px >= market_px:
                        logger.warning(
                            f"Hyperliquid SL trigger for {coin}: price {trigger_px} must be below "
                            f"market {market_px} for long position. Skipping."
                        )
                        return False
                    if is_buy and trigger_px <= market_px:
                        logger.warning(
                            f"Hyperliquid SL trigger for {coin}: price {trigger_px} must be above "
                            f"market {market_px} for short position. Skipping."
                        )
                        return False
        except Exception as e:
            logger.debug(f"Could not validate trigger price for {coin}: {e}")

        # Round trigger price to appropriate precision
        rounded_px = self._round_price(trigger_px, self._get_tick_size(coin))

        try:
            builder_kwargs = {"builder": self._builder} if self._builder and not self.demo_mode else {}
            result = await self._cb_call(
                self._exchange.order,
                name=coin,
                is_buy=is_buy,
                sz=size,
                limit_px=rounded_px,
                order_type={
                    "trigger": {
                        "isMarket": True,
                        "triggerPx": float(rounded_px),
                        "tpsl": tpsl,
                    }
                },
                reduce_only=True,
                **builder_kwargs,
            )
            logger.info(f"Hyperliquid {tpsl.upper()} trigger set for {coin} @ {rounded_px}: {result}")
            return True
        except Exception as e:
            logger.warning(f"Hyperliquid {tpsl.upper()} trigger failed for {coin}: {e}")
            return False

    async def close_position(self, symbol: str, side: str, margin_mode: str = "cross") -> Optional[Order]:
        coin = self._normalize_symbol(symbol)

        # Get current position size
        pos = await self.get_position(coin)
        if not pos:
            logger.warning(f"Hyperliquid: no position found for {coin} to close")
            return None

        # Round size to szDecimals to avoid 'float_to_wire causes rounding' error
        sz_decimals = self._get_sz_decimals(coin)
        close_size = round(pos.size, sz_decimals)

        logger.info(
            f"Hyperliquid market_close: {coin} size={close_size} "
            f"wallet={self._wallet.address[:10]}..."
        )

        builder_kwargs = {"builder": self._builder} if self._builder and not self.demo_mode else {}
        result = await self._cb_call(
            self._exchange.market_close,
            coin=coin,
            sz=close_size,
            slippage=DEFAULT_SLIPPAGE,
            **builder_kwargs,
        )

        order_status = _parse_order_response(result)
        order_id = order_status.get("oid", "hl-close")
        fill_price = float(order_status.get("avgPx", 0))

        if order_id == "hl-close" or not order_status.get("oid"):
            logger.warning(
                "Hyperliquid close_position for %s returned no oid — "
                "close may not have executed. Response: %s",
                coin, result,
            )

        logger.info(f"Hyperliquid position closed: oid={order_id}, avgPx={fill_price}")

        return Order(
            order_id=str(order_id),
            symbol=coin,
            side=side,
            size=close_size,
            price=fill_price,
            status="filled",
            exchange="hyperliquid",
        )

    async def set_position_tpsl(
        self,
        symbol: str,
        position_id: str = "",
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        side: str = "long",
        size: Optional[float] = None,
    ) -> Optional[str]:
        """Set position-level TP/SL on Hyperliquid using positionTpsl grouping.

        Unlike normalTpsl (separate trigger orders), positionTpsl:
        - Uses size=0 (auto-matches position size)
        - Adjusts automatically when position size changes
        - Always executes as market order
        """
        if take_profit is None and stop_loss is None:
            return None

        coin = self._normalize_symbol(symbol)
        # For position TP/SL: closing side is opposite
        is_buy_close = side != "long"
        tick_size = self._get_tick_size(coin)
        order_req = []
        builder_kwargs = {"builder": self._builder} if self._builder and not self.demo_mode else {}

        if take_profit is not None:
            rounded_tp = self._round_price(take_profit, tick_size)
            order_req.append({
                "coin": coin,
                "is_buy": is_buy_close,
                "sz": 0,
                "limit_px": float(rounded_tp),
                "order_type": {
                    "trigger": {
                        "isMarket": True,
                        "triggerPx": float(rounded_tp),
                        "tpsl": "tp",
                    }
                },
                "reduce_only": True,
            })

        if stop_loss is not None:
            rounded_sl = self._round_price(stop_loss, tick_size)
            order_req.append({
                "coin": coin,
                "is_buy": is_buy_close,
                "sz": 0,
                "limit_px": float(rounded_sl),
                "order_type": {
                    "trigger": {
                        "isMarket": True,
                        "triggerPx": float(rounded_sl),
                        "tpsl": "sl",
                    }
                },
                "reduce_only": True,
            })

        try:
            result = await self._cb_call(
                self._exchange.bulk_orders,
                order_req,
                grouping="positionTpsl",
                **builder_kwargs,
            )
            logger.info(
                "Hyperliquid position TP/SL set for %s: TP=%s SL=%s result=%s",
                coin, take_profit, stop_loss, result,
            )
            return str(result)
        except Exception as e:
            logger.warning("Hyperliquid position TP/SL failed for %s: %s", coin, e)
            # Fallback to individual trigger orders
            try:
                sz_decimals = self._get_sz_decimals(coin)
                rounded_size = round(size, sz_decimals) if size else 0
                if take_profit is not None:
                    await self._place_trigger_order(coin, is_buy_close, rounded_size, take_profit, "tp")
                if stop_loss is not None:
                    await self._place_trigger_order(coin, is_buy_close, rounded_size, stop_loss, "sl")
                return "fallback"
            except Exception as e2:
                logger.warning("Hyperliquid trigger fallback also failed: %s", e2)
        return None

    async def cancel_position_tpsl(
        self,
        symbol: str,
        side: str = "long",
    ) -> bool:
        """Cancel all position-level TP/SL triggers on Hyperliquid.

        Attempts to clear via empty positionTpsl bulk_orders first.
        Falls back to querying open orders and cancelling trigger orders.
        """
        return await self._cancel_triggers_by_tpsl(symbol, side, target_tpsl=None)

    async def cancel_tp_only(self, symbol: str, side: str = "long") -> bool:
        """Cancel only TP trigger orders for an open position.

        Queries ``frontendOpenOrders``, filters to position-linked triggers
        classified as TP by ``_classify_tpsl`` (``orderType`` / ``tpsl`` /
        ``triggerCondition`` fields), then cancels each by ``oid``. SL and
        any non-trigger orders remain untouched. Epic #188 follow-up to the
        Bitget leg-cancel pair on dashboard edits.
        """
        return await self._cancel_triggers_by_tpsl(symbol, side, target_tpsl="tp")

    async def cancel_sl_only(self, symbol: str, side: str = "long") -> bool:
        """Cancel only SL trigger orders for an open position.

        Mirror of :meth:`cancel_tp_only`. HL has no native trailing primitive,
        so software-emulated trailing (rewritten as an SL trigger) is also
        cleared by this method — callers that want to keep a trailing leg
        must re-place it after calling this.
        """
        return await self._cancel_triggers_by_tpsl(symbol, side, target_tpsl="sl")

    async def _cancel_triggers_by_tpsl(
        self, symbol: str, side: str, target_tpsl: Optional[str],
    ) -> bool:
        """Shared helper: query open orders, filter, cancel by ``oid``.

        :param target_tpsl: ``"tp"`` or ``"sl"`` for leg-specific cancel,
            ``None`` to cancel every trigger order on the coin (legacy
            ``cancel_position_tpsl`` behaviour).
        """
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()

        try:
            open_orders = self._info_exec.frontend_open_orders(address)
        except Exception as e:
            logger.warning("Failed to query frontend open orders for %s: %s", coin, e)
            return False

        if not isinstance(open_orders, list):
            return True

        to_cancel: List[Dict[str, Any]] = []
        for order in open_orders:
            if not isinstance(order, dict):
                continue
            if order.get("coin") != coin:
                continue
            if not (order.get("isTrigger") or order.get("isPositionTpsl")):
                continue
            if target_tpsl is None:
                to_cancel.append(order)
                continue
            if self._classify_tpsl(order, side) == target_tpsl:
                to_cancel.append(order)

        if not to_cancel:
            logger.debug(
                "No %s trigger orders to cancel for %s",
                target_tpsl or "tpsl", coin,
            )
            return True

        for order in to_cancel:
            oid = order.get("oid")
            if oid is None:
                continue
            try:
                self._exchange.cancel(coin, oid)
                logger.info(
                    "Cancelled Hyperliquid %s trigger %s for %s",
                    target_tpsl or "tpsl", oid, coin,
                )
            except Exception as e:
                logger.warning("Failed to cancel Hyperliquid order %s: %s", oid, e)

        return True

    @staticmethod
    def _classify_tpsl(order: Dict[str, Any], side: str) -> Optional[str]:
        """Classify a HL trigger order as ``"tp"`` or ``"sl"``.

        HL's ``frontendOpenOrders`` response does not expose the original
        ``tpsl`` field from the order spec, so we derive it from
        ``orderType`` (e.g. ``"Take Profit Market"`` vs ``"Stop Market"``)
        — the same heuristic used by :meth:`get_position_tpsl` (#191) so
        both methods stay in lockstep. Falls back to ``triggerCondition``
        + position side when ``orderType`` is missing or ambiguous:

        - Long position: TP triggers above entry (``Price >=``),
          SL triggers below entry (``Price <=``).
        - Short position: inverse.

        Returns ``None`` when classification is not possible; callers
        treat this as "do not touch" to avoid false cancels.
        """
        order_type = str(order.get("orderType") or "").lower()
        if "tp" in order_type or "take" in order_type:
            return "tp"
        if "sl" in order_type or "stop" in order_type:
            return "sl"

        # Fallback: infer from triggerCondition + position side.
        condition = str(order.get("triggerCondition") or "").lower()
        is_long = side.lower() == "long"
        if ">=" in condition or "above" in condition:
            return "tp" if is_long else "sl"
        if "<=" in condition or "below" in condition:
            return "sl" if is_long else "tp"
        return None

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        coin = self._normalize_symbol(symbol)
        try:
            await self._cb_call(self._exchange.cancel, name=coin, oid=int(order_id))
            logger.info(f"Hyperliquid order cancelled: {coin} oid={order_id}")
            return True
        except Exception as e:
            logger.warning(f"Hyperliquid cancel failed: {e}")
            return False
