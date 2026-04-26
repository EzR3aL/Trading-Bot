"""Read-side operations for the Hyperliquid client.

Wallet validation, balance, positions, ticker, funding rate. Methods here
expect the host class to expose ``_info``, ``_info_exec``, ``_exchange``,
``wallet_address``, ``_wallet``, ``demo_mode`` and ``_cb_call`` —
everything :class:`HyperliquidClient` already provides.

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

from typing import List, Optional

from src.exchanges.types import Balance, FundingRateInfo, Position, Ticker
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HyperliquidReadMixin:
    """Read-only HL queries used by :class:`HyperliquidClient`."""

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
