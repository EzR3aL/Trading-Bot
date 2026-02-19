"""
Backtest Edge Indicator across multiple timeframes and parameter sets.
Generates recommendations for optimal settings.

Usage:
    cd Trading-Bot
    python scripts/backtest_edge_indicator.py
"""

import asyncio
import json
import sys
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.strategy_adapter import run_backtest_for_strategy


async def run_single_backtest(
    timeframe: str,
    params: Dict[str, Any],
    label: str,
    days: int = 90,
    capital: float = 10000.0,
) -> Dict[str, Any]:
    """Run a single backtest and return results with metadata."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    try:
        result = await run_backtest_for_strategy(
            strategy_type="edge_indicator",
            symbol="BTCUSDT",
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_capital=capital,
            strategy_params=params,
        )
        metrics = result["metrics"]
        return {
            "label": label,
            "timeframe": timeframe,
            "params": params,
            "return_pct": metrics["total_return_percent"],
            "win_rate": metrics["win_rate"],
            "max_drawdown": metrics["max_drawdown_percent"],
            "sharpe": metrics["sharpe_ratio"],
            "profit_factor": metrics["profit_factor"],
            "total_trades": metrics["total_trades"],
            "avg_win": metrics["average_win"],
            "avg_loss": metrics["average_loss"],
            "ending_capital": metrics["ending_capital"],
            "success": True,
        }
    except Exception as e:
        return {
            "label": label,
            "timeframe": timeframe,
            "params": params,
            "error": str(e),
            "success": False,
        }


async def main():
    print("=" * 70)
    print("EDGE INDICATOR BACKTEST — 3 Month Analysis")
    print(f"Period: {(datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 70)

    # Test configurations: different timeframes with default params
    timeframe_tests = [
        ("15m", {}, "15min Default"),
        ("30m", {}, "30min Default"),
        ("1h", {}, "1h Default"),
        ("4h", {}, "4h Default"),
        ("1d", {}, "1d Default"),
    ]

    # Parameter variations on 1h timeframe (most common)
    param_tests = [
        ("1h", {"take_profit_percent": 2.0, "stop_loss_percent": 1.0}, "1h Conservative TP/SL"),
        ("1h", {"take_profit_percent": 5.0, "stop_loss_percent": 2.5}, "1h Aggressive TP/SL"),
        ("1h", {"leverage": 5, "take_profit_percent": 3.5, "stop_loss_percent": 2.0}, "1h 5x Leverage"),
        ("1h", {"leverage": 2, "take_profit_percent": 3.5, "stop_loss_percent": 2.0}, "1h 2x Leverage"),
        ("1h", {"max_trades_per_day": 5, "position_size_percent": 8}, "1h More Trades"),
        ("1h", {"max_trades_per_day": 2, "position_size_percent": 15}, "1h Fewer, Bigger"),
    ]

    # Parameter variations on 4h timeframe
    param_tests_4h = [
        ("4h", {"take_profit_percent": 4.0, "stop_loss_percent": 2.0}, "4h Conservative"),
        ("4h", {"take_profit_percent": 6.0, "stop_loss_percent": 3.0}, "4h Aggressive"),
        ("4h", {"leverage": 5}, "4h 5x Leverage"),
        ("4h", {"leverage": 2}, "4h 2x Leverage"),
    ]

    all_tests = timeframe_tests + param_tests + param_tests_4h
    results = []

    print(f"\nRunning {len(all_tests)} backtest configurations...\n")

    for i, (tf, params, label) in enumerate(all_tests):
        print(f"  [{i+1}/{len(all_tests)}] {label} ...", end=" ", flush=True)
        result = await run_single_backtest(tf, params, label)
        results.append(result)
        if result["success"]:
            print(
                f"Return: {result['return_pct']:+.1f}% | "
                f"Win: {result['win_rate']:.0f}% | "
                f"DD: {result['max_drawdown']:.1f}% | "
                f"Sharpe: {result['sharpe'] or 'N/A'} | "
                f"Trades: {result['total_trades']}"
            )
        else:
            print(f"FAILED: {result['error']}")

    # Filter successful results
    ok = [r for r in results if r["success"]]

    if not ok:
        print("\nAll backtests failed! Check data availability.")
        return

    # Sort by different criteria
    by_return = sorted(ok, key=lambda r: r["return_pct"], reverse=True)
    by_sharpe = sorted(ok, key=lambda r: r["sharpe"] or -999, reverse=True)
    by_winrate = sorted(ok, key=lambda r: r["win_rate"], reverse=True)
    by_drawdown = sorted(ok, key=lambda r: r["max_drawdown"])

    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    print("\n--- TOP 5 by Return ---")
    for r in by_return[:5]:
        print(f"  {r['label']:30s} | {r['return_pct']:+7.1f}% | Win {r['win_rate']:5.1f}% | DD {r['max_drawdown']:5.1f}% | Sharpe {r['sharpe'] or 'N/A'}")

    print("\n--- TOP 5 by Sharpe Ratio ---")
    for r in by_sharpe[:5]:
        print(f"  {r['label']:30s} | Sharpe {str(r['sharpe'] or 'N/A'):>6s} | {r['return_pct']:+7.1f}% | Win {r['win_rate']:5.1f}%")

    print("\n--- TOP 5 by Win Rate ---")
    for r in by_winrate[:5]:
        print(f"  {r['label']:30s} | Win {r['win_rate']:5.1f}% | {r['return_pct']:+7.1f}% | Trades {r['total_trades']}")

    print("\n--- Lowest Drawdown ---")
    for r in by_drawdown[:5]:
        print(f"  {r['label']:30s} | DD {r['max_drawdown']:5.1f}% | {r['return_pct']:+7.1f}% | Win {r['win_rate']:5.1f}%")

    # Generate recommendations
    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)

    # Best overall (weighted score: return 40%, sharpe 30%, -drawdown 20%, winrate 10%)
    for r in ok:
        sharpe = r["sharpe"] or 0
        r["composite_score"] = (
            r["return_pct"] * 0.4
            + sharpe * 10 * 0.3
            + (100 - r["max_drawdown"]) * 0.2
            + r["win_rate"] * 0.1
        )

    by_composite = sorted(ok, key=lambda r: r["composite_score"], reverse=True)

    print("\n--- Best Overall (Composite Score) ---")
    best = by_composite[0]
    print(f"  Winner: {best['label']}")
    print(f"  Timeframe: {best['timeframe']}")
    print(f"  Return: {best['return_pct']:+.1f}%")
    print(f"  Win Rate: {best['win_rate']:.1f}%")
    print(f"  Max Drawdown: {best['max_drawdown']:.1f}%")
    print(f"  Sharpe: {best['sharpe'] or 'N/A'}")
    print(f"  Profit Factor: {best['profit_factor']:.2f}")
    if best["params"]:
        print(f"  Custom Params: {best['params']}")

    # Timeframe-only results (default params)
    tf_results = [r for r in ok if not r["params"]]
    if tf_results:
        tf_best = max(tf_results, key=lambda r: r.get("composite_score", 0))
        print(f"\n--- Best Timeframe (Default Params) ---")
        print(f"  Winner: {tf_best['timeframe']}")
        print(f"  Return: {tf_best['return_pct']:+.1f}% | Sharpe: {tf_best['sharpe'] or 'N/A'}")

    # Save results as JSON for frontend consumption
    recommendations = {
        "generated_at": datetime.now().isoformat(),
        "period_days": 90,
        "strategy": "edge_indicator",
        "symbol": "BTCUSDT",
        "total_configs_tested": len(ok),
        "best_overall": {
            "timeframe": best["timeframe"],
            "return_pct": best["return_pct"],
            "win_rate": best["win_rate"],
            "max_drawdown": best["max_drawdown"],
            "sharpe": best["sharpe"],
            "profit_factor": best["profit_factor"],
            "total_trades": best["total_trades"],
            "params": best["params"],
        },
        "timeframe_ranking": [
            {
                "timeframe": r["timeframe"],
                "label": r["label"],
                "return_pct": r["return_pct"],
                "win_rate": r["win_rate"],
                "max_drawdown": r["max_drawdown"],
                "sharpe": r["sharpe"],
                "profit_factor": r["profit_factor"],
                "total_trades": r["total_trades"],
                "composite_score": round(r["composite_score"], 1),
            }
            for r in by_composite
        ],
        "all_results": [
            {k: v for k, v in r.items() if k != "composite_score"}
            for r in ok
        ],
    }

    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "backtest", "edge_indicator_recommendations.json"
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(recommendations, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
