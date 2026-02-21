"""
Weex Exchange Client implementing ExchangeClient ABC.

Weex API is similar to Bitget with HMAC-SHA256 auth.
Uses ccxt-compatible symbol format (e.g. BTC/USDT:USDT).
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional

import aiohttp

from src.exceptions import ExchangeError
from src.exchanges.base import ExchangeClient
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker
from src.exchanges.weex.constants import BASE_URL, SUCCESS_CODE, TESTNET_URL
from src.utils.logger import get_logger

logger = get_logger(__name__)


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
        self.base_url = TESTNET_URL if demo_mode else BASE_URL
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info(f"WeexClient initialized ({'DEMO' if demo_mode else 'LIVE'} mode)")

    @property
    def exchange_name(self) -> str:
        return "weex"

    @property
    def supports_demo(self) -> bool:
        return True

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
        }

    async def _request(
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

        async with self._session.request(
            method=method, url=url, headers=headers,
            data=body if body else None,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            result = await response.json()
            if response.status != 200 or result.get("code") != SUCCESS_CODE:
                raise WeexClientError(f"Weex API Error: {result.get('msg', 'Unknown')}")
            return result.get("data", result)

    async def get_account_balance(self) -> Balance:
        data = await self._request("GET", "/api/v2/mix/account/account", params={
            "symbol": "BTCUSDT", "productType": "USDT-FUTURES", "marginCoin": "USDT",
        })
        if isinstance(data, list):
            data = data[0] if data else {}
        return Balance(
            total=float(data.get("accountEquity", 0)),
            available=float(data.get("available", 0)),
            unrealized_pnl=float(data.get("unrealizedPL", 0)),
        )

    async def place_market_order(
        self, symbol: str, side: str, size: float, leverage: int,
        take_profit: Optional[float] = None, stop_loss: Optional[float] = None,
    ) -> Order:
        await self.set_leverage(symbol, leverage)
        order_side = "buy" if side == "long" else "sell"
        data = {
            "symbol": symbol, "productType": "USDT-FUTURES",
            "marginMode": "crossed", "marginCoin": "USDT",
            "side": order_side, "tradeSide": "open",
            "orderType": "market", "size": str(size),
        }
        if take_profit is not None:
            data["presetStopSurplusPrice"] = str(take_profit)
        if stop_loss is not None:
            data["presetStopLossPrice"] = str(stop_loss)

        result = await self._request("POST", "/api/v2/mix/order/place-order", data=data)
        return Order(
            order_id=str(result.get("orderId", "")),
            symbol=symbol, side=side, size=size, price=0.0,
            status="filled", exchange="weex", leverage=leverage,
            take_profit=take_profit, stop_loss=stop_loss,
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            await self._request("POST", "/api/v2/mix/order/cancel-order", data={
                "symbol": symbol, "productType": "USDT-FUTURES", "orderId": order_id,
            })
            return True
        except WeexClientError:
            return False

    async def close_position(self, symbol: str, side: str) -> Optional[Order]:
        pos = await self.get_position(symbol)
        if not pos:
            return None
        order_side = "sell" if side == "long" else "buy"
        data = {
            "symbol": symbol, "productType": "USDT-FUTURES",
            "marginMode": "crossed", "marginCoin": "USDT",
            "side": order_side, "tradeSide": "close",
            "orderType": "market", "size": str(pos.size),
        }
        result = await self._request("POST", "/api/v2/mix/order/place-order", data=data)
        return Order(
            order_id=str(result.get("orderId", "")),
            symbol=symbol, side=side, size=pos.size,
            price=0.0, status="filled", exchange="weex",
        )

    async def get_position(self, symbol: str) -> Optional[Position]:
        data = await self._request("GET", "/api/v2/mix/position/single-position", params={
            "symbol": symbol, "productType": "USDT-FUTURES", "marginCoin": "USDT",
        })
        positions = data if isinstance(data, list) else [data] if data else []
        for pos in positions:
            total = float(pos.get("total", 0))
            if total > 0:
                return Position(
                    symbol=symbol, side=pos.get("holdSide", "long"), size=total,
                    entry_price=float(pos.get("openPriceAvg", 0)),
                    current_price=float(pos.get("markPrice", 0)),
                    unrealized_pnl=float(pos.get("unrealizedPL", 0)),
                    leverage=int(pos.get("leverage", 1)), exchange="weex",
                )
        return None

    async def get_open_positions(self) -> List[Position]:
        data = await self._request("GET", "/api/v2/mix/position/all-position", params={
            "productType": "USDT-FUTURES", "marginCoin": "USDT",
        })
        positions = []
        for pos in (data if isinstance(data, list) else []):
            total = float(pos.get("total", 0))
            if total > 0:
                positions.append(Position(
                    symbol=pos.get("symbol", ""), side=pos.get("holdSide", "long"),
                    size=total, entry_price=float(pos.get("openPriceAvg", 0)),
                    current_price=float(pos.get("markPrice", 0)),
                    unrealized_pnl=float(pos.get("unrealizedPL", 0)),
                    leverage=int(pos.get("leverage", 1)), exchange="weex",
                ))
        return positions

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        for hold_side in ("long", "short"):
            try:
                await self._request("POST", "/api/v2/mix/account/set-leverage", data={
                    "symbol": symbol, "productType": "USDT-FUTURES",
                    "marginCoin": "USDT", "leverage": str(leverage), "holdSide": hold_side,
                })
            except WeexClientError:
                pass
        return True

    async def get_ticker(self, symbol: str) -> Ticker:
        data = await self._request("GET", "/api/v2/mix/market/ticker", params={
            "symbol": symbol, "productType": "USDT-FUTURES",
        }, auth=False)
        if isinstance(data, list):
            data = data[0] if data else {}
        return Ticker(
            symbol=symbol,
            last_price=float(data.get("lastPr", 0)),
            bid=float(data.get("bidPr", 0)),
            ask=float(data.get("askPr", 0)),
            volume_24h=float(data.get("baseVolume", 0)),
        )

    async def check_affiliate_uid(self, uid: str) -> bool:
        """Check if a UID is in our affiliate referral list via Weex Rebate API."""
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
            from src.utils.logger import get_logger
            get_logger(__name__).warning(f"Affiliate UID check failed for {uid}: {e}")
            return False

    async def get_funding_rate(self, symbol: str) -> FundingRateInfo:
        data = await self._request("GET", "/api/v2/mix/market/current-fund-rate", params={
            "symbol": symbol, "productType": "USDT-FUTURES",
        }, auth=False)
        if isinstance(data, list):
            data = data[0] if data else {}
        return FundingRateInfo(
            symbol=symbol,
            current_rate=float(data.get("fundingRate", 0)),
        )
