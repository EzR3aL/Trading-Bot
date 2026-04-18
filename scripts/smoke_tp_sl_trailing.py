"""Live smoke test: every TP/SL/Trailing combination against Bitget Demo.

Runs through 12 scenarios covering the full cross-leg matrix, using the
RiskStateManager so it exercises the same code path the FastAPI endpoint uses.
After each step we readback from the exchange AND the DB and assert they agree.

Run inside the Docker container on the server:
    docker exec bitget-trading-bot python scripts/smoke_tp_sl_trailing.py

Environment (passed via docker exec -e):
    SMOKE_USER_ID       default=1 (admin)
    SMOKE_SYMBOL        default=BTCUSDT
    SMOKE_MARGIN_USDT   default=20.0
    SMOKE_LEVERAGE      default=10
"""
import asyncio
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, "/app")

from sqlalchemy import select

from src.api.dependencies.risk_state import get_risk_state_manager
from src.bot.risk_reasons import ExitReason  # noqa: F401 — ensures module imports
from src.bot.risk_state_manager import RiskLeg
from src.exchanges.base import ExchangeClient
from src.exchanges.factory import create_exchange_client
from src.models.database import ExchangeConnection, TradeRecord, User
from src.models.session import get_session
from src.utils.encryption import decrypt_value

USER_ID = int(os.environ.get("SMOKE_USER_ID", "1"))
SYMBOL = os.environ.get("SMOKE_SYMBOL", "BTCUSDT")
MARGIN_USDT = float(os.environ.get("SMOKE_MARGIN_USDT", "20.0"))
LEVERAGE = int(os.environ.get("SMOKE_LEVERAGE", "10"))
SIDE = "long"


@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str


RESULTS: list[StepResult] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append(StepResult(name, passed, detail))
    tag = "PASS" if passed else "FAIL"
    print(f"  [{tag}] {name}{(' — ' + detail) if detail else ''}")


async def _get_client() -> ExchangeClient:
    async with get_session() as s:
        conn = (
            await s.execute(
                select(ExchangeConnection).where(
                    ExchangeConnection.user_id == USER_ID,
                    ExchangeConnection.exchange_type == "bitget",
                )
            )
        ).scalar_one()
    return create_exchange_client(
        exchange_type="bitget",
        api_key=decrypt_value(conn.demo_api_key_encrypted),
        api_secret=decrypt_value(conn.demo_api_secret_encrypted),
        passphrase=decrypt_value(conn.demo_passphrase_encrypted or ""),
        demo_mode=True,
    )


async def _cleanup(client: ExchangeClient) -> None:
    """Best-effort clear of any pending plans + close any open position."""
    try:
        await client.cancel_position_tpsl(symbol=SYMBOL, side=SIDE)
    except Exception as e:
        print(f"  cleanup cancel_position_tpsl: {e}")
    try:
        pos = await client.get_position(SYMBOL)
        if pos:
            await client.close_position(SYMBOL, pos.side)
    except Exception as e:
        print(f"  cleanup close_position: {e}")
    await asyncio.sleep(1.5)


async def _create_trade_row(client: ExchangeClient) -> int:
    ticker = await client.get_ticker(SYMBOL)
    price = ticker.last_price
    size = round((MARGIN_USDT * LEVERAGE) / price, 6)

    order = await client.place_market_order(
        symbol=SYMBOL, side=SIDE, size=size, leverage=LEVERAGE,
        take_profit=None, stop_loss=None, margin_mode="cross",
    )
    await asyncio.sleep(1.5)

    async with get_session() as s:
        trade = TradeRecord(
            user_id=USER_ID, bot_config_id=None, exchange="bitget",
            symbol=SYMBOL, side=SIDE, size=size,
            entry_price=order.price or price,
            leverage=LEVERAGE, confidence=0, reason="smoke-test",
            order_id=order.order_id, status="open",
            entry_time=datetime.now(timezone.utc),
            demo_mode=True, native_trailing_stop=False, risk_source="unknown",
            last_synced_at=datetime.now(timezone.utc),
        )
        s.add(trade)
        await s.commit()
        await s.refresh(trade)
        return trade.id


async def _read_db(trade_id: int) -> dict:
    async with get_session() as s:
        t = await s.get(TradeRecord, trade_id)
        return {
            "take_profit": t.take_profit,
            "stop_loss": t.stop_loss,
            "tp_status": t.tp_status,
            "sl_status": t.sl_status,
            "trailing_status": t.trailing_status,
            "trailing_callback_rate": t.trailing_callback_rate,
            "risk_source": t.risk_source,
            "tp_order_id": t.tp_order_id,
            "sl_order_id": t.sl_order_id,
            "trailing_order_id": t.trailing_order_id,
        }


