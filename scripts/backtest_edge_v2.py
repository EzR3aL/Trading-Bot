"""
Backtest: Edge Indicator v1 vs v2 (+ Default SL + MACD Floor).

v1 = default_sl_atr=0 (alte Logik, kein Default SL, kein MACD Floor)
v2 = default_sl_atr=2.0 (neues Sicherheitsnetz + MACD Floor ist immer aktiv)

20 Coins x 3 Timeframes (15m, 1h, 4h), 90 Tage, $10k.
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


def fmt_short(m):
    sh = m["sharpe_ratio"]
    sh_str = f'{sh:.2f}' if sh else "N/A"
    return f'{m["total_return_percent"]:+7.1f}% | {m["win_rate"]:5.1f}% | {m["max_drawdown_percent"]:5.1f}% | {sh_str:>6s} | {m["profit_factor"]:5.2f}'


async def main():
    end = datetime.now()
    start = end - timedelta(days=DAYS)

    print("=" * 120)
    print(f"  EDGE INDICATOR v1 vs v2 — 20 Coins x 3 Timeframes")
    print(f"  v1 = kein Default SL (alt)  |  v2 = Default SL 2x ATR + MACD Floor (neu)")
    print(f"  {DAYS} Tage, ${CAPITAL:,} — {start.strftime('%Y-%m-%d')} bis {end.strftime('%Y-%m-%d')}")
    print("=" * 120)

    results = {}

    for tf in TIMEFRAMES:
        print(f"\n{'=' * 120}")
        print(f"  TIMEFRAME: {tf}")
        print(f"{'=' * 120}")
        print(f'{"Symbol":>12s} | {"v1 Return":>8s} | {"v1 WR":>6s} | {"v1 DD":>6s} | {"v1 Sh":>6s} | {"v1 PF":>6s} | {"v2 Return":>8s} | {"v2 WR":>6s} | {"v2 DD":>6s} | {"v2 Sh":>6s} | {"v2 PF":>6s} | {"Besser":>6s}')
        print("-" * 120)

        for symbol in SYMBOLS:
            v1_str = "---"
            v2_str = "---"
            winner = "?"

            # v1: Edge without Default SL
            try:
                r1 = await run_backtest_for_strategy(
                    "edge_indicator", symbol, tf, start, end, CAPITAL,
                    {"default_sl_atr": 0}
                )
                m1 = r1["metrics"]
                v1_str = fmt_short(m1)
                results[(symbol, tf, "v1")] = m1
            except Exception as e:
                print(f'{symbol:>12s} | v1 ERROR: {e}')
                results[(symbol, tf, "v1")] = None
                continue

            # v2: Edge with Default SL + MACD Floor
            try:
                r2 = await run_backtest_for_strategy(
                    "edge_indicator", symbol, tf, start, end, CAPITAL,
                    {"default_sl_atr": 2.0}
                )
                m2 = r2["metrics"]
                v2_str = fmt_short(m2)
                results[(symbol, tf, "v2")] = m2
            except Exception as e:
                print(f'{symbol:>12s} | v2 ERROR: {e}')
                results[(symbol, tf, "v2")] = None
                continue

            sh1 = m1["sharpe_ratio"] or 0
            sh2 = m2["sharpe_ratio"] or 0
            winner = "v2" if sh2 > sh1 else "v1" if sh1 > sh2 else "="

            print(f'{symbol:>12s} | {v1_str} | {v2_str} | {winner:>6s}')

    # ==================== SUMMARY ====================
    print(f"\n\n{'=' * 120}")
    print("  ZUSAMMENFASSUNG PRO TIMEFRAME")
    print(f"{'=' * 120}")

    for tf in TIMEFRAMES:
        v1_wins = 0
        v2_wins = 0
        v1_rets = []
        v2_rets = []
        v1_dds = []
        v2_dds = []
        v1_sharpes = []
        v2_sharpes = []

        for symbol in SYMBOLS:
            m1 = results.get((symbol, tf, "v1"))
            m2 = results.get((symbol, tf, "v2"))
            if not m1 or not m2:
                continue

            sh1 = m1["sharpe_ratio"] or 0
            sh2 = m2["sharpe_ratio"] or 0

            v1_rets.append(m1["total_return_percent"])
            v2_rets.append(m2["total_return_percent"])
            v1_dds.append(m1["max_drawdown_percent"])
            v2_dds.append(m2["max_drawdown_percent"])
            v1_sharpes.append(sh1)
            v2_sharpes.append(sh2)

            if sh2 > sh1:
                v2_wins += 1
            elif sh1 > sh2:
                v1_wins += 1

        n = len(v1_rets)
        if n == 0:
            continue

        print(f"\n  {tf}: v2 gewinnt {v2_wins}/{n}, v1 gewinnt {v1_wins}/{n}")
        print(f"    v1 avg: Return {sum(v1_rets)/n:+.1f}%  Sharpe {sum(v1_sharpes)/n:.2f}  MaxDD {sum(v1_dds)/n:.1f}%")
        print(f"    v2 avg: Return {sum(v2_rets)/n:+.1f}%  Sharpe {sum(v2_sharpes)/n:.2f}  MaxDD {sum(v2_dds)/n:.1f}%")

    # ==================== BEST COINS PER TF ====================
    print(f"\n\n{'=' * 120}")
    print("  BESTE COINS: Edge v2 (nach Sharpe, nur profitabel)")
    print(f"{'=' * 120}")

    for tf in TIMEFRAMES:
        profitable = []
        for symbol in SYMBOLS:
            m = results.get((symbol, tf, "v2"))
            if m and m["total_return_percent"] > 0:
                profitable.append((symbol, m["total_return_percent"], m["sharpe_ratio"] or 0, m["max_drawdown_percent"]))

        profitable.sort(key=lambda x: x[2], reverse=True)

        print(f"\n  {tf} — {len(profitable)}/{len(SYMBOLS)} profitabel:")
        for sym, ret, sh, dd in profitable:
            print(f"    {sym:<12s}  {ret:>+7.1f}%  Sharpe {sh:>5.2f}  MaxDD {dd:.1f}%")

    print(f"\n{'=' * 120}\n")


if __name__ == "__main__":
    asyncio.run(main())
