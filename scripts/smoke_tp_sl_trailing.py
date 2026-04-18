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
            "trailing_atr_override": t.trailing_atr_override,
            "native_trailing_stop": t.native_trailing_stop,
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
        # Bitget requires trigger_price ≥ current market for long trailing.
        # Use a 1 % activation buffer above the most recent ticker so the
        # placement isn't rejected by price-drift during the smoke run.
        print("\nSTEP 7: TP=%s + SL=%s, then trailing 2.5%%" % (tp1, sl1))
        await manager.apply_intent(trade_id, RiskLeg.TP, tp1)
        await manager.apply_intent(trade_id, RiskLeg.SL, sl1)
        cur_ticker = await client.get_ticker(SYMBOL)
        trigger_long = round(cur_ticker.last_price * 1.01, 1)
        trail_v1 = {"callback_rate": 2.5, "activation_price": None,
                    "trigger_price": trigger_long, "atr_override": 2.5}
        await manager.apply_intent(trade_id, RiskLeg.TRAILING, trail_v1)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record("TP present", _approx(ex["tp_price"], tp1))
        record("SL present", _approx(ex["sl_price"], sl1))
        record(
            "Trailing placed with callback ≈ 2.5 %",
            ex["trailing_callback"] is not None and abs(ex["trailing_callback"] - 2.5) < 0.2,
            f"callback={ex['trailing_callback']}%",
        )
        record(
            "Trailing DB row confirmed",
            db["trailing_status"] == "confirmed"
            and db["trailing_callback_rate"] is not None
            and abs(db["trailing_callback_rate"] - 2.5) < 0.2,
            f"db={db['trailing_status']} callback={db['trailing_callback_rate']}",
        )
        # Frontend edit-modal reads these legacy flags to seed its toggle +
        # slider. A successful trailing set MUST populate them.
        record(
            "DB native_trailing_stop flag set",
            db["native_trailing_stop"] is True,
            f"native_trailing_stop={db['native_trailing_stop']}",
        )
        record(
            "DB trailing_atr_override persisted",
            db["trailing_atr_override"] is not None and abs(db["trailing_atr_override"] - 2.5) < 0.01,
            f"trailing_atr_override={db['trailing_atr_override']}",
        )
        t1_oid = ex["trailing_order_id"]

        # ── Step 8: change trailing 2.5 -> 1.5 ──────────────────────
        print("\nSTEP 8: change trailing 2.5%% -> 1.5%% (TP+SL must survive)")
        cur_ticker = await client.get_ticker(SYMBOL)
        trigger_long = round(cur_ticker.last_price * 1.01, 1)
        trail_v2 = {"callback_rate": 1.5, "activation_price": None,
                    "trigger_price": trigger_long, "atr_override": 1.5}
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
        cur_ticker = await client.get_ticker(SYMBOL)
        trigger_long = round(cur_ticker.last_price * 1.01, 1)
        trail_v3 = {"callback_rate": 3.5, "activation_price": None,
                    "trigger_price": trigger_long, "atr_override": 3.5}
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
        record("Trailing cleared in DB", db["trailing_status"] == "cleared")
        record("native_trailing_stop reset to False", db["native_trailing_stop"] is False)
        record("trailing_atr_override cleared", db["trailing_atr_override"] is None)
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

        # ── Step 12: always-sweep against drift ────────────────────
        # Regression: a stray moving_plan placed behind the manager's back
        # (e.g. by a prior bot tick or manual exchange edit) used to survive
        # an apply_intent call. The manager now ALWAYS sweeps before placing,
        # so after an intent only the new plan should remain.
        print("\nSTEP 12: always-sweep — manager must clear stray plan")
        # Re-arm a position-level trailing baseline 2.5 % via the manager.
        cur_ticker = await client.get_ticker(SYMBOL)
        trigger_long = round(cur_ticker.last_price * 1.01, 1)
        baseline = {"callback_rate": 2.5, "activation_price": None,
                    "trigger_price": trigger_long, "atr_override": 2.5}
        await manager.apply_intent(trade_id, RiskLeg.TRAILING, baseline)
        await asyncio.sleep(1.0)
        # Now place a SECOND moving_plan directly on the exchange behind the
        # manager's back. This simulates drift (concurrent bot tick / manual
        # placement) — both plans now coexist on Bitget.
        pos = await client.get_position(SYMBOL)
        stray_size = pos.size if pos else round((MARGIN_USDT * LEVERAGE) / cur_ticker.last_price, 6)
        cur_ticker = await client.get_ticker(SYMBOL)
        stray_trigger = round(cur_ticker.last_price * 1.01, 1)
        await client.place_trailing_stop(
            symbol=SYMBOL, hold_side=SIDE, size=stray_size,
            callback_ratio=4.0, trigger_price=stray_trigger,
            margin_mode="cross",
        )
        await asyncio.sleep(1.5)
        # Apply a NEW intent (1.8 %) — manager must sweep BOTH stale plans
        # (its own previous one + the stray) and leave exactly the new one.
        cur_ticker = await client.get_ticker(SYMBOL)
        trigger_long = round(cur_ticker.last_price * 1.01, 1)
        new_trail = {"callback_rate": 1.8, "activation_price": None,
                     "trigger_price": trigger_long, "atr_override": 1.8}
        await manager.apply_intent(trade_id, RiskLeg.TRAILING, new_trail)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        # Count live moving_plan entries on the exchange — must be exactly 1.
        raw = await client._request(
            "GET", "/api/v2/mix/order/orders-plan-pending",
            params={"productType": "USDT-FUTURES", "symbol": SYMBOL,
                    "planType": "profit_loss"},
            auth=True,
        )
        entries = raw.get("entrustedList") if isinstance(raw, dict) else None
        moving_plans = [
            p for p in (entries or [])
            if (p.get("planType") or "").lower() == "moving_plan"
            and (p.get("posSide") or p.get("holdSide") or "").lower()
                in ("", SIDE.lower())
        ]
        record(
            "Exactly ONE moving_plan after sweep",
            len(moving_plans) == 1,
            f"found {len(moving_plans)} moving_plan entries",
        )
        record(
            "Exchange callback matches new value (1.8%)",
            ex["trailing_callback"] is not None and abs(ex["trailing_callback"] - 1.8) < 0.5,
            f"callback={ex['trailing_callback']}%",
        )
        record(
            "DB row confirmed with new order_id",
            db["trailing_status"] == "confirmed"
            and db["trailing_order_id"] is not None
            and ex["trailing_order_id"] is not None
            and db["trailing_order_id"] == ex["trailing_order_id"],
            f"db_oid={db['trailing_order_id']} ex_oid={ex['trailing_order_id']}",
        )

        # ── Step 13: user_cleared guard data-state proxy ───────────
        # Regression: the bot monitor must NOT auto-place a trailing after
        # the user explicitly cleared it. The behavioral test (mock the
        # monitor) is brittle, so we assert the data-state proxy that the
        # guard reads: trailing_status='cleared', native_trailing_stop=False,
        # trailing_atr_override=None. If any of these drifts, the guard
        # silently fails and the bot replaces the trailing on next tick.
        print("\nSTEP 13: user-clear data-state proxy for monitor guard")
        await manager.apply_intent(trade_id, RiskLeg.TRAILING, None)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record(
            "trailing_status == 'cleared' (guard reads this)",
            db["trailing_status"] == "cleared",
            f"trailing_status={db['trailing_status']}",
        )
        record(
            "native_trailing_stop is False (legacy guard flag)",
            db["native_trailing_stop"] is False,
            f"native_trailing_stop={db['native_trailing_stop']}",
        )
        record(
            "trailing_atr_override is None (slider seed cleared)",
            db["trailing_atr_override"] is None,
            f"trailing_atr_override={db['trailing_atr_override']}",
        )
        record(
            "Exchange trailing actually gone after user-clear",
            ex["trailing_callback"] is None,
            f"callback={ex['trailing_callback']}",
        )

        # ── Step 14: Insufficient-position recovery ────────────────
        # Regression: placing a fresh trailing then immediately changing the
        # slider used to fail with "Insufficient position" because the
        # previous moving_plan still owned the size. Always-sweep clears it
        # before re-placing, so the slider change must succeed.
        print("\nSTEP 14: place 2.5%% then immediately change to 1.8%%")
        cur_ticker = await client.get_ticker(SYMBOL)
        trigger_long = round(cur_ticker.last_price * 1.01, 1)
        place_trail = {"callback_rate": 2.5, "activation_price": None,
                       "trigger_price": trigger_long, "atr_override": 2.5}
        await manager.apply_intent(trade_id, RiskLeg.TRAILING, place_trail)
        ex_after_place = await _read_exchange(client)
        record(
            "Initial 2.5%% trailing placed",
            ex_after_place["trailing_callback"] is not None
            and abs(ex_after_place["trailing_callback"] - 2.5) < 0.5,
            f"callback={ex_after_place['trailing_callback']}%",
        )
        # Immediate slider change — no sleep, this is the regression scenario.
        cur_ticker = await client.get_ticker(SYMBOL)
        trigger_long = round(cur_ticker.last_price * 1.01, 1)
        change_trail = {"callback_rate": 1.8, "activation_price": None,
                        "trigger_price": trigger_long, "atr_override": 1.8}
        change_ok = True
        change_err = ""
        try:
            await manager.apply_intent(trade_id, RiskLeg.TRAILING, change_trail)
        except Exception as e:
            change_ok = False
            change_err = str(e)
        ex = await _read_exchange(client); db = await _read_db(trade_id)
        record(
            "Slider change accepted (no Insufficient-position reject)",
            change_ok and "insufficient" not in change_err.lower(),
            change_err or "ok",
        )
        record(
            "Trailing now reflects 1.8% on exchange",
            ex["trailing_callback"] is not None and abs(ex["trailing_callback"] - 1.8) < 0.5,
            f"callback={ex['trailing_callback']}%",
        )
        record(
            "Trailing DB confirmed at 1.8%",
            db["trailing_status"] == "confirmed"
            and db["trailing_callback_rate"] is not None
            and abs(db["trailing_callback_rate"] - 1.8) < 0.2,
            f"db={db['trailing_status']} callback={db['trailing_callback_rate']}",
        )

        # ── Step 15: close position ────────────────────────────────
        print("\nSTEP 15: close position")
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
