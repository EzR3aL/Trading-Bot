"""Bitget-specific constants, URLs, and error codes."""

BASE_URL = "https://api.bitget.com"
TESTNET_URL = "https://api.bitget.com"  # Bitget uses same URL with demo header

WS_PUBLIC_URL = "wss://ws.bitget.com/v2/ws/public"
WS_PRIVATE_URL = "wss://ws.bitget.com/v2/ws/private"

# Product types
PRODUCT_TYPE_USDT = "USDT-FUTURES"
PRODUCT_TYPE_COIN = "COIN-FUTURES"

# API Endpoints
ENDPOINTS = {
    "account_balance": "/api/v2/mix/account/account",
    "all_positions": "/api/v2/mix/position/all-position",
    "single_position": "/api/v2/mix/position/single-position",
    "ticker": "/api/v2/mix/market/ticker",
    "funding_rate": "/api/v2/mix/market/current-fund-rate",
    "historical_funding": "/api/v2/mix/market/history-fund-rate",
    "candles": "/api/v2/mix/market/candles",
    "open_interest": "/api/v2/mix/market/open-interest",
    "contracts": "/api/v2/mix/market/contracts",
    "set_leverage": "/api/v2/mix/account/set-leverage",
    "place_order": "/api/v2/mix/order/place-order",
    "cancel_order": "/api/v2/mix/order/cancel-order",
    "order_detail": "/api/v2/mix/order/detail",
    "orders_pending": "/api/v2/mix/order/orders-pending",
    "orders_history": "/api/v2/mix/order/orders-history",
    "order_fills": "/api/v2/mix/order/fills",
    "close_positions": "/api/v2/mix/order/close-positions",
    "account_bill": "/api/v2/mix/account/bill",
    "place_plan_order": "/api/v2/mix/order/place-plan-order",
}

# Bitget success code
SUCCESS_CODE = "00000"

# Error codes
ERROR_CODES = {
    "40034": "Invalid API key",
    "40037": "Invalid signature",
    "40015": "Request timestamp expired",
    "43011": "Insufficient balance",
    "45110": "Order does not exist",
}
