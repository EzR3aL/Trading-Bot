"""Fix over-allocated Bitget bot budgets: 116% -> 100%."""
import asyncio
import json
import sys
sys.path.insert(0, "/app")

from src.models.session import get_session

FIXES = {
    11: 42,  # was 50
    12: 42,  # was 50
    # 13 stays at 16
}

async def fix():
    from sqlalchemy import text
    async with get_session() as session:
        for bot_id, new_pct in FIXES.items():
            result = await session.execute(text(
                "SELECT per_asset_config FROM bot_configs WHERE id = :id"
            ), {"id": bot_id})
            row = result.fetchone()
            if not row or not row[0]:
                print(f"  Bot #{bot_id}: no per_asset_config, skipping")
                continue

            cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            old_pct = None
            for symbol, asset_cfg in cfg.items():
                old_pct = asset_cfg.get("position_pct")
                asset_cfg["position_pct"] = new_pct

            new_cfg = json.dumps(cfg)
            await session.execute(text(
                "UPDATE bot_configs SET per_asset_config = :cfg WHERE id = :id"
            ), {"cfg": new_cfg, "id": bot_id})
            print(f"  Bot #{bot_id}: position_pct {old_pct}% -> {new_pct}%")

        await session.commit()
        print("\n  Committed. Verifying...")

        # Verify
        result = await session.execute(text(
            "SELECT id, name, per_asset_config FROM bot_configs "
            "WHERE exchange_type = 'bitget' ORDER BY id"
        ))
        total = 0
        for r in result.fetchall():
            cfg = json.loads(r[2]) if r[2] else {}
            for sym, ac in cfg.items():
                pct = ac.get("position_pct", 0)
                total += pct
                print(f"  Bot #{r[0]} ({r[1]}): {sym} = {pct}%")
        print(f"\n  Total allocation: {total}%")

asyncio.run(fix())
