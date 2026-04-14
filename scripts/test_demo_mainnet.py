"""Validation: demo-mode HL client returns MAINNET prices, not testnet."""
import asyncio
import os
import sys

sys.path.insert(0, "/app")

from eth_account import Account as EthAccount
from hyperliquid.info import Info
from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL
from src.exchanges.hyperliquid.client import HyperliquidClient


async def main():
    # Use a throwaway key — we only read prices, no orders placed
    throwaway = EthAccount.create()
    key = throwaway.key.hex()
    addr = throwaway.address

    print("=" * 72)
    print("Test: demo_mode client must return MAINNET market data")
    print("=" * 72)

    # Direct reference: mainnet mid-price via a fresh Info client
    info_mainnet = Info(
        base_url=MAINNET_API_URL, skip_ws=True,
        spot_meta={"tokens": [], "universe": []},
    )
    info_testnet = Info(
        base_url=TESTNET_API_URL, skip_ws=True,
        spot_meta={"tokens": [], "universe": []},
    )
    mids_mainnet = info_mainnet.all_mids()
    mids_testnet = info_testnet.all_mids()

    symbols = ["AAVE", "BTC", "ETH", "SOL"]

    print(f"\n{'Symbol':<8} {'Mainnet':>12} {'Testnet':>12} {'Delta %':>10}")
    print("-" * 48)
    for s in symbols:
        m = float(mids_mainnet.get(s, 0))
        t = float(mids_testnet.get(s, 0))
        d = ((t - m) / m * 100) if m else 0
        print(f"{s:<8} {m:>12.4f} {t:>12.4f} {d:>9.2f}%")

    # Instantiate demo-mode client — should now use mainnet for price data
    client = HyperliquidClient(
        api_key=addr,
        api_secret=key,
        demo_mode=True,
    )

    print(f"\nClient demo_mode: {client.demo_mode}")
    print(f"Client.base_url (execution): {client.base_url}")
    print(f"Client._info.base_url (prices): {client._info.base_url}")
    print(f"Client._info_exec.base_url (user data): {client._info_exec.base_url}")

    # Run the actual method used by position_monitor
    ticker = await client.get_ticker("AAVE")
    print(f"\nclient.get_ticker('AAVE').last_price = {ticker.last_price}")
    print(f"mainnet reference mid              = {mids_mainnet.get('AAVE')}")
    print(f"testnet reference mid              = {mids_testnet.get('AAVE')}")

    # Also validate close-fill behavior returns None in demo (forces ticker fallback)
    cfp = await client.get_close_fill_price("AAVE")
    print(f"\nclient.get_close_fill_price('AAVE') in demo = {cfp}  (expected: None)")

    # Validate get_fill_price falls back to mainnet ticker
    fp = await client.get_fill_price("AAVE", "fake-order-id")
    print(f"client.get_fill_price('AAVE', fake) in demo = {fp}  (expected: mainnet mid)")

    # Assertions
    mainnet_aave = float(mids_mainnet.get("AAVE", 0))
    assert abs(ticker.last_price - mainnet_aave) / mainnet_aave < 0.001, (
        f"get_ticker returned {ticker.last_price}, expected ~{mainnet_aave}"
    )
    assert cfp is None, f"get_close_fill_price must return None in demo, got {cfp}"
    assert fp is not None and abs(fp - mainnet_aave) / mainnet_aave < 0.001, (
        f"get_fill_price must match mainnet mid, got {fp}"
    )
    assert client._info.base_url == MAINNET_API_URL, "info client must be MAINNET"
    assert client._info_exec.base_url == TESTNET_API_URL, "info_exec must be TESTNET in demo"
    assert client.base_url == TESTNET_API_URL, "execution base_url must be TESTNET in demo"

    print("\n" + "=" * 72)
    print("ALL ASSERTIONS PASSED")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
