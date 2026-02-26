"""
Backtest: Edge Indicator auf 20 Altcoins.

Test: 20 Coins x 1h TF, 90 Tage, $10k.
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.strategy_adapter import run_backtest_for_strategy


SYMBOLS = [
    # Top Coins
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "MATICUSDT",
    "DOTUSDT",
    # DeFi / Mid-Caps
    "AAVEUSDT",
    "UNIUSDT",
    "MKRUSDT",
    "SNXUSDT",
    "COMPUSDT",
    # L1 / L2
    "NEARUSDT",
    "APTUSDT",
    "ARBUSDT",
    "OPUSDT",
    "SUIUSDT",
]

STRATEGIES = ["edge_indicator"]
TIMEFRAME = "1h"
DAYS = 90
CAPITAL = 10_000


def fmt(m):
    sh = m["sharpe_ratio"]
    sh_str = f'{sh:.2f}' if sh else "N/A"
    return (
        f'{m["total_return_percent"]:+8.1f}% | '
        f'{m["win_rate"]:5.1f}% | '
        f'{m["max_drawdown_percent"]:6.1f}% | '
        f'{sh_str:>7s} | '
        f'{m["total_trades"]:6d} | '
        f'{m["profit_factor"]:6.2f}'
    )


HDR = (
    f'{"Symbol":>12s} | {"Strategie":>25s} | '
    f'{"Return":>9s} | {"Win%":>6s} | {"MaxDD%":>7s} | '
    f'{"Sharpe":>7s} | {"Trades":>6s} | {"PF":>7s}'
)
SEP = "-" * 100


async def main():
    end = datetime.now()
    start = end - timedelta(days=DAYS)

    print("=" * 100)
    print(f"  ALTCOIN BACKTEST — Edge Indicator — 20 Coins")
    print(f"  {TIMEFRAME}, {DAYS} Tage, ${CAPITAL:,} — {start.strftime('%Y-%m-%d')} bis {end.strftime('%Y-%m-%d')}")
    print("=" * 100)
    print(HDR)
    print(SEP)

    results = {}

    for symbol in SYMBOLS:
        for strat in STRATEGIES:
            try:
                r = await run_backtest_for_strategy(
                    strat, symbol, TIMEFRAME, start, end, CAPITAL
                )
                m = r["metrics"]
                print(f'{symbol:>12s} | {strat:>25s} | {fmt(m)}')
                results[(symbol, strat)] = m
            except Exception as e:
                print(f'{symbol:>12s} | {strat:>25s} | ERROR: {e}')
                results[(symbol, strat)] = None
        print(SEP)

    # Summary
    print(f"\n{'=' * 100}")
    print("  ZUSAMMENFASSUNG: Edge Indicator Altcoin Performance")
    print(f"{'=' * 100}")

    edge_returns = [results[(s, "edge_indicator")]["total_return_percent"]
                    for s in SYMBOLS if results.get((s, "edge_indicator"))]
    edge_sharpes = [results[(s, "edge_indicator")]["sharpe_ratio"] or 0
                    for s in SYMBOLS if results.get((s, "edge_indicator"))]
    edge_dds = [results[(s, "edge_indicator")]["max_drawdown_percent"]
                for s in SYMBOLS if results.get((s, "edge_indicator"))]

    if edge_returns:
        print(f"\n  Durchschnitt:  Return {sum(edge_returns)/len(edge_returns):+.1f}%  |  Sharpe {sum(edge_sharpes)/len(edge_sharpes):.2f}  |  MaxDD {sum(edge_dds)/len(edge_dds):.1f}%")

    # Profitable coins
    print(f"\n{'=' * 100}")
    print("  PROFITABEL: Welche Coins sind profitabel?")
    print(f"{'=' * 100}")

    edge_profitable = []
    for symbol in SYMBOLS:
        e = results.get((symbol, "edge_indicator"))
        if e and e["total_return_percent"] > 0:
            edge_profitable.append((symbol, e["total_return_percent"], e["sharpe_ratio"] or 0))

    edge_profitable.sort(key=lambda x: x[2], reverse=True)

    print(f"\n  Edge Indicator — profitabel auf {len(edge_profitable)}/{len(SYMBOLS)} Coins:")
    for sym, ret, sh in edge_profitable:
        print(f"    {sym:<12s}  {ret:>+7.1f}%  Sharpe {sh:.2f}")

    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    asyncio.run(main())
