"""Trade history endpoints (user-scoped)."""

from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.trade import TradeListResponse, TradeResponse
from src.auth.dependencies import get_current_user
from src.exchanges.factory import create_exchange_client
from src.models.database import ExchangeConnection, TradeRecord, User, UserConfig
from src.models.session import get_db
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=TradeListResponse)
async def list_trades(
    status: Optional[str] = Query(None, pattern="^(open|closed|cancelled)$"),
    symbol: Optional[str] = None,
    exchange: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List trades for the current user with filters."""
    query = select(TradeRecord).where(TradeRecord.user_id == user.id)

    if status:
        query = query.where(TradeRecord.status == status)
    if symbol:
        query = query.where(TradeRecord.symbol == symbol)
    if exchange:
        query = query.where(TradeRecord.exchange == exchange)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(TradeRecord.entry_time.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    trades = result.scalars().all()

    return TradeListResponse(
        trades=[
            TradeResponse(
                id=t.id,
                symbol=t.symbol,
                side=t.side,
                size=t.size,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                take_profit=t.take_profit,
                stop_loss=t.stop_loss,
                leverage=t.leverage,
                confidence=t.confidence,
                reason=t.reason,
                status=t.status,
                pnl=t.pnl,
                pnl_percent=t.pnl_percent,
                fees=t.fees or 0,
                funding_paid=t.funding_paid or 0,
                entry_time=t.entry_time.isoformat() if t.entry_time else "",
                exit_time=t.exit_time.isoformat() if t.exit_time else None,
                exit_reason=t.exit_reason,
                exchange=t.exchange,
                demo_mode=t.demo_mode,
            )
            for t in trades
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/sync")
async def sync_trades(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync open trades with the exchange — close any that no longer exist on the exchange."""
    # 1. Get all open trades
    result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.user_id == user.id,
            TradeRecord.status == "open",
        )
    )
    open_trades = list(result.scalars().all())

    if not open_trades:
        return {"synced": 0, "closed_trades": []}

    # 2. Group trades by exchange
    trades_by_exchange: dict[str, list[TradeRecord]] = defaultdict(list)
    for trade in open_trades:
        trades_by_exchange[trade.exchange].append(trade)

    closed_trades = []

    # 3. Per exchange: check positions
    for exchange_type, trades in trades_by_exchange.items():
        # Get exchange connection
        conn_result = await db.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user.id,
                ExchangeConnection.exchange_type == exchange_type,
            )
        )
        conn = conn_result.scalar_one_or_none()
        if not conn:
            logger.warning(f"Sync: no connection for {exchange_type}, skipping {len(trades)} trades")
            continue

        # Create exchange client (prefer demo keys, then live)
        if conn.demo_api_key_encrypted:
            api_key = decrypt_value(conn.demo_api_key_encrypted)
            api_secret = decrypt_value(conn.demo_api_secret_encrypted)
            passphrase = decrypt_value(conn.demo_passphrase_encrypted) if conn.demo_passphrase_encrypted else ""
            demo_mode = True
        elif conn.api_key_encrypted:
            api_key = decrypt_value(conn.api_key_encrypted)
            api_secret = decrypt_value(conn.api_secret_encrypted)
            passphrase = decrypt_value(conn.passphrase_encrypted) if conn.passphrase_encrypted else ""
            demo_mode = False
        else:
            continue

        client = create_exchange_client(
            exchange_type=exchange_type,
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo_mode=demo_mode,
        )

        try:
            # Get all open positions from exchange
            exchange_positions = await client.get_open_positions()

            # Build set of (symbol, side) tuples for quick lookup
            open_on_exchange = {
                (pos.symbol, pos.side) for pos in exchange_positions
            }

            # Check each trade
            for trade in trades:
                if (trade.symbol, trade.side) in open_on_exchange:
                    continue  # Still open on exchange

                # Position no longer exists — close the trade
                try:
                    # Try to get current price for PnL calculation
                    ticker = await client.get_ticker(trade.symbol)
                    exit_price = ticker.last_price

                    # Determine exit reason from price proximity
                    if trade.take_profit and abs(exit_price - trade.take_profit) < trade.entry_price * 0.005:
                        exit_reason = "TAKE_PROFIT"
                    elif trade.stop_loss and abs(exit_price - trade.stop_loss) < trade.entry_price * 0.005:
                        exit_reason = "STOP_LOSS"
                    else:
                        exit_reason = "MANUAL_CLOSE"

                    # Calculate PnL
                    if trade.side == "long":
                        pnl = (exit_price - trade.entry_price) * trade.size
                    else:
                        pnl = (trade.entry_price - exit_price) * trade.size
                    pnl_percent = (pnl / (trade.entry_price * trade.size)) * 100

                    # Update trade record
                    trade.status = "closed"
                    trade.exit_price = exit_price
                    trade.pnl = round(pnl, 4)
                    trade.pnl_percent = round(pnl_percent, 2)
                    trade.exit_time = datetime.utcnow()
                    trade.exit_reason = exit_reason

                    closed_trades.append({
                        "id": trade.id,
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "exit_price": exit_price,
                        "pnl": round(pnl, 2),
                        "exit_reason": exit_reason,
                    })

                    logger.info(
                        f"Sync: closed trade #{trade.id} {trade.symbol} {trade.side} "
                        f"| {exit_reason} | PnL: ${pnl:.2f} ({pnl_percent:+.2f}%)"
                    )
                except Exception as e:
                    logger.error(f"Sync: failed to close trade #{trade.id}: {e}")

        except Exception as e:
            logger.error(f"Sync: failed to query {exchange_type} positions: {e}")
        finally:
            await client.close()

    await db.flush()

    # Send Discord notifications for closed trades
    if closed_trades:
        cfg_result = await db.execute(
            select(UserConfig).where(UserConfig.user_id == user.id)
        )
        config = cfg_result.scalar_one_or_none()

        if config and config.discord_webhook_url:
            try:
                webhook_url = decrypt_value(config.discord_webhook_url)
            except (ValueError, Exception):
                webhook_url = None

            if webhook_url:
                from src.notifications.discord_notifier import DiscordNotifier
                notifier = DiscordNotifier(webhook_url=webhook_url)
                try:
                    for ct in closed_trades:
                        matching = [t for t in open_trades if t.id == ct["id"]]
                        if not matching:
                            continue
                        trade = matching[0]

                        duration_minutes = None
                        if trade.entry_time:
                            duration = datetime.utcnow() - trade.entry_time
                            duration_minutes = int(duration.total_seconds() / 60)

                        await notifier.send_trade_exit(
                            symbol=trade.symbol,
                            side=trade.side,
                            size=trade.size,
                            entry_price=trade.entry_price,
                            exit_price=trade.exit_price,
                            pnl=trade.pnl,
                            pnl_percent=trade.pnl_percent,
                            fees=trade.fees or 0,
                            funding_paid=trade.funding_paid or 0,
                            reason=trade.exit_reason,
                            order_id=trade.order_id,
                            duration_minutes=duration_minutes,
                            demo_mode=trade.demo_mode,
                            strategy_reason=trade.reason,
                        )
                except Exception as e:
                    logger.warning(f"Discord sync notification failed: {e}")
                finally:
                    await notifier.close()

    return {"synced": len(closed_trades), "closed_trades": closed_trades}


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(
    trade_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific trade."""
    from fastapi import HTTPException

    result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.id == trade_id, TradeRecord.user_id == user.id
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    return TradeResponse(
        id=trade.id,
        symbol=trade.symbol,
        side=trade.side,
        size=trade.size,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        take_profit=trade.take_profit,
        stop_loss=trade.stop_loss,
        leverage=trade.leverage,
        confidence=trade.confidence,
        reason=trade.reason,
        status=trade.status,
        pnl=trade.pnl,
        pnl_percent=trade.pnl_percent,
        fees=trade.fees or 0,
        funding_paid=trade.funding_paid or 0,
        entry_time=trade.entry_time.isoformat() if trade.entry_time else "",
        exit_time=trade.exit_time.isoformat() if trade.exit_time else None,
        exit_reason=trade.exit_reason,
        exchange=trade.exchange,
        demo_mode=trade.demo_mode,
    )
