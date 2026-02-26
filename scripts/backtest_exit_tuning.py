"""
A/B Test: Edge Indicator Exit-Tuning.

v1 = aktuelle Defaults (aggressive exits: threshold 0.20, trail 1.5 ATR)
v2 = entschaerfte Exits (threshold 0.35, trail 2.5 ATR, smooth 5)

10 Coins x 3 Timeframes, 90 Tage.
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

# v1: current defaults (no overrides needed)
V1_PARAMS = {}

# v2: relaxed exits (optimized thresholds)
V2_PARAMS = {
    "momentum_bull_threshold": 0.35,
    "momentum_bear_threshold": -0.35,
    "trailing_trail_atr": 2.5,
    "trailing_breakeven_atr": 1.5,
    "momentum_smooth_period": 5,
}


async def main():
    end = datetime.now()
    start = end - timedelta(days=DAYS)

    print("=" * 130)
    print(f"  EXIT-TUNING: Aggressive (v1) vs Relaxed (v2)")
    print(f"  v1: threshold 0.20, trail 1.5 ATR, smooth 3")
    print(f"  v2: threshold 0.35, trail 2.5 ATR, smooth 5")
    print(f"  10 Coins x 3 TFs, {DAYS}d, ${CAPITAL:,}")
    print("=" * 130)

    results = {}

    for tf in TIMEFRAMES:
        print(f"\n{'=' * 130}")
        print(f"  {tf}")
        print(f"{'=' * 130}")
        print(f'{"Symbol":>12s} | {"v1 Ret":>7s} {"v1 WR":>6s} {"v1 DD":>6s} {"v1 Sh":>7s} {"v1 PF":>6s} {"v1 Trd":>6s} | {"v2 Ret":>7s} {"v2 WR":>6s} {"v2 DD":>6s} {"v2 Sh":>7s} {"v2 PF":>6s} {"v2 Trd":>6s} | {"Besser":>6s}')
        print("-" * 130)

        for symbol in SYMBOLS:
            try:
                r1 = await run_backtest_for_strategy(
                    "edge_indicator", symbol, tf, start, end, CAPITAL, V1_PARAMS
                )
                m1 = r1["metrics"]
            except Exception as e:
                print(f'{symbol:>12s} | v1 ERROR: {e}')
                continue

            try:
                r2 = await run_backtest_for_strategy(
                    "edge_indicator", symbol, tf, start, end, CAPITAL, V2_PARAMS
                )
                m2 = r2["metrics"]
            except Exception as e:
                print(f'{symbol:>12s} | v2 ERROR: {e}')
                continue

            results[(symbol, tf, "v1")] = m1
            results[(symbol, tf, "v2")] = m2

            sh1 = m1["sharpe_ratio"] or 0
            sh2 = m2["sharpe_ratio"] or 0
            winner = "v2" if sh2 > sh1 else "v1" if sh1 > sh2 else "="

            print(
                f'{symbol:>12s} | '
                f'{m1["total_return_percent"]:>+6.1f}% {m1["win_rate"]:>5.1f}% {m1["max_drawdown_percent"]:>5.1f}% {sh1:>7.2f} {m1["profit_factor"]:>5.2f} {m1["total_trades"]:>6d} | '
                f'{m2["total_return_percent"]:>+6.1f}% {m2["win_rate"]:>5.1f}% {m2["max_drawdown_percent"]:>5.1f}% {sh2:>7.2f} {m2["profit_factor"]:>5.2f} {m2["total_trades"]:>6d} | '
                f'{winner:>6s}'
            )

    # Summary
    print(f"\n\n{'=' * 130}")
    print("  ZUSAMMENFASSUNG")
    print(f"{'=' * 130}")

    for tf in TIMEFRAMES:
        v1_wins = 0
        v2_wins = 0
        v1_rets = []
        v2_rets = []
        v1_sharpes = []
        v2_sharpes = []
        v1_dds = []
        v2_dds = []
        v1_trades = []
        v2_trades = []

        for symbol in SYMBOLS:
            m1 = results.get((symbol, tf, "v1"))
            m2 = results.get((symbol, tf, "v2"))
            if not m1 or not m2:
                continue

            sh1 = m1["sharpe_ratio"] or 0
            sh2 = m2["sharpe_ratio"] or 0

            v1_rets.append(m1["total_return_percent"])
            v2_rets.append(m2["total_return_percent"])
            v1_sharpes.append(sh1)
            v2_sharpes.append(sh2)
            v1_dds.append(m1["max_drawdown_percent"])
            v2_dds.append(m2["max_drawdown_percent"])
            v1_trades.append(m1["total_trades"])
            v2_trades.append(m2["total_trades"])

            if sh2 > sh1:
                v2_wins += 1
            elif sh1 > sh2:
                v1_wins += 1

        n = len(v1_rets)
        if n == 0:
            continue

        print(f"\n  {tf}: v2 (relaxed) gewinnt {v2_wins}/{n}, v1 (aggressive) gewinnt {v1_wins}/{n}")
        print(f"    v1: Ret {sum(v1_rets)/n:+.1f}%  Sharpe {sum(v1_sharpes)/n:.2f}  MaxDD {sum(v1_dds)/n:.1f}%  Trades {sum(v1_trades)/n:.0f}")
        print(f"    v2: Ret {sum(v2_rets)/n:+.1f}%  Sharpe {sum(v2_sharpes)/n:.2f}  MaxDD {sum(v2_dds)/n:.1f}%  Trades {sum(v2_trades)/n:.0f}")

    print(f"\n{'=' * 130}\n")


if __name__ == "__main__":
    asyncio.run(main())
