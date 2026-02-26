"""Run comprehensive multi-timeframe backtest with improved engine."""
import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.strategy_adapter import run_backtest_for_strategy


def fmt(m):
    sh = m["sharpe_ratio"]
    return (
        f'{m["total_return_percent"]:+7.1f}% | '
        f'{m["win_rate"]:5.1f}% | '
        f'{m["max_drawdown_percent"]:5.1f}% | '
        f'{str(sh) if sh else "N/A":>7s} | '
        f'{m["total_trades"]:6d} | '
        f'{m["profit_factor"]:5.2f}'
    )


HDR = f'{"":>30s} | {"Return":>8s} | {"Win%":>6s} | {"DD%":>6s} | {"Sharpe":>7s} | {"Trades":>6s} | {"PF":>6s}'


async def main():
    end = datetime.now()
    start = end - timedelta(days=90)

    print("=" * 90)
    print("EDGE INDICATOR — Timeframe Comparison (90 days, BTCUSDT, $10k)")
    print("=" * 90)
    print(HDR)
    print("-" * 90)
    for tf in ["15m", "30m", "1h", "4h", "1d"]:
        try:
            r = await run_backtest_for_strategy("edge_indicator", "BTCUSDT", tf, start, end, 10000)
            print(f'{tf:>30s} | {fmt(r["metrics"])}')
        except Exception as e:
            print(f'{tf:>30s} | ERROR: {e}')

    print()
    print("=" * 90)
    print("EDGE INDICATOR — Parameter Variations")
    print("=" * 90)
    print(HDR)
    print("-" * 90)
    variations = [
        ("1h", "1h Conservative", {"take_profit_percent": 2.0, "stop_loss_percent": 1.0, "leverage": 2}),
        ("1h", "1h Balanced (default)", {}),
        ("1h", "1h Aggressive", {"take_profit_percent": 5.0, "stop_loss_percent": 2.5, "leverage": 5}),
        ("1h", "1h More Trades", {"max_trades_per_day": 5, "low_confidence_min": 45}),
        ("4h", "4h Conservative", {"take_profit_percent": 2.0, "stop_loss_percent": 1.0, "leverage": 2}),
        ("4h", "4h Balanced", {"take_profit_percent": 3.5, "stop_loss_percent": 2.0}),
        ("4h", "4h Aggressive", {"take_profit_percent": 6.0, "stop_loss_percent": 3.0, "leverage": 5}),
    ]
    for tf, label, params in variations:
        try:
            r = await run_backtest_for_strategy("edge_indicator", "BTCUSDT", tf, start, end, 10000, params)
            print(f'{label:>30s} | {fmt(r["metrics"])}')
        except Exception as e:
            print(f'{label:>30s} | ERROR: {e}')

    print()
    print("=" * 90)
    print("ALL STRATEGIES — Comparison (1h, default params)")
    print("=" * 90)
    print(HDR)
    print("-" * 90)
    for strat in ["edge_indicator", "sentiment_surfer", "liquidation_hunter", "degen", "llm_signal"]:
        try:
            r = await run_backtest_for_strategy(strat, "BTCUSDT", "1h", start, end, 10000)
            print(f'{strat:>30s} | {fmt(r["metrics"])}')
        except Exception as e:
            print(f'{strat:>30s} | ERROR: {e}')


if __name__ == "__main__":
    asyncio.run(main())
