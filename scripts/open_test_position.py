"""Open a demo BTCUSDT LONG with TP/SL so the user can test frontend risk-state flows.

Usage:
    docker exec bitget-trading-bot python scripts/open_test_position.py
"""
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")

from sqlalchemy import select
from src.models.session import get_session
from src.models.database import ExchangeConnection, User, TradeRecord
from src.exchanges.factory import create_exchange_client
from src.utils.encryption import decrypt_value

SYMBOL = "BTCUSDT"
SIDE = "long"
MARGIN_USDT = 20.0
LEVERAGE = 10
TP_PCT = 2.0
SL_PCT = 1.0


async def main():
    async with get_session() as s:
        user = (await s.execute(select(User).where(User.username == "admin"))).scalar_one()
        conn = (await s.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user.id,
                ExchangeConnection.exchange_type == "bitget",
            )
        )).scalar_one()

        api_key = decrypt_value(conn.demo_api_key_encrypted)
        api_secret = decrypt_value(conn.demo_api_secret_encrypted)
        passphrase = decrypt_value(conn.demo_passphrase_encrypted) if conn.demo_passphrase_encrypted else ""

    client = create_exchange_client(
        exchange_type="bitget",
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        demo_mode=True,
    )

    existing = await client.get_position(SYMBOL)
    if existing:
        print(f"Position already open: {existing.symbol} {existing.side} size={existing.size}")
        return

    ticker = await client.get_ticker(SYMBOL)
    price = ticker.last_price
    tp = round(price * (1 + TP_PCT / 100), 1)
    sl = round(price * (1 - SL_PCT / 100), 1)
    size = round((MARGIN_USDT * LEVERAGE) / price, 6)

    print(f"Opening LONG {SYMBOL} size={size} entry~${price:,.2f} TP=${tp:,.2f} SL=${sl:,.2f}")

    order = await client.place_market_order(
        symbol=SYMBOL, side=SIDE, size=size, leverage=LEVERAGE,
        take_profit=tp, stop_loss=sl, margin_mode="cross",
    )
    print(f"order_id={order.order_id} fill=${order.price} tpsl_failed={getattr(order, 'tpsl_failed', False)}")

    await asyncio.sleep(2)

    tpsl_snapshot = None
    try:
        tpsl_snapshot = await client.get_position_tpsl(symbol=SYMBOL, side=SIDE)
        print(f"readback tpsl: tp_order={tpsl_snapshot.tp_order_id} sl_order={tpsl_snapshot.sl_order_id}")
    except Exception as e:
        print(f"tpsl readback failed: {e}")

    async with get_session() as s:
        tr = TradeRecord(
            user_id=user.id,
            bot_config_id=None,
            exchange="bitget",
            symbol=SYMBOL,
            side=SIDE,
            size=size,
            entry_price=order.price or price,
            take_profit=tp,
            stop_loss=sl,
            leverage=LEVERAGE,
            confidence=0,
            reason="manual-test-position",
            order_id=order.order_id,
            status="open",
            entry_time=datetime.now(timezone.utc),
            demo_mode=True,
            native_trailing_stop=False,
            risk_source="native_exchange",
            tp_intent=tp,
            tp_status="active",
            sl_intent=sl,
            sl_status="active",
            tp_order_id=tpsl_snapshot.tp_order_id if tpsl_snapshot else None,
            sl_order_id=tpsl_snapshot.sl_order_id if tpsl_snapshot else None,
            last_synced_at=datetime.now(timezone.utc),
        )
        s.add(tr)
        await s.commit()
        await s.refresh(tr)
        print(f"\nTrade record #{tr.id} created for admin (user_id={user.id}).")
        print(f"View in frontend: https://bots.trading-department.com/trades")


if __name__ == "__main__":
    asyncio.run(main())
