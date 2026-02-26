"""Analyze EMA Ribbon state around the time Bot #11's SHORT was closed."""
import asyncio
import sys
sys.path.insert(0, "/app")

from src.data.market_data import MarketDataFetcher

def ema(data, period):
    k = 2 / (period + 1)
    result = [data[0]]
    for i in range(1, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result

async def analyze():
    f = MarketDataFetcher()
    klines = await f.get_binance_klines("BTCUSDT", "1h", 200)
    closes = [float(k[4]) for k in klines]
    times = [k[0] for k in klines]  # open time ms

    ema8 = ema(closes, 8)
    ema21 = ema(closes, 21)

    # ATR for context
    atr_series = MarketDataFetcher.calculate_atr(klines, 14)

    print("=" * 90)
    print("  EMA RIBBON ANALYSIS — BTCUSDT 1h (last 24 hours)")
    print("=" * 90)

    header = f"{'Hr':>4} {'Close':>10} {'EMA(8)':>10} {'EMA(21)':>10} {'Band':>8} {'Dist':>8} {'Status':>12}"
    print(header)
    print("-" * 90)

    flips = 0
    prev_status = None
    for i in range(-24, 0):
        c = closes[i]
        e8 = ema8[i]
        e21 = ema21[i]
        upper = max(e8, e21)
        lower = min(e8, e21)
        band = upper - lower
        dist_to_upper = c - upper

        if c > upper:
            status = "BULL"
        elif c < lower:
            status = "BEAR"
        else:
            status = "NEUTRAL"

        if prev_status and status != prev_status:
            flips += 1
            marker = " <-- FLIP"
        else:
            marker = ""

        prev_status = status

        print(f"{i:>4} ${c:>9.1f} ${e8:>9.1f} ${e21:>9.1f} ${band:>7.1f} ${dist_to_upper:>7.1f}  {status:>8}{marker}")

    print(f"\n  Status flips in 24h: {flips}")

    # Current ATR
    atr = atr_series[-1] if atr_series else closes[-1] * 0.015
    print(f"\n  ATR(14): ${atr:,.1f}")

    # Show how tiny the band is vs ATR
    c = closes[-1]
    e8 = ema8[-1]
    e21 = ema21[-1]
    band = abs(e8 - e21)
    print(f"  Band width: ${band:,.1f}")
    print(f"  Band as % of ATR: {band/atr*100:.1f}%")
    print(f"  Band as % of price: {band/c*100:.4f}%")

    # How much price movement needed to flip from BEAR to BULL?
    upper = max(e8, e21)
    lower = min(e8, e21)
    print(f"\n  To flip BEAR -> BULL: close must move from <${lower:,.1f} to >${upper:,.1f}")
    print(f"  That's a ${upper - lower:,.1f} move (${band:,.1f} band)")
    print(f"  Typical 1h candle range (ATR/24): ~${atr:,.1f}")
    print(f"  -> A single 1h candle can easily cross the entire band")

    # Entry price context
    entry = 68031.7
    exit_price = 68180.4
    print(f"\n  Bot #11 context:")
    print(f"  Entry: ${entry:,.1f}  Exit: ${exit_price:,.1f}")
    print(f"  Price moved ${exit_price - entry:,.1f} against SHORT")
    print(f"  That's {(exit_price - entry)/atr*100:.1f}% of one ATR")

    await f.close()

asyncio.run(analyze())
