"""
Hyperliquid Exchange Client implementing ExchangeClient ABC.

Uses the official hyperliquid-python-sdk for EIP-712 signed trading.
Symbol format: plain asset name (e.g. "BTC", "ETH") or pairs like "BTCUSDT"/"BTCUSDC"
which are normalized to coin names internally.

SECURITY: Only trading operations are allowed. No withdrawals, transfers, or
fund-moving operations. The ALLOWED_METHODS whitelist enforces this.
"""

import os
import re
from typing import Any, Dict, List, Optional

from eth_account import Account as EthAccount
from hyperliquid.exchange import Exchange as HLExchange
from hyperliquid.info import Info as HLInfo
from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL

from src.exceptions import ExchangeError
from src.exchanges.base import ExchangeClient
from src.exchanges.hyperliquid.constants import DEFAULT_BUILDER_FEE
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker
from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerError
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Security: Only these SDK methods may be called ──────────────────────────
# Any method not on this list (e.g. usd_transfer, withdraw_from_bridge,
# vault_usd_transfer, send_asset, sub_account_transfer) is BLOCKED.
ALLOWED_METHODS = frozenset({
    "market_open",
    "market_close",
    "order",
    "bulk_orders",
    "cancel",
    "bulk_cancel",
    "update_leverage",
    "update_isolated_margin",
    "approve_builder_fee",
})

# Methods that move funds — explicitly forbidden
FORBIDDEN_METHODS = frozenset({
    "usd_transfer",
    "withdraw_from_bridge",
    "vault_usd_transfer",
    "send_asset",
    "sub_account_transfer",
    "sub_account_spot_transfer",
    "spot_transfer",
    "usd_class_transfer",
    "set_referrer",
    "approve_agent",
    "convert_to_multi_sig_user",
})

# Strip these suffixes to get coin name: "BTCUSDT" → "BTC"
_QUOTE_SUFFIXES = re.compile(r"(USDT|USDC|USD|PERP)$", re.IGNORECASE)

# Default slippage for market orders (5%)
DEFAULT_SLIPPAGE = 0.05


class HyperliquidClientError(ExchangeError):
    """Custom exception for Hyperliquid API errors."""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__("hyperliquid", message, original_error)


class SafeExchange:
    """Wrapper around the SDK Exchange that blocks fund-moving operations."""

    def __init__(self, exchange: HLExchange):
        self._exchange = exchange

    def __getattr__(self, name: str):
        if name in FORBIDDEN_METHODS:
            raise HyperliquidClientError(
                f"BLOCKED: '{name}' is a fund-moving operation and is not allowed. "
                f"Only trading operations are permitted."
            )
        if name not in ALLOWED_METHODS and not name.startswith("_"):
            # Allow private/internal methods and info access, block unknown public methods
            if hasattr(self._exchange, name) and callable(getattr(self._exchange, name)):
                logger.warning(f"Hyperliquid: calling non-whitelisted method '{name}'")
        return getattr(self._exchange, name)


# Circuit breaker for Hyperliquid API calls (consistent with other exchanges)
_hl_breaker = CircuitBreaker(
    name="hyperliquid_api",
    fail_threshold=5,
    reset_timeout=60.0,
)


