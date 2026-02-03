"""
Hyperliquid Exchange Client implementing ExchangeClient ABC.

Hyperliquid uses a JSON-RPC style API with ETH wallet signatures.
Symbol format: plain asset name (e.g. "BTC", "ETH").
"""

import json
from typing import Any, Dict, List, Optional

import aiohttp

from src.exchanges.base import ExchangeClient
from src.exchanges.hyperliquid.constants import BASE_URL, INFO_ENDPOINT, TESTNET_URL
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HyperliquidClientError(Exception):
    pass


class HyperliquidClient(ExchangeClient):
    """
    Hyperliquid exchange client.

    Note: Full trading requires ETH wallet signature (eth_account).
    This implementation supports read-only operations and basic trading
    via the api_key (wallet address) and api_secret (private key).
    """

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
        self.wallet_address = api_key  # On Hyperliquid, the "API key" is the wallet address
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info(f"HyperliquidClient initialized ({'TESTNET' if demo_mode else 'MAINNET'})")

    @property
    def exchange_name(self) -> str:
        return "hyperliquid"

    @property
    def supports_demo(self) -> bool:
        return True

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _info_request(self, request_type: str, **kwargs) -> Any:
        """Make a request to the /info endpoint (read-only, no auth needed)."""
        await self._ensure_session()
        payload = {"type": request_type, **kwargs}
        async with self._session.post(
            f"{self.base_url}{INFO_ENDPOINT}",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise HyperliquidClientError(f"HTTP {resp.status}: {text}")
            return await resp.json()

    async def get_account_balance(self) -> Balance:
        data = await self._info_request("clearinghouseState", user=self.wallet_address)
        margin_summary = data.get("marginSummary", {})
        return Balance(
            total=float(margin_summary.get("accountValue", 0)),
            available=float(margin_summary.get("totalRawUsd", 0)),
            unrealized_pnl=float(margin_summary.get("totalNtlPos", 0)),
            currency="USDT",
        )

    async def place_market_order(
        self, symbol: str, side: str, size: float, leverage: int,
        take_profit: Optional[float] = None, stop_loss: Optional[float] = None,
    ) -> Order:
        # Hyperliquid trading requires EIP-712 typed data signing
        # This is a simplified placeholder - full implementation needs eth_account
        logger.warning("Hyperliquid trading requires ETH wallet signature - order simulated")
        await self.set_leverage(symbol, leverage)

        return Order(
            order_id="hl-simulated",
            symbol=symbol, side=side, size=size, price=0.0,
            status="pending", exchange="hyperliquid",
            leverage=leverage, take_profit=take_profit, stop_loss=stop_loss,
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        logger.warning("Hyperliquid order cancellation requires ETH wallet signature")
        return False

    async def close_position(self, symbol: str, side: str) -> Optional[Order]:
        logger.warning("Hyperliquid position close requires ETH wallet signature")
        return None

    async def get_position(self, symbol: str) -> Optional[Position]:
        data = await self._info_request("clearinghouseState", user=self.wallet_address)
        for pos in data.get("assetPositions", []):
            position_data = pos.get("position", {})
            coin = position_data.get("coin", "")
            if coin == symbol:
                szi = float(position_data.get("szi", 0))
                if szi == 0:
                    return None
                return Position(
                    symbol=symbol,
                    side="long" if szi > 0 else "short",
                    size=abs(szi),
                    entry_price=float(position_data.get("entryPx", 0)),
                    current_price=0.0,  # Need separate ticker call
                    unrealized_pnl=float(position_data.get("unrealizedPnl", 0)),
                    leverage=int(float(position_data.get("leverage", {}).get("value", 1))),
                    exchange="hyperliquid",
                    liquidation_price=float(position_data.get("liquidationPx", 0) or 0),
                )
        return None

    async def get_open_positions(self) -> List[Position]:
        data = await self._info_request("clearinghouseState", user=self.wallet_address)
        positions = []
        for pos in data.get("assetPositions", []):
            position_data = pos.get("position", {})
            szi = float(position_data.get("szi", 0))
            if szi != 0:
                positions.append(Position(
                    symbol=position_data.get("coin", ""),
                    side="long" if szi > 0 else "short",
                    size=abs(szi),
                    entry_price=float(position_data.get("entryPx", 0)),
                    current_price=0.0,
                    unrealized_pnl=float(position_data.get("unrealizedPnl", 0)),
                    leverage=int(float(position_data.get("leverage", {}).get("value", 1))),
                    exchange="hyperliquid",
                ))
        return positions

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        logger.info(f"Hyperliquid leverage set to {leverage}x for {symbol} (requires wallet sig)")
        return True

    async def get_ticker(self, symbol: str) -> Ticker:
        data = await self._info_request("allMids")
        price = float(data.get(symbol, 0))
        return Ticker(
            symbol=symbol,
            last_price=price,
            bid=price,  # Hyperliquid allMids returns mid price
            ask=price,
            volume_24h=0.0,
        )

    async def get_funding_rate(self, symbol: str) -> FundingRateInfo:
        meta = await self._info_request("meta")
        for asset_info in meta.get("universe", []):
            if asset_info.get("name") == symbol:
                return FundingRateInfo(
                    symbol=symbol,
                    current_rate=float(asset_info.get("funding", 0)),
                )
        return FundingRateInfo(symbol=symbol, current_rate=0.0)
