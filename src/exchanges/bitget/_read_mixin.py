"""Read-side operations for the Bitget client.

Account balance, positions, ticker, funding rate plus the raw
exchange-shaped passthrough getters used by Bitget-specific callers.
Methods here expect the host class to expose ``_request`` (from
:class:`HTTPExchangeClientMixin`).

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.exchanges.bitget.constants import ENDPOINTS, PRODUCT_TYPE_USDT
from src.exchanges.types import Balance, FundingRateInfo, Position, Ticker
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BitgetReadMixin:
    """Read-only Bitget queries used by :class:`BitgetExchangeClient`."""

    async def get_account_balance(self) -> Balance:
        endpoint = ENDPOINTS["account_balance"]
        params = {
            "symbol": "BTCUSDT",
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": "USDT",
        }
        data = await self._request("GET", endpoint, params=params)

        if isinstance(data, list):
            data = data[0] if data else {}

        logger.debug(
            "Bitget balance: equity=%s available=%s crossedMax=%s unrealizedPL=%s",
            data.get("accountEquity"), data.get("available"),
            data.get("crossedMaxAvailable"), data.get("unrealizedPL"),
        )

        return Balance(
            total=float(data.get("accountEquity", 0) or data.get("usdtEquity", 0)),
            available=float(data.get("crossedMaxAvailable", 0) or data.get("available", 0)),
            unrealized_pnl=float(data.get("unrealizedPL", 0)),
            currency="USDT",
        )

    async def get_position(self, symbol: str) -> Optional[Position]:
        params = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": "USDT",
        }
        data = await self._request("GET", ENDPOINTS["single_position"], params=params)

        positions = data if isinstance(data, list) else [data] if data else []
        for pos in positions:
            total = float(pos.get("total", 0))
            if total > 0:
                return Position(
                    symbol=symbol,
                    side=pos.get("holdSide", "long"),
                    size=total,
                    entry_price=float(pos.get("openPriceAvg", 0)),
                    current_price=float(pos.get("markPrice", 0)),
                    unrealized_pnl=float(pos.get("unrealizedPL", 0)),
                    leverage=int(pos.get("leverage", 1)),
                    exchange="bitget",
                    margin=float(pos.get("margin", 0)),
                    liquidation_price=float(pos.get("liquidationPrice", 0) or 0),
                )
        return None

    async def get_open_positions(self) -> List[Position]:
        params = {
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": "USDT",
        }
        data = await self._request("GET", ENDPOINTS["all_positions"], params=params)
        positions = []
        items = data if isinstance(data, list) else []
        for pos in items:
            total = float(pos.get("total", 0))
            if total > 0:
                positions.append(
                    Position(
                        symbol=pos.get("symbol", ""),
                        side=pos.get("holdSide", "long"),
                        size=total,
                        entry_price=float(pos.get("openPriceAvg", 0)),
                        current_price=float(pos.get("markPrice", 0)),
                        unrealized_pnl=float(pos.get("unrealizedPL", 0)),
                        leverage=int(pos.get("leverage", 1)),
                        exchange="bitget",
                        margin=float(pos.get("margin", 0)),
                        liquidation_price=float(pos.get("liquidationPrice", 0) or 0),
                    )
                )
        return positions

    async def get_ticker(self, symbol: str) -> Ticker:
        params = {"symbol": symbol, "productType": PRODUCT_TYPE_USDT}
        data = await self._request("GET", ENDPOINTS["ticker"], params=params, auth=False)

        if isinstance(data, list):
            data = data[0] if data else {}

        return Ticker(
            symbol=symbol,
            last_price=float(data.get("lastPr", 0) or data.get("last", 0)),
            bid=float(data.get("bidPr", 0) or data.get("bestBid", 0)),
            ask=float(data.get("askPr", 0) or data.get("bestAsk", 0)),
            volume_24h=float(data.get("baseVolume", 0) or data.get("volume24h", 0)),
            high_24h=float(data.get("high24h", 0)) if data.get("high24h") else None,
            low_24h=float(data.get("low24h", 0)) if data.get("low24h") else None,
            change_24h_percent=float(data.get("change24h", 0)) if data.get("change24h") else None,
        )

    async def get_funding_rate(self, symbol: str) -> FundingRateInfo:
        params = {"symbol": symbol, "productType": PRODUCT_TYPE_USDT}
        data = await self._request(
            "GET", ENDPOINTS["funding_rate"], params=params, auth=False
        )

        if isinstance(data, list):
            data = data[0] if data else {}

        return FundingRateInfo(
            symbol=symbol,
            current_rate=float(data.get("fundingRate", 0)),
        )

    async def get_raw_account_balance(self, margin_coin: str = "USDT") -> Dict[str, Any]:
        """Get raw account balance data (Bitget-specific format)."""
        params = {
            "symbol": "BTCUSDT",
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": margin_coin,
        }
        return await self._request("GET", ENDPOINTS["account_balance"], params=params)

    async def get_raw_position(self, symbol: str) -> Dict[str, Any]:
        """Get raw position data (Bitget-specific format)."""
        params = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": "USDT",
        }
        return await self._request("GET", ENDPOINTS["single_position"], params=params)
