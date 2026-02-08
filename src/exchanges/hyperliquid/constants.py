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