async def _read_exchange(client: ExchangeClient) -> dict:
    tpsl = await client.get_position_tpsl(SYMBOL, SIDE)
    trailing = await client.get_trailing_stop(SYMBOL, SIDE)
    return {
        "tp_price": tpsl.tp_price, "tp_order_id": tpsl.tp_order_id,
        "sl_price": tpsl.sl_price, "sl_order_id": tpsl.sl_order_id,
        "trailing_callback": trailing.callback_rate if trailing else None,
        "trailing_order_id": trailing.order_id if trailing else None,
    }


def _approx(a: Optional[float], b: Optional[float], tol: float = 0.5) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


async def run_smoke() -> bool:
    print("\n" + "=" * 72)
    print("  BITGET DEMO — TP/SL/TRAILING SMOKE TEST")
    print("=" * 72)

    client = await _get_client()
    manager = get_risk_state_manager()

    await _cleanup(client)

    ticker = await client.get_ticker(SYMBOL)
    price = ticker.last_price
    tp1 = round(price * 1.03, 1)
    tp2 = round(price * 1.05, 1)
    sl1 = round(price * 0.985, 1)
    sl2 = round(price * 0.97, 1)

    print(f"\n  Entry~${price:,.2f}  TP1={tp1}  TP2={tp2}  SL1={sl1}  SL2={sl2}")

    trade_id = await _create_trade_row(client)
    print(f"  Trade row #{trade_id} created\n")

    try:
        # ── Step 1: set TP ─────────────────────────────────────────
        print("STEP 1: apply TP=%s" % tp1)
        await manager.apply_intent(trade_id, RiskLeg.TP, tp1)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("TP on exchange", _approx(ex["tp_price"], tp1), f"exchange tp={ex['tp_price']}")
        record("TP in DB", _approx(db["take_profit"], tp1), f"db tp={db['take_profit']}")
        record("SL still empty", ex["sl_price"] is None and db["stop_loss"] is None)

        # ── Step 2: set SL (TP must survive) ────────────────────────
        print("\nSTEP 2: apply SL=%s (TP must survive)" % sl1)
        await manager.apply_intent(trade_id, RiskLeg.SL, sl1)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("SL on exchange", _approx(ex["sl_price"], sl1))
        record("TP still on exchange (leg isolation)", _approx(ex["tp_price"], tp1))
        record("SL in DB", _approx(db["stop_loss"], sl1))

        # ── Step 3: change TP to tp2 (SL must survive) ──────────────
        print("\nSTEP 3: change TP -> %s (SL must survive)" % tp2)
        await manager.apply_intent(trade_id, RiskLeg.TP, tp2)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("TP updated on exchange", _approx(ex["tp_price"], tp2))
        record("SL unchanged (leg isolation)", _approx(ex["sl_price"], sl1))
        record("TP in DB reflects new value", _approx(db["take_profit"], tp2))

        # ── Step 4: change SL to sl2 (TP must survive) ──────────────
        print("\nSTEP 4: change SL -> %s (TP must survive)" % sl2)
        await manager.apply_intent(trade_id, RiskLeg.SL, sl2)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("SL updated on exchange", _approx(ex["sl_price"], sl2))
        record("TP unchanged", _approx(ex["tp_price"], tp2))
        record("SL in DB reflects new value", _approx(db["stop_loss"], sl2))

        # ── Step 5: clear TP (SL must survive) ──────────────────────
        print("\nSTEP 5: clear TP (SL must survive)")
        await manager.apply_intent(trade_id, RiskLeg.TP, None)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("TP cleared on exchange", ex["tp_price"] is None)
        record("SL still on exchange", _approx(ex["sl_price"], sl2))
        record("TP cleared in DB", db["take_profit"] is None and db["tp_status"] == "cleared")

        # ── Step 6: clear SL (nothing should remain) ────────────────
        print("\nSTEP 6: clear SL (no TP/SL should remain)")
        await manager.apply_intent(trade_id, RiskLeg.SL, None)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("SL cleared on exchange", ex["sl_price"] is None)
        record("TP still cleared", ex["tp_price"] is None)
        record("SL cleared in DB", db["stop_loss"] is None and db["sl_status"] == "cleared")

        # ── Step 7: re-apply TP+SL, then add trailing 2.5% ──────────
        print("\nSTEP 7: TP=%s + SL=%s, then trailing 2.5%%" % (tp1, sl1))
        await manager.apply_intent(trade_id, RiskLeg.TP, tp1)
        await manager.apply_intent(trade_id, RiskLeg.SL, sl1)
        trail_v1 = {"callback_rate": 2.5, "activation_price": None,
                    "trigger_price": price, "atr_override": 2.5}
        await manager.apply_intent(trade_id, RiskLeg.TRAILING, trail_v1)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("TP present", _approx(ex["tp_price"], tp1))
        record("SL present", _approx(ex["sl_price"], sl1))
        record("Trailing present on exchange", ex["trailing_callback"] is not None,
               f"callback={ex['trailing_callback']}%")
        record("Trailing in DB", db["trailing_status"] in ("confirmed", "pending"),
               f"db={db['trailing_status']} callback={db['trailing_callback_rate']}")
        t1_oid = ex["trailing_order_id"]

        # ── Step 8: change trailing 2.5 -> 1.5 ──────────────────────
        print("\nSTEP 8: change trailing 2.5%% -> 1.5%% (TP+SL must survive)")
        trail_v2 = {"callback_rate": 1.5, "activation_price": None,
                    "trigger_price": price, "atr_override": 1.5}
        await manager.apply_intent(trade_id, RiskLeg.TRAILING, trail_v2)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("Trailing updated", ex["trailing_callback"] is not None and
               abs(ex["trailing_callback"] - 1.5) < 0.5)
        record("Trailing order_id rotated", ex["trailing_order_id"] != t1_oid,
               f"{t1_oid} -> {ex['trailing_order_id']}")
        record("TP survived trailing change", _approx(ex["tp_price"], tp1))
        record("SL survived trailing change", _approx(ex["sl_price"], sl1))
        t2_oid = ex["trailing_order_id"]

        # ── Step 9: change trailing 1.5 -> 3.5 ──────────────────────
        print("\nSTEP 9: change trailing 1.5%% -> 3.5%% (TP+SL must survive)")
        trail_v3 = {"callback_rate": 3.5, "activation_price": None,
                    "trigger_price": price, "atr_override": 3.5}
        await manager.apply_intent(trade_id, RiskLeg.TRAILING, trail_v3)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("Trailing updated to 3.5%", ex["trailing_callback"] is not None and
               abs(ex["trailing_callback"] - 3.5) < 0.5)
        record("Trailing order_id rotated again", ex["trailing_order_id"] != t2_oid)
        record("TP survived", _approx(ex["tp_price"], tp1))
        record("SL survived", _approx(ex["sl_price"], sl1))

        # ── Step 10: clear trailing (TP+SL survive) ─────────────────
        print("\nSTEP 10: clear trailing (TP+SL must survive)")
        await manager.apply_intent(trade_id, RiskLeg.TRAILING, None)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("Trailing cleared on exchange", ex["trailing_callback"] is None)
        record("Trailing cleared in DB", db["trailing_status"] == "cleared"),
        record("TP survived trailing clear", _approx(ex["tp_price"], tp1))
        record("SL survived trailing clear", _approx(ex["sl_price"], sl1))

        # ── Step 11: clear everything ──────────────────────────────
        print("\nSTEP 11: clear all legs")
        await manager.apply_intent(trade_id, RiskLeg.TP, None)
        await manager.apply_intent(trade_id, RiskLeg.SL, None)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("All exchange legs cleared",
               ex["tp_price"] is None and ex["sl_price"] is None and ex["trailing_callback"] is None)
        record("All DB legs cleared",
               db["take_profit"] is None and db["stop_loss"] is None)

        # ── Step 12: close position ────────────────────────────────
        print("\nSTEP 12: close position")
        closed = await client.close_position(SYMBOL, SIDE)
        await asyncio.sleep(1.5)
        pos = await client.get_position(SYMBOL)
        record("Position closed", pos is None, f"close_order={getattr(closed, 'order_id', None)}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        record("smoke run crashed", False, str(e))
    finally:
        await _cleanup(client)
        await client.close()

    # Summary
    passed = sum(1 for r in RESULTS if r.passed)
    total = len(RESULTS)
    failed = total - passed
    print("\n" + "=" * 72)
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 72)
    if failed:
        for r in RESULTS:
            if not r.passed:
                print(f"  [FAIL] {r.name}  {r.detail}")
    print()
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(run_smoke())
    sys.exit(0 if ok else 1)