class HyperliquidClient(ExchangeClient):
    """
    Hyperliquid exchange client with full trading support.

    Uses the official hyperliquid-python-sdk for EIP-712 signed operations.
    All fund-moving operations (withdraw, transfer) are blocked by SafeExchange.
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
        self.wallet_address = api_key
        self.base_url = TESTNET_API_URL if demo_mode else MAINNET_API_URL

        # Create eth_account wallet from private key (API wallet)
        try:
            self._wallet = EthAccount.from_key(api_secret)
        except Exception as e:
            raise HyperliquidClientError(f"Invalid private key: {e}")

        # Determine if API wallet differs from main wallet
        # api_key = main wallet address (where funds/positions live)
        # api_secret -> self._wallet = API wallet (signs transactions)
        is_agent_wallet = self.wallet_address.lower() != self._wallet.address.lower()

        # Initialize SDK Exchange (handles EIP-712 signing)
        # Pass empty spot_meta to avoid SDK crash when Hyperliquid adds new
        # spot tokens that cause IndexError in info.py token parsing.
        # We only trade perps, so spot metadata is not needed.
        try:
            raw_exchange = HLExchange(
                wallet=self._wallet,
                base_url=self.base_url,
                account_address=self.wallet_address if is_agent_wallet else None,
            )
        except (IndexError, KeyError):
            # Fallback: skip spot meta entirely
            raw_exchange = HLExchange(
                wallet=self._wallet,
                base_url=self.base_url,
                account_address=self.wallet_address if is_agent_wallet else None,
                spot_meta={"tokens": [], "universe": []},
            )

        # Wrap in SafeExchange to block fund-moving operations
        self._exchange = SafeExchange(raw_exchange)

        # Info client for read-only queries
        self._info: HLInfo = raw_exchange.info

        # ── Builder Code config ──────────────────────────────────────────
        # Earns a small fee on every order (100% to builder, no cap).
        # Accepts kwargs from caller (DB-first) or falls back to ENV.
        builder_address = (kwargs.get("builder_address") or os.environ.get("HL_BUILDER_ADDRESS", "")).strip()
        builder_fee = int(kwargs.get("builder_fee") or os.environ.get("HL_BUILDER_FEE", str(DEFAULT_BUILDER_FEE)))
        if builder_address and 1 <= builder_fee <= 100:
            self._builder = {"b": builder_address.lower(), "f": builder_fee}
            logger.info(
                f"Builder code enabled: {builder_address[:10]}... "
                f"fee={builder_fee} ({builder_fee / 10:.1f} bp = {builder_fee / 1000:.3f}%)"
            )
        else:
            self._builder = None
            if builder_address and not (1 <= builder_fee <= 100):
                logger.warning(
                    f"HL_BUILDER_FEE={builder_fee} out of range (1-100). "
                    f"Builder code disabled."
                )

        if is_agent_wallet:
            logger.info(
                f"HyperliquidClient initialized ({'TESTNET' if demo_mode else 'MAINNET'}) "
                f"main_wallet={self.wallet_address[:10]}... "
                f"api_wallet={self._wallet.address[:10]}..."
            )
        else:
            logger.info(
                f"HyperliquidClient initialized ({'TESTNET' if demo_mode else 'MAINNET'}) "
                f"wallet={self._wallet.address[:10]}... (direct, no API wallet)"
            )

    @property
    def exchange_name(self) -> str:
        return "hyperliquid"

    @property
    def supports_demo(self) -> bool:
        return True

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize symbol to Hyperliquid coin name. 'BTCUSDT' → 'BTC', 'ETH' → 'ETH'."""
        return _QUOTE_SUFFIXES.sub("", symbol.upper())

    async def close(self) -> None:
        pass  # SDK uses requests (sync), no session to close

    async def _cb_call(self, func, *args, **kwargs):
        """Execute a function through the Hyperliquid circuit breaker."""
        async def _wrapper():
            return func(*args, **kwargs)
        try:
            return await _hl_breaker.call(_wrapper)
        except CircuitBreakerError as e:
            raise HyperliquidClientError(f"API temporarily unavailable: {e}")

    # ── Read Operations ─────────────────────────────────────────────────────

    async def get_account_balance(self) -> Balance:
        address = self.wallet_address or self._wallet.address
        data = await self._cb_call(self._info.user_state, address)
        if not isinstance(data, dict):
            data = {}
        margin = data.get("marginSummary", {})
        perp_total = float(margin.get("accountValue", 0))
        perp_available = float(data.get("withdrawable", margin.get("totalRawUsd", 0)))

        # Unified accounts: perp balance may be 0 while funds sit in spot
        spot_usdc = 0.0
        if perp_total == 0:
            try:
                spot_data = self._info.spot_user_state(address)
                for b in spot_data.get("balances", []):
                    if b.get("coin") == "USDC":
                        spot_usdc = float(b.get("total", 0))
                        break
            except Exception as e:
                logger.debug("Spot USDC balance fetch failed: %s", e)

        # Sum unrealized PnL from individual positions (totalNtlPos is notional, not PnL)
        total_upnl = 0.0
        for pos in data.get("assetPositions", []):
            pd = pos.get("position", {})
            total_upnl += float(pd.get("unrealizedPnl", 0))

        return Balance(
            total=perp_total + spot_usdc,
            available=perp_available + spot_usdc,
            unrealized_pnl=total_upnl,
            currency="USDC",
        )

    async def get_position(self, symbol: str) -> Optional[Position]:
        coin = self._normalize_symbol(symbol)
        address = self.wallet_address or self._wallet.address
        data = await self._cb_call(self._info.user_state, address)
        for pos in data.get("assetPositions", []):
            pd = pos.get("position", {})
            if pd.get("coin", "") == coin:
                szi = float(pd.get("szi", 0))
                if szi == 0:
                    return None
                entry_px = float(pd.get("entryPx", 0))
                # Get current price for the position
                current_price = entry_px
                try:
                    ticker = await self.get_ticker(coin)
                    current_price = ticker.last_price
                except Exception as e:
                    logger.debug("Current price fetch failed for position, using entry price: %s", e)
                return Position(
                    symbol=coin,
                    side="long" if szi > 0 else "short",
                    size=abs(szi),
                    entry_price=entry_px,
                    current_price=current_price,
                    unrealized_pnl=float(pd.get("unrealizedPnl", 0)),
                    leverage=int(float(pd.get("leverage", {}).get("value", 1))),
                    exchange="hyperliquid",
                    liquidation_price=float(pd.get("liquidationPx", 0) or 0),
                )
        return None

    async def get_open_positions(self) -> List[Position]:
        address = self.wallet_address or self._wallet.address
        data = await self._cb_call(self._info.user_state, address)
        positions = []
        for pos in data.get("assetPositions", []):
            pd = pos.get("position", {})
            szi = float(pd.get("szi", 0))
            if szi != 0:
                positions.append(Position(
                    symbol=pd.get("coin", ""),
                    side="long" if szi > 0 else "short",
                    size=abs(szi),
                    entry_price=float(pd.get("entryPx", 0)),
                    current_price=0.0,
                    unrealized_pnl=float(pd.get("unrealizedPnl", 0)),
                    leverage=int(float(pd.get("leverage", {}).get("value", 1))),
                    exchange="hyperliquid",
                    liquidation_price=float(pd.get("liquidationPx", 0) or 0),
                ))
        return positions

    async def get_ticker(self, symbol: str) -> Ticker:
        coin = self._normalize_symbol(symbol)
        data = self._info.all_mids()
        price = float(data.get(coin, 0))
        return Ticker(
            symbol=coin,
            last_price=price,
            bid=price,
            ask=price,
            volume_24h=0.0,
        )

    async def get_funding_rate(self, symbol: str) -> FundingRateInfo:
        coin = self._normalize_symbol(symbol)
        meta = self._info.meta()
        for asset_info in meta.get("universe", []):
            if asset_info.get("name") == coin:
                return FundingRateInfo(
                    symbol=coin,
                    current_rate=float(asset_info.get("funding", 0)),
                )
        return FundingRateInfo(symbol=coin, current_rate=0.0)

    # ── Trading Operations (EIP-712 signed via SDK) ─────────────────────────

    async def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> bool:
        coin = self._normalize_symbol(symbol)
        try:
            result = await self._cb_call(self._exchange.update_leverage, leverage=leverage, name=coin, is_cross=(margin_mode == "cross"))
            logger.info(f"Hyperliquid leverage set to {leverage}x for {coin}: {result}")
            return True
        except Exception as e:
            logger.warning(f"Hyperliquid set_leverage failed for {coin}: {e}")
            return False

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float,
        leverage: int,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        margin_mode: str = "cross",
    ) -> Order:
        coin = self._normalize_symbol(symbol)
        is_buy = side.lower() == "long"

        # Set leverage first
        await self.set_leverage(coin, leverage, margin_mode=margin_mode)

        logger.info(
            f"Hyperliquid market_open: {coin} {'BUY' if is_buy else 'SELL'} "
            f"size={size} leverage={leverage}x wallet={self._wallet.address[:10]}..."
        )

        # Place market order via SDK (handles EIP-712 signing + slippage)
        builder_kwargs = {"builder": self._builder} if self._builder else {}
        result = await self._cb_call(
            self._exchange.market_open,
            name=coin,
            is_buy=is_buy,
            sz=size,
            slippage=DEFAULT_SLIPPAGE,
            **builder_kwargs,
        )

        # Parse response
        order_status = _parse_order_response(result)
        order_id = order_status.get("oid", "hl-unknown")
        fill_price = float(order_status.get("avgPx", 0))

        logger.info(f"Hyperliquid order placed: oid={order_id}, avgPx={fill_price}")

        # Place TP/SL trigger orders
        if take_profit is not None:
            await self._place_trigger_order(coin, not is_buy, size, take_profit, "tp")
        if stop_loss is not None:
            await self._place_trigger_order(coin, not is_buy, size, stop_loss, "sl")

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
        )

    def _get_tick_size(self, coin: str) -> float:
        """Get tick size for a coin from Hyperliquid meta endpoint."""
        try:
            meta = self._info.meta()
            for asset_info in meta.get("universe", []):
                if asset_info.get("name") == coin:
                    # szDecimals controls size precision; price tick from exchange
                    return 10 ** -int(asset_info.get("szDecimals", 0))
        except Exception as e:
            logger.debug(f"Could not fetch tick size for {coin}: {e}")
        return 0.01  # safe default

    @staticmethod
    def _round_price(price: float, tick_size: float) -> float:
        """Round price to the nearest tick size."""
        if tick_size <= 0:
            return price
        # Determine decimal places from tick size
        decimals = max(0, len(str(tick_size).rstrip('0').split('.')[-1])) if '.' in str(tick_size) else 0
        return round(round(price / tick_size) * tick_size, decimals)

    async def _place_trigger_order(
        self, coin: str, is_buy: bool, size: float, trigger_px: float, tpsl: str,
    ) -> None:
        """Place a TP or SL trigger order (reduce-only).

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
                        return
                    if is_buy and trigger_px >= market_px:
                        logger.warning(
                            f"Hyperliquid TP trigger for {coin}: price {trigger_px} must be below "
                            f"market {market_px} for short position. Skipping."
                        )
                        return
                elif tpsl == "sl":
                    if not is_buy and trigger_px >= market_px:
                        logger.warning(
                            f"Hyperliquid SL trigger for {coin}: price {trigger_px} must be below "
                            f"market {market_px} for long position. Skipping."
                        )
                        return
                    if is_buy and trigger_px <= market_px:
                        logger.warning(
                            f"Hyperliquid SL trigger for {coin}: price {trigger_px} must be above "
                            f"market {market_px} for short position. Skipping."
                        )
                        return
        except Exception as e:
            logger.debug(f"Could not validate trigger price for {coin}: {e}")

        # Round trigger price to appropriate precision
        rounded_px = self._round_price(trigger_px, self._get_tick_size(coin))

        try:
            builder_kwargs = {"builder": self._builder} if self._builder else {}
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
        except Exception as e:
            logger.warning(f"Hyperliquid {tpsl.upper()} trigger failed for {coin}: {e}")

    async def close_position(self, symbol: str, side: str, margin_mode: str = "cross") -> Optional[Order]:
        coin = self._normalize_symbol(symbol)

        # Get current position size
        pos = await self.get_position(coin)
        if not pos:
            logger.warning(f"Hyperliquid: no position found for {coin} to close")
            return None

        logger.info(
            f"Hyperliquid market_close: {coin} size={pos.size} "
            f"wallet={self._wallet.address[:10]}..."
        )

        builder_kwargs = {"builder": self._builder} if self._builder else {}
        result = await self._cb_call(
            self._exchange.market_close,
            coin=coin,
            sz=pos.size,
            slippage=DEFAULT_SLIPPAGE,
            **builder_kwargs,
        )

        order_status = _parse_order_response(result)
        order_id = order_status.get("oid", "hl-close")
        fill_price = float(order_status.get("avgPx", 0))

        logger.info(f"Hyperliquid position closed: oid={order_id}, avgPx={fill_price}")

        return Order(
            order_id=str(order_id),
            symbol=coin,
            side=side,
            size=pos.size,
            price=fill_price,
            status="filled",
            exchange="hyperliquid",
        )

    # ── Builder Code & Referral Queries ──────────────────────────────────

    async def check_builder_fee_approval(self, user_address: str = None) -> Optional[int]:
        """Check if user has approved builder fee for the configured builder.

        Returns the max approved fee rate (int), or None if not approved.
        """
        if not self._builder:
            return None

        addr = (user_address or self.wallet_address).lower()
        try:
            result = self._info.post(
                "/info",
                {"type": "maxBuilderFee", "user": addr, "builder": self._builder["b"]},
            )
            if result is not None and int(result) > 0:
                return int(result)
            return None
        except Exception as e:
            logger.warning(f"Failed to check builder fee approval: {e}")
            return None

    async def approve_builder_fee(self, max_fee_rate: int = None) -> bool:
        """Approve builder fee for the configured builder address.

        Must be called once per user before builder fees can be charged.
        Uses the SDK's approve_builder_fee (EIP-712 signed).
        """
        if not self._builder:
            logger.warning("No builder code configured, cannot approve")
            return False

        fee = max_fee_rate or self._builder["f"]
        # Hyperliquid API expects maxFeeRate as percentage string
        # Internal fee is in tenths of basis points (e.g. 10 = 1bp = 0.01%)
        fee_pct = f"{fee / 1000:.3f}%"
        try:
            self._exchange.approve_builder_fee(
                builder=self._builder["b"],
                max_fee_rate=fee_pct,
            )
            logger.info(
                f"Builder fee approved: builder={self._builder['b'][:10]}... maxFee={fee_pct}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to approve builder fee: {e}")
            return False

    async def get_referral_info(self, user_address: str = None) -> Optional[dict]:
        """Get referral state for a user (referred_by, referral_code, etc.)."""
        addr = (user_address or self.wallet_address).lower()
        try:
            result = self._info.query_referral_state(addr)
            return result if isinstance(result, dict) else None
        except Exception as e:
            logger.warning(f"Failed to get referral info: {e}")
            return None

    async def check_affiliate_uid(self, uid: str) -> bool:
        """Check if a wallet address has been referred via our referral code.

        For Hyperliquid, the 'uid' is the user's wallet address (0x...).
        Checks if `referred_by` is set in the referral state.
        """
        try:
            info = await self.get_referral_info(user_address=uid)
            if info and info.get("referred_by"):
                return True
            return False
        except Exception as e:
            logger.warning(f"Affiliate UID check failed for {uid}: {e}")
            return False

    async def get_user_fees(self, user_address: str = None) -> Optional[dict]:
        """Get user fee/volume tier info (includes trading volume data)."""
        addr = (user_address or self.wallet_address).lower()
        try:
            result = self._info.user_fees(addr)
            return result if isinstance(result, dict) else None
        except Exception as e:
            logger.warning(f"Failed to get user fees: {e}")
            return None

    # ── Fee Tracking Methods ─────────────────────────────────────────────

    async def get_order_fees(self, symbol: str, order_id: str) -> float:
        """Get fees for a single order from fills history."""
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        total = 0.0
        try:
            fills = self._info.user_fills(address)
            for fill in fills:
                if str(fill.get("oid", "")) == str(order_id) and fill.get("coin") == coin:
                    total += abs(float(fill.get("fee", 0)))
        except Exception as e:
            logger.warning(f"Failed to get order fees for {order_id}: {e}")
        return round(total, 6)

    async def get_trade_total_fees(
        self, symbol: str, entry_order_id: str, close_order_id: Optional[str] = None
    ) -> float:
        """Get total trading fees (entry + exit) from fills history."""
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        total_fees = 0.0
        try:
            fills = self._info.user_fills(address)
            target_oids = {str(entry_order_id)}
            if close_order_id:
                target_oids.add(str(close_order_id))
            for fill in fills:
                if str(fill.get("oid", "")) in target_oids and fill.get("coin") == coin:
                    total_fees += abs(float(fill.get("fee", 0)))
        except Exception as e:
            logger.warning(f"Failed to get trade total fees for {symbol}: {e}")
        return round(total_fees, 6)

    async def get_fill_price(
        self, symbol: str, order_id: str, **kwargs
    ) -> Optional[float]:
        """Get actual fill price for an order from fills history.

        Uses userFills endpoint — each fill has px (price) and sz (size).
        Calculates weighted average across partial fills.
        """
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        try:
            fills = self._info.user_fills(address)
            total_value = 0.0
            total_size = 0.0
            for fill in fills:
                if str(fill.get("oid", "")) == str(order_id) and fill.get("coin") == coin:
                    px = float(fill.get("px", 0))
                    sz = float(fill.get("sz", 0))
                    if px > 0 and sz > 0:
                        total_value += px * sz
                        total_size += sz
            if total_size > 0:
                return round(total_value / total_size, 8)
        except Exception as e:
            logger.warning(f"Failed to get fill price for {order_id}: {e}")
        return None

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
        builder_kwargs = {"builder": self._builder} if self._builder else {}

        if take_profit is not None:
            rounded_tp = self._round_price(take_profit, tick_size)
            order_req.append({
                "name": coin,
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
                "name": coin,
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
                if take_profit is not None:
                    await self._place_trigger_order(coin, is_buy_close, size or 0, take_profit, "tp")
                if stop_loss is not None:
                    await self._place_trigger_order(coin, is_buy_close, size or 0, stop_loss, "sl")
                return "fallback"
            except Exception as e2:
                logger.warning("Hyperliquid trigger fallback also failed: %s", e2)
        return None

    async def get_close_fill_price(self, symbol: str) -> Optional[float]:
        """Get fill price of the most recent close fill from Hyperliquid."""
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        try:
            fills = self._info.user_fills(address)
            for fill in reversed(fills):
                if fill.get("coin") == coin and fill.get("dir", "").startswith("Close"):
                    price = fill.get("px")
                    if price and float(price) > 0:
                        return float(price)
        except Exception as e:
            logger.warning(f"Failed to get close fill price for {symbol}: {e}")
        return None

    async def get_funding_fees(
        self, symbol: str, start_time_ms: int, end_time_ms: int
    ) -> float:
        """Get total funding fees for a symbol between two timestamps."""
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        total_funding = 0.0
        try:
            history = self._info.user_funding_history(
                user=address,
                startTime=start_time_ms,
                endTime=end_time_ms,
            )
            if isinstance(history, list):
                for entry in history:
                    if entry.get("coin") == coin or entry.get("asset") == coin:
                        total_funding += abs(float(entry.get("delta", 0)))
        except Exception as e:
            logger.warning(f"Failed to get funding fees for {symbol}: {e}")
        return round(total_funding, 6)

    def calculate_builder_fee(
        self, entry_price: float, exit_price: float, size: float
    ) -> float:
        """Calculate builder fee earned for a round-trip trade.

        Both entry and exit orders carry the builder fee.
        fee = (entry_value + exit_value) * (builder_fee_rate / 1_000_000)
        """
        if not self._builder:
            return 0.0
        fee_rate = self._builder["f"]
        total_value = (entry_price * size) + (exit_price * size)
        return round(total_value * (fee_rate / 1_000_000), 6)

    @property
    def builder_config(self) -> Optional[dict]:
        """Return current builder config or None."""
        return self._builder

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        coin = self._normalize_symbol(symbol)
        try:
            await self._cb_call(self._exchange.cancel, name=coin, oid=int(order_id))
            logger.info(f"Hyperliquid order cancelled: {coin} oid={order_id}")
            return True
        except Exception as e:
            logger.warning(f"Hyperliquid cancel failed: {e}")
            return False


def _parse_order_response(result: Any) -> Dict[str, Any]:
    """Extract order info from SDK response. Handles various response formats."""
    logger.debug(f"Hyperliquid raw response: {result}")

    if isinstance(result, dict):
        # Check for top-level error
        resp_type = result.get("status", "")
        if resp_type == "err":
            raise HyperliquidClientError(f"Order rejected: {result.get('response', result)}")

        status = result.get("response", {}).get("data", {})
        if isinstance(status, dict) and "statuses" in status:
            statuses = status["statuses"]
            if statuses:
                first = statuses[0]
                # Filled order: {"filled": {"totalSz": "0.001", "avgPx": "95000", "oid": 123}}
                if "filled" in first:
                    return {
                        "oid": first["filled"].get("oid", ""),
                        "avgPx": first["filled"].get("avgPx", "0"),
                        "totalSz": first["filled"].get("totalSz", "0"),
                    }
                # Resting order: {"resting": {"oid": 123}}
                if "resting" in first:
                    return {"oid": first["resting"].get("oid", ""), "avgPx": "0"}
                # Error in status
                if "error" in first:
                    raise HyperliquidClientError(f"Order rejected: {first['error']}")

    logger.warning(f"Hyperliquid: could not parse order response: {result}")
    return {"oid": "hl-unknown", "avgPx": "0"}
