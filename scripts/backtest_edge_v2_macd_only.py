"""
Backtest: Edge Indicator v2 (MACD Floor, kein Default SL).

Testet den aktuellen Edge Indicator mit MACD Floor aber OHNE Default SL.
20 Coins x 3 Timeframes (15m, 1h, 4h), 90 Tage, $10k.

Vergleich: v1-Zahlen aus dem vorherigen Lauf.
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
    "AAVEUSDT", "UNIUSDT", "MKRUSDT", "SNXUSDT", "COMPUSDT",
    "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT",
]

TIMEFRAMES = ["15m", "1h", "4h"]
DAYS = 90
CAPITAL = 10_000


def fmt(m):
    sh = m["sharpe_ratio"]
    sh_str = f'{sh:.2f}' if sh else "N/A"
    return (
        f'{m["total_return_percent"]:+7.1f}% | '
        f'{m["win_rate"]:5.1f}% | '
        f'{m["max_drawdown_percent"]:5.1f}% | '
        f'{sh_str:>6s} | '
        f'{m["total_trades"]:5d} | '
        f'{m["profit_factor"]:5.2f}'
    )


HDR = (
    f'{"Symbol":>12s} | '
    f'{"Return":>8s} | {"Win%":>6s} | {"MaxDD":>6s} | '
    f'{"Sharpe":>6s} | {"Trd":>5s} | {"PF":>6s}'
)


async def main():
    end = datetime.now()
    start = end - timedelta(days=DAYS)

    print("=" * 80)
    print(f"  EDGE INDICATOR v2 (MACD Floor, kein Default SL)")
    print(f"  20 Coins x 3 TFs, {DAYS}d, ${CAPITAL:,}")
    print(f"  {start.strftime('%Y-%m-%d')} bis {end.strftime('%Y-%m-%d')}")
    print("=" * 80)

    results = {}

    for tf in TIMEFRAMES:
        print(f"\n{'=' * 80}")
        print(f"  {tf}")
        print(f"{'=' * 80}")
        print(HDR)
        print("-" * 80)

        for symbol in SYMBOLS:
            try:
                r = await run_backtest_for_strategy(
                    "edge_indicator", symbol, tf, start, end, CAPITAL
                )
                m = r["metrics"]
                print(f'{symbol:>12s} | {fmt(m)}')
                results[(symbol, tf)] = m
            except Exception as e:
                print(f'{symbol:>12s} | ERROR: {e}')
                results[(symbol, tf)] = None

    # Summary per TF
    print(f"\n\n{'=' * 80}")
    print("  ZUSAMMENFASSUNG")
    print(f"{'=' * 80}")

    for tf in TIMEFRAMES:
        rets = []
        sharpes = []
        dds = []
        profitable = 0

        for symbol in SYMBOLS:
            m = results.get((symbol, tf))
            if not m:
                continue
            rets.append(m["total_return_percent"])
            sharpes.append(m["sharpe_ratio"] or 0)
            dds.append(m["max_drawdown_percent"])
            if m["total_return_percent"] > 0:
                profitable += 1

        n = len(rets)
        if n == 0:
            continue

        print(f"\n  {tf}: {profitable}/{n} profitabel")
        print(f"    Avg Return: {sum(rets)/n:+.1f}%  |  Avg Sharpe: {sum(sharpes)/n:.2f}  |  Avg MaxDD: {sum(dds)/n:.1f}%")

    # Best coins per TF
    print(f"\n\n{'=' * 80}")
    print("  BESTE COINS (Sharpe > 0.5, profitabel)")
    print(f"{'=' * 80}")

    for tf in TIMEFRAMES:
        good = []
        for symbol in SYMBOLS:
            m = results.get((symbol, tf))
            if m and m["total_return_percent"] > 0 and (m["sharpe_ratio"] or 0) >= 0.5:
                good.append((symbol, m["total_return_percent"], m["sharpe_ratio"] or 0, m["max_drawdown_percent"], m["win_rate"]))

        good.sort(key=lambda x: x[2], reverse=True)

        print(f"\n  {tf} ({len(good)} Coins mit Sharpe >= 0.5):")
        if not good:
            print("    Keine")
        for sym, ret, sh, dd, wr in good:
            print(f"    {sym:<12s}  {ret:>+7.1f}%  Sharpe {sh:>5.2f}  MaxDD {dd:>5.1f}%  WR {wr:.0f}%")

    print(f"\n{'=' * 80}\n")


if __name__ == "__main__":
    asyncio.run(main())
