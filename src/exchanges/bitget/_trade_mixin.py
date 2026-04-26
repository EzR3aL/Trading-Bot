"""Trade-side operations for the Bitget client.

Order placement, leverage, position TP/SL, native trailing stops,
flash-close and the per-symbol contract-info / price-rounding helpers
that the trade methods depend on. Methods here expect the host class
to expose ``_request`` (from :class:`HTTPExchangeClientMixin`),
``get_position`` (from :class:`BitgetReadMixin`) and the module-level
``BitgetClientError`` (re-exported from ``client.py``).

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any, Dict, Literal, Optional

from src.exchanges.bitget._helpers import _log_bitget_cancel_outcome
from src.exchanges.bitget.constants import ENDPOINTS, PRODUCT_TYPE_USDT
from src.exchanges.bitget.signing import BitgetClientError
from src.exchanges.types import Order
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BitgetTradeMixin:
    """Trade / order-management methods used by :class:`BitgetExchangeClient`."""

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
        # Set leverage first
        await self.set_leverage(symbol, leverage, margin_mode=margin_mode)

        api_margin = "crossed" if margin_mode == "cross" else "isolated"
        order_side = "buy" if side == "long" else "sell"
        # Round to the exchange's volumePlace so the DB value matches what
        # Bitget actually books. Otherwise a 6-decimal caller value (e.g.
        # 11.978866) gets silently truncated to 11.97 on the exchange,
        # desyncing trade.size from the real position and breaking later
        # trailing-stop/close operations that expect an exact match.
        contract = await self._get_contract_info(symbol)
        volume_place = contract["volumePlace"]
        rounded_size = math.floor(size * 10**volume_place) / 10**volume_place
        size = rounded_size
        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginMode": api_margin,
            "marginCoin": "USDT",
            "side": order_side,
            "tradeSide": "open",
            "orderType": "market",
            "size": str(rounded_size),
        }
        # Idempotency: forward ``client_order_id`` as Bitget's ``clientOid``.
        # Bitget requires it to be <= 40 chars; the executor hands us a
        # ``bot-<id>-<uuid>`` shape that fits comfortably (#ARCH-C2).
        if client_order_id:
            data["clientOid"] = str(client_order_id)[:40]

        result = await self._request("POST", ENDPOINTS["place_order"], data=data)

        order_id = result.get("orderId", result.get("data", {}).get("orderId", ""))

        # Set Entire TP/SL via dedicated endpoint (covers full position)
        # Brief delay to ensure order fill is registered before setting TP/SL
        tpsl_failed = False
        if take_profit is not None or stop_loss is not None:
            await asyncio.sleep(0.2)
            for attempt in range(2):
                try:
                    await self._set_position_tpsl(
                        symbol=symbol,
                        hold_side=side,
                        take_profit=take_profit,
                        stop_loss=stop_loss,
                    )
                    tpsl_failed = False
                    break
                except Exception as e:
                    tpsl_failed = True
                    if attempt == 0:
                        logger.warning(f"TP/SL attempt 1 failed for {symbol}, retrying: {e}")
                        await asyncio.sleep(0.5)
                    else:
                        logger.error(
                            f"CRITICAL: TP/SL failed for {symbol} after 2 attempts: {e}. "
                            "Position is UNPROTECTED — manual intervention required."
                        )

        return Order(
            order_id=str(order_id),
            symbol=symbol,
            side=side,
            size=size,
            price=0.0,  # Market order; fill price obtained separately
            status="filled",
            exchange="bitget",
            leverage=leverage,
            take_profit=take_profit,
            stop_loss=stop_loss,
            tpsl_failed=tpsl_failed,
        )

    async def _set_position_tpsl(
        self,
        symbol: str,
        hold_side: str,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
    ) -> None:
        """Set Entire TP/SL for a position (covers full position size)."""
        contract = await self._get_contract_info(symbol)
        pp = contract["pricePlace"]
        ps = contract["priceEndStep"]

        tpsl_data: Dict[str, str] = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": "USDT",
            "holdSide": hold_side,
        }
        if take_profit is not None:
            tpsl_data["stopSurplusTriggerPrice"] = str(self._round_price(take_profit, pp, ps))
            tpsl_data["stopSurplusTriggerType"] = "fill_price"
        if stop_loss is not None:
            tpsl_data["stopLossTriggerPrice"] = str(self._round_price(stop_loss, pp, ps))
            tpsl_data["stopLossTriggerType"] = "fill_price"

        await self._request(
            "POST",
            "/api/v2/mix/order/place-pos-tpsl",
            data=tpsl_data,
        )
        logger.info(f"Entire TP/SL set for {symbol} {hold_side}: TP={take_profit}, SL={stop_loss}")

    async def set_position_tpsl(
        self,
        symbol: str,
        position_id: Optional[str] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        side: str = "long",
        size: float = 0,
    ) -> None:
        """Public wrapper for Bitget position TP/SL."""
        await self._set_position_tpsl(symbol, side, take_profit, stop_loss)

    async def cancel_position_tpsl(
        self,
        symbol: str,
        side: str = "long",
    ) -> bool:
        """Cancel position-level TP/SL and moving plans on Bitget.

        Uses cancel-plan-order with ``{symbol, productType, planType}`` per
        plan type. Live-verified against Bitget demo (hedge_mode): this form
        cancels every matching plan for the symbol including ``moving_plan``.
        The orderIdList-based variant was tried and silently no-ops in demo,
        so we stay with the simpler per-planType form.

        Note: this cancels every plan of these types on the symbol, not just
        the ``side``. Bitget plan orders are keyed by symbol+planType; the
        per-side filter is done by the caller when needed.
        """
        plan_types = ["pos_profit", "pos_loss", "moving_plan", "profit_plan", "loss_plan"]

        for plan_type in plan_types:
            try:
                result = await self._request(
                    "POST",
                    "/api/v2/mix/order/cancel-plan-order",
                    data={
                        "symbol": symbol,
                        "productType": PRODUCT_TYPE_USDT,
                        "planType": plan_type,
                    },
                )
                success = result.get("successList", []) if isinstance(result, dict) else []
                if success:
                    logger.info(
                        "Cancelled Bitget %s for %s: %s",
                        plan_type, symbol, [s.get("orderId") for s in success],
                    )
            except Exception as e:
                _log_bitget_cancel_outcome(
                    "cancel_position_tpsl", plan_type, symbol, e,
                )

        return True

    async def cancel_native_trailing_stop(self, symbol: str, side: str = "long") -> bool:
        """Cancel only the ``moving_plan`` (native trailing stop) for a symbol.

        Needed so the TP/SL edit endpoint can replace trailing without
        touching user-set TP/SL plans.
        """
        return await self._cancel_plan_types(symbol, ["moving_plan"])

    async def cancel_tp_only(self, symbol: str, side: str = "long") -> bool:
        """Cancel only take-profit plans (``pos_profit`` + ``profit_plan``).

        Leaves ``pos_loss`` (SL) and ``moving_plan`` (trailing) alive.
        Used by :class:`RiskStateManager` so that clearing one leg via the
        dashboard never collapses the other legs — see Epic #188 follow-up
        to #192.
        """
        return await self._cancel_plan_types(symbol, ["pos_profit", "profit_plan"])

    async def cancel_sl_only(self, symbol: str, side: str = "long") -> bool:
        """Cancel only stop-loss plans (``pos_loss`` + ``loss_plan``)."""
        return await self._cancel_plan_types(symbol, ["pos_loss", "loss_plan"])

    async def _cancel_plan_types(self, symbol: str, plan_types: list[str]) -> bool:
        """Shared helper: cancel every plan of the given types on ``symbol``.

        Per-plan-type failures are classified via
        :func:`_log_bitget_cancel_outcome` — benign "no matching plan"
        errors stay at DEBUG, genuine network/auth/contract errors
        escalate to WARN (Pattern C mitigation per #225).
        """
        for plan_type in plan_types:
            try:
                result = await self._request(
                    "POST",
                    "/api/v2/mix/order/cancel-plan-order",
                    data={
                        "symbol": symbol,
                        "productType": PRODUCT_TYPE_USDT,
                        "planType": plan_type,
                    },
                )
                success = result.get("successList", []) if isinstance(result, dict) else []
                if success:
                    logger.info(
                        "Cancelled Bitget %s for %s: %s",
                        plan_type, symbol, [s.get("orderId") for s in success],
                    )
            except Exception as e:
                _log_bitget_cancel_outcome(
                    "_cancel_plan_types", plan_type, symbol, e,
                )
        return True

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "orderId": order_id,
        }
        try:
            await self._request("POST", ENDPOINTS["cancel_order"], data=data)
            return True
        except BitgetClientError:
            return False

    async def close_position(self, symbol: str, side: str, margin_mode: str = "cross") -> Optional[Order]:
        # Get position size and actual hold side from exchange
        pos = await self.get_position(symbol)
        if not pos:
            return None

        actual_side = pos.side  # "long" or "short" from exchange

        # Use flash-close endpoint (works reliably in both hedge and one-way mode)
        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "holdSide": actual_side,
        }
        result = await self._request("POST", ENDPOINTS["close_positions"], data=data)

        success_list = result.get("successList", [])
        order_id = success_list[0].get("orderId", "") if success_list else ""

        if not order_id:
            logger.warning(
                "Bitget close_position for %s returned empty orderId — "
                "close may not have executed. Response: %s",
                symbol, result,
            )

        return Order(
            order_id=str(order_id),
            symbol=symbol,
            side=side,
            size=pos.size,
            price=0.0,
            status="filled",
            exchange="bitget",
        )

    async def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> bool:
        for hold_side in ("long", "short"):
            data = {
                "symbol": symbol,
                "productType": PRODUCT_TYPE_USDT,
                "marginCoin": "USDT",
                "leverage": str(leverage),
                "holdSide": hold_side,
            }
            try:
                # Skip circuit breaker — leverage errors are expected when
                # a position already exists and should not poison the breaker
                await self._request("POST", ENDPOINTS["set_leverage"], data=data,
                                    use_circuit_breaker=False)
            except BitgetClientError as e:
                err_msg = str(e).lower()
                # "already set" is fine — leverage matches what we want
                if "same" in err_msg or "not changed" in err_msg or "equal" in err_msg:
                    continue
                # Position open with different leverage — cannot change
                logger.warning("set_leverage failed for %s %s: %s", symbol, hold_side, e)
                return False
        return True

    async def place_raw_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        trade_side: Literal["open", "close"],
        size: str,
        order_type: Literal["market", "limit"] = "market",
        price: Optional[str] = None,
        take_profit: Optional[str] = None,
        stop_loss: Optional[str] = None,
        margin_mode: str = "cross",
    ) -> Dict[str, Any]:
        """Place an order using raw Bitget API format."""
        api_margin = "crossed" if margin_mode == "cross" else "isolated"
        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginMode": api_margin,
            "marginCoin": "USDT",
            "side": side,
            "tradeSide": trade_side,
            "orderType": order_type,
            "size": size,
        }
        if price and order_type == "limit":
            data["price"] = price
        if take_profit:
            data["presetStopSurplusPrice"] = take_profit
        if stop_loss:
            data["presetStopLossPrice"] = stop_loss

        return await self._request("POST", ENDPOINTS["place_order"], data=data)

    # ==================== Trailing Stop ====================

    async def _get_contract_info(self, symbol: str) -> dict:
        """Fetch contract specification for a symbol from Bitget contracts API.

        Returns dict with 'volumePlace' and 'pricePlace' (decimal precision).
        """
        try:
            result = await self._request(
                "GET", ENDPOINTS["contracts"],
                params={"productType": PRODUCT_TYPE_USDT, "symbol": symbol},
                use_circuit_breaker=False,
            )
            contracts = result if isinstance(result, list) else [result] if result else []
            for c in contracts:
                if c.get("symbol") == symbol:
                    return {
                        "volumePlace": int(c.get("volumePlace", 2)),
                        "pricePlace": int(c.get("pricePlace", 2)),
                        "priceEndStep": int(c.get("priceEndStep", 1)),
                    }
        except Exception:
            pass
        return {"volumePlace": 2, "pricePlace": 2, "priceEndStep": 1}

    async def _get_volume_place(self, symbol: str) -> int:
        """Fetch volumePlace (size decimal precision) for a symbol."""
        info = await self._get_contract_info(symbol)
        return info["volumePlace"]

    def _round_price(self, price: float, price_place: int, price_end_step: int) -> float:
        """Round price to exchange precision using pricePlace and priceEndStep.

        pricePlace = number of decimal places (e.g. 1 for BTC → $70000.1)
        priceEndStep = minimum tick increment at the last decimal
                       (e.g. 5 means price must end in 0 or 5)
        """
        factor = 10 ** price_place
        stepped = math.floor(price * factor / price_end_step) * price_end_step
        return stepped / factor

    async def place_trailing_stop(
        self,
        symbol: str,
        hold_side: str,
        size: float,
        callback_ratio: float,
        trigger_price: float,
        margin_mode: str = "cross",
    ) -> Optional[dict]:
        """Place a position-level trailing stop (moving_plan) on Bitget.

        Uses place-tpsl-order with planType=moving_plan, which shows up in
        the Bitget UI under "Trailing TP/SL" on the position card.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT")
            hold_side: "long" or "short"
            size: Position size
            callback_ratio: Trail distance in % (e.g. 2.5 = 2.5%)
            trigger_price: Price at which trailing begins
            margin_mode: "cross" or "isolated"

        Returns:
            API response dict or None on failure.
        """
        api_margin = "crossed" if margin_mode == "cross" else "isolated"

        # Fetch contract precision for size and price
        contract = await self._get_contract_info(symbol)
        volume_place = contract["volumePlace"]
        rounded_size = math.floor(size * 10**volume_place) / 10**volume_place

        # Round trigger price to exchange precision
        rounded_trigger = self._round_price(
            trigger_price, contract["pricePlace"], contract["priceEndStep"],
        )

        # rangeRate must have exactly 2 decimal places
        range_rate = f"{callback_ratio:.2f}"

        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginMode": api_margin,
            "marginCoin": "USDT",
            "planType": "moving_plan",
            "triggerPrice": str(rounded_trigger),
            "triggerType": "mark_price",
            "rangeRate": range_rate,
            "holdSide": hold_side,
            "size": str(rounded_size),
        }

        result = await self._request(
            "POST", ENDPOINTS["place_tpsl_order"], data=data,
            use_circuit_breaker=False,
        )
        logger.info(
            "Trailing stop placed on Bitget: %s %s size=%s rangeRate=%s%% trigger=$%.2f",
            symbol, hold_side, rounded_size, range_rate, trigger_price,
        )
        return result

    async def has_native_trailing_stop(self, symbol: str, hold_side: str) -> bool:
        """Query pending plan orders for a live ``moving_plan`` on this side.

        Bitget's plan-order API exposes every active TP/SL/trailing plan; we
        look for any whose planType is ``moving_plan`` and posSide/holdSide
        matches. Returns False on any error so callers treat the check as
        inconclusive and fall through to the normal placement attempt.
        """
        try:
            r = await self._request(
                "GET",
                "/api/v2/mix/order/orders-plan-pending",
                params={
                    "productType": PRODUCT_TYPE_USDT,
                    "symbol": symbol,
                    "planType": "profit_loss",
                },
                auth=True,
            )
            entries = r.get("entrustedList") if isinstance(r, dict) else None
            if not entries:
                return False
            for p in entries:
                if p.get("planType") != "moving_plan":
                    continue
                side_field = p.get("posSide") or p.get("holdSide") or ""
                status = p.get("planStatus", "")
                if side_field.lower() == hold_side.lower() and status == "live":
                    return True
        except Exception as e:
            logger.debug("has_native_trailing_stop(%s,%s) failed: %s", symbol, hold_side, e)
        return False
