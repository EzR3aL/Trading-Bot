"""
Weex Exchange Client implementing ExchangeClient ABC.

Weex API uses /capi/v2/ endpoints on api-contract.weex.com.
Demo mode uses the same URL but different symbol names:
  Live:  cmt_btcusdt   (BTC-USDT)
  Demo:  cmt_btcsusdt  (BTC-SUSDT)
Auth: HMAC-SHA256 + Base64 (same algorithm as Bitget).
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Dict, List, Optional

import asyncio

import aiohttp

from src.exceptions import ExchangeError
from src.exchanges.base import ExchangeClient
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker
from src.exchanges.weex.constants import (
    BASE_URL,
    ENDPOINTS,
    MARGIN_CROSS,
    MARGIN_ISOLATED,
    ORDER_TYPE_CLOSE_LONG,
    ORDER_TYPE_CLOSE_SHORT,
    ORDER_TYPE_OPEN_LONG,
    ORDER_TYPE_OPEN_SHORT,
    SUCCESS_CODE,
)
from src.utils.circuit_breaker import CircuitBreakerError, circuit_registry, with_retry
from src.utils.logger import get_logger

logger = get_logger(__name__)

_weex_breaker = circuit_registry.get("weex_api", fail_threshold=5, reset_timeout=60)


class WeexClientError(ExchangeError):
    """Custom exception for Weex API errors."""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__("weex", message, original_error)


class WeexClient(ExchangeClient):
    """Weex Futures exchange client."""

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

    # ── HTTP plumbing ──────────────────────────────────────────────

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

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
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        auth: bool = True,
        use_circuit_breaker: bool = True,
    ) -> Dict[str, Any]:
        if use_circuit_breaker:
            async def _do():
                return await self._raw_request(method, endpoint, params, data, auth)
            try:
                return await _weex_breaker.call(_do)
            except CircuitBreakerError as e:
                raise WeexClientError(f"API temporarily unavailable: {e}")
        return await self._raw_request(method, endpoint, params, data, auth)

    @with_retry(max_attempts=3, min_wait=1.0, max_wait=10.0,
                retry_on=(aiohttp.ClientError, asyncio.TimeoutError))
    async def _raw_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        auth: bool = True,
    ) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"{self.base_url}{endpoint}"
        body = json.dumps(data) if data else ""

        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            request_path = f"{endpoint}?{query}"
            url = f"{url}?{query}"
        else:
            request_path = endpoint

        headers = self._get_headers(method, request_path, body) if auth else {"Content-Type": "application/json"}

        try:
            async with self._session.request(
                method=method, url=url, headers=headers,
                data=body if body else None,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                result = await response.json()

                if response.status == 429:
                    raise aiohttp.ClientResponseError(
                        response.request_info, response.history,
                        status=429, message="Rate limited",
                    )

                # Some endpoints return raw list/data without {code, data} wrapper
                if not isinstance(result, dict):
                    if response.status == 200:
                        return result
                    raise WeexClientError(
                        f"Weex API Error: unexpected response (status={response.status})"
                    )

                code = result.get("code")
                logger.debug(f"Weex {method} {endpoint}: status={response.status} code={code}")

                # Some endpoints return dict without code wrapper
                if code is None and response.status == 200:
                    return result

                if response.status != 200 or str(code) != SUCCESS_CODE:
                    msg = result.get("msg", result.get("message", "Unknown"))
                    raise WeexClientError(
                        f"Weex API Error: {msg} (code={code}, status={response.status})"
                    )
                return result.get("data", result)

        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise

    # ── Account ────────────────────────────────────────────────────

    async def get_account_balance(self) -> Balance:
        data = await self._request("GET", ENDPOINTS["account_assets"])
        if isinstance(data, list):
            for item in data:
                coin = item.get("coinName", "").upper()
                if coin in ("USDT", "SUSDT"):
                    return Balance(
                        total=float(item.get("equity", 0)),
                        available=float(item.get("available", 0)),
                        unrealized_pnl=float(item.get("unrealizePnl", 0)),
                    )
            item = data[0] if data else {}
        else:
            item = data
        return Balance(
            total=float(item.get("equity", item.get("accountEquity", 0))),
            available=float(item.get("available", 0)),
            unrealized_pnl=float(item.get("unrealizePnl", item.get("unrealizedPL", 0))),
        )

    # ── Orders ─────────────────────────────────────────────────────

    async def place_market_order(
        self, symbol: str, side: str, size: float, leverage: int,
        take_profit: Optional[float] = None, stop_loss: Optional[float] = None,
        margin_mode: str = "cross",
    ) -> Order:
        await self.set_leverage(symbol, leverage, margin_mode=margin_mode)
        api_symbol = self._to_api_symbol(symbol)
        margin = MARGIN_CROSS if margin_mode == "cross" else MARGIN_ISOLATED
        order_type = ORDER_TYPE_OPEN_LONG if side == "long" else ORDER_TYPE_OPEN_SHORT

        data = {
            "symbol": api_symbol,
            "client_oid": uuid.uuid4().hex[:32],
            "size": str(size),
            "type": order_type,
            "order_type": "0",
            "match_price": "1",
            "marginMode": margin,
        }
        if take_profit is not None:
            data["presetTakeProfitPrice"] = str(take_profit)
        if stop_loss is not None:
            data["presetStopLossPrice"] = str(stop_loss)

        result = await self._request("POST", ENDPOINTS["place_order"], data=data)
        return Order(
            order_id=str(result.get("orderId", result.get("order_id", ""))),
            symbol=symbol, side=side, size=size, price=0.0,
            status="filled", exchange="weex", leverage=leverage,
            take_profit=take_profit, stop_loss=stop_loss,
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            await self._request("POST", ENDPOINTS["cancel_order"], data={
                "orderId": order_id,
            })
            return True
        except WeexClientError:
            return False

    async def close_position(self, symbol: str, side: str, margin_mode: str = "cross") -> Optional[Order]:
        """Close position using flash-close endpoint."""
        pos = await self.get_position(symbol)
        if not pos:
            return None
        api_symbol = self._to_api_symbol(symbol)
        result = await self._request("POST", ENDPOINTS["close_positions"], data={
            "symbol": api_symbol,
        })
        order_id = ""
        if isinstance(result, dict):
            order_id = str(result.get("orderId", result.get("order_id", "")))
        elif isinstance(result, list) and result:
            order_id = str(result[0].get("orderId", result[0].get("order_id", "")))
        return Order(
            order_id=order_id, symbol=symbol, side=side,
            size=pos.size, price=0.0, status="filled", exchange="weex",
        )

    # ── Positions ──────────────────────────────────────────────────

    def _parse_position(self, pos: Dict, fallback_symbol: str = "") -> Optional[Position]:
        """Parse a single position dict from Weex API response."""
        total = float(pos.get("hold_amount", pos.get("holdAmount", pos.get("total", 0))))
        if total <= 0:
            return None
        raw_side = str(pos.get("side", pos.get("holdSide", "long")))
        hold_side = "long" if raw_side in ("1", "long") else "short"
        api_sym = pos.get("symbol", "")
        db_symbol = self._from_api_symbol(api_sym) if api_sym else fallback_symbol
        return Position(
            symbol=db_symbol, side=hold_side, size=total,
            entry_price=float(pos.get("cost_open", pos.get("averageOpenPrice", pos.get("openPriceAvg", 0)))),
            current_price=float(pos.get("markPrice", pos.get("mark_price", 0))),
            unrealized_pnl=float(pos.get("profit_unreal", pos.get("unrealizedPnl", pos.get("unrealizedPL", 0)))),
            leverage=int(float(pos.get("leverage", 1))),
            exchange="weex",
        )

    async def get_position(self, symbol: str) -> Optional[Position]:
        api_symbol = self._to_api_symbol(symbol)
        data = await self._request("GET", ENDPOINTS["single_position"], params={
            "symbol": api_symbol,
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
        except WeexClientError:
            pass
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
        data = await self._request("GET", ENDPOINTS["funding_rate"], auth=False)
        # Response is a list of all rates; match by baseCurrency (e.g. "BTC_USDT")
        base = symbol.replace("USDT", "")
        target_currency = f"{base}_USDT"
        rate = 0.0
        if isinstance(data, list):
            for item in data:
                if item.get("baseCurrency", "") == target_currency:
                    rate = float(item.get("fundingRate", 0))
                    break
        elif isinstance(data, dict):
            rate = float(data.get("fundingRate", 0))
        return FundingRateInfo(symbol=symbol, current_rate=rate)

    # ── Affiliate ──────────────────────────────────────────────────

    async def check_affiliate_uid(self, uid: str) -> bool:
        """Check if a UID is in our affiliate referral list."""
        try:
            result = await self._request(
                "GET",
                "/api/v2/rebate/affiliate/getChannelUserTradeAndAsset",
                params={"uid": str(uid), "pageSize": "10"},
            )
            records = result if isinstance(result, list) else result.get("records", [])
            for item in records:
                if str(item.get("uid", "")) == str(uid):
                    return True
            return False
        except Exception as e:
            logger.warning(f"Affiliate UID check failed for {uid}: {e}")
            return False
