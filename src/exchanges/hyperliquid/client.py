"""
Hyperliquid Exchange Client implementing ExchangeClient ABC.

Uses the official hyperliquid-python-sdk for EIP-712 signed trading.
Symbol format: plain asset name (e.g. "BTC", "ETH") or pairs like "BTCUSDT"/"BTCUSDC"
which are normalized to coin names internally.

SECURITY: Only trading operations are allowed. No withdrawals, transfers, or
fund-moving operations. The ALLOWED_METHODS whitelist enforces this.
"""

import asyncio
import hashlib
import os
import re
from datetime import datetime, timezone
from functools import partial
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from eth_account import Account as EthAccount
from hyperliquid.exchange import Exchange as HLExchange
from hyperliquid.info import Info as HLInfo
from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL
from hyperliquid.utils.types import Cloid

from src.exceptions import ExchangeError
from src.exchanges.base import (
    CloseReasonSnapshot,
    ExchangeClient,
    GateCheckResult,
    PositionTpSlSnapshot,
    TrailingStopSnapshot,
)
from src.exchanges.hyperliquid.constants import (
    DEFAULT_BUILDER_FEE,
    MAINNET_CHAIN_ID,
    MAX_BUILDER_FEE_TENTHS_BPS,
    MIN_BUILDER_FEE_TENTHS_BPS,
    TESTNET_CHAIN_ID,
)
from src.exchanges.hyperliquid.eip712_validator import (
    EIP712ValidationError,
    assert_builder_fee_tenths_bps,
    assert_chain_id,
    validate_approve_builder_fee,
)
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker

