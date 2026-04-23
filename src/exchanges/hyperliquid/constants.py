"""Hyperliquid-specific constants and URLs."""

from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL

BASE_URL = MAINNET_API_URL  # "https://api.hyperliquid.xyz"
TESTNET_URL = TESTNET_API_URL  # "https://api.hyperliquid-testnet.xyz"

WS_URL = "wss://api.hyperliquid.xyz/ws"
WS_TESTNET_URL = "wss://api.hyperliquid-testnet.xyz/ws"

# Hyperliquid uses JSON-RPC style API
INFO_ENDPOINT = "/info"
EXCHANGE_ENDPOINT = "/exchange"

# ── EIP-712 signature chain IDs ───────────────────────────────────────────────
# HL settles on Arbitrum; these are the chain IDs used in the EIP-712 domain.
# SEC-005: pinning prevents a manipulated SDK from producing signatures that
# replay on a different chain.
MAINNET_CHAIN_ID = 42161          # Arbitrum One
TESTNET_CHAIN_ID = 421614         # Arbitrum Sepolia

# Legacy alias — kept for callers importing the old constant.
CHAIN_ID = TESTNET_CHAIN_ID

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

# ── Builder-fee safety bounds (SEC-008) ───────────────────────────────────────
# Defense-in-depth against a recurrence of the 10x-too-high regression
# (fixed 2026-03-17). Enforced at construction AND inside approve_builder_fee.
# Units are tenths of basis points (integer).
#   MIN = 1   → 0.001%
#   MAX = 100 → 0.1% (HL perps hard cap)
MIN_BUILDER_FEE_TENTHS_BPS = 1
MAX_BUILDER_FEE_TENTHS_BPS = 100

# Same bounds expressed as percentages — used when validating the string
# form HL expects on the wire ("0.01%").
MIN_BUILDER_FEE_PCT = MIN_BUILDER_FEE_TENTHS_BPS / 1000.0   # 0.001%
MAX_BUILDER_FEE_PCT = MAX_BUILDER_FEE_TENTHS_BPS / 1000.0   # 0.1%

# ── EIP-712 primaryType whitelist (SEC-005) ───────────────────────────────────
# Only these message shapes may be signed. SafeExchange's method-name
# whitelist already filters callable surface; this second layer pins the
# EIP-712 primaryType so a manipulated SDK cannot smuggle a different
# signed-action shape through an allowed method name.
ALLOWED_PRIMARY_TYPES = frozenset({
    "Order",
    "Cancel",
    "CancelByCloid",
    "ModifyOrder",
    "BatchModify",
    "UpdateLeverage",
    "UpdateIsolatedMargin",
    "ApproveBuilderFee",
    "ScheduleCancel",
})
