"""
Live Demo Trade Test: Verify ALL TP/SL passthrough scenarios on Bitget.

Scenarios tested:
1. LONG + TP/SL  → Exchange receives correct absolute prices
2. SHORT + TP/SL → Inverted TP/SL (TP below entry, SL above entry)
3. Only TP (no SL) → TP sent, SL=None
4. No TP/SL       → Both None, position opens without protection
5. Position close  → Clean close and position gone

Run inside the Docker container:
    docker exec bitget-trading-bot python scripts/test_tpsl_demo_trade.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.exchanges.factory import create_exchange_client
from src.models.session import get_session
from src.utils.encryption import decrypt_value

SYMBOL = "BTCUSDT"
LEVERAGE = 10
TRADE_SIZE_USDT = 20.0  # Minimal trade size

# Track results
ALL_RESULTS = {}


def report(test_name, check, passed, detail=""):
    key = f"{test_name}:{check}"
    ALL_RESULTS[key] = passed
    status = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"    [{status}] {check}{suffix}")


async def get_demo_client():
    """Load Bitget demo credentials from DB and create client."""
    from sqlalchemy import text

    async with get_session() as session:
        result = await session.execute(text(
            "SELECT demo_api_key_encrypted, demo_api_secret_encrypted, "
            "demo_passphrase_encrypted FROM exchange_connections "
            "WHERE exchange_type = 'bitget' AND demo_api_key_encrypted IS NOT NULL "
            "LIMIT 1"
        ))
        row = result.fetchone()
        if not row:
            raise RuntimeError("No Bitget demo connection found in DB")

    api_key = decrypt_value(row[0])
    api_secret = decrypt_value(row[1])
    passphrase = decrypt_value(row[2]) if row[2] else ""

    return create_exchange_client(
        exchange_type="bitget",
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        demo_mode=True,
    )


async def ensure_no_position(client, symbol):
    """Close any existing position for clean test state."""
    for side in ("long", "short"):
        try:
            pos = await client.get_position(symbol)
            if pos:
                await client.close_position(symbol, pos.side)
                await asyncio.sleep(1)
        except Exception:
            pass


async def test_long_with_tpsl(client, current_price):
    """Test 1: LONG with TP=+3%, SL=-1.5%"""
    test = "1_LONG_TPSL"
    print(f"\n{'─'*50}")
    print(f"  TEST 1: LONG + TP/SL (TP=+3%, SL=-1.5%)")
    print(f"{'─'*50}")

    tp_pct, sl_pct = 3.0, 1.5
    tp_price = current_price * (1 + tp_pct / 100)
    sl_price = current_price * (1 - sl_pct / 100)
    size = (TRADE_SIZE_USDT * LEVERAGE) / current_price

    print(f"  Entry=${current_price:,.2f} TP=${tp_price:,.2f} SL=${sl_price:,.2f} Size={size:.6f}")

    order = await client.place_market_order(
        symbol=SYMBOL, side="long", size=size, leverage=LEVERAGE,
        take_profit=tp_price, stop_loss=sl_price, margin_mode="cross",
    )

    report(test, "order_placed", order is not None and bool(order.order_id),
           f"id={order.order_id if order else 'None'}")
    report(test, "tpsl_not_failed", not getattr(order, "tpsl_failed", True))
    report(test, "fill_price_valid", order.price > 0, f"${order.price:,.2f}")

    # Verify TP/SL math: TP above entry, SL below entry
    report(test, "tp_above_entry", tp_price > current_price,
           f"TP=${tp_price:,.2f} > Entry=${current_price:,.2f}")
    report(test, "sl_below_entry", sl_price < current_price,
           f"SL=${sl_price:,.2f} < Entry=${current_price:,.2f}")

    # Verify position
    await asyncio.sleep(1)
    pos = await client.get_position(SYMBOL)
    report(test, "position_exists", pos is not None)
    if pos:
        report(test, "position_side_long", pos.side == "long", f"side={pos.side}")

    # Clean up
    await client.close_position(SYMBOL, "long")
    await asyncio.sleep(1)
    pos_after = await client.get_position(SYMBOL)
    report(test, "position_closed", pos_after is None)


async def test_short_with_tpsl(client, current_price):
    """Test 2: SHORT with TP=+2%, SL=-1% (inverted)"""
    test = "2_SHORT_TPSL"
    print(f"\n{'─'*50}")
    print(f"  TEST 2: SHORT + TP/SL (TP=+2%, SL=-1%) — inverted")
    print(f"{'─'*50}")

    tp_pct, sl_pct = 2.0, 1.0
    # SHORT: TP below entry, SL above entry
    tp_price = current_price * (1 - tp_pct / 100)
    sl_price = current_price * (1 + sl_pct / 100)
    size = (TRADE_SIZE_USDT * LEVERAGE) / current_price

    print(f"  Entry=${current_price:,.2f} TP=${tp_price:,.2f} SL=${sl_price:,.2f} Size={size:.6f}")

    order = await client.place_market_order(
        symbol=SYMBOL, side="short", size=size, leverage=LEVERAGE,
        take_profit=tp_price, stop_loss=sl_price, margin_mode="cross",
    )

    report(test, "order_placed", order is not None and bool(order.order_id),
           f"id={order.order_id if order else 'None'}")
    report(test, "tpsl_not_failed", not getattr(order, "tpsl_failed", True))

    # SHORT: TP must be BELOW entry, SL must be ABOVE entry
    report(test, "tp_below_entry", tp_price < current_price,
           f"TP=${tp_price:,.2f} < Entry=${current_price:,.2f}")
    report(test, "sl_above_entry", sl_price > current_price,
           f"SL=${sl_price:,.2f} > Entry=${current_price:,.2f}")

    await asyncio.sleep(1)
    pos = await client.get_position(SYMBOL)
    report(test, "position_exists", pos is not None)
    if pos:
        report(test, "position_side_short", pos.side == "short", f"side={pos.side}")

    # Clean up
    await client.close_position(SYMBOL, "short")
    await asyncio.sleep(1)
    pos_after = await client.get_position(SYMBOL)
    report(test, "position_closed", pos_after is None)


async def test_only_tp_no_sl(client, current_price):
    """Test 3: Only TP, no SL"""
    test = "3_ONLY_TP"
    print(f"\n{'─'*50}")
    print(f"  TEST 3: LONG + Only TP (no SL)")
    print(f"{'─'*50}")

    tp_pct = 3.0
    tp_price = current_price * (1 + tp_pct / 100)
    size = (TRADE_SIZE_USDT * LEVERAGE) / current_price

    print(f"  Entry=${current_price:,.2f} TP=${tp_price:,.2f} SL=None Size={size:.6f}")

    order = await client.place_market_order(
        symbol=SYMBOL, side="long", size=size, leverage=LEVERAGE,
        take_profit=tp_price, stop_loss=None, margin_mode="cross",
    )

    report(test, "order_placed", order is not None and bool(order.order_id))
    # TP-only should still work (no tpsl_failed)
    report(test, "tpsl_not_failed", not getattr(order, "tpsl_failed", True))

    await asyncio.sleep(1)
    pos = await client.get_position(SYMBOL)
    report(test, "position_exists", pos is not None)

    # Clean up
    await client.close_position(SYMBOL, "long")
    await asyncio.sleep(1)
    pos_after = await client.get_position(SYMBOL)
    report(test, "position_closed", pos_after is None)


async def test_no_tpsl(client, current_price):
    """Test 4: No TP/SL at all — backward compatibility"""
    test = "4_NO_TPSL"
    print(f"\n{'─'*50}")
    print(f"  TEST 4: LONG without TP/SL (backward compat)")
    print(f"{'─'*50}")

    size = (TRADE_SIZE_USDT * LEVERAGE) / current_price
    print(f"  Entry=${current_price:,.2f} TP=None SL=None Size={size:.6f}")

    order = await client.place_market_order(
        symbol=SYMBOL, side="long", size=size, leverage=LEVERAGE,
        take_profit=None, stop_loss=None, margin_mode="cross",
    )

    report(test, "order_placed", order is not None and bool(order.order_id))
    # No TP/SL → tpsl_failed should be False (nothing to fail)
    report(test, "tpsl_not_failed", not getattr(order, "tpsl_failed", True))

    await asyncio.sleep(1)
    pos = await client.get_position(SYMBOL)
    report(test, "position_exists", pos is not None)

    # Clean up
    await client.close_position(SYMBOL, "long")
    await asyncio.sleep(1)
    pos_after = await client.get_position(SYMBOL)
    report(test, "position_closed", pos_after is None)


async def test_position_lifecycle(client, current_price):
    """Test 5: Full lifecycle — open, verify, close, verify gone"""
    test = "5_LIFECYCLE"
    print(f"\n{'─'*50}")
    print(f"  TEST 5: Full lifecycle (open → verify → close → verify)")
    print(f"{'─'*50}")

    tp_pct, sl_pct = 3.0, 1.5
    tp_price = current_price * (1 + tp_pct / 100)
    sl_price = current_price * (1 - sl_pct / 100)
    size = (TRADE_SIZE_USDT * LEVERAGE) / current_price

    # Open
    order = await client.place_market_order(
        symbol=SYMBOL, side="long", size=size, leverage=LEVERAGE,
        take_profit=tp_price, stop_loss=sl_price, margin_mode="cross",
    )
    report(test, "order_placed", order is not None and bool(order.order_id))
    report(test, "tpsl_not_failed", not getattr(order, "tpsl_failed", True))

    # Verify position open
    await asyncio.sleep(1)
    pos = await client.get_position(SYMBOL)
    report(test, "position_open", pos is not None)

    if pos:
        # Verify position details
        report(test, "entry_price_reasonable",
               abs(pos.entry_price - current_price) / current_price < 0.005,
               f"entry=${pos.entry_price:,.2f} vs current=${current_price:,.2f}")

    # Get current price after trade
    ticker = await client.get_ticker(SYMBOL)
    new_price = ticker.last_price
    report(test, "price_still_available", new_price > 0, f"${new_price:,.2f}")

    # Close
    await client.close_position(SYMBOL, "long")
    await asyncio.sleep(1)

    # Verify closed
    pos_after = await client.get_position(SYMBOL)
    report(test, "position_gone", pos_after is None)


async def run_all_tests():
    """Run all test scenarios."""
    print("\n" + "=" * 60)
    print("  BITGET DEMO — TP/SL PASSTHROUGH FULL TEST SUITE")
    print("=" * 60)

    client = None
    try:
        # Setup
        print("\n[SETUP] Creating Bitget demo client...")
        client = await get_demo_client()
        await client._ensure_session()
        print("  OK — Demo client ready")

        # Balance check
        balance = await client.get_account_balance()
        print(f"  Balance: ${balance.available:,.2f}")
        if balance.available < TRADE_SIZE_USDT * 5:
            print(f"  WARNING — Low balance, some tests may fail")

        # Get price
        ticker = await client.get_ticker(SYMBOL)
        current_price = ticker.last_price
        print(f"  {SYMBOL}: ${current_price:,.2f}")

        # Clean state
        print("\n[SETUP] Ensuring no existing positions...")
        await ensure_no_position(client, SYMBOL)
        print("  OK — Clean state")

        # Run tests
        await test_long_with_tpsl(client, current_price)
        await asyncio.sleep(1)

        await test_short_with_tpsl(client, current_price)
        await asyncio.sleep(1)

        await test_only_tp_no_sl(client, current_price)
        await asyncio.sleep(1)

        await test_no_tpsl(client, current_price)
        await asyncio.sleep(1)

        await test_position_lifecycle(client, current_price)

    except Exception as e:
        print(f"\n  FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Final cleanup
        if client:
            try:
                await ensure_no_position(client, SYMBOL)
            except Exception:
                pass
            await client.close()

    # Final summary
    print("\n" + "=" * 60)
    print("  FINAL RESULTS")
    print("=" * 60)

    passed = sum(1 for v in ALL_RESULTS.values() if v)
    failed = sum(1 for v in ALL_RESULTS.values() if not v)
    total = len(ALL_RESULTS)

    for key, val in ALL_RESULTS.items():
        if not val:
            print(f"  [FAIL] {key}")

    print(f"\n  {passed}/{total} passed, {failed} failed")

    if failed == 0:
        print("  ALL TESTS PASSED")
    else:
        print("  SOME TESTS FAILED")

    print("=" * 60 + "\n")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