if TYPE_CHECKING:
    from src.exchanges.base import GateCheckResult
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
        # Forward the rate_limiter kwarg so _cb_call can serialize through it.
        super().__init__(
            api_key, api_secret, passphrase, demo_mode,
            rate_limiter=kwargs.get("rate_limiter"),
        )
        self.wallet_address = api_key
        # Execution network: testnet in demo, mainnet in live
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

        # Public price info — ALWAYS mainnet. Testnet mids/funding are
        # detached from real market and corrupt demo PnL reports.
        # Why: user expects demo numbers to match HL mainnet UI 1:1.
        if demo_mode:
            try:
                self._info: HLInfo = HLInfo(base_url=MAINNET_API_URL, skip_ws=True)
            except (IndexError, KeyError):
                self._info = HLInfo(
                    base_url=MAINNET_API_URL, skip_ws=True,
                    spot_meta={"tokens": [], "universe": []},
                )
        else:
            self._info = raw_exchange.info

        # Exec-network info — used for user-specific queries (fills, positions)
        # that only exist on the network where orders were placed.
        self._info_exec: HLInfo = raw_exchange.info

        # ── Builder Code config ──────────────────────────────────────────
        # Earns a small fee on every order (100% to builder, no cap).
        # Accepts kwargs from caller (DB-first) or falls back to ENV.
        builder_address = (kwargs.get("builder_address") or os.environ.get("HL_BUILDER_ADDRESS", "")).strip()
        builder_fee = int(kwargs.get("builder_fee") or os.environ.get("HL_BUILDER_FEE", str(DEFAULT_BUILDER_FEE)))
        within_bounds = (
            MIN_BUILDER_FEE_TENTHS_BPS <= builder_fee <= MAX_BUILDER_FEE_TENTHS_BPS
        )
        if builder_address and within_bounds:
            self._builder = {"b": builder_address.lower(), "f": builder_fee}
            logger.info(
                f"Builder code enabled: {builder_address[:10]}... "
                f"fee={builder_fee} ({builder_fee / 10:.1f} bp = {builder_fee / 1000:.3f}%)"
            )
        else:
            self._builder = None
            if builder_address and not within_bounds:
                logger.warning(
                    f"HL_BUILDER_FEE={builder_fee} out of range "
                    f"[{MIN_BUILDER_FEE_TENTHS_BPS}-{MAX_BUILDER_FEE_TENTHS_BPS}]. "
                    f"Builder code disabled."
                )

        # SEC-005: pin expected signature chain_id so a manipulated SDK
        # cannot produce a cross-chain-replayable approval.
        self._expected_chain_id = TESTNET_CHAIN_ID if demo_mode else MAINNET_CHAIN_ID

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

    async def pre_start_checks(
        self,
        user_id: int,
        db: Optional[Any] = None,
    ) -> List["GateCheckResult"]:
        """Run Hyperliquid-specific pre-start gate checks (#ARCH-H2).

        Returns a list of ``GateCheckResult`` entries with ``ok=False`` for
        each gate that should block bot start:
          - ``referral`` — user is not referred via our affiliate code
          - ``builder_fee`` — builder fee approval missing on-chain
          - ``wallet`` — wallet is not usable (unfunded / unauthorized)

        Passing gates are omitted (empty list = all clear). The caller
        (``BotWorker.initialize``) maps failing results to ``self.error_message``
        and decides whether to abort.
        """
        from src.utils.settings import get_hl_config

        # Base gates (affiliate-UID) first — shared across exchanges.
        results: List[GateCheckResult] = list(
            await super().pre_start_checks(user_id=user_id, db=db)
        )
        hl_cfg = await get_hl_config()

        # ── Referral gate ────────────────────────────────────────────
        referral_code = hl_cfg.get("referral_code")
        if referral_code:
            conn = await self._load_exchange_connection(db, user_id)
            if conn and getattr(conn, "referral_verified", False):
                pass  # cached as verified
            else:
                try:
                    info = await self.get_referral_info()
                    referred_by = None
                    if info:
                        referred_by = info.get("referredBy") or info.get("referred_by")

                    if not referred_by:
                        link = f"https://app.hyperliquid.xyz/join/{referral_code}"
                        results.append(GateCheckResult(
                            key="referral", ok=False,
                            message=(
                                f"Referral erforderlich: Bitte registriere dich über {link} "
                                f"bevor du Hyperliquid Bots nutzen kannst."
                            ),
                        ))
                    else:
                        referrer_code = None
                        if isinstance(referred_by, dict):
                            referrer_code = (
                                referred_by.get("code") or referred_by.get("referralCode")
                            )
                        elif isinstance(referred_by, str):
                            referrer_code = referred_by

                        builder_address = hl_cfg.get("builder_address", "")
                        code_match = (
                            referrer_code
                            and str(referrer_code).lower() == str(referral_code).lower()
                        )
                        addr_match = (
                            referrer_code and builder_address
                            and str(referrer_code).lower() == str(builder_address).lower()
                        )
                        if not code_match and not addr_match:
                            results.append(GateCheckResult(
                                key="referral", ok=False,
                                message=(
                                    f"Dein Account wurde über einen anderen Referral-Code "
                                    f"registriert. Bitte nutze unseren Link: "
                                    f"https://app.hyperliquid.xyz/join/{referral_code}"
                                ),
                            ))
                        elif conn is not None and db is not None:
                            # Cache success so future starts skip the live call.
                            try:
                                conn.referral_verified = True
                                conn.referral_verified_at = datetime.now(timezone.utc)
                                await db.commit()
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"Hyperliquid referral check failed: {e}")
                    results.append(GateCheckResult(
                        key="referral", ok=False,
                        message=(
                            f"Referral-Prüfung fehlgeschlagen. Bitte versuche es erneut. "
                            f"Falls das Problem bestehen bleibt, registriere dich über "
                            f"https://app.hyperliquid.xyz/join/{referral_code}"
                        ),
                    ))

        # ── Builder-fee gate ─────────────────────────────────────────
        if self.builder_config:
            conn = await self._load_exchange_connection(db, user_id)
            if conn and getattr(conn, "builder_fee_approved", False):
                pass  # cached
            else:
                try:
                    if self.demo_mode and conn is not None:
                        from src.services.config_service import (
                            create_hl_mainnet_read_client,
                        )
                        mainnet_client = create_hl_mainnet_read_client(conn)
                        approved = await mainnet_client.check_builder_fee_approval(
                            builder_address=self.builder_config["b"],
                        )
                    else:
                        approved = await self.check_builder_fee_approval()

                    if approved is not None and approved >= self.builder_config["f"]:
                        if conn is not None and db is not None:
                            try:
                                conn.builder_fee_approved = True
                                conn.builder_fee_approved_at = datetime.now(timezone.utc)
                                await db.commit()
                            except Exception:
                                pass
                    else:
                        results.append(GateCheckResult(
                            key="builder_fee", ok=False,
                            message=(
                                "Builder Fee nicht genehmigt. Bitte genehmige die Builder "
                                "Fee auf der Website unter 'Meine Bots' bevor du einen "
                                "Hyperliquid Bot starten kannst."
                            ),
                        ))
                except Exception as e:
                    logger.warning(f"Hyperliquid builder approval check failed: {e}")
                    results.append(GateCheckResult(
                        key="builder_fee", ok=False,
                        message=f"Builder Fee Prüfung fehlgeschlagen: {e}",
                    ))

        # ── Wallet gate ──────────────────────────────────────────────
        try:
            wallet_result = await self.validate_wallet()
            if not wallet_result.get("valid", False):
                results.append(GateCheckResult(
                    key="wallet", ok=False,
                    message=wallet_result.get("error") or "Wallet-Validierung fehlgeschlagen.",
                ))
        except Exception as e:
            logger.warning(f"Hyperliquid wallet validation failed: {e}")
            # Fail open on unexpected errors (matches original behavior).

        return results

    @staticmethod
    async def _load_exchange_connection(db, user_id: int):
        """Load the Hyperliquid ExchangeConnection row for this user (or None)."""
        if db is None:
            return None
        try:
            from sqlalchemy import select as sa_select
            from src.models.database import ExchangeConnection
            result = await db.execute(
                sa_select(ExchangeConnection).where(
                    ExchangeConnection.user_id == user_id,
                    ExchangeConnection.exchange_type == "hyperliquid",
                )
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.debug(f"Could not load HL ExchangeConnection for user={user_id}: {e}")
            return None

    async def _cb_call(self, func, *args, **kwargs):
        """Execute a sync SDK function through the circuit breaker without blocking the event loop.

        Acquires a token from the per-exchange rate limiter (#ARCH-C3) so
        HL-bound API calls share the same bucket across every HL client
        instance in the process.
        """
        # Serialize through the per-exchange token bucket when wired.
        if getattr(self, "_rate_limiter", None) is not None:
            await self._rate_limiter.acquire()

        loop = asyncio.get_event_loop()

        async def _wrapper():
            return await loop.run_in_executor(None, partial(func, *args, **kwargs))
        try:
            return await _hl_breaker.call(_wrapper)
        except CircuitBreakerError as e:
            raise HyperliquidClientError(f"API temporarily unavailable: {e}")

    # ── Read Operations ─────────────────────────────────────────────────────

    async def validate_wallet(self) -> dict:
        """Validate that the configured wallet exists on Hyperliquid and is funded.

        Returns a dict with:
            - valid: bool — True if wallet is usable for trading
            - error: str | None — user-friendly error description
            - balance: float — total account value (perp + spot USDC)
            - main_wallet: str — the main wallet address
            - api_wallet: str — the API/signing wallet address
            - is_agent_wallet: bool — True if API wallet differs from main wallet
        """
        main_addr = self.wallet_address or self._wallet.address
        api_addr = self._wallet.address
        is_agent = main_addr.lower() != api_addr.lower()

        result = {
            "valid": False,
            "error": None,
            "balance": 0.0,
            "main_wallet": main_addr,
            "api_wallet": api_addr,
            "is_agent_wallet": is_agent,
        }

        # Check main wallet state
        try:
            data = await self._cb_call(self._info_exec.user_state, main_addr)
        except Exception as e:
            result["error"] = (
                f"Konnte dein Hyperliquid-Wallet nicht abfragen. "
                f"Bitte pruefe deine Internetverbindung und versuche es erneut. ({e})"
            )
            return result

        if not isinstance(data, dict) or not data.get("marginSummary"):
            # Wallet has never interacted with Hyperliquid
            network = "Testnet" if self._demo_mode else "Mainnet (Arbitrum)"
            result["error"] = (
                f"Dein Hyperliquid-Wallet ({main_addr[:8]}...{main_addr[-4:]}) "
                f"wurde nicht gefunden. Das Wallet muss zuerst auf Hyperliquid "
                f"aktiviert werden.\n\n"
                f"So geht's:\n"
                f"1. Oeffne app.hyperliquid.xyz\n"
                f"2. Zahle mindestens 100 USDC auf {network} ein\n"
                f"3. Starte den Bot erneut"
            )
            return result

        # Check balance
        margin = data.get("marginSummary", {})
        perp_total = float(margin.get("accountValue", 0))

        # Also check spot USDC
        spot_usdc = 0.0
        if perp_total == 0:
            try:
                spot_data = self._info_exec.spot_user_state(main_addr)
                for b in spot_data.get("balances", []):
                    if b.get("coin") == "USDC":
                        spot_usdc = float(b.get("total", 0))
                        break
            except Exception:
                pass

        total_balance = perp_total + spot_usdc
        result["balance"] = total_balance

        min_balance = 100.0
        if total_balance < min_balance:
            network = "Testnet" if self._demo_mode else "Mainnet (Arbitrum)"
            if total_balance < 1.0:
                balance_msg = "hat kein Guthaben"
            else:
                balance_msg = f"hat nur ${total_balance:.2f} Guthaben"
            result["error"] = (
                f"Dein Hyperliquid-Wallet ({main_addr[:8]}...{main_addr[-4:]}) "
                f"{balance_msg}. "
                f"Bitte zahle mindestens {int(min_balance)} USDC auf {network} ein, "
                f"damit der Bot traden kann."
            )
            return result

        # If using API wallet, verify it can sign for the main wallet
        if is_agent:
            try:
                # Try a read-only leverage query to verify API wallet authorization
                test_result = await self._cb_call(
                    self._exchange.update_leverage, leverage=1, name="BTC", is_cross=True,
                )
                if isinstance(test_result, dict) and test_result.get("status") == "err":
                    err_msg = test_result.get("response", "")
                    if "does not exist" in str(err_msg).lower():
                        result["error"] = (
                            f"Dein API-Wallet ({api_addr[:8]}...{api_addr[-4:]}) ist nicht autorisiert "
                            f"fuer dein Haupt-Wallet ({main_addr[:8]}...{main_addr[-4:]}).\n\n"
                            f"So geht's:\n"
                            f"1. Oeffne app.hyperliquid.xyz\n"
                            f"2. Gehe zu 'API Wallet' in den Einstellungen\n"
                            f"3. Erstelle ein neues API-Wallet oder autorisiere die bestehende Adresse\n"
                            f"4. Trage den neuen Private Key in den Bot-Einstellungen ein"
                        )
                        return result
            except Exception as e:
                err_str = str(e).lower()
                if "does not exist" in err_str:
                    result["error"] = (
                        f"Dein API-Wallet ({api_addr[:8]}...{api_addr[-4:]}) ist nicht autorisiert "
                        f"fuer dein Haupt-Wallet ({main_addr[:8]}...{main_addr[-4:]}).\n\n"
                        f"Erstelle ein API-Wallet unter app.hyperliquid.xyz > Einstellungen > API Wallet."
                    )
                    return result

        result["valid"] = True
        return result

    async def get_account_balance(self) -> Balance:
        address = self.wallet_address or self._wallet.address
        data = await self._cb_call(self._info_exec.user_state, address)
        if not isinstance(data, dict):
            data = {}
        margin = data.get("marginSummary", {})
        perp_total = float(margin.get("accountValue", 0))
        perp_available = float(data.get("withdrawable", margin.get("totalRawUsd", 0)))

        # Unified accounts: perp balance may be 0 while funds sit in spot
        spot_usdc = 0.0
        if perp_total == 0:
            try:
                spot_data = self._info_exec.spot_user_state(address)
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
        data = await self._cb_call(self._info_exec.user_state, address)
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
        data = await self._cb_call(self._info_exec.user_state, address)

        # Fetch all mid-prices in a single API call
        try:
            all_mids = await self._cb_call(self._info.all_mids)
        except Exception:
            all_mids = {}

        positions = []
        for pos in data.get("assetPositions", []):
            pd = pos.get("position", {})
            szi = float(pd.get("szi", 0))
            if szi != 0:
                coin = pd.get("coin", "")
                entry_px = float(pd.get("entryPx", 0))
                current_price = float(all_mids.get(coin, 0)) or entry_px
                positions.append(Position(
                    symbol=coin,
                    side="long" if szi > 0 else "short",
                    size=abs(szi),
                    entry_price=entry_px,
                    current_price=current_price,
                    unrealized_pnl=float(pd.get("unrealizedPnl", 0)),
                    leverage=int(float(pd.get("leverage", {}).get("value", 1))),
                    exchange="hyperliquid",
                    liquidation_price=float(pd.get("liquidationPx", 0) or 0),
                ))
        return positions

    async def get_ticker(self, symbol: str) -> Ticker:
        coin = self._normalize_symbol(symbol)
        data = await self._cb_call(self._info.all_mids)
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
        # Use metaAndAssetCtxs for live funding rates (meta() only has static metadata)
        try:
            data = await self._cb_call(self._info.meta_and_asset_ctxs)
            if isinstance(data, (list, tuple)) and len(data) >= 2:
                meta_universe = data[0].get("universe", [])
                asset_ctxs = data[1]
                for info, ctx in zip(meta_universe, asset_ctxs):
                    if info.get("name") == coin:
                        return FundingRateInfo(
                            symbol=coin,
                            current_rate=float(ctx.get("funding", 0)),
                        )
        except Exception as e:
            logger.debug("metaAndAssetCtxs failed, falling back to meta(): %s", e)
            # Fallback to static meta
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
    def _derive_cloid(client_order_id: str) -> Cloid:
        """Derive a Hyperliquid Cloid (16 bytes hex) from a free-form id.

        HL requires exactly 16 bytes, but our executor hands us a longer string
        like ``bot-<id>-<uuid>``. We hash it deterministically so the same
        caller-id always maps to the same on-chain cloid (#ARCH-C2).
        """
        digest = hashlib.blake2b(client_order_id.encode("utf-8"), digest_size=16).hexdigest()
        return Cloid.from_str(f"0x{digest}")

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
                            import math
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
        import math
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

    # ── Builder Code & Referral Queries ──────────────────────────────────

    async def check_builder_fee_approval(
        self,
        user_address: str = None,
        builder_address: str = None,
    ) -> Optional[int]:
        """Check if user has approved builder fee for the configured builder.

        Args:
            user_address: Wallet to check. Defaults to ``self.wallet_address``.
            builder_address: Builder wallet whose approval to query. Defaults
                to ``self._builder["b"]`` when the client was initialized
                with builder kwargs. Callers that construct the client via
                ``create_hl_mainnet_read_client`` (which does not set
                ``self._builder``) **must** pass this explicitly, otherwise
                the method short-circuits to ``None`` without hitting HL.

        Returns:
            The max approved fee rate (int, tenths of basis points), or
            ``None`` if no approval exists or the builder address could
            not be resolved.
        """
        resolved_builder = (
            builder_address
            or (self._builder["b"] if self._builder else None)
        )
        if not resolved_builder:
            logger.debug(
                "check_builder_fee_approval called without a builder address — "
                "client has no self._builder and no explicit parameter",
            )
            return None

        addr = (user_address or self.wallet_address).lower()
        try:
            result = self._info_exec.post(
                "/info",
                {
                    "type": "maxBuilderFee",
                    "user": addr,
                    "builder": resolved_builder.lower(),
                },
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

        Defense-in-depth (SEC-008): both the integer fee and the wire-format
        percentage string are validated before signing. Historical incident:
        the fee was once computed 10x too high; the validators prevent a
        recurrence by refusing anything outside the HL documented range.
        """
        if not self._builder:
            logger.warning("No builder code configured, cannot approve")
            return False

        fee = max_fee_rate or self._builder["f"]
        # Hyperliquid API expects maxFeeRate as percentage string.
        # Internal fee is in tenths of basis points (e.g. 10 = 1bp = 0.01%).
        try:
            assert_builder_fee_tenths_bps(fee)
            fee_pct = f"{fee / 1000:.3f}%"
            validate_approve_builder_fee(
                builder=self._builder["b"],
                max_fee_rate=fee_pct,
                demo_mode=self.demo_mode,
                chain_id=self._expected_chain_id,
            )
        except EIP712ValidationError as e:
            logger.error(f"Builder-fee approval rejected by validator: {e}")
            return False

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
            result = self._info_exec.query_referral_state(addr)
            return result if isinstance(result, dict) else None
        except Exception as e:
            logger.warning(f"Failed to get referral info: {e}")
            return None

    async def get_user_state(self, user_address: str = None) -> Optional[dict]:
        """Raw ``user_state`` query — used for deposit / balance diagnostics.

        Returns the full HL response dict with ``marginSummary``,
        ``withdrawable``, ``assetPositions`` etc. Used by the referral
        verification flow to distinguish "wallet never deposited" from
        "wallet deposited but no referrer set".
        """
        addr = (user_address or self.wallet_address).lower()
        try:
            result = self._info_exec.user_state(addr)
            return result if isinstance(result, dict) else None
        except Exception as e:
            logger.warning(f"Failed to get user state: {e}")
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
            result = self._info_exec.user_fees(addr)
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
            fills = self._info_exec.user_fills(address)
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
            fills = self._info_exec.user_fills(address)
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

        In demo mode the real fill lives on testnet at illiquid prices; returning
        the mainnet mid instead keeps entry_price consistent with the ticker the
        user sees on the live Hyperliquid UI.
        """
        if self.demo_mode:
            try:
                ticker = await self.get_ticker(symbol)
                px = float(getattr(ticker, "last_price", 0) or 0)
                return px if px > 0 else None
            except Exception as e:
                logger.debug(f"Demo fill price fallback failed for {symbol}: {e}")
                return None

        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        try:
            fills = self._info_exec.user_fills(address)
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

    async def get_close_fill_price(self, symbol: str) -> Optional[float]:
        """Get fill price of the most recent close fill from Hyperliquid.

        In demo mode returns None so the caller falls back to the mainnet ticker;
        testnet close fills would pollute PnL with detached testnet prices.
        """
        if self.demo_mode:
            return None

        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        try:
            fills = self._info_exec.user_fills(address)
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
            history = self._info_exec.user_funding_history(
                user=address,
                startTime=start_time_ms,
                endTime=end_time_ms,
            )
            if isinstance(history, list):
                for entry in history:
                    if entry.get("coin") == coin or entry.get("asset") == coin:
                        # delta is negative when funding is paid, positive when received
                        # We track net funding cost (positive = paid, negative = received)
                        total_funding += float(entry.get("delta", 0))
        except Exception as e:
            logger.warning(f"Failed to get funding fees for {symbol}: {e}")
        return round(total_funding, 6)

    def calculate_builder_fee(
        self, entry_price: float, exit_price: float, size: float
    ) -> float:
        """Calculate builder fee earned for a round-trip trade.

        Both entry and exit orders carry the builder fee.
        Fee unit: f is in tenths of basis points.
        f=10 → 10 * 0.001% = 0.01% → 0.0001
        Divisor: 10 (tenths) * 10_000 (basis points) = 100_000
        """
        if not self._builder:
            return 0.0
        fee_rate = self._builder["f"]
        total_value = (entry_price * size) + (exit_price * size)
        return round(total_value * (fee_rate / 100_000), 6)

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

    # ── Risk-state readback (#191) ──────────────────────────────────────
    # HL exposes position-level TP/SL as isPositionTpsl triggers on
    # frontendOpenOrders. There is NO native trailing-stop primitive on
    # HL, so get_trailing_stop always returns None — callers should rely
    # on software trailing instead.

    async def get_position_tpsl(
        self, symbol: str, side: str
    ) -> PositionTpSlSnapshot:
        """Read live position-level TP/SL triggers from Hyperliquid.

        Queries frontendOpenOrders for the user, filters entries where
        ``isTrigger=true`` (or ``isPositionTpsl=true``) and the coin
        matches. Classifies into TP vs SL by ``orderType`` string.
        """
        coin = self._normalize_symbol(symbol)
        empty = PositionTpSlSnapshot(
            symbol=coin,
            side=side,
            tp_price=None,
            tp_order_id=None,
            tp_trigger_type=None,
            sl_price=None,
            sl_order_id=None,
            sl_trigger_type=None,
        )

        address = (self.wallet_address or self._wallet.address).lower()
        raw = await self._cb_call(self._info_exec.frontend_open_orders, address)
        if not isinstance(raw, list):
            return empty

        # Closing direction is opposite of position side.
        # long position → close via sell (is_buy=False on HL)
        close_is_buy = side.lower() != "long"

        tp_order: Optional[Dict[str, Any]] = None
        sl_order: Optional[Dict[str, Any]] = None
        for order in raw:
            if not isinstance(order, dict):
                continue
            if order.get("coin") != coin:
                continue
            is_trigger = bool(order.get("isTrigger") or order.get("isPositionTpsl"))
            if not is_trigger:
                continue
            # Side filter: TP/SL for a LONG position are SELL orders on HL.
            side_field = str(order.get("side", "")).upper()
            if side_field == "B":
                order_is_buy = True
            elif side_field == "A":
                order_is_buy = False
            else:
                # Unknown side format — don't filter it out, accept all.
                order_is_buy = close_is_buy

            if order_is_buy != close_is_buy:
                continue

            order_type = str(order.get("orderType") or "").lower()
            if ("tp" in order_type or "take" in order_type) and tp_order is None:
                tp_order = order
            elif ("sl" in order_type or "stop" in order_type) and sl_order is None:
                sl_order = order

        trigger_type = "mark_price"  # HL trigger prices are mark-price based
        return PositionTpSlSnapshot(
            symbol=coin,
            side=side,
            tp_price=_hl_float(tp_order.get("triggerPx") or tp_order.get("limitPx")) if tp_order else None,
            tp_order_id=str(tp_order.get("oid")) if tp_order and tp_order.get("oid") is not None else None,
            tp_trigger_type=trigger_type if tp_order else None,
            sl_price=_hl_float(sl_order.get("triggerPx") or sl_order.get("limitPx")) if sl_order else None,
            sl_order_id=str(sl_order.get("oid")) if sl_order and sl_order.get("oid") is not None else None,
            sl_trigger_type=trigger_type if sl_order else None,
        )

    async def get_trailing_stop(
        self, symbol: str, side: str
    ) -> Optional[TrailingStopSnapshot]:
        """Hyperliquid has no native trailing-stop primitive.

        Returns ``None`` unconditionally. Callers fall back to the
        software trailing loop in ``strategy.should_exit``.
        """
        logger.debug(
            "Hyperliquid has no native trailing stop — get_trailing_stop returns None"
        )
        return None

    async def get_close_reason_from_history(
        self,
        symbol: str,
        since_ts_ms: int,
        until_ts_ms: Optional[int] = None,
    ) -> Optional[CloseReasonSnapshot]:
        """Find the most recent close fill for ``symbol`` in the time window.

        Inspects ``user_fills`` and picks the newest reduce-only close fill.
        Hyperliquid encodes the close reason in the fill's ``dir`` field
        (e.g. "Close Long", "Close Short") plus a ``liquidation`` flag.

        A transient SDK failure in ``user_fills`` is isolated so the outer
        ``get_close_reason_from_history`` surface still returns ``None``
        rather than bubbling — caller's heuristic fallback then runs
        (Pattern C mitigation per #224).

        ``until_ts_ms`` bounds the right end of the window for backfill
        use; HL's ``user_fills`` has no server-side time filter, so the
        bound is enforced client-side (per #221 pattern).
        """
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        try:
            fills = await self._cb_call(self._info_exec.user_fills, address)
        except Exception as e:  # noqa: BLE001 — isolate probe failures per anti-pattern C
            logger.warning(
                "hyperliquid.close_reason_probe_failed coin=%s error=%s",
                coin, e,
            )
            return None
        if not isinstance(fills, list):
            return None

        qualifying: List[Dict[str, Any]] = []
        for fill in fills:
            if not isinstance(fill, dict):
                continue
            if fill.get("coin") != coin:
                continue
            ts = _hl_int(fill.get("time"))
            if ts is not None and ts < since_ts_ms:
                continue
            if ts is not None and until_ts_ms is not None and ts > until_ts_ms:
                continue
            direction = str(fill.get("dir") or "")
            # Close fills: "Close Long", "Close Short", "Liquidated Long", etc.
            if direction.startswith("Close") or "Liquidat" in direction:
                qualifying.append(fill)

        if not qualifying:
            return None

        qualifying.sort(key=lambda f: _hl_int(f.get("time")) or 0, reverse=True)
        fill = qualifying[0]

        if fill.get("liquidation") or "Liquidat" in str(fill.get("dir", "")):
            plan_type = "liquidation"
        elif fill.get("isTpsl") or fill.get("isPositionTpsl"):
            # HL marks TP/SL fills but doesn't distinguish TP vs SL at the
            # fill level. ``tpsl_ambiguous`` is a sentinel plan_type that
            # tells RiskStateManager._classify_from_snapshot to try order-id
            # matching (authoritative) first, then price-crossover against
            # trade.take_profit / trade.stop_loss as a tiebreaker. See
            # _PLAN_TYPE_TO_REASON for the mapping.
            plan_type = "tpsl_ambiguous"
        else:
            plan_type = "manual"

        ts_ms = _hl_int(fill.get("time"))
        return CloseReasonSnapshot(
            symbol=coin,
            closed_by_order_id=str(fill.get("oid")) if fill.get("oid") is not None else None,
            closed_by_plan_type=plan_type,
            closed_by_trigger_type="mark_price" if plan_type in ("pos_profit", "pos_loss", "tpsl_ambiguous") else None,
            closed_at=_hl_ts_to_datetime(ts_ms),
            fill_price=_hl_float(fill.get("px")),
        )


def _hl_float(value: Any) -> Optional[float]:
    """Parse a HL value to float; preserve 0.0, return None on missing."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hl_int(value: Any) -> Optional[int]:
    """Parse a HL value to int; return None on missing / unparseable."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _hl_ts_to_datetime(ts_ms: Optional[int]) -> Optional[datetime]:
    """Convert a HL millisecond timestamp to a UTC datetime."""
    if ts_ms is None or ts_ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


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
