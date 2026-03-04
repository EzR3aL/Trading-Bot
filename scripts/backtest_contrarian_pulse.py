"""
Backtest: Contrarian Pulse Strategy across all timeframes.

Tests the Fear & Greed contrarian scalper on 15m, 30m, 1h, 4h, 1d
with Bitget standard fees.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from src.backtest.strategy_adapter import run_backtest_for_strategy


STRATEGY = "contrarian_pulse"
TIMEFRAMES = ["15m", "30m", "1h", "4h", "1d"]
SYMBOL = "BTCUSDT"

# 90-day backtest
END_DATE = datetime(2025, 6, 1)
START_DATE = END_DATE - timedelta(days=90)
INITIAL_CAPITAL = 10000.0

# Parameter variations to test
PARAM_SETS = {
    "default": {},
    "tight F&G 20/80": {"fg_extreme_fear": 20, "fg_extreme_greed": 80},
    "wide F&G 35/65": {"fg_extreme_fear": 35, "fg_extreme_greed": 65},
    "1 confirm": {"min_confirmations": 1},
    "3 confirms": {"min_confirmations": 3},
    "TP 1.5 / SL 1.0": {"take_profit_percent": 1.5, "stop_loss_percent": 1.0},
    "TP 2.0 / SL 1.0": {"take_profit_percent": 2.0, "stop_loss_percent": 1.0},
    "aggressive L/S": {"lsr_long_max": 1.5, "lsr_short_min": 1.2},
}


async def run_single(timeframe: str, params: dict) -> dict:
    try:
        result = await run_backtest_for_strategy(
            strategy_type=STRATEGY,
            symbol=SYMBOL,
            timeframe=timeframe,
            start_date=START_DATE,
            end_date=END_DATE,
            initial_capital=INITIAL_CAPITAL,
            strategy_params=params,
        )
        return result["metrics"]
    except Exception as e:
        return {"error": str(e)[:120]}


async def main():
    print("=" * 100)
    print(f"  CONTRARIAN PULSE BACKTEST")
    print(f"  Period: {START_DATE.strftime('%Y-%m-%d')} to {END_DATE.strftime('%Y-%m-%d')} (90 days)")
    print(f"  Capital: ${INITIAL_CAPITAL:,.0f} | Symbol: {SYMBOL}")
    print(f"  Timeframes: {', '.join(TIMEFRAMES)}")
    print(f"  Parameter Variants: {len(PARAM_SETS)}")
    print("=" * 100)

    all_results = {}
    total = len(PARAM_SETS) * len(TIMEFRAMES)
    done = 0

    for name, params in PARAM_SETS.items():
        all_results[name] = {}
        for tf in TIMEFRAMES:
            done += 1
            print(f"  [{done}/{total}] {name} @ {tf}...", end=" ", flush=True)
            metrics = await run_single(tf, params)
            all_results[name][tf] = metrics
            if "error" in metrics:
                print(f"ERROR: {metrics['error']}")
            else:
                trades = metrics.get("total_trades", 0)
                ret = metrics.get("total_return_percent", 0)
                wr = metrics.get("win_rate", 0)
                fees = metrics.get("total_fees", 0)
                print(f"{trades} trades, {ret:+.2f}%, WR {wr:.0f}%, fees ${fees:.2f}")

    # Combined overview
    print(f"\n{'=' * 120}")
    print(f"CONTRARIAN PULSE BACKTEST ERGEBNISSE")
    print(f"{'=' * 120}")
    print(f"{'Variante':<22} {'TF':>4} | {'Trades':>7} {'Win%':>7} {'Return%':>9} {'MaxDD%':>8} {'PF':>7} {'Sharpe':>7} {'Fees$':>8} {'PnL$':>10}")
    print("-" * 110)

    best_ret = -999
    best_combo = ""

    for name, tf_results in all_results.items():
        for tf in TIMEFRAMES:
            m = tf_results.get(tf, {})
            if "error" in m:
                print(f"{name:<22} {tf:>4} | ERROR: {m['error'][:60]}")
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
                print(f"{name:<22} {tf:>4} | {trades:>7} {wr:>7.1f} {ret:>+9.2f} {dd:>8.2f} {pf:>7.2f} {sr_str} {fees:>8.2f} {pnl:>+10.2f}")

                if isinstance(ret, (int, float)) and ret > best_ret:
                    best_ret = ret
                    best_combo = f"{name} @ {tf}"
        print("-" * 110)

    print(f"\nBEST RESULT: {best_combo} with {best_ret:+.2f}% return")
    print(f"\nNote: Using mock data + BacktestMarketDataFetcher | Fees: Bitget Standard")


if __name__ == "__main__":
    asyncio.run(main())
