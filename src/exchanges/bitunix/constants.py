"""Bitunix-specific constants, URLs, and endpoint paths."""

# --- Base URLs ---
# Bitunix futures REST API
BASE_URL = "https://fapi.bitunix.com"

# Bitunix does not offer a dedicated testnet / demo-trading domain.
# Demo mode is handled via a separate demo API key provided by the exchange.
TESTNET_URL = BASE_URL

# --- WebSocket URLs ---
WS_PUBLIC_URL = "wss://fapi.bitunix.com/public/"
WS_PRIVATE_URL = "wss://fapi.bitunix.com/private/"

# --- API Endpoints (Futures v1) ---
ENDPOINTS = {
    # Account
    "account": "/api/v1/futures/account",
    "change_leverage": "/api/v1/futures/account/change_leverage",
    "change_margin_mode": "/api/v1/futures/account/change_margin_mode",
    "get_leverage_margin_mode": "/api/v1/futures/account/get_leverage_margin_mode",
    "adjust_position_margin": "/api/v1/futures/account/adjust_position_margin",
    "change_position_mode": "/api/v1/futures/account/change_position_mode",
    # Market (public, no auth required)
    "tickers": "/api/v1/futures/market/tickers",
    "trading_pairs": "/api/v1/futures/market/trading_pairs",
    "funding_rate": "/api/v1/futures/market/funding_rate",
    "funding_rate_batch": "/api/v1/futures/market/funding_rate/batch",
    "depth": "/api/v1/futures/market/depth",
    "kline": "/api/v1/futures/market/kline",
    # Trade
    "place_order": "/api/v1/futures/trade/place_order",
    "batch_order": "/api/v1/futures/trade/batch_order",
    "cancel_orders": "/api/v1/futures/trade/cancel_orders",
    "modify_order": "/api/v1/futures/trade/modify_order",
    "get_pending_orders": "/api/v1/futures/trade/get_pending_orders",
    "get_history_orders": "/api/v1/futures/trade/get_history_orders",
    "get_order_detail": "/api/v1/futures/trade/get_order_detail",
    "get_history_trades": "/api/v1/futures/trade/get_history_trades",
    # Positions
    "get_pending_positions": "/api/v1/futures/position/get_pending_positions",
    "get_history_positions": "/api/v1/futures/position/get_history_positions",
    "get_position_tiers": "/api/v1/futures/position/get_position_tiers",
    # TP/SL
    "tpsl_place_order": "/api/v1/futures/tpsl/place_order",
    "tpsl_modify_order": "/api/v1/futures/tpsl/modify_order",
    "tpsl_cancel_order": "/api/v1/futures/tpsl/cancel_order",
    "tpsl_get_pending_orders": "/api/v1/futures/tpsl/get_pending_orders",
    "tpsl_get_history_orders": "/api/v1/futures/tpsl/get_history_orders",
    # Position-level TP/SL (auto-adjusts to position size, 1 per position)
    "tpsl_position_place": "/api/v1/futures/tpsl/position/place_order",
    "tpsl_position_modify": "/api/v1/futures/tpsl/position/modify_order",
}

# --- Success Code ---
# Bitunix returns code=0 for success
SUCCESS_CODE = 0

# --- Error Codes ---
ERROR_CODES = {
    "10001": "System error",
    "10002": "Parameter error",
    "10003": "Signature error",
    "10004": "Timestamp expired",
    "10005": "API key invalid",
    "10006": "IP not whitelisted",
    "10007": "Rate limit exceeded",
}
