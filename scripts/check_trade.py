"""Detailed analysis: when would Bot #11's open SHORT be closed?"""
import asyncio
import sys
sys.path.insert(0, "/app")

from src.exchanges.factory import create_exchange_client
from src.models.session import get_session
from src.utils.encryption import decrypt_value
from src.data.market_data import MarketDataFetcher
from src.strategy.edge_indicator import EdgeIndicatorStrategy, DEFAULTS

async def check():
    from sqlalchemy import text

    # Get client
    async with get_session() as session:
        result = await session.execute(text(
            "SELECT demo_api_key_encrypted, demo_api_secret_encrypted, "
            "demo_passphrase_encrypted FROM exchange_connections "
            "WHERE exchange_type = 'bitget' LIMIT 1"
        ))
        row = result.fetchone()

    client = create_exchange_client(
        exchange_type="bitget",
        api_key=decrypt_value(row[0]),
        api_secret=decrypt_value(row[1]),
        passphrase=decrypt_value(row[2]) if row[2] else "",
        demo_mode=True,
    )
    await client._ensure_session()

    # Current state
    ticker = await client.get_ticker("BTCUSDT")
    pos = await client.get_position("BTCUSDT")
    current_price = ticker.last_price

    print("=" * 60)
    print("  TRADE ANALYSIS — Bot #11 SHORT BTCUSDT")
    print("=" * 60)

    entry_price = 68031.7
    lowest_price = 67842.9  # highest_price field (tracks lowest for SHORT)

    if pos:
        print(f"\n  Position: {pos.side} {pos.size} BTC")
        print(f"  Entry:    ${entry_price:,.2f}")
        print(f"  Current:  ${current_price:,.2f}")
        print(f"  Lowest:   ${lowest_price:,.2f}")
        pnl_pct = (entry_price - current_price) / entry_price * 100
        print(f"  PnL:      ${pos.unrealized_pnl:,.2f} ({pnl_pct:+.3f}%)")

    # Update lowest if current is lower
    if current_price < lowest_price:
        lowest_price = current_price
        print(f"  [Updated lowest to ${lowest_price:,.2f}]")

    # Strategy analysis
    strategy = EdgeIndicatorStrategy(params=None)

    # Fetch klines
    fetcher = MarketDataFetcher()
    klines = await fetcher.get_binance_klines("BTCUSDT", "1h", 200)
    closes = [float(k[4]) for k in klines]

    # ATR
    atr_series = MarketDataFetcher.calculate_atr(klines, DEFAULTS["atr_period"])
    atr_val = atr_series[-1] if atr_series else current_price * 0.015

    # Trailing stop calc
    breakeven_atr = DEFAULTS["trailing_breakeven_atr"]  # 1.5
    trail_atr = DEFAULTS["trailing_trail_atr"]           # 2.5
    trail_distance = atr_val * trail_atr
    breakeven_threshold = atr_val * breakeven_atr

    print(f"\n--- Layer 1: Trailing Stop ---")
    print(f"  ATR(14): ${atr_val:,.2f}")
    print(f"  Trail distance: ATR * {trail_atr} = ${trail_distance:,.2f}")
    print(f"  Breakeven threshold: ATR * {breakeven_atr} = ${breakeven_threshold:,.2f}")

    profit_from_lowest = entry_price - lowest_price
    was_profitable = profit_from_lowest >= breakeven_threshold
    print(f"  Profit from lowest: ${profit_from_lowest:,.2f}")
    print(f"  Was profitable enough for trailing: {was_profitable}")

    if was_profitable:
        trailing_stop = lowest_price + trail_distance
        trailing_stop = min(trailing_stop, entry_price)  # cap at entry
        print(f"  Trailing stop price: ${trailing_stop:,.2f}")
        print(f"  Current vs stop: ${current_price:,.2f} vs ${trailing_stop:,.2f}")
        if current_price >= trailing_stop:
            print(f"  >>> TRAILING STOP WOULD TRIGGER NOW <<<")
        else:
            distance_to_stop = trailing_stop - current_price
            print(f"  Distance to stop: ${distance_to_stop:,.2f} ({distance_to_stop/current_price*100:.3f}%)")
    else:
        needed = breakeven_threshold - profit_from_lowest
        price_needed = entry_price - breakeven_threshold
        print(f"  Trailing NOT active yet. Need ${needed:,.2f} more profit")
        print(f"  Price must drop to ~${price_needed:,.2f} to activate trailing")

    # Indicator analysis
    ribbon = strategy._calculate_ema_ribbon(closes)
    momentum = strategy._calculate_predator_momentum(closes, klines, ribbon["ema_fast_above"])

    print(f"\n--- Layer 2: Indicator Exit ---")
    print(f"  EMA Ribbon:")
    print(f"    bull_trend={ribbon['bull_trend']}  bear_trend={ribbon['bear_trend']}  neutral={ribbon['neutral']}")
    print(f"    EMA fast > slow: {ribbon['ema_fast_above']}")
    print(f"  Momentum:")
    raw = momentum.get('raw_score', 'N/A')
    print(f"    Raw score: {raw:.4f}" if isinstance(raw, (int, float)) else f"    Raw score: {raw}")
    print(f"    Smoothed score: {momentum['smoothed_score']:.4f}")
    print(f"    Regime: {momentum.get('regime', 'N/A')} (1=bull, -1=bear, 0=neutral)")
    print(f"    regime_flip_bull: {momentum.get('regime_flip_bull', False)}")
    print(f"    regime_flip_bear: {momentum.get('regime_flip_bear', False)}")
    print(f"  Thresholds:")
    print(f"    Bull threshold: {DEFAULTS['momentum_bull_threshold']}")
    print(f"    Bear threshold: {DEFAULTS['momentum_bear_threshold']}")

    # SHORT exit conditions
    print(f"\n--- SHORT Exit Triggers ---")
    would_exit = False

    if ribbon["bull_trend"]:
        print(f"  [YES] EMA bull_trend — price above ribbon")
        would_exit = True
    else:
        print(f"  [NO]  EMA bull_trend=False — price NOT above ribbon")

    if ribbon["neutral"] and momentum.get("regime") == 1:
        print(f"  [YES] Neutral ribbon + bullish momentum")
        would_exit = True
    else:
        print(f"  [NO]  Neutral+bull combo not met (neutral={ribbon['neutral']}, regime={momentum.get('regime')})")

    if momentum.get("regime_flip_bull"):
        print(f"  [YES] Regime flip to bull (score={momentum['smoothed_score']:.4f} > {DEFAULTS['momentum_bull_threshold']})")
        would_exit = True
    else:
        distance = DEFAULTS['momentum_bull_threshold'] - momentum['smoothed_score']
        print(f"  [NO]  No regime flip (score={momentum['smoothed_score']:.4f}, need >{DEFAULTS['momentum_bull_threshold']}, gap={distance:.4f})")

    # Run actual should_exit
    should_close, reason = await strategy.should_exit(
        symbol="BTCUSDT",
        side="short",
        entry_price=entry_price,
        metrics_at_entry={"adx": 27.24},
        current_price=current_price,
        highest_price=lowest_price,
    )

    print(f"\n{'='*60}")
    print(f"  VERDICT: should_exit = {should_close}")
    if reason:
        print(f"  Reason: {reason}")
    else:
        print(f"  Trade stays open — no exit condition met")
    print(f"{'='*60}")

    await fetcher.close()
    await client.close()

asyncio.run(check())
