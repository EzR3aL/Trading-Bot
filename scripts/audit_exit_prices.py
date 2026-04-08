"""One-off audit: refetch real fill prices for all closed trades and report drift.

Usage (inside the trading-bot container):
    python -m scripts.audit_exit_prices              # dry-run report only
    python -m scripts.audit_exit_prices --apply      # write corrections to DB

For each closed trade with a `close_order_id`, calls
`exchange_client.get_fill_price(symbol, close_order_id)` and compares against
the stored `exit_price`. Trades without a close_order_id are listed but cannot
be auto-corrected (printed in a separate section so the operator can decide).

Recomputes pnl/pnl_percent via `calculate_pnl` to keep everything consistent
when --apply is set.
"""

import argparse
import asyncio
from typing import Optional

from sqlalchemy import select

from src.bot.pnl import calculate_pnl
from src.exchanges.factory import create_exchange_client
from src.models.database import ExchangeConnection, TradeRecord, User
from src.models.session import get_session
from src.utils.encryption import decrypt_value

DRIFT_TOLERANCE = 0.0001  # 0.01% — anything above is reported


def _pct_diff(old: float, new: float) -> float:
    if not old:
        return 0.0
    return abs(new - old) / abs(old)


async def _client_for(conn: ExchangeConnection, demo: bool):
    if demo:
        api_key_enc = conn.demo_api_key_encrypted
        api_secret_enc = conn.demo_api_secret_encrypted
        passphrase_enc = conn.demo_passphrase_encrypted
    else:
        api_key_enc = conn.api_key_encrypted
        api_secret_enc = conn.api_secret_encrypted
        passphrase_enc = conn.passphrase_encrypted
    if not api_key_enc or not api_secret_enc:
        return None
    return create_exchange_client(
        exchange_type=conn.exchange_type,
        api_key=decrypt_value(api_key_enc),
        api_secret=decrypt_value(api_secret_enc),
        passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
        demo_mode=demo,
    )


async def audit(apply: bool) -> None:
    async with get_session() as session:
        rows = (
            await session.execute(
                select(TradeRecord, User.username)
                .join(User, User.id == TradeRecord.user_id)
                .where(TradeRecord.status == "closed")
                .order_by(TradeRecord.exit_time.desc())
            )
        ).all()

        # Group by (user_id, exchange, demo_mode) to reuse one client
        clients: dict[tuple[int, str, bool], object] = {}

        async def get_client(user_id: int, exchange: str, demo: bool):
            key = (user_id, exchange, demo)
            if key in clients:
                return clients[key]
            conn = (
                await session.execute(
                    select(ExchangeConnection).where(
                        ExchangeConnection.user_id == user_id,
                        ExchangeConnection.exchange_type == exchange,
                    )
                )
            ).scalar_one_or_none()
            if not conn:
                clients[key] = None
                return None
            client = await _client_for(conn, demo)
            clients[key] = client
            return client

        drifted: list[tuple[TradeRecord, float, float]] = []
        no_close_oid: list[TradeRecord] = []
        no_fill_found: list[TradeRecord] = []
        errors: list[tuple[TradeRecord, str]] = []

        for trade, username in rows:
            if not trade.close_order_id:
                no_close_oid.append((trade, username))
                continue
            client = await get_client(trade.user_id, trade.exchange, bool(trade.demo_mode))
            if client is None:
                errors.append(((trade, username), "no exchange connection / keys"))
                continue
            try:
                real = await client.get_fill_price(trade.symbol, trade.close_order_id)
            except Exception as e:
                errors.append(((trade, username), f"get_fill_price error: {e}"))
                continue
            if real is None or real <= 0:
                no_fill_found.append((trade, username))
                continue
            stored = float(trade.exit_price or 0)
            if _pct_diff(stored, real) > DRIFT_TOLERANCE:
                drifted.append(((trade, username), stored, real))

        # Close all clients
        for c in clients.values():
            if c is not None:
                try:
                    await c.close()
                except Exception:
                    pass

        # ---------------- REPORT ----------------
        print(f"\n=== Exit-Price Drift Audit ===")
        print(f"Total closed trades scanned: {len(rows)}")
        print(f"Trades without close_order_id (cannot auto-fix): {len(no_close_oid)}")
        print(f"Trades where exchange returned no fill price: {len(no_fill_found)}")
        print(f"Errors: {len(errors)}")
        print(f"Drifted (> {DRIFT_TOLERANCE * 100:.2f}%): {len(drifted)}")
        print()

        if drifted:
            print("--- DRIFTED TRADES ---")
            print(f"{'ID':>5} {'USER':<15} {'EXCH':<12} {'SYMBOL':<12} {'SIDE':<6} "
                  f"{'STORED':>12} {'REAL':>12} {'OLD PNL':>12} {'NEW PNL':>12}")
            for (trade, username), stored, real in drifted:
                new_pnl, new_pct = calculate_pnl(trade.side, trade.entry_price, real, trade.size)
                print(
                    f"{trade.id:>5} {username:<15} {trade.exchange:<12} {trade.symbol:<12} "
                    f"{trade.side:<6} {stored:>12.6f} {real:>12.6f} "
                    f"{(trade.pnl or 0):>12.4f} {new_pnl:>12.4f}"
                )

        if no_close_oid:
            print("\n--- TRADES WITHOUT close_order_id (manual review needed) ---")
            for trade, username in no_close_oid[:30]:
                print(f"  #{trade.id} {username} {trade.exchange} {trade.symbol} {trade.side} "
                      f"exit={trade.exit_price} pnl={trade.pnl}")
            if len(no_close_oid) > 30:
                print(f"  ... +{len(no_close_oid) - 30} more")

        if errors:
            print("\n--- ERRORS ---")
            for (trade, username), msg in errors[:20]:
                print(f"  #{trade.id} {username}: {msg}")

        # ---------------- APPLY ----------------
        if apply and drifted:
            print(f"\n--- APPLYING {len(drifted)} CORRECTIONS ---")
            for (trade, _username), _stored, real in drifted:
                new_pnl, new_pct = calculate_pnl(trade.side, trade.entry_price, real, trade.size)
                db_trade = (
                    await session.execute(
                        select(TradeRecord).where(TradeRecord.id == trade.id)
                    )
                ).scalar_one()
                db_trade.exit_price = real
                db_trade.pnl = round(new_pnl, 4)
                db_trade.pnl_percent = round(new_pct, 2)
            await session.commit()
            print("Done.")
        elif drifted:
            print("\n(Dry-run; pass --apply to write corrections.)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write corrections to DB")
    args = parser.parse_args()
    asyncio.run(audit(args.apply))


if __name__ == "__main__":
    main()
