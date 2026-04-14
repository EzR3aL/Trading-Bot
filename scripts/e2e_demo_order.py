"""E2E: place a demo AAVE order and verify entry/exit prices match MAINNET mids."""
import asyncio
import sys
import time

sys.path.insert(0, "/app")

from hyperliquid.info import Info
from hyperliquid.utils.constants import MAINNET_API_URL
from src.models.session import get_session
from src.models.database import ExchangeConnection
from src.services.config_service import create_hl_client
from sqlalchemy import select


async def main():
    async with get_session() as s:
        conn = (await s.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.exchange_type == "hyperliquid",
                ExchangeConnection.user_id == 1,
            )
        )).scalar_one()

    client = create_hl_client(conn, use_demo=True)

    # Reference mainnet mid
    info_mn = Info(
        base_url=MAINNET_API_URL, skip_ws=True,
        spot_meta={"tokens": [], "universe": []},
    )
    mainnet_aave = float(info_mn.all_mids().get("AAVE", 0))

    # 1) ticker must come from mainnet
    tkr = await client.get_ticker("AAVE")
    print(f"[1] get_ticker(AAVE).last_price = {tkr.last_price:.4f}")
    print(f"    mainnet reference          = {mainnet_aave:.4f}")
    assert abs(tkr.last_price - mainnet_aave) / mainnet_aave < 0.002

    # 2) Place a small testnet order via the normal code path
    # leverage 3x, 20 USDC notional ≈ 0.2 AAVE
    try:
        await client.set_leverage("AAVE", 3, margin_mode="cross")
    except Exception as e:
        print(f"    set_leverage warning: {e}")

    size = round(20.0 / mainnet_aave, 2)
    print(f"\n[2] place_market_order(AAVE BUY size={size}) on TESTNET")
    order = await client.place_market_order(
        symbol="AAVE",
        side="BUY",
        size=size,
        leverage=3,
    )
    print(f"    order_id={order.order_id}  price={order.price}  status={order.status}")

    # 3) get_fill_price MUST return mainnet mid, not testnet fill
    fill = await client.get_fill_price("AAVE", order.order_id)
    mainnet_aave_now = float(info_mn.all_mids().get("AAVE", 0))
    print(f"\n[3] get_fill_price = {fill}")
    print(f"    mainnet mid now = {mainnet_aave_now:.4f}")
    assert fill is not None
    assert abs(fill - mainnet_aave_now) / mainnet_aave_now < 0.002, (
        f"fill {fill} diverges too much from mainnet {mainnet_aave_now}"
    )

    # 4) Close and verify get_close_fill_price returns None (force ticker fallback)
    await asyncio.sleep(2)
    print(f"\n[4] close_position(AAVE)")
    closed = await client.close_position(symbol="AAVE", side="long")
    print(f"    close order_id={getattr(closed, 'order_id', closed)}")

    cfp = await client.get_close_fill_price("AAVE")
    print(f"    get_close_fill_price = {cfp} (expected None in demo)")
    assert cfp is None

    tkr2 = await client.get_ticker("AAVE")
    mainnet_aave_final = float(info_mn.all_mids().get("AAVE", 0))
    print(f"    ticker fallback for exit = {tkr2.last_price}")
    print(f"    mainnet mid final        = {mainnet_aave_final:.4f}")
    assert abs(tkr2.last_price - mainnet_aave_final) / mainnet_aave_final < 0.002

    print("\n" + "=" * 72)
    print("E2E PASSED — demo-mode prices track MAINNET")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
