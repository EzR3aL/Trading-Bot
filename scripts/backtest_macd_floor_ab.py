"""
A/B Test: Edge Indicator v1 (kein MACD Floor) vs v2 (mit MACD Floor).

Isoliert den Effekt des MACD Floors — kein Default SL bei beiden.
10 Coins x 3 Timeframes, 90 Tage, $10k.
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.strategy_adapter import run_backtest_for_strategy


SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT", "DOTUSDT",
]

TIMEFRAMES = ["15m", "1h", "4h"]
DAYS = 90
CAPITAL = 10_000


async def main():
    end = datetime.now()
    start = end - timedelta(days=DAYS)

    print("=" * 130)
    print(f"  A/B TEST: MACD Floor Effekt (kein Default SL bei beiden)")
    print(f"  v1 = use_macd_floor=False  |  v2 = use_macd_floor=True")
    print(f"  10 Coins x 3 TFs, {DAYS}d, ${CAPITAL:,}")
    print("=" * 130)

    results = {}

    for tf in TIMEFRAMES:
        print(f"\n{'=' * 130}")
        print(f"  {tf}")
        print(f"{'=' * 130}")
        print(f'{"Symbol":>12s} | {"v1 Return":>9s} {"v1 WR":>6s} {"v1 DD":>6s} {"v1 Sh":>7s} {"v1 PF":>6s} | {"v2 Return":>9s} {"v2 WR":>6s} {"v2 DD":>6s} {"v2 Sh":>7s} {"v2 PF":>6s} | {"Delta":>7s}')
        print("-" * 130)

        for symbol in SYMBOLS:
            m1 = None
            m2 = None

            try:
                r1 = await run_backtest_for_strategy(
                    "edge_indicator", symbol, tf, start, end, CAPITAL,
                    {"use_macd_floor": False, "default_sl_atr": 0}
                )
                m1 = r1["metrics"]
            except Exception as e:
                print(f'{symbol:>12s} | v1 ERROR: {e}')
                continue

            try:
                r2 = await run_backtest_for_strategy(
                    "edge_indicator", symbol, tf, start, end, CAPITAL,
                    {"use_macd_floor": True, "default_sl_atr": 0}
                )
                m2 = r2["metrics"]
            except Exception as e:
                print(f'{symbol:>12s} | v2 ERROR: {e}')
                continue

            results[(symbol, tf, "v1")] = m1
            results[(symbol, tf, "v2")] = m2

            sh1 = m1["sharpe_ratio"] or 0
            sh2 = m2["sharpe_ratio"] or 0
            delta = sh2 - sh1

            print(
                f'{symbol:>12s} | '
                f'{m1["total_return_percent"]:>+8.1f}% {m1["win_rate"]:>5.1f}% {m1["max_drawdown_percent"]:>5.1f}% {sh1:>7.2f} {m1["profit_factor"]:>5.2f} | '
                f'{m2["total_return_percent"]:>+8.1f}% {m2["win_rate"]:>5.1f}% {m2["max_drawdown_percent"]:>5.1f}% {sh2:>7.2f} {m2["profit_factor"]:>5.2f} | '
                f'{delta:>+7.2f}'
            )

    # Summary
    print(f"\n\n{'=' * 130}")
    print("  ZUSAMMENFASSUNG PRO TIMEFRAME")
    print(f"{'=' * 130}")

    for tf in TIMEFRAMES:
        v2_better = 0
        v1_better = 0
        same = 0
        deltas = []

        for symbol in SYMBOLS:
            m1 = results.get((symbol, tf, "v1"))
            m2 = results.get((symbol, tf, "v2"))
            if not m1 or not m2:
                continue

            sh1 = m1["sharpe_ratio"] or 0
            sh2 = m2["sharpe_ratio"] or 0
            d = sh2 - sh1
            deltas.append(d)

            if abs(d) < 0.01:
                same += 1
            elif d > 0:
                v2_better += 1
            else:
                v1_better += 1

        n = len(deltas)
        if n == 0:
            continue

        avg_delta = sum(deltas) / n
        print(f"\n  {tf}:")
        print(f"    v2 besser: {v2_better}/{n}  |  v1 besser: {v1_better}/{n}  |  gleich: {same}/{n}")
        print(f"    Avg Sharpe Delta: {avg_delta:+.3f}")

    print(f"\n{'=' * 130}\n")


if __name__ == "__main__":
    asyncio.run(main())
