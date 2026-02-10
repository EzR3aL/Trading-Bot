"""Bot control endpoints (start/stop/mode per user, per exchange)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.bot import (
    BotModeRequest,
    BotStartRequest,
    BotStatusResponse,
    BotStopRequest,
    MultiBotStatusResponse,
    TestTradeRequest,
)
from src.auth.dependencies import get_current_user
from src.exchanges.factory import create_exchange_client
from src.models.database import ExchangeConnection, TradeRecord, User, UserConfig
from src.models.session import get_db
from src.strategy.base import StrategyRegistry
from src.utils.encryption import decrypt_value, encrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/bot", tags=["bot"])

# BotManager will be injected at app startup
_bot_manager = None


def set_bot_manager(manager):
    """Set the bot manager instance (called during app initialization)."""
    global _bot_manager
    _bot_manager = manager


def _get_bot_manager():
    if _bot_manager is None:
        raise HTTPException(status_code=503, detail="Bot manager not initialized")
    return _bot_manager


@router.post("/start")
async def start_bot(
    request: BotStartRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start the trading bot on a specific exchange."""
    manager = _get_bot_manager()
    try:
        success = await manager.start_bot(
            user_id=user.id,
            exchange_type=request.exchange_type,
            preset_id=request.preset_id,
            demo_mode=request.demo_mode,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start bot")
    return {"status": "ok", "message": f"Bot started on {request.exchange_type}"}


@router.post("/stop")
async def stop_bot(
    request: BotStopRequest,
    user: User = Depends(get_current_user),
):
    """Stop the trading bot on a specific exchange."""
    manager = _get_bot_manager()
    success = await manager.stop_bot(user.id, request.exchange_type)
    if not success:
        raise HTTPException(status_code=400, detail=f"Bot is not running on {request.exchange_type}")
    return {"status": "ok", "message": f"Bot stopped on {request.exchange_type}"}


@router.post("/stop-all")
async def stop_all_bots(
    user: User = Depends(get_current_user),
):
    """Stop all running bots for the current user."""
    manager = _get_bot_manager()
    stopped = await manager.stop_all_for_user(user.id)
    return {"status": "ok", "message": f"{stopped} bot(s) stopped"}


@router.get("/status", response_model=MultiBotStatusResponse)
async def get_bot_status(
    user: User = Depends(get_current_user),
):
    """Get bot status for all exchanges."""
    manager = _get_bot_manager()
    statuses = manager.get_status(user.id)
    return MultiBotStatusResponse(
        bots=[BotStatusResponse(**s) for s in statuses]
    )


@router.post("/mode")
async def set_bot_mode(
    request: BotModeRequest,
    user: User = Depends(get_current_user),
):
    """Switch between demo and live mode for a specific exchange."""
    manager = _get_bot_manager()
    is_running = manager.is_running(user.id, request.exchange_type)

    if is_running:
        await manager.stop_bot(user.id, request.exchange_type)

    return {
        "status": "ok",
        "exchange_type": request.exchange_type,
        "demo_mode": request.demo_mode,
        "message": f"Mode set to {'demo' if request.demo_mode else 'live'} for {request.exchange_type}. "
                   f"{'Bot was stopped - restart with new mode.' if is_running else ''}",
    }


@router.post("/test-trade")
async def open_test_trade(
    body: TestTradeRequest = TestTradeRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Open a test trade in demo mode using a real strategy signal."""
    # Get user config for discord + general settings
    cfg_result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user.id)
    )
    config = cfg_result.scalar_one_or_none()

    # Find first exchange connection with demo keys
    result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user.id)
    )
    connections = result.scalars().all()

    conn = None
    for c in connections:
        if c.demo_api_key_encrypted:
            conn = c
            break

    if not conn:
        raise HTTPException(
            status_code=400,
            detail="No demo API keys configured on any exchange. Set up demo keys in Settings first.",
        )

    api_key = decrypt_value(conn.demo_api_key_encrypted)
    api_secret = decrypt_value(conn.demo_api_secret_encrypted)
    passphrase = decrypt_value(conn.demo_passphrase_encrypted) if conn.demo_passphrase_encrypted else ""
    exchange_type = conn.exchange_type

    client = create_exchange_client(
        exchange_type=exchange_type,
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        demo_mode=True,
    )

    try:
        # Hyperliquid uses coin names (BTC), others use pairs (BTCUSDT)
        trade_symbol = "BTC" if exchange_type == "hyperliquid" else "BTCUSDT"
        db_symbol = "BTCUSDC" if exchange_type == "hyperliquid" else "BTCUSDT"

        ticker = await client.get_ticker(trade_symbol)
        price = ticker.last_price
        if price <= 0:
            raise HTTPException(status_code=502, detail="Could not get current BTC price")

        balance = await client.get_account_balance()
        logger.info(f"Test trade: Balance={balance.available} {balance.currency}, BTC price={price}")

        # Generate real strategy signal to determine direction
        strategy_name = body.strategy or "liquidation_hunter"
        available = StrategyRegistry.list_available()
        valid_names = [s["name"] for s in available]
        if strategy_name not in valid_names:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown strategy '{strategy_name}'. Available: {', '.join(valid_names)}",
            )
        try:
            strategy = StrategyRegistry.create(strategy_name)
            signal = await strategy.generate_signal(trade_symbol)
            side = signal.direction.value  # "long" or "short"
            confidence = signal.confidence
            reason = signal.reason
            tp = signal.target_price
            sl = signal.stop_loss
            logger.info(f"Test trade signal: {side} (confidence={confidence}, reason={reason})")
            await strategy.close()
        except Exception as e:
            logger.warning(f"Strategy signal failed ({e}), falling back to market data")
            # Fallback: use price momentum (24h change)
            side = "long"
            confidence = 50
            reason = "Fallback: strategy unavailable"
            tp = float(f"{round(price * 1.02, 1):.1f}")
            sl = float(f"{round(price * 0.99, 1):.1f}")

        leverage = 4
        notional = 50.0
        size = round(notional / price, 6)
        if size < 0.001:
            size = 0.001

        # Ensure TP/SL are on correct side for the direction
        if side == "short":
            if tp >= price:
                tp = float(f"{round(price * 0.98, 1):.1f}")
            if sl <= price:
                sl = float(f"{round(price * 1.01, 1):.1f}")
        else:
            if tp <= price:
                tp = float(f"{round(price * 1.02, 1):.1f}")
            if sl >= price:
                sl = float(f"{round(price * 0.99, 1):.1f}")

        order = await client.place_market_order(
            symbol=trade_symbol,
            side=side,
            size=size,
            leverage=leverage,
            take_profit=tp,
            stop_loss=sl,
        )

        fill_price = order.price if order.price > 0 else price
        if order.order_id:
            try:
                actual = await client.get_fill_price(trade_symbol, order.order_id)
                if actual:
                    fill_price = actual
            except Exception as e:
                logger.warning(f"Failed to get fill price for {trade_symbol} order {order.order_id}: {e}")

        # Send Discord notification
        if config and config.discord_webhook_url:
            try:
                webhook_url = decrypt_value(config.discord_webhook_url)
            except (ValueError, Exception) as e:
                logger.warning(f"Failed to decrypt Discord webhook URL: {e}")
                webhook_url = None

            if webhook_url:
                from src.notifications.discord_notifier import DiscordNotifier
                notifier = DiscordNotifier(webhook_url=webhook_url)
                try:
                    await notifier.send_trade_entry(
                        symbol=db_symbol,
                        side=side,
                        size=size,
                        entry_price=fill_price,
                        leverage=leverage,
                        take_profit=tp,
                        stop_loss=sl,
                        confidence=confidence,
                        reason=reason,
                        order_id=order.order_id,
                        demo_mode=True,
                    )
                except Exception as e:
                    logger.warning(f"Discord notification failed: {e}")
                finally:
                    await notifier.close()

        side_label = side.capitalize()
        trade = TradeRecord(
            user_id=user.id,
            exchange=exchange_type,
            symbol=db_symbol,
            side=side,
            size=size,
            entry_price=fill_price,
            take_profit=tp,
            stop_loss=sl,
            leverage=leverage,
            confidence=confidence,
            reason=reason,
            order_id=order.order_id,
            status="open",
            entry_time=datetime.utcnow(),
            demo_mode=True,
        )
        db.add(trade)
        await db.flush()
        await db.refresh(trade)

        logger.info(f"Test trade opened: {side} {order.order_id} @ {fill_price}")

        return {
            "status": "ok",
            "message": f"Demo test trade opened: {db_symbol} {side_label} on {exchange_type}",
            "trade": {
                "id": trade.id,
                "order_id": order.order_id,
                "symbol": db_symbol,
                "side": side,
                "size": size,
                "entry_price": fill_price,
                "leverage": leverage,
                "take_profit": tp,
                "stop_loss": sl,
                "exchange": exchange_type,
                "demo_mode": True,
                "confidence": confidence,
                "reason": reason,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test trade failed: {e}")
        raise HTTPException(status_code=500, detail=f"Test trade failed: {str(e)}")
    finally:
        await client.close()


async def _get_exchange_client_for_trade(trade: TradeRecord, user_id: int, db: AsyncSession):
    """Create exchange client from ExchangeConnection matching the trade's exchange."""
    result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user_id,
            ExchangeConnection.exchange_type == trade.exchange,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return None

    # Use demo keys if available, otherwise live
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
        return None

    return create_exchange_client(
        exchange_type=trade.exchange,
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        demo_mode=demo_mode,
    )


@router.post("/close-trade/{trade_id}")
async def close_trade(
    trade_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Close an open trade and send Discord notification with strategy details."""
    result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.id == trade_id,
            TradeRecord.user_id == user.id,
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade.status != "open":
        raise HTTPException(status_code=400, detail=f"Trade is already {trade.status}")

    # Get exchange client from ExchangeConnection
    client = await _get_exchange_client_for_trade(trade, user.id, db)
    if not client:
        raise HTTPException(status_code=400, detail=f"No API keys configured for {trade.exchange}")

    # Get user config for discord webhook
    cfg_result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user.id)
    )
    config = cfg_result.scalar_one_or_none()

    try:
        close_order = await client.close_position(trade.symbol, trade.side)

        exit_price = None
        if close_order and close_order.price and close_order.price > 0:
            exit_price = close_order.price
        elif close_order and close_order.order_id:
            try:
                exit_price = await client.get_fill_price(trade.symbol, close_order.order_id)
            except Exception as e:
                logger.warning(f"Failed to get fill price for close order {close_order.order_id}: {e}")

        if not exit_price:
            ticker = await client.get_ticker(trade.symbol)
            exit_price = ticker.last_price

        if trade.side == "long":
            pnl = (exit_price - trade.entry_price) * trade.size
        else:
            pnl = (trade.entry_price - exit_price) * trade.size

        pnl_percent = (pnl / (trade.entry_price * trade.size)) * 100
        fees = trade.fees or 0
        funding_paid = trade.funding_paid or 0

        if abs(exit_price - trade.take_profit) < trade.entry_price * 0.001:
            exit_reason = "TAKE_PROFIT"
        elif abs(exit_price - trade.stop_loss) < trade.entry_price * 0.001:
            exit_reason = "STOP_LOSS"
        else:
            exit_reason = "MANUAL_CLOSE"

        duration_minutes = None
        if trade.entry_time:
            duration = datetime.utcnow() - trade.entry_time
            duration_minutes = int(duration.total_seconds() / 60)

        # Fetch trading fees from exchange (entry + exit)
        try:
            close_oid = close_order.order_id if close_order and close_order.order_id else None
            trade.fees = await client.get_trade_total_fees(
                symbol=trade.symbol,
                entry_order_id=trade.order_id or "",
                close_order_id=close_oid,
            )
        except Exception:
            trade.fees = 0

        # Fetch funding fees (charged every 8h while position was open)
        try:
            if trade.entry_time:
                entry_ms = int(trade.entry_time.timestamp() * 1000)
                exit_ms = int(datetime.utcnow().timestamp() * 1000)
                trade.funding_paid = await client.get_funding_fees(
                    symbol=trade.symbol,
                    start_time_ms=entry_ms,
                    end_time_ms=exit_ms,
                )
        except Exception:
            trade.funding_paid = 0

        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.pnl_percent = pnl_percent
        trade.exit_time = datetime.utcnow()
        trade.exit_reason = exit_reason
        trade.close_order_id = close_order.order_id if close_order else "manual"
        trade.status = "closed"
        await db.flush()

        if config and config.discord_webhook_url:
            try:
                close_webhook_url = decrypt_value(config.discord_webhook_url)
            except (ValueError, Exception) as e:
                logger.warning(f"Failed to decrypt Discord webhook URL for trade close: {e}")
                close_webhook_url = None

            if close_webhook_url:
                from src.notifications.discord_notifier import DiscordNotifier
                notifier = DiscordNotifier(webhook_url=close_webhook_url)
                try:
                    await notifier.send_trade_exit(
                        symbol=trade.symbol,
                        side=trade.side,
                        size=trade.size,
                        entry_price=trade.entry_price,
                        exit_price=exit_price,
                        pnl=pnl,
                        pnl_percent=pnl_percent,
                        fees=fees,
                        funding_paid=funding_paid,
                        reason=exit_reason,
                        order_id=trade.order_id,
                        duration_minutes=duration_minutes,
                        demo_mode=trade.demo_mode,
                        strategy_reason=trade.reason,
                    )
                except Exception as e:
                    logger.warning(f"Discord close notification failed: {e}")
                finally:
                    await notifier.close()

        logger.info(f"Trade #{trade.id} closed: {exit_reason} | PnL: ${pnl:.2f} ({pnl_percent:+.2f}%)")

        return {
            "status": "ok",
            "message": f"Trade closed: {trade.symbol} {trade.side.upper()} - {exit_reason}",
            "trade": {
                "id": trade.id,
                "symbol": trade.symbol,
                "side": trade.side,
                "entry_price": trade.entry_price,
                "exit_price": exit_price,
                "pnl": round(pnl, 2),
                "pnl_percent": round(pnl_percent, 2),
                "exit_reason": exit_reason,
                "duration_minutes": duration_minutes,
                "strategy_reason": trade.reason,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Close trade failed: {e}")
        raise HTTPException(status_code=500, detail=f"Close trade failed: {str(e)}")
    finally:
        await client.close()
