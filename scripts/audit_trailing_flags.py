"""Audit open trades for DB/exchange drift on native_trailing_stop.

Scans every open trade against the exchange and reconciles the DB flag.
The drift we saw in prod: a failed TP/SL edit zeros `native_trailing_stop`
but `cancel_position_tpsl` silently leaves the moving_plan alive on Bitget,
then the position_monitor spams warnings forever. Running this once cleans
up any record still in that state.

Usage:
  python audit_trailing_flags.py          # dry run, prints drift
  python audit_trailing_flags.py --apply  # write the corrected flag
"""
import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select

from src.models.database import ExchangeConnection, TradeRecord
from src.models.session import get_session
from src.services.config_service import decrypt_value
from src.exchanges.factory import create_exchange_client


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write corrected flags")
    args = ap.parse_args()

    async with get_session() as s:
        trades = (await s.execute(
            select(TradeRecord).where(TradeRecord.status == "open").order_by(TradeRecord.id)
        )).scalars().all()
        conns = {
            (c.user_id, c.exchange_type): c for c in (await s.execute(
                select(ExchangeConnection)
            )).scalars().all()
        }

    print(f"Scanning {len(trades)} open trades ...\n")
    print(f"{'ID':>4} {'USER':>4} {'EXCH':<12} {'SYM':<8} {'SIDE':<5} "
          f"{'DB':<3} {'EXCH':<4}  {'DRIFT':<7} {'ACTION'}")

    updates = []
    for tr in trades:
        conn = conns.get((tr.user_id, tr.exchange))
        if not conn:
            print(f"{tr.id:>4} {tr.user_id:>4} {tr.exchange:<12} {tr.symbol:<8} {tr.side:<5} "
                  f"{str(tr.native_trailing_stop):<3}  —     —      (no connection)")
            continue

        api_key_enc = conn.demo_api_key_encrypted if tr.demo_mode else conn.api_key_encrypted
        api_secret_enc = conn.demo_api_secret_encrypted if tr.demo_mode else conn.api_secret_encrypted
        passphrase_enc = conn.demo_passphrase_encrypted if tr.demo_mode else conn.passphrase_encrypted
        if not api_key_enc or not api_secret_enc:
            print(f"{tr.id:>4} {tr.user_id:>4} {tr.exchange:<12} {tr.symbol:<8} {tr.side:<5} "
                  f"{str(tr.native_trailing_stop):<3}  —     —      (no keys for mode)")
            continue

        try:
            client = create_exchange_client(
                exchange_type=tr.exchange,
                api_key=decrypt_value(api_key_enc),
                api_secret=decrypt_value(api_secret_enc),
                passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
                demo_mode=tr.demo_mode,
            )
        except Exception as e:
            print(f"{tr.id:>4} {tr.user_id:>4} {tr.exchange:<12} {tr.symbol:<8} {tr.side:<5} "
                  f"{str(tr.native_trailing_stop):<3}  ERR   —      ({type(e).__name__})")
            continue

        probe_supported = getattr(type(client), "SUPPORTS_NATIVE_TRAILING_PROBE", False)
        if not probe_supported:
            await client.close()
            print(f"{tr.id:>4} {tr.user_id:>4} {tr.exchange:<12} {tr.symbol:<8} {tr.side:<5} "
                  f"{str(tr.native_trailing_stop):<3}  —     —      (probe not supported, skip)")
            continue

        try:
            exchange_has = await client.has_native_trailing_stop(tr.symbol, tr.side)
            await client.close()
        except Exception as e:
            print(f"{tr.id:>4} {tr.user_id:>4} {tr.exchange:<12} {tr.symbol:<8} {tr.side:<5} "
                  f"{str(tr.native_trailing_stop):<3}  ERR   —      ({type(e).__name__})")
            continue

        db_has = bool(tr.native_trailing_stop)
        drift = db_has != exchange_has
        action = ""
        if drift:
            action = f"SET {exchange_has}"
            updates.append((tr.id, exchange_has))
        print(f"{tr.id:>4} {tr.user_id:>4} {tr.exchange:<12} {tr.symbol:<8} {tr.side:<5} "
              f"{str(db_has):<3}  {str(exchange_has):<4}  {'YES' if drift else 'no':<7} {action}")

    print(f"\n{len(updates)} row(s) drift from exchange state")
    if not updates or not args.apply:
        if updates:
            print("Dry run — re-run with --apply to fix")
        return

    async with get_session() as s:
        for tid, new_flag in updates:
            tr = (await s.execute(
                select(TradeRecord).where(TradeRecord.id == tid)
            )).scalar_one()
            tr.native_trailing_stop = new_flag
        await s.commit()
    print(f"Applied {len(updates)} corrections.")


if __name__ == "__main__":
    asyncio.run(main())
