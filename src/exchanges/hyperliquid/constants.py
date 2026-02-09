"""Hyperliquid-specific constants and URLs."""

from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL

BASE_URL = MAINNET_API_URL  # "https://api.hyperliquid.xyz"
TESTNET_URL = TESTNET_API_URL  # "https://api.hyperliquid-testnet.xyz"

WS_URL = "wss://api.hyperliquid.xyz/ws"
WS_TESTNET_URL = "wss://api.hyperliquid-testnet.xyz/ws"

# Hyperliquid uses JSON-RPC style API
INFO_ENDPOINT = "/info"
EXCHANGE_ENDPOINT = "/exchange"

# EIP-712 chain ID (same for testnet and mainnet)
CHAIN_ID = 421614  # 0x66eee

# Default slippage for market orders
DEFAULT_SLIPPAGE = 0.05

# ── Builder Code (revenue) ───────────────────────────────────────────────────
# Builder codes let the bot earn a small fee on every Hyperliquid order.
# The fee is additional to the exchange fee and goes 100% to the builder.
# Set via ENV: HL_BUILDER_ADDRESS (wallet with >=100 USDC in perps)
#              HL_BUILDER_FEE (tenths of basis points, default 10 = 0.01%)
#
# Fee unit: f=1 → 0.001%, f=10 → 0.01%, f=50 → 0.05%, f=100 → 0.1% (max perps)
DEFAULT_BUILDER_FEE = 10  # 0.01% — low enough for easy user approval
