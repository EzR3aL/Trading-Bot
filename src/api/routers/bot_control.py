"""Bot control endpoints (start/stop/mode per user)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.bot import BotModeRequest, BotStartRequest, BotStatusResponse
from src.auth.dependencies import get_current_user
from src.exchanges.factory import create_exchange_client
from src.models.database import TradeRecord, User, UserConfig
from src.models.session import get_db
from src.utils.encryption import decrypt_value
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
    """Start the trading bot for the current user."""
    manager = _get_bot_manager()
    success = await manager.start_bot(
        user_id=user.id,
        exchange_type=request.exchange_type,
        preset_id=request.preset_id,
        demo_mode=request.demo_mode,
        db=db,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start bot")
    return {"status": "ok", "message": "Bot started"}


@router.post("/stop")
async def stop_bot(
    user: User = Depends(get_current_user),
):
    """Stop the trading bot for the current user."""
    manager = _get_bot_manager()
    success = await manager.stop_bot(user.id)
    if not success:
        raise HTTPException(status_code=400, detail="Bot is not running")
    return {"status": "ok", "message": "Bot stopped"}


@router.get("/status", response_model=BotStatusResponse)
async def get_bot_status(
    user: User = Depends(get_current_user),
):
    """Get bot status for the current user."""
    manager = _get_bot_manager()
    status = manager.get_status(user.id)
    return BotStatusResponse(**status)


@router.post("/mode")
async def set_bot_mode(
    request: BotModeRequest,
    user: User = Depends(get_current_user),
):
    """Switch between demo and live mode."""
    manager = _get_bot_manager()
    is_running = manager.is_running(user.id)

    if is_running:
        # Stop, switch mode, restart
        await manager.stop_bot(user.id)

    return {
        "status": "ok",
        "demo_mode": request.demo_mode,
        "message": f"Mode set to {'demo' if request.demo_mode else 'live'}. "
                   f"{'Bot was stopped - restart with new mode.' if is_running else ''}",
    }


@router.post("/test-trade")
async def open_test_trade(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Open a small test trade in demo mode on the configured exchange."""

    # Get user config
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=400, detail="No config found. Set up API keys first.")

    # Get API credentials (prefer demo keys, fall back to regular)
    if config.demo_api_key_encrypted:
        api_key = decrypt_value(config.demo_api_key_encrypted)
        api_secret = decrypt_value(config.demo_api_secret_encrypted)
        passphrase = decrypt_value(config.demo_passphrase_encrypted) if config.demo_passphrase_encrypted else ""
    elif config.api_key_encrypted:
        api_key = decrypt_value(config.api_key_encrypted)
        api_secret = decrypt_value(config.api_secret_encrypted)
        passphrase = decrypt_value(config.passphrase_encrypted) if config.passphrase_encrypted else ""
    else:
        raise HTTPException(status_code=400, detail="No API keys configured.")

    exchange_type = config.exchange_type or "bitget"

    # Create exchange client in DEMO mode
    client = create_exchange_client(
        exchange_type=exchange_type,
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        demo_mode=True,
    )

    try:
        # Get current price
        ticker = await client.get_ticker("BTCUSDT")
        price = ticker.last_price
        if price <= 0:
            raise HTTPException(status_code=502, detail="Could not get current BTC price")

        # Get balance
        balance = await client.get_account_balance()
        logger.info(f"Test trade: Balance={balance.available} USDT, BTC price={price}")

        # Calculate small position: ~50 USDT notional with 4x leverage
        leverage = 4
        notional = 50.0  # 50 USDT worth
        size = round(notional / price, 6)
        if size < 0.001:
            size = 0.001  # Bitget minimum for BTC

        # Place demo market order (long)
        # Bitget requires prices as multiples of 0.1 for BTCUSDT
        tp = float(f"{round(price * 1.02, 1):.1f}")  # +2% take profit
        sl = float(f"{round(price * 0.99, 1):.1f}")  # -1% stop loss

        order = await client.place_market_order(
            symbol="BTCUSDT",
            side="long",
            size=size,
            leverage=leverage,
            take_profit=tp,
            stop_loss=sl,
        )

        # Get fill price
        fill_price = price
        if hasattr(client, 'get_fill_price') and order.order_id:
            actual = await client.get_fill_price("BTCUSDT", order.order_id)
            if actual:
                fill_price = actual

        # Send Discord notification
        from src.notifications.discord_notifier import DiscordNotifier
        if config.discord_webhook_url:
            notifier = DiscordNotifier(webhook_url=config.discord_webhook_url)
            try:
                await notifier.send_trade_entry(
                    symbol="BTCUSDT",
                    side="long",
                    size=size,
                    entry_price=fill_price,
                    leverage=leverage,
                    take_profit=tp,
                    stop_loss=sl,
                    confidence=75,
                    reason="Test trade via API",
                    order_id=order.order_id,
                    demo_mode=True,
                )
            except Exception as e:
                logger.warning(f"Discord notification failed: {e}")
            finally:
                await notifier.close()

        # Record in database
        trade = TradeRecord(
            user_id=user.id,
            exchange=exchange_type,
            symbol="BTCUSDT",
            side="long",
            size=size,
            entry_price=fill_price,
            take_profit=tp,
            stop_loss=sl,
            leverage=leverage,
            confidence=75,
            reason="Test trade via API",
            order_id=order.order_id,
            status="open",
            entry_time=datetime.utcnow(),
        )
        db.add(trade)
        await db.flush()
        await db.refresh(trade)

        logger.info(f"Test trade opened: {order.order_id} @ {fill_price}")

        return {
            "status": "ok",
            "message": f"Demo test trade opened: BTCUSDT Long",
            "trade": {
                "id": trade.id,
                "order_id": order.order_id,
                "symbol": "BTCUSDT",
                "side": "long",
                "size": size,
                "entry_price": fill_price,
                "leverage": leverage,
                "take_profit": tp,
                "stop_loss": sl,
                "exchange": exchange_type,
                "demo_mode": True,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test trade failed: {e}")
        raise HTTPException(status_code=500, detail=f"Test trade failed: {str(e)}")
    finally:
        await client.close()


async def _get_exchange_client(config: UserConfig, demo_mode: bool = True):
    """Create exchange client from user config."""
    if config.demo_api_key_encrypted:
        api_key = decrypt_value(config.demo_api_key_encrypted)
        api_secret = decrypt_value(config.demo_api_secret_encrypted)
        passphrase = decrypt_value(config.demo_passphrase_encrypted) if config.demo_passphrase_encrypted else ""
    elif config.api_key_encrypted:
        api_key = decrypt_value(config.api_key_encrypted)
        api_secret = decrypt_value(config.api_secret_encrypted)
        passphrase = decrypt_value(config.passphrase_encrypted) if config.passphrase_encrypted else ""
    else:
        return None

    return create_exchange_client(
        exchange_type=config.exchange_type or "bitget",
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

    # Get trade
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

    # Get user config for exchange credentials + discord
    cfg_result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user.id)
    )
    config = cfg_result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=400, detail="No config found")

    client = await _get_exchange_client(config, demo_mode=True)
    if not client:
        raise HTTPException(status_code=400, detail="No API keys configured")

    try:
        # Close the position on the exchange
        close_order = await client.close_position(trade.symbol, trade.side)

        # Get exit price
        exit_price = None
        if close_order and close_order.order_id:
            if hasattr(client, 'get_fill_price'):
                exit_price = await client.get_fill_price(trade.symbol, close_order.order_id)

        if not exit_price:
            ticker = await client.get_ticker(trade.symbol)
            exit_price = ticker.last_price

        # Calculate PnL
        if trade.side == "long":
            pnl = (exit_price - trade.entry_price) * trade.size
        else:
            pnl = (trade.entry_price - exit_price) * trade.size

        pnl_percent = (pnl / (trade.entry_price * trade.size)) * 100
        fees = trade.fees or 0
        funding_paid = trade.funding_paid or 0

        # Determine exit reason
        if abs(exit_price - trade.take_profit) < trade.entry_price * 0.001:
            exit_reason = "TAKE_PROFIT"
        elif abs(exit_price - trade.stop_loss) < trade.entry_price * 0.001:
            exit_reason = "STOP_LOSS"
        else:
            exit_reason = "MANUAL_CLOSE"

        # Calculate duration
        duration_minutes = None
        if trade.entry_time:
            duration = datetime.utcnow() - trade.entry_time
            duration_minutes = int(duration.total_seconds() / 60)

        # Update trade in database
        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.pnl_percent = pnl_percent
        trade.exit_time = datetime.utcnow()
        trade.exit_reason = exit_reason
        trade.close_order_id = close_order.order_id if close_order else "manual"
        trade.status = "closed"
        await db.flush()

        # Send Discord close notification with strategy reason
        from src.notifications.discord_notifier import DiscordNotifier
        if config.discord_webhook_url:
            notifier = DiscordNotifier(webhook_url=config.discord_webhook_url)
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
                    demo_mode=True,
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
