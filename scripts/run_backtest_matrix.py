"""
Backtest Performance Matrix — 4 Strategies × 5 Timeframes.

Runs all unified strategies across 15m, 30m, 1h, 4h, 1d
and prints a formatted results table.
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from src.backtest.strategy_adapter import run_backtest_for_strategy


STRATEGIES = ["edge_indicator", "claude_edge_indicator", "sentiment_surfer", "liquidation_hunter"]
TIMEFRAMES = ["15m", "30m", "1h", "4h", "1d"]

# 30-day backtest period
END_DATE = datetime(2025, 1, 15)
START_DATE = END_DATE - timedelta(days=30)
INITIAL_CAPITAL = 10000.0


async def run_single(strategy: str, timeframe: str) -> dict:
    """Run a single backtest and return metrics."""
    try:
        result = await run_backtest_for_strategy(
            strategy_type=strategy,
            symbol="BTCUSDT",
            timeframe=timeframe,
            start_date=START_DATE,
            end_date=END_DATE,
            initial_capital=INITIAL_CAPITAL,
            strategy_params={},
        )
        return result["metrics"]
    except Exception as e:
        return {"error": str(e)}


async def main():
    print(f"Backtest: {START_DATE.strftime('%Y-%m-%d')} bis {END_DATE.strftime('%Y-%m-%d')} | Kapital: ${INITIAL_CAPITAL:,.0f} | Symbol: BTCUSDT")
    print(f"Strategien: {', '.join(STRATEGIES)}")
    print(f"Timeframes: {', '.join(TIMEFRAMES)}")
    print()

    # Collect all results
    results = {}
    total = len(STRATEGIES) * len(TIMEFRAMES)
    done = 0

    for strategy in STRATEGIES:
        results[strategy] = {}
        for tf in TIMEFRAMES:
            done += 1
            print(f"  [{done}/{total}] {strategy} @ {tf}...", end=" ", flush=True)
            metrics = await run_single(strategy, tf)
            results[strategy][tf] = metrics
            if "error" in metrics:
                print(f"ERROR: {metrics['error']}")
            else:
                trades = metrics.get("total_trades", 0)
                ret = metrics.get("total_return_percent", 0)
                print(f"{trades} Trades, {ret:+.2f}%")

    print("\n" + "=" * 120)

    # --- Table 1: Return % ---
    print("\n### Rendite (%) — Total Return")
    print(f"{'Strategie':<25} | {'15m':>10} | {'30m':>10} | {'1h':>10} | {'4h':>10} | {'1d':>10}")
    print("-" * 85)
    for s in STRATEGIES:
        row = f"{s:<25}"
        for tf in TIMEFRAMES:
            m = results[s][tf]
            if "error" in m:
                row += f" | {'ERR':>10}"
            else:
                val = m.get("total_return_percent", 0)
                row += f" | {val:>+10.2f}"
        print(row)

    # --- Table 2: Win Rate ---
    print(f"\n### Win Rate (%)")
    print(f"{'Strategie':<25} | {'15m':>10} | {'30m':>10} | {'1h':>10} | {'4h':>10} | {'1d':>10}")
    print("-" * 85)
    for s in STRATEGIES:
        row = f"{s:<25}"
        for tf in TIMEFRAMES:
            m = results[s][tf]
            if "error" in m:
                row += f" | {'ERR':>10}"
            else:
                val = m.get("win_rate", 0)
                row += f" | {val:>10.1f}"
        print(row)

    # --- Table 3: Trades ---
    print(f"\n### Anzahl Trades")
    print(f"{'Strategie':<25} | {'15m':>10} | {'30m':>10} | {'1h':>10} | {'4h':>10} | {'1d':>10}")
    print("-" * 85)
    for s in STRATEGIES:
        row = f"{s:<25}"
        for tf in TIMEFRAMES:
            m = results[s][tf]
            if "error" in m:
                row += f" | {'ERR':>10}"
            else:
                val = m.get("total_trades", 0)
                row += f" | {val:>10}"
        print(row)

    # --- Table 4: Max Drawdown ---
    print(f"\n### Max Drawdown (%)")
    print(f"{'Strategie':<25} | {'15m':>10} | {'30m':>10} | {'1h':>10} | {'4h':>10} | {'1d':>10}")
    print("-" * 85)
    for s in STRATEGIES:
        row = f"{s:<25}"
        for tf in TIMEFRAMES:
            m = results[s][tf]
            if "error" in m:
                row += f" | {'ERR':>10}"
            else:
                val = m.get("max_drawdown_percent", 0)
                row += f" | {val:>10.2f}"
        print(row)

    # --- Table 5: Profit Factor ---
    print(f"\n### Profit Factor")
    print(f"{'Strategie':<25} | {'15m':>10} | {'30m':>10} | {'1h':>10} | {'4h':>10} | {'1d':>10}")
    print("-" * 85)
    for s in STRATEGIES:
        row = f"{s:<25}"
        for tf in TIMEFRAMES:
            m = results[s][tf]
            if "error" in m:
                row += f" | {'ERR':>10}"
            else:
                val = m.get("profit_factor", 0)
                row += f" | {val:>10.2f}"
        print(row)

    # --- Table 6: Sharpe Ratio ---
    print(f"\n### Sharpe Ratio")
    print(f"{'Strategie':<25} | {'15m':>10} | {'30m':>10} | {'1h':>10} | {'4h':>10} | {'1d':>10}")
    print("-" * 85)
    for s in STRATEGIES:
        row = f"{s:<25}"
        for tf in TIMEFRAMES:
            m = results[s][tf]
            if "error" in m:
                row += f" | {'ERR':>10}"
            else:
                val = m.get("sharpe_ratio")
                if val is None:
                    row += f" | {'N/A':>10}"
                else:
                    row += f" | {val:>10.2f}"
        print(row)

    # --- Table 7: Fees + Funding ---
    print(f"\n### Kosten (Fees + Funding in $)")
    print(f"{'Strategie':<25} | {'15m':>10} | {'30m':>10} | {'1h':>10} | {'4h':>10} | {'1d':>10}")
    print("-" * 85)
    for s in STRATEGIES:
        row = f"{s:<25}"
        for tf in TIMEFRAMES:
            m = results[s][tf]
            if "error" in m:
                row += f" | {'ERR':>10}"
            else:
                fees = m.get("total_fees", 0)
                row += f" | {fees:>10.2f}"
        print(row)

    # --- Combined Overview Table ---
    print(f"\n{'=' * 120}")
    print(f"### ÜBERSICHT: Strategie × Timeframe")
    print(f"{'Strategie':<25} {'TF':>4} | {'Trades':>7} {'Win%':>7} {'Return%':>9} {'MaxDD%':>8} {'PF':>7} {'Sharpe':>7} {'Fees$':>8} {'PnL$':>10}")
    print("-" * 105)
    for s in STRATEGIES:
        for tf in TIMEFRAMES:
            m = results[s][tf]
            if "error" in m:
                print(f"{s:<25} {tf:>4} | ERROR: {m['error'][:60]}")
            else:
                trades = m.get("total_trades", 0)
                wr = m.get("win_rate", 0)
                ret = m.get("total_return_percent", 0)
                dd = m.get("max_drawdown_percent", 0)
                pf = m.get("profit_factor", 0)
                sr = m.get("sharpe_ratio")
                fees = m.get("total_fees", 0)
                pnl = m.get("total_pnl", 0)
                sr_str = f"{sr:>7.2f}" if sr is not None else "    N/A"
                print(f"{s:<25} {tf:>4} | {trades:>7} {wr:>7.1f} {ret:>+9.2f} {dd:>8.2f} {pf:>7.2f} {sr_str} {fees:>8.2f} {pnl:>+10.2f}")
        print("-" * 105)

    print(f"\nDatenquelle: Mock-Daten (seed=42) | ExecutionSimulator: Bitget Standard Tier")


if __name__ == "__main__":
    asyncio.run(main())
