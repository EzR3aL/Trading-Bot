"""Copy-trading specific endpoints: source-wallet validation + leverage limits."""

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.auth.dependencies import get_current_user
from src.exchanges.hyperliquid.wallet_tracker import HyperliquidWalletTracker
from src.exchanges.leverage_limits import ExchangeNotSupported, get_max_leverage
from src.exchanges.symbol_fetcher import get_exchange_symbols
from src.exchanges.symbol_map import to_exchange_symbol
from src.models.database import User
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["copy-trading"])

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
LOOKBACK_DAYS = 30


class ValidateSourceRequest(BaseModel):
    wallet: str
    target_exchange: str


class ValidateSourceResponse(BaseModel):
    valid: bool
    wallet_label: str
    trades_30d: int
    available: list[str]
    unavailable: list[str]
    warning: str | None = None


@router.post("/copy-trading/validate-source", response_model=ValidateSourceResponse)
async def validate_source(
    body: ValidateSourceRequest,
    user: User = Depends(get_current_user),
):
    """Validate a Hyperliquid source wallet for copy-trading."""

    # 1. Format check
    if not WALLET_RE.match(body.wallet):
        raise HTTPException(
            status_code=400,
            detail="Ungültige Wallet-Adresse — erwartet wird 0x gefolgt von 40 Hex-Zeichen.",
        )

    tracker = HyperliquidWalletTracker()
    try:
        # 2. Existence check
        positions = await tracker.get_open_positions(body.wallet)

        # 3. Activity check — fills in the last 30d
        since_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000
        )
        fills = await tracker.get_fills_since(body.wallet, since_ms)
        if not fills and not positions:
            raise HTTPException(
                status_code=404,
                detail="Wallet hat in den letzten 30 Tagen keine Trading-Aktivität. "
                       "Copy-Trading benötigt eine aktive Source-Wallet.",
            )

        # 4. Symbol availability preview
        try:
            target_symbols_raw = await get_exchange_symbols(body.target_exchange, demo_mode=False)
        except Exception as e:
            logger.warning("Failed to fetch %s symbols: %s", body.target_exchange, e)
            target_symbols_raw = []
        target_symbols = {s.upper() for s in target_symbols_raw}

        seen_coins = sorted({f.coin for f in fills} | {p.coin for p in positions})
        available: list[str] = []
        unavailable: list[str] = []
        for coin in seen_coins:
            try:
                target_sym = to_exchange_symbol(coin, body.target_exchange)
            except Exception:
                target_sym = None
            if target_sym and target_sym.upper() in target_symbols:
                available.append(coin)
            else:
                unavailable.append(coin)

        if not available:
            raise HTTPException(
                status_code=400,
                detail=f"Keines der zuletzt von dieser Wallet gehandelten Symbole "
                       f"ist auf {body.target_exchange} verfügbar — Bot würde nichts kopieren können.",
            )

        warning = None
        if unavailable:
            warning = (
                f"{len(unavailable)} von {len(seen_coins)} zuletzt gehandelten "
                f"Symbolen sind nicht auf {body.target_exchange} verfügbar und werden übersprungen."
            )

        return ValidateSourceResponse(
            valid=True,
            wallet_label=body.wallet[:6] + "…" + body.wallet[-4:],
            trades_30d=len(fills),
            available=available,
            unavailable=unavailable,
            warning=warning,
        )
    finally:
        close = getattr(tracker, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001
                pass


class LeverageLimitsResponse(BaseModel):
    exchange: str
    symbol: str
    max_leverage: int


@router.get("/exchanges/{exchange}/leverage-limits", response_model=LeverageLimitsResponse)
async def leverage_limits(
    exchange: str,
    symbol: str = Query(...),
    user: User = Depends(get_current_user),
):
    try:
        max_lev = get_max_leverage(exchange, symbol)
    except ExchangeNotSupported as e:
        raise HTTPException(status_code=404, detail=str(e))
    return LeverageLimitsResponse(exchange=exchange, symbol=symbol, max_leverage=max_lev)
