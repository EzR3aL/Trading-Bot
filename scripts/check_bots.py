"""Quick check: active bots, their budgets, and TP/SL config."""
import asyncio
import sys
sys.path.insert(0, "/app")

from src.models.session import get_session

async def check():
    from sqlalchemy import text
    async with get_session() as session:
        result = await session.execute(text(
            "SELECT id, name, exchange_type, is_enabled, "
            "take_profit_percent, stop_loss_percent, per_asset_config, "
            "trading_pairs "
            "FROM bot_configs ORDER BY id"
        ))
        rows = result.fetchall()
        print(f"{'='*70}")
        print(f"  ACTIVE BOTS & TP/SL CONFIG")
        print(f"{'='*70}")
        for r in rows:
            enabled = "ON" if r[3] else "OFF"
            print(f"\n  Bot #{r[0]}: {r[1]} [{enabled}]")
            print(f"    Exchange: {r[2]}")
            print(f"    Pairs: {r[7]}")
            print(f"    TP: {r[4]}%  SL: {r[5]}%")
            print(f"    Per-asset: {r[6]}")

asyncio.run(check())
