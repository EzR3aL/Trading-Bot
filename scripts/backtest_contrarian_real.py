"""
Backtest: Contrarian Pulse v2 with REAL historical data.

Data coverage (for >30 day backtests):
- Fear & Greed Index: 98%+ real (Alternative.me)
- Klines (EMA, RSI, Volume): 100% real (Binance Futures)
- Funding Rate: 100% real (Binance Futures)
- L/S Ratio: 0% (Binance only stores 30 days)
- Open Interest: 0% (Binance only stores 30 days)

3/5 confirmation channels have real data.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from src.backtest.strategy_adapter import run_backtest_for_strategy


STRATEGY = "contrarian_pulse"
TIMEFRAMES = ["15m", "30m", "1h", "4h"]
SYMBOL = "BTCUSDT"

END_DATE = datetime(2025, 6, 1)
START_DATE = END_DATE - timedelta(days=90)
INITIAL_CAPITAL = 10000.0

PARAM_SETS = {
    "v2 default": {},
    "v2 1-confirm": {"min_confirmations": 1},
    "v2 2-confirms": {"min_confirmations": 2},
    "v2 wide F&G 35/65": {"fg_extreme_fear": 35, "fg_extreme_greed": 65},
    "v2 TP1.5/SL0.75": {"take_profit_percent": 1.5, "stop_loss_percent": 0.75},
    "v2 TP3.0/SL1.5": {"take_profit_percent": 3.0, "stop_loss_percent": 1.5},
    "v2 aggressive": {
        "fg_extreme_fear": 35,
        "fg_extreme_greed": 65,
        "fg_ultra_fear": 25,
        "fg_ultra_greed": 75,
        "min_confirmations": 1,
    },
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
    print("=" * 110)
    print("  CONTRARIAN PULSE v2 — REAL DATA BACKTEST")
    print(f"  Period: {START_DATE.strftime('%Y-%m-%d')} to {END_DATE.strftime('%Y-%m-%d')} (90 days)")
    print(f"  Capital: ${INITIAL_CAPITAL:,.0f} | Symbol: {SYMBOL}")
    print(f"  Timeframes: {', '.join(TIMEFRAMES)}")
    print(f"  Parameter Variants: {len(PARAM_SETS)}")
    print(f"  Data: REAL (F&G 98%, Klines 100%, Funding 100%, L/S 0%, OI 0%)")
    print("=" * 110)

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

    # Results table
    print(f"\n{'=' * 120}")
    print(f"CONTRARIAN PULSE v2 — REAL DATA ERGEBNISSE")
    print(f"{'=' * 120}")
    header = f"{'Variante':<22} {'TF':>4} | {'Trades':>7} {'Win%':>7} {'Return%':>9} {'MaxDD%':>8} {'PF':>7} {'Sharpe':>7} {'Fees$':>8} {'PnL$':>10}"
    print(header)
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
    print(f"\nData: REAL historical (Alternative.me F&G, Binance Klines+Funding)")
    print(f"Note: L/S Ratio and OI unavailable for >30d backtests (Binance API limit)")
    print(f"Fees: Bitget Standard")


if __name__ == "__main__":
    asyncio.run(main())
