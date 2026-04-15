"""Backfill demo-mode HL trade prices from Hyperliquid mainnet candle data.

Historical demo trades were recorded with testnet prices because the client
queried testnet endpoints. Testnet AAVE traded at ~114.94 for hours while
mainnet was at ~100.93, which produced fantasy PnL (+80 USD vs actual +3 USD).

This script:
  1. Finds closed demo-mode HL trades
  2. Fetches the 1m mainnet close price at each trade's entry_time and exit_time
  3. Recomputes entry_price, exit_price, pnl, pnl_percent using those prices
  4. Writes results back (or prints a dry-run diff when --apply is omitted)

Usage:
  python backfill_demo_prices.py            # dry run
  python backfill_demo_prices.py --apply    # write
"""
import argparse
import asyncio
import sys
from datetime import timezone

sys.path.insert(0, "/app")

from hyperliquid.info import Info
from hyperliquid.utils.constants import MAINNET_API_URL
from sqlalchemy import select

from src.models.database import TradeRecord
from src.models.session import get_session


def mainnet_info() -> Info:
    try:
        return Info(base_url=MAINNET_API_URL, skip_ws=True)
    except (IndexError, KeyError):
        return Info(
            base_url=MAINNET_API_URL, skip_ws=True,
            spot_meta={"tokens": [], "universe": []},
        )


def normalize(symbol: str) -> str:
    if symbol.endswith("USDT"):
        return symbol[:-4]
    if symbol.endswith("USD"):
        return symbol[:-3]
    return symbol


def fetch_close_at(info: Info, coin: str, t_ms: int) -> float | None:
    """Fetch mainnet close price near the given timestamp.

    Tries progressively coarser intervals since HL retains fewer 1m candles
    than 1h/4h; older trades need wider buckets.
    """
    for interval, pad_ms in [
        ("1m", 60_000),
        ("5m", 5 * 60_000),
        ("15m", 15 * 60_000),
        ("1h", 60 * 60_000),
        ("4h", 4 * 60 * 60_000),
    ]:
        try:
            candles = info.candles_snapshot(coin, interval, t_ms - pad_ms, t_ms + pad_ms)
        except Exception as e:
            print(f"  {interval} fetch failed for {coin} @ {t_ms}: {e}")
            continue
        if not candles:
            continue
        best = None
        for c in candles:
            t_open = int(c.get("t", 0))
            if t_open <= t_ms and (best is None or t_open > int(best.get("t", 0))):
                best = c
        if best is None:
            best = candles[0]
        price = float(best.get("c", 0))
        if price > 0:
            return price
    return None


def compute_pnl(side: str, entry: float, exit_: float, size: float) -> tuple[float, float]:
    if side == "long":
        pnl = (exit_ - entry) * size
    else:
        pnl = (entry - exit_) * size
    pnl_pct = ((exit_ - entry) / entry * 100) * (1 if side == "long" else -1)
    return round(pnl, 6), round(pnl_pct, 6)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually update DB")
    ap.add_argument("--threshold", type=float, default=0.5,
                    help="Minimum price divergence (%) to consider a row mispriced")
    args = ap.parse_args()

    info = mainnet_info()

    async with get_session() as s:
        rows = (await s.execute(
            select(TradeRecord).where(
                TradeRecord.exchange == "hyperliquid",
                TradeRecord.demo_mode == True,  # noqa: E712
                TradeRecord.status == "closed",
            ).order_by(TradeRecord.id)
        )).scalars().all()

    print(f"Found {len(rows)} closed demo HL trades")
    print(f"{'ID':>4} {'SYM':<6} {'SIDE':<5} {'ENTRY_DB':>10} {'ENTRY_MN':>10} "
          f"{'EXIT_DB':>10} {'EXIT_MN':>10} {'PNL_DB':>10} {'PNL_MN':>10} {'ACTION':<10}")

    updates = []
    for tr in rows:
        coin = normalize(tr.symbol)
        entry_ms = int(tr.entry_time.replace(tzinfo=timezone.utc).timestamp() * 1000)
        exit_ms = int(tr.exit_time.replace(tzinfo=timezone.utc).timestamp() * 1000)

        entry_mn = fetch_close_at(info, coin, entry_ms)
        exit_mn = fetch_close_at(info, coin, exit_ms)
        if entry_mn is None or exit_mn is None:
            print(f"{tr.id:>4} {coin:<6} {tr.side:<5}  <missing mainnet candle, skip>")
            continue

        entry_div = abs(tr.entry_price - entry_mn) / entry_mn * 100
        exit_div = abs(tr.exit_price - exit_mn) / exit_mn * 100
        action = "KEEP"
        if entry_div > args.threshold or exit_div > args.threshold:
            action = "FIX"

        new_pnl, new_pct = compute_pnl(tr.side, entry_mn, exit_mn, tr.size)

        print(f"{tr.id:>4} {coin:<6} {tr.side:<5} "
              f"{tr.entry_price:>10.4f} {entry_mn:>10.4f} "
              f"{tr.exit_price:>10.4f} {exit_mn:>10.4f} "
              f"{tr.pnl:>10.4f} {new_pnl:>10.4f} {action:<10}")

        if action == "FIX":
            updates.append((tr.id, entry_mn, exit_mn, new_pnl, new_pct))

    print(f"\n{len(updates)} rows need correction (threshold {args.threshold}%)")

    if not updates:
        return
    if not args.apply:
        print("\nDry run — re-run with --apply to write changes")
        return

    async with get_session() as s:
        for tid, entry, ex, pnl, pct in updates:
            tr = (await s.execute(
                select(TradeRecord).where(TradeRecord.id == tid)
            )).scalar_one()
            tr.entry_price = entry
            tr.exit_price = ex
            tr.pnl = pnl
            tr.pnl_percent = pct
        await s.commit()
    print(f"Applied {len(updates)} updates")


if __name__ == "__main__":
    asyncio.run(main())
