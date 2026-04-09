"""Position reconciliation endpoint: compare exchange positions with DB trades."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.schemas.reconciliation import (
    PhantomTrade,
    ReconciliationResult,
    UntrackedPosition,
)
from src.auth.dependencies import get_current_user
from src.errors import ERR_BOT_NOT_FOUND, ERR_EXCHANGE_CREDENTIALS_MISSING, ERR_NO_EXCHANGE_CONNECTION
from src.models.database import BotConfig, ExchangeConnection, TradeRecord, User
from src.models.session import get_db
from src.utils.logger import get_logger

logger = get_logger(__name__)

reconciliation_router = APIRouter(prefix="/api/bots", tags=["reconciliation"])


def _normalize_symbol(symbol: str) -> str:
    """Normalize a symbol string for comparison across exchange and DB formats.

    Strips whitespace, lowercases, and removes common suffixes like '_umcbl',
    '/usdt:usdt', '-usdt-swap' so that 'BTCUSDT', 'BTC/USDT:USDT', and
    'BTCUSDT_UMCBL' all map to the same canonical form.
    """
    s = symbol.strip().lower()
    # Remove common exchange suffixes
    for suffix in ("_umcbl", ":usdt", "-swap"):
        s = s.replace(suffix, "")
    # Remove separators
    for sep in ("/", "-", "_"):
        s = s.replace(sep, "")
    return s


@reconciliation_router.get("/{bot_id}/reconcile", response_model=ReconciliationResult)
@limiter.limit("10/minute")
async def reconcile_positions(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compare open positions on the exchange with open trades in the database.

    Reports discrepancies:
    - Untracked: positions on exchange with no corresponding DB trade
    - Phantom: DB trades marked open but no matching exchange position
    """
    from src.exchanges.factory import create_exchange_client
    from src.utils.encryption import decrypt_value

    # Load bot config
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    # Load exchange connection
    conn_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == config.exchange_type,
        )
    )
    conn = conn_result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=400, detail=ERR_NO_EXCHANGE_CONNECTION)

    # Determine demo vs live credentials based on bot mode
    is_demo = config.mode in ("demo", "both")
    api_key_enc = conn.demo_api_key_encrypted if is_demo else conn.api_key_encrypted
    api_secret_enc = conn.demo_api_secret_encrypted if is_demo else conn.api_secret_encrypted
    passphrase_enc = conn.demo_passphrase_encrypted if is_demo else conn.passphrase_encrypted

    if not api_key_enc or not api_secret_enc:
        raise HTTPException(status_code=400, detail=ERR_EXCHANGE_CREDENTIALS_MISSING)

    client = create_exchange_client(
        exchange_type=config.exchange_type,
        api_key=decrypt_value(api_key_enc),
        api_secret=decrypt_value(api_secret_enc),
        passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
        demo_mode=is_demo,
    )

    # Fetch exchange positions (with timeout to avoid hanging)
    try:
        exchange_positions = await asyncio.wait_for(
            client.get_open_positions(),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Exchange did not respond in time. Please try again later.",
        )
    except Exception as e:
        logger.error("Reconciliation: failed to fetch positions from %s for bot %d: %s",
                      config.exchange_type, bot_id, e)
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch positions from exchange: {e}",
        )
    finally:
        # Clean up HTTP session
        try:
            await client.close()
        except Exception:
            pass

    # Fetch open trades from DB for this bot
    trades_result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.bot_config_id == bot_id,
            TradeRecord.status == "open",
        )
    )
    db_trades = list(trades_result.scalars().all())

    # Build lookup maps keyed by normalized symbol+side
    exchange_map: dict[str, object] = {}
    for pos in exchange_positions:
        if pos.size <= 0:
            continue
        key = f"{_normalize_symbol(pos.symbol)}:{pos.side.lower()}"
        exchange_map[key] = pos

    db_map: dict[str, TradeRecord] = {}
    for trade in db_trades:
        key = f"{_normalize_symbol(trade.symbol)}:{trade.side.lower()}"
        db_map[key] = trade

    # Compare
    untracked: list[UntrackedPosition] = []
    phantom: list[PhantomTrade] = []
    matched = 0

    # Positions on exchange — check if tracked in DB
    for key, pos in exchange_map.items():
        if key in db_map:
            matched += 1
        else:
            untracked.append(UntrackedPosition(
                symbol=pos.symbol,
                side=pos.side,
                size=pos.size,
                entry_price=pos.entry_price,
                unrealized_pnl=pos.unrealized_pnl,
                leverage=pos.leverage,
            ))

    # Trades in DB — check if present on exchange
    for key, trade in db_map.items():
        if key not in exchange_map:
            phantom.append(PhantomTrade(
                trade_id=trade.id,
                symbol=trade.symbol,
                side=trade.side,
                size=trade.size,
                entry_price=trade.entry_price,
                entry_time=trade.entry_time.isoformat() if trade.entry_time else "",
            ))

    is_consistent = len(untracked) == 0 and len(phantom) == 0

    if not is_consistent:
        logger.warning(
            "Reconciliation: bot %d (%s) has %d untracked, %d phantom positions",
            bot_id, config.name, len(untracked), len(phantom),
        )

    return ReconciliationResult(
        bot_id=bot_id,
        bot_name=config.name,
        exchange=config.exchange_type,
        checked_at=datetime.now(timezone.utc).isoformat(),
        is_consistent=is_consistent,
        untracked_positions=untracked,
        phantom_trades=phantom,
        matched=matched,
    )
