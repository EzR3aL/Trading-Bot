"""Live-mode smoke test — read-only verification per exchange.

Run this BEFORE flipping any user from demo to live mode. Calls only
non-mutating endpoints (balance, positions, ticker) on live API keys
to verify the live code paths work end-to-end. No orders are placed.

Usage (one user at a time, takes ~10s per exchange):

    docker exec bitget-trading-bot \\
        python /app/scripts/live_mode_smoke.py --user-id 4

    # Optional: limit to specific exchanges
    python /app/scripts/live_mode_smoke.py --user-id 4 --exchanges bitget,bingx

Output: green check per exchange × feature, red X with error otherwise.
Exit code 0 if every selected (exchange × feature) pair succeeded.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, "/app")  # docker container layout

try:
    sys.path.insert(0, ".")  # local dev fallback
except Exception:
    pass

from sqlalchemy import select

from src.exchanges.factory import create_exchange_client
from src.models.database import ExchangeConnection
from src.models.session import get_session
from src.utils.encryption import decrypt_value


PROBE_SYMBOL = {
    "bitget": "BTCUSDT",
    "weex": "BTCUSDT",
    "hyperliquid": "BTC",
    "bitunix": "BTCUSDT",
    "bingx": "BTC-USDT",
}


@dataclass
class CheckResult:
    exchange: str
    feature: str
    ok: bool
    detail: str = ""


async def _probe_exchange(exchange: str, conn: ExchangeConnection) -> list[CheckResult]:
    """Run all read-only probes for one exchange."""
    results: list[CheckResult] = []

    if not conn.api_key_encrypted or not conn.api_secret_encrypted:
        results.append(CheckResult(exchange, "live_keys_present", False, "no live keys configured"))
        return results

    results.append(CheckResult(exchange, "live_keys_present", True, "✓"))

    try:
        client = create_exchange_client(
            exchange_type=exchange,
            api_key=decrypt_value(conn.api_key_encrypted),
            api_secret=decrypt_value(conn.api_secret_encrypted),
            passphrase=decrypt_value(conn.passphrase_encrypted) if conn.passphrase_encrypted else "",
            demo_mode=False,
        )
    except Exception as exc:
        results.append(CheckResult(exchange, "client_init", False, str(exc)))
        return results

    results.append(CheckResult(exchange, "client_init", True, "✓"))

    symbol = PROBE_SYMBOL.get(exchange, "BTCUSDT")

    async def _try(feature: str, coro):
        try:
            value = await coro
            return CheckResult(exchange, feature, True, _short(value))
        except Exception as exc:
            return CheckResult(exchange, feature, False, f"{type(exc).__name__}: {exc}")

    results.append(await _try("get_account_balance", client.get_account_balance()))
    results.append(await _try("get_open_positions", client.get_open_positions()))
    results.append(await _try("get_ticker", client.get_ticker(symbol)))
    results.append(await _try("get_funding_rate", client.get_funding_rate(symbol)))

    if hasattr(client, "close") and asyncio.iscoroutinefunction(client.close):
        try:
            await client.close()
        except Exception:
            pass

    return results


def _short(value) -> str:
    s = str(value)
    return s if len(s) <= 80 else s[:77] + "..."


async def main(user_id: int, exchanges: Optional[list[str]]) -> int:
    async with get_session() as db:
        rows = (await db.execute(
            select(ExchangeConnection).where(ExchangeConnection.user_id == user_id)
        )).scalars().all()

    if not rows:
        print(f"No exchange_connections rows for user_id={user_id}")
        return 1

    selected = {e.lower() for e in exchanges} if exchanges else None

    print(f"\n=== Live-Mode Smoke Test — user_id={user_id} ===\n")
    all_ok = True
    summary: dict[str, int] = {}

    for conn in sorted(rows, key=lambda r: r.exchange_type):
        ex = conn.exchange_type
        if selected and ex not in selected:
            continue

        results = await _probe_exchange(ex, conn)
        ok_count = sum(1 for r in results if r.ok)
        total = len(results)
        summary[ex] = ok_count
        if ok_count < total:
            all_ok = False

        print(f"--- {ex} ---")
        for r in results:
            mark = "✓" if r.ok else "✗"
            print(f"  {mark} {r.feature:<24} {r.detail}")
        print()

    print("=== Summary ===")
    for ex, ok_count in summary.items():
        print(f"  {ex}: {ok_count} ok")
    return 0 if all_ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--exchanges", type=str, default="",
                        help="Comma-separated list (default: all configured)")
    args = parser.parse_args()
    exchange_filter = [e.strip() for e in args.exchanges.split(",") if e.strip()] or None
    sys.exit(asyncio.run(main(args.user_id, exchange_filter)))
