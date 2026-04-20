"""
Weex Exchange Client implementing ExchangeClient ABC.

Trading endpoints migrated to V3 (/capi/v3/) as of 2026-03-09.
V3 uses plain symbols (BTCUSDT) and BUY/SELL + LONG/SHORT params.
Account/position/leverage endpoints remain on V2 (cmt_btcusdt format).
Auth: HMAC-SHA256 + Base64 (same algorithm as Bitget).
"""

import asyncio
import base64
import hashlib
import hmac
import time
import uuid
from typing import Any, Dict, List, Optional

import aiohttp

from src.exceptions import ExchangeError
from src.exchanges.base import ExchangeClient, HTTPExchangeClientMixin
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker
from src.exchanges.weex.constants import (
    BASE_URL,
    ENDPOINTS,
    MARGIN_CROSS,
    MARGIN_ISOLATED,
    SUCCESS_CODE,
)
from src.utils.circuit_breaker import circuit_registry
from src.utils.logger import get_logger

logger = get_logger(__name__)

_weex_breaker = circuit_registry.get("weex_api", fail_threshold=5, reset_timeout=60)


class WeexClientError(ExchangeError):
    """Custom exception for Weex API errors."""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__("weex", message, original_error)


class WeexClient(HTTPExchangeClientMixin, ExchangeClient):
    """Weex Futures exchange client.

    Uses HTTPExchangeClientMixin for session management, circuit breaker,
    and the standard REST request flow.
    """

    _client_error_class = WeexClientError

    @property
    def _circuit_breaker(self):
        return _weex_breaker

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        demo_mode: bool = True,
        **kwargs,
    ):
        super().__init__(api_key, api_secret, passphrase, demo_mode)
        self.base_url = BASE_URL
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info(f"WeexClient initialized ({'DEMO' if demo_mode else 'LIVE'} mode)")

    @property
    def exchange_name(self) -> str:
        return "weex"

    @property
    def supports_demo(self) -> bool:
        return True

    # ── Symbol transformation ──────────────────────────────────────

    def _to_api_symbol(self, symbol: str) -> str:
        """Convert DB symbol (BTCUSDT) to Weex API format.

        BTCUSDT -> cmt_btcusdt
        Demo/live use the same symbol; demo is account-level on Weex.
        """
        base = symbol.replace("USDT", "").lower()
        return f"cmt_{base}usdt"

    def _from_api_symbol(self, api_symbol: str) -> str:
        """Convert Weex API symbol back to DB format.

        cmt_btcusdt -> BTCUSDT
        """
        s = api_symbol.replace("cmt_", "")
        if s.endswith("usdt"):
            base = s[:-4]
        else:
            base = s
        return f"{base.upper()}USDT"

    # ── Auth ──────────────────────────────────────────────────────

    def _generate_signature(self, timestamp: str, method: str,
                            request_path: str, body: str = "") -> str:
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()

    def _get_headers(self, method: str, request_path: str,
                     body: str = "") -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp, method, request_path, body)
        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }
        if self.demo_mode:
            headers["paptrading"] = "1"
        return headers

    # ── Response parsing ──────────────────────────────────────────

    def _parse_response(self, result: Any, response: aiohttp.ClientResponse) -> Any:
        """Parse Weex API response — handles non-dict, missing code, and error codes."""
        # Some endpoints return raw list/data without {code, data} wrapper
        if not isinstance(result, dict):
            if response.status == 200:
                return result
            raise WeexClientError(
                f"Weex API Error: unexpected response (status={response.status})"
            )

        code = result.get("code")
        logger.debug(f"Weex response: status={response.status} code={code}")

        # Some endpoints return dict without code wrapper
        if code is None and response.status == 200:
            return result

        if response.status != 200 or str(code) != SUCCESS_CODE:
            msg = result.get("msg", result.get("message", "Unknown"))
            raise WeexClientError(
                f"Weex API Error: {msg} (code={code}, status={response.status})"
            )
        return result.get("data", result)

    # ── Account ────────────────────────────────────────────────────

    async def get_account_balance(self) -> Balance:
        """V3: GET /capi/v3/account/balance returns array of {asset, balance,
        availableBalance, frozen, unrealizePnl}.
        """
        data = await self._request("GET", ENDPOINTS["account_assets"])
        items = data if isinstance(data, list) else [data] if data else []
        usdt_item = None
        for item in items:
            asset = (item.get("asset") or item.get("coinName") or "").upper()
            if asset in ("USDT", "SUSDT"):
                usdt_item = item
                break
        item = usdt_item or (items[0] if items else {})
        return Balance(
            total=float(item.get("balance") or item.get("equity") or item.get("accountEquity") or 0),
            available=float(item.get("availableBalance") or item.get("available") or 0),
            unrealized_pnl=float(item.get("unrealizePnl") or item.get("unrealizedPL") or 0),
        )

    # ── Orders ─────────────────────────────────────────────────────

    async def place_market_order(
        self, symbol: str, side: str, size: float, leverage: int,
        take_profit: Optional[float] = None, stop_loss: Optional[float] = None,
        margin_mode: str = "cross",
    ) -> Order:
        # Leverage is set by trade_executor before calling this method

        # V3 uses plain symbols (BTCUSDT) and BUY/SELL + LONG/SHORT
        v3_symbol = symbol.upper().replace("-", "")
        v3_side = "SELL" if side == "short" else "BUY"
        v3_position_side = "SHORT" if side == "short" else "LONG"

        data: Dict[str, Any] = {
            "symbol": v3_symbol,
            "newClientOrderId": uuid.uuid4().hex[:32],
            "side": v3_side,
            "positionSide": v3_position_side,
            "type": "MARKET",
            "quantity": str(round(size, 4)),
        }
        if take_profit is not None:
            data["tpTriggerPrice"] = str(take_profit)
        if stop_loss is not None:
            data["slTriggerPrice"] = str(stop_loss)

        result = await self._request("POST", ENDPOINTS["place_order"], data=data)
        return Order(
            order_id=str(result.get("orderId", result.get("order_id", ""))),
            symbol=symbol, side=side, size=size, price=0.0,
            status="filled", exchange="weex", leverage=leverage,
            take_profit=take_profit, stop_loss=stop_loss,
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """V3: DELETE /capi/v3/order?orderId=..."""
        try:
            await self._request("DELETE", ENDPOINTS["cancel_order"], params={
                "orderId": order_id,
            })
            return True
        except WeexClientError:
            return False

    async def close_position(self, symbol: str, side: str, margin_mode: str = "cross") -> Optional[Order]:
        """Close position using V3 flash-close endpoint."""
        pos = await self.get_position(symbol)
        if not pos:
            return None
        # V3 closePositions uses plain symbol
        v3_symbol = symbol.upper().replace("-", "")
        result = await self._request("POST", ENDPOINTS["close_positions"], data={
            "symbol": v3_symbol,
        })
        order_id = ""
        if isinstance(result, list) and result:
            first = result[0]
            if isinstance(first, dict) and first.get("success"):
                order_id = str(first.get("successOrderId", first.get("orderId", "")))
        elif isinstance(result, dict):
            order_id = str(result.get("orderId", result.get("order_id", "")))
        if not order_id:
            logger.warning(
                "Weex close_position for %s returned empty orderId — "
                "close may not have executed. Response: %s",
                symbol, result,
            )
        return Order(
            order_id=order_id, symbol=symbol, side=side,
            size=pos.size, price=0.0, status="filled", exchange="weex",
        )

    # ── Positions ──────────────────────────────────────────────────

    def _parse_position(self, pos: Dict, fallback_symbol: str = "") -> Optional[Position]:
        """Parse a single position dict (V3 or V2 shape)."""
        # V3: size, V2: hold_amount/holdAmount/total
        total = float(
            pos.get("size") or pos.get("hold_amount")
            or pos.get("holdAmount") or pos.get("total") or 0
        )
        if total <= 0:
            return None
        # V3: side="LONG"/"SHORT", V2: side="1"/"2" or holdSide
        raw_side = str(pos.get("side") or pos.get("holdSide") or "long").upper()
        hold_side = "long" if raw_side in ("1", "LONG") else "short"
        api_sym = pos.get("symbol") or ""
        # V3 returns plain BTCUSDT, V2 returns cmt_btcusdt
        if api_sym.startswith("cmt_"):
            db_symbol = self._from_api_symbol(api_sym)
        elif api_sym:
            db_symbol = api_sym.upper()
        else:
            db_symbol = fallback_symbol
        return Position(
            symbol=db_symbol, side=hold_side, size=total,
            entry_price=float(
                pos.get("cost_open") or pos.get("averageOpenPrice")
                or pos.get("openPriceAvg") or pos.get("openValue") or 0
            ),
            current_price=float(pos.get("markPrice") or pos.get("mark_price") or 0),
            unrealized_pnl=float(
                pos.get("unrealizePnl") or pos.get("profit_unreal")
                or pos.get("unrealizedPnl") or pos.get("unrealizedPL") or 0
            ),
            leverage=int(float(pos.get("leverage") or 1)),
            exchange="weex",
        )

    async def get_position(self, symbol: str) -> Optional[Position]:
        # V3 single_position takes plain symbol (BTCUSDT)
        v3_symbol = symbol.upper().replace("-", "")
        data = await self._request("GET", ENDPOINTS["single_position"], params={
            "symbol": v3_symbol,
        })
        positions = data if isinstance(data, list) else [data] if data else []
        for pos in positions:
            result = self._parse_position(pos, fallback_symbol=symbol)
            if result:
                return result
        return None

    async def get_open_positions(self) -> List[Position]:
        data = await self._request("GET", ENDPOINTS["all_positions"])
        positions = []
        for pos in (data if isinstance(data, list) else []):
            result = self._parse_position(pos)
            if result:
                positions.append(result)
        return positions

    # ── Leverage ───────────────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> bool:
        api_symbol = self._to_api_symbol(symbol)
        margin = MARGIN_CROSS if margin_mode == "cross" else MARGIN_ISOLATED
        try:
            await self._request("POST", ENDPOINTS["set_leverage"], data={
                "symbol": api_symbol,
                "marginMode": margin,
                "longLeverage": str(leverage),
                "shortLeverage": str(leverage),
            })
        except WeexClientError as e:
            logger.warning("set_leverage failed for %s: %s", symbol, e)
            return False
        return True

    # ── Market data ────────────────────────────────────────────────

    async def get_ticker(self, symbol: str) -> Ticker:
        api_symbol = self._to_api_symbol(symbol)
        data = await self._request("GET", ENDPOINTS["ticker"], params={
            "symbol": api_symbol,
        }, auth=False)
        if isinstance(data, list):
            data = data[0] if data else {}
        return Ticker(
            symbol=symbol,
            last_price=float(data.get("last", 0)),
            bid=float(data.get("best_bid", 0)),
            ask=float(data.get("best_ask", 0)),
            volume_24h=float(data.get("volume_24h", data.get("base_volume", 0))),
        )

    async def get_funding_rate(self, symbol: str) -> FundingRateInfo:
        """V3: GET /capi/v3/market/premiumIndex?symbol=BTCUSDT
        Returns {symbol, lastFundingRate, forecastFundingRate, ...}.
        """
        v3_symbol = symbol.upper().replace("-", "")
        data = await self._request("GET", ENDPOINTS["funding_rate"], params={
            "symbol": v3_symbol,
        }, auth=False)
        rate = 0.0
        if isinstance(data, dict):
            rate = float(
                data.get("lastFundingRate")
                or data.get("fundingRate")
                or 0
            )
        elif isinstance(data, list):
            for item in data:
                if str(item.get("symbol", "")).upper() == v3_symbol:
                    rate = float(item.get("lastFundingRate") or item.get("fundingRate") or 0)
                    break
        return FundingRateInfo(symbol=symbol, current_rate=rate)

    async def get_close_fill_price(self, symbol: str) -> Optional[float]:
        """Get fill price of the most recent close order from V3 order history."""
        try:
            v3_symbol = symbol.upper().replace("-", "")
            data = await self._request("GET", ENDPOINTS["orders_history"], params={
                "symbol": v3_symbol,
                "limit": "20",
            })
            orders = data if isinstance(data, list) else data.get("list", []) if isinstance(data, dict) else []
            for order in orders:
                status = order.get("status", "")
                pos_side = order.get("positionSide", "")
                side = order.get("side", "")
                # V3: a close is BUY+SHORT or SELL+LONG
                is_close = (
                    (side == "BUY" and pos_side == "SHORT")
                    or (side == "SELL" and pos_side == "LONG")
                )
                if is_close and status in ("FILLED", "filled"):
                    price = order.get("avgPrice") or order.get("price")
                    if price and float(price) > 0:
                        return float(price)
        except Exception as e:
            logger.warning(f"Failed to get close fill price for {symbol}: {e}")
        return None

    # ── Fee Tracking ────────────────────────────────────────────────

    async def get_order_fees(self, symbol: str, order_id: str) -> float:
        """Get fees for a single order via v3 userTrades (fills) endpoint.

        Weex /capi/v3/userTrades returns fills with `commission` field.
        """
        try:
            params = {"orderId": order_id, "limit": "50"}
            data = await self._request("GET", ENDPOINTS["user_trades"], params=params)
            fills = data if isinstance(data, list) else data.get("fills", []) if isinstance(data, dict) else []
            total = 0.0
            for fill in fills:
                commission = fill.get("commission", "0")
                if commission:
                    total += abs(float(commission))
            return round(total, 6)
        except Exception as e:
            logger.warning(f"Failed to get order fees for {order_id}: {e}")
            return 0.0

    async def get_trade_total_fees(
        self, symbol: str, entry_order_id: str, close_order_id: Optional[str] = None
    ) -> float:
        """Get total fees (entry + exit) for a complete trade."""
        total_fees = 0.0
        if entry_order_id:
            total_fees += await self.get_order_fees(symbol, entry_order_id)
        if close_order_id:
            total_fees += await self.get_order_fees(symbol, close_order_id)
        return round(total_fees, 6)

    async def get_fill_price(
        self, symbol: str, order_id: str, max_retries: int = 3, retry_delay: float = 0.5
    ) -> Optional[float]:
        """Get actual fill price for a completed order via userTrades."""
        for attempt in range(max_retries):
            try:
                params = {"orderId": order_id, "limit": "10"}
                data = await self._request("GET", ENDPOINTS["user_trades"], params=params)
                fills = data if isinstance(data, list) else data.get("fills", []) if isinstance(data, dict) else []
                if fills:
                    # Weighted average price across all fills
                    total_qty = 0.0
                    total_value = 0.0
                    for fill in fills:
                        qty = float(fill.get("qty", fill.get("quantity", 0)))
                        price = float(fill.get("price", 0))
                        if qty > 0 and price > 0:
                            total_qty += qty
                            total_value += qty * price
                    if total_qty > 0:
                        return round(total_value / total_qty, 8)
            except Exception as e:
                logger.warning(f"Error getting fill price (attempt {attempt + 1}): {e}")
            await asyncio.sleep(retry_delay * (2 ** attempt))
        return None

    async def get_funding_fees(
        self, symbol: str, start_time_ms: int, end_time_ms: int
    ) -> float:
        """Get total funding fees via v3 account income endpoint.

        Uses POST /capi/v3/account/income with incomeType=position_funding.
        """
        try:
            v3_symbol = symbol.upper().replace("-", "")
            data = await self._request("POST", ENDPOINTS["account_income"], data={
                "symbol": v3_symbol,
                "incomeType": "position_funding",
                "startTime": str(start_time_ms),
                "endTime": str(end_time_ms),
                "limit": "100",
            })
            items = data if isinstance(data, list) else data.get("bills", data.get("list", [])) if isinstance(data, dict) else []
            total_funding = 0.0
            for item in items:
                amount = item.get("income", item.get("amount", "0"))
                if amount:
                    total_funding += float(amount)
            return round(total_funding, 6)
        except Exception as e:
            logger.warning(f"Failed to get funding fees for {symbol}: {e}")
            return 0.0

    # ── TP/SL Management (v3 endpoints) ─────────────────────────────

    async def cancel_position_tpsl(
        self,
        symbol: str,
        side: str = "long",
    ) -> bool:
        """Cancel all pending TP/SL orders for a position on Weex.

        Queries /capi/v3/pendingTpSlOrders, filters by symbol and positionSide,
        then cancels each via /capi/v3/cancelTpSlOrder.
        Best-effort: partial failures are logged but don't fail the operation.
        """
        return await self._cancel_pending_tpsl_by_role(symbol, side, target_role=None)

    async def cancel_tp_only(self, symbol: str, side: str = "long") -> bool:
        """Cancel only pending TAKE_PROFIT orders for a position, leave SL intact.

        Epic #188 follow-up to #192: a dashboard edit that clears only TP must
        not collateral-cancel the SL leg. Weex V3 persists TP and SL as
        separate conditional orders with distinct ``planType`` values
        (``TAKE_PROFIT`` vs ``STOP_LOSS``), so role-based filtering is clean.

        Best-effort: partial failures are logged but don't fail the operation.
        Returns True if no matching orders or all cancels succeeded; False if
        the initial query fails (caller should treat as cancel failure).
        """
        return await self._cancel_pending_tpsl_by_role(symbol, side, target_role="tp")

    async def cancel_sl_only(self, symbol: str, side: str = "long") -> bool:
        """Cancel only pending STOP_LOSS orders for a position, leave TP intact.

        Mirror of :meth:`cancel_tp_only`. Filters Weex pending conditional
        orders by ``planType == "STOP_LOSS"`` so the TP leg and any other
        plan (trigger, algo) remain untouched.
        """
        return await self._cancel_pending_tpsl_by_role(symbol, side, target_role="sl")

    async def _cancel_pending_tpsl_by_role(
        self,
        symbol: str,
        side: str,
        target_role: Optional[str],
    ) -> bool:
        """Shared helper: query pending TP/SL, filter by positionSide + role.

        :param target_role: ``"tp"`` to cancel only TAKE_PROFIT plans,
            ``"sl"`` for STOP_LOSS, or ``None`` to cancel both (legacy
            ``cancel_position_tpsl`` behaviour).
        """
        v3_symbol = symbol.upper().replace("-", "")
        position_side = "LONG" if side == "long" else "SHORT"

        try:
            data = await self._request("GET", ENDPOINTS["pending_tpsl_orders"], params={
                "symbol": v3_symbol,
            })
        except Exception as e:
            logger.warning("Failed to query pending TP/SL orders for %s: %s", symbol, e)
            return False

        orders = data if isinstance(data, list) else (data.get("orders", []) if isinstance(data, dict) else [])

        to_cancel: List[Dict[str, Any]] = []
        for o in orders:
            if not isinstance(o, dict):
                continue
            if o.get("positionSide") != position_side:
                continue
            if target_role is not None and self._classify_plan_type(o) != target_role:
                continue
            to_cancel.append(o)

        if not to_cancel:
            logger.debug(
                "No %s pending TP/SL orders to cancel for %s %s",
                target_role or "tpsl", symbol, side,
            )
            return True

        for order in to_cancel:
            oid = str(order.get("orderId", ""))
            try:
                await self._request("POST", ENDPOINTS["cancel_tpsl_order"], data={
                    "symbol": v3_symbol,
                    "orderId": oid,
                })
                logger.info(
                    "Cancelled Weex %s order %s for %s",
                    target_role or "TP/SL", oid, symbol,
                )
            except Exception as e:
                logger.warning(
                    "Failed to cancel Weex %s order %s for %s: %s",
                    target_role or "TP/SL", oid, symbol, e,
                )

        return True

    @staticmethod
    def _classify_plan_type(order: Dict[str, Any]) -> Optional[str]:
        """Classify a Weex pending order as ``"tp"`` or ``"sl"`` by planType.

        Weex V3 stores the role explicitly in ``planType``:
        - ``"TAKE_PROFIT"`` -> ``"tp"``
        - ``"STOP_LOSS"``   -> ``"sl"``

        Returns ``None`` for unrecognised planTypes (e.g. trigger/algo plans)
        so callers can safely ignore them in leg-specific cancels.
        """
        plan_type = str(order.get("planType") or "").upper()
        if plan_type == "TAKE_PROFIT":
            return "tp"
        if plan_type == "STOP_LOSS":
            return "sl"
        return None

    # planType tokens Weex emits per leg. Kept as frozensets so callers
    # can combine them when scoping the pre-place sweep.
    _TP_PLAN_TYPES = frozenset({"TAKE_PROFIT"})
    _SL_PLAN_TYPES = frozenset({"STOP_LOSS"})
    _TPSL_PLAN_TYPES = _TP_PLAN_TYPES | _SL_PLAN_TYPES

    async def _cancel_existing_tpsl(
        self,
        symbol: str,
        target_types: Optional[frozenset] = None,
    ) -> None:
        """Cancel existing TP/SL plan orders for a symbol before placing new ones.

        ``target_types`` scopes the sweep to a subset of planType values
        (e.g. ``{"TAKE_PROFIT"}`` to clear only the TP leg). When ``None``
        the sweep wipes every TAKE_PROFIT + STOP_LOSS order for the symbol —
        the legacy default kept for callers that rely on a full reset.

        Internal callers in :meth:`set_position_tpsl` MUST scope to the leg
        they are about to replace so they don't collateral-cancel the user's
        other live leg (Epic #188 / #216 S2 leg-isolation invariant). Without
        scoping, setting only TP would silently delete the SL every time.
        """
        types = target_types if target_types is not None else self._TPSL_PLAN_TYPES
        v3_symbol = symbol.upper().replace("-", "")
        try:
            data = await self._request("GET", ENDPOINTS["pending_tpsl_orders"], params={
                "symbol": v3_symbol,
            })
            orders = data if isinstance(data, list) else []
            for order in orders:
                oid = str(order.get("orderId", order.get("id", "")))
                plan_type = str(order.get("planType", "")).upper()
                if plan_type not in types:
                    continue
                if oid:
                    try:
                        await self._request("POST", ENDPOINTS["cancel_tpsl_order"], data={
                            "symbol": v3_symbol,
                            "orderId": oid,
                        })
                        logger.info("Weex: cancelled old %s order %s for %s", plan_type, oid, symbol)
                    except Exception as e:
                        logger.warning("Weex: failed to cancel %s order %s: %s", plan_type, oid, e)
        except Exception as e:
            # Classify: "pending TP/SL query not available" used to swallow
            # every failure at DEBUG, hiding auth/network errors (Pattern C
            # per #225). Benign "no such order" messages stay at DEBUG;
            # everything else escalates to WARN so a real cancel failure
            # does not mask a stale exchange-side TP/SL.
            msg = str(e).lower()
            benign = ("no plan", "no order", "not found", "does not exist")
            if any(tok in msg for tok in benign):
                logger.debug(
                    "Weex: no pending TP/SL to cancel for %s: %s", symbol, e,
                )
            else:
                logger.warning(
                    "Weex: pending TP/SL query FAILED for %s: %s", symbol, e,
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
        """Set TP/SL for an existing position via Weex v3 endpoint.

        Weex uses /capi/v3/placeTpSlOrder with planType TAKE_PROFIT or STOP_LOSS.
        Each TP and SL must be placed as separate orders.
        """
        v3_symbol = symbol.upper().replace("-", "")
        position_side = "LONG" if side == "long" else "SHORT"
        order_ids = []

        # Sweep only the leg(s) being placed so the user's other live leg
        # stays intact. A naked TP set must not collateral-cancel the SL
        # (and vice versa) — the RiskStateManager already cleared the
        # targeted leg upstream, this is just defence-in-depth against
        # mid-call drift. Epic #188 / #216 S2 leg-isolation invariant.
        sweep_types: set[str] = set()
        if take_profit is not None:
            sweep_types |= self._TP_PLAN_TYPES
        if stop_loss is not None:
            sweep_types |= self._SL_PLAN_TYPES
        if sweep_types:
            await self._cancel_existing_tpsl(symbol, target_types=frozenset(sweep_types))

        # Get position size if not provided
        if size is None:
            pos = await self.get_position(symbol)
            if not pos:
                return None
            size = pos.size

        if take_profit is not None:
            try:
                result = await self._request("POST", ENDPOINTS["place_tpsl_order"], data={
                    "symbol": v3_symbol,
                    "clientAlgoId": uuid.uuid4().hex[:32],
                    "planType": "TAKE_PROFIT",
                    "triggerPrice": str(take_profit),
                    "executePrice": "0",
                    "quantity": str(round(size, 4)),
                    "positionSide": position_side,
                    "triggerPriceType": "MARK_PRICE",
                })
                orders = result if isinstance(result, list) else [result]
                for o in orders:
                    if isinstance(o, dict) and o.get("success"):
                        order_ids.append(str(o.get("orderId", "")))
                logger.info("Weex TP set for %s: $%.2f", symbol, take_profit)
            except Exception as e:
                logger.warning("Failed to set TP for %s: %s", symbol, e)

        if stop_loss is not None:
            try:
                result = await self._request("POST", ENDPOINTS["place_tpsl_order"], data={
                    "symbol": v3_symbol,
                    "clientAlgoId": uuid.uuid4().hex[:32],
                    "planType": "STOP_LOSS",
                    "triggerPrice": str(stop_loss),
                    "executePrice": "0",
                    "quantity": str(round(size, 4)),
                    "positionSide": position_side,
                    "triggerPriceType": "MARK_PRICE",
                })
                orders = result if isinstance(result, list) else [result]
                for o in orders:
                    if isinstance(o, dict) and o.get("success"):
                        order_ids.append(str(o.get("orderId", "")))
                logger.info("Weex SL set for %s: $%.2f", symbol, stop_loss)
            except Exception as e:
                logger.warning("Failed to set SL for %s: %s", symbol, e)

        return ",".join(order_ids) if order_ids else None

    # ── Affiliate ──────────────────────────────────────────────────

    async def check_affiliate_uid(self, uid: str) -> bool:
        """Check if a UID is in our affiliate referral list via Weex v3 Rebate API.

        Uses GET /api/v3/rebate/affiliate/getAffiliateUIDs with uid filter
        to check if the given UID was referred by the admin account.
        """
        try:
            result = await self._request(
                "GET",
                "/api/v3/rebate/affiliate/getAffiliateUIDs",
                params={"uid": str(uid), "pageSize": "10"},
            )
            items = (
                result.get("channelUserInfoItemList", [])
                if isinstance(result, dict)
                else result if isinstance(result, list)
                else []
            )
            for item in items:
                if str(item.get("uid", "")) == str(uid):
                    return True
            return False
        except Exception as e:
            logger.warning(f"Affiliate UID check failed for {uid}: {e}")
            return False
