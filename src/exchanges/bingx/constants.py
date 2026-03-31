"""BingX-specific constants, URLs, and error codes."""

# Base URLs
# Production API domain (all REST endpoints are under /openApi/)
BASE_URL = "https://open-api.bingx.com"
# VST (Virtual Simulated Trading) demo mode domain
TESTNET_URL = "https://open-api-vst.bingx.com"

# WebSocket URLs (Perpetual Swap)
WS_PUBLIC_URL = "wss://open-api-swap.bingx.com/swap-market"
WS_PRIVATE_URL = "wss://open-api-swap.bingx.com/swap-market"
WS_PUBLIC_URL_VST = "wss://vst-open-api-ws.bingx.com/swap-market"
WS_PRIVATE_URL_VST = "wss://vst-open-api-ws.bingx.com/swap-market"

# API Endpoints (Perpetual Swap V2/V3)
# All paths are relative to BASE_URL
ENDPOINTS = {
    # === Account ===
    "account_balance": "/openApi/swap/v3/user/balance",
    "account_income": "/openApi/swap/v2/user/income",
    "commission_rate": "/openApi/swap/v2/user/commissionRate",

    # === Positions ===
    "all_positions": "/openApi/swap/v2/user/positions",
    # Single position uses same endpoint with ?symbol= param
    "single_position": "/openApi/swap/v2/user/positions",

    # === Trading ===
    "place_order": "/openApi/swap/v2/trade/order",
    "cancel_order": "/openApi/swap/v2/trade/order",       # DELETE method
    "close_all_positions": "/openApi/swap/v1/trade/closeAllPositions",
    "close_position": "/openApi/swap/v1/trade/closePosition",
    "batch_orders": "/openApi/swap/v2/trade/batchOrders",
    "test_order": "/openApi/swap/v2/trade/order/test",

    # === Order Queries ===
    "order_detail": "/openApi/swap/v2/trade/order",        # GET method
    "open_orders": "/openApi/swap/v2/trade/openOrders",
    "all_orders": "/openApi/swap/v2/trade/allOrders",
    "all_fill_orders": "/openApi/swap/v2/trade/allFillOrders",
    "fill_history": "/openApi/swap/v2/trade/fillHistory",

    # === Leverage & Margin ===
    "set_leverage": "/openApi/swap/v2/trade/leverage",
    "get_leverage": "/openApi/swap/v2/trade/leverage",      # GET method
    "set_margin_type": "/openApi/swap/v2/trade/marginType",  # POST method
    "get_margin_type": "/openApi/swap/v2/trade/marginType",  # GET method

    # === Market Data (Public) ===
    "ticker": "/openApi/swap/v2/quote/ticker",
    "contracts": "/openApi/swap/v2/quote/contracts",
    "price": "/openApi/swap/v2/quote/price",
    "depth": "/openApi/swap/v2/quote/depth",
    "trades": "/openApi/swap/v2/quote/trades",
    "klines": "/openApi/swap/v2/quote/klines",
    "funding_rate": "/openApi/swap/v2/quote/fundingRate",
    "premium_index": "/openApi/swap/v2/quote/premiumIndex",
    "open_interest": "/openApi/swap/v2/quote/openInterest",
    "book_ticker": "/openApi/swap/v2/quote/bookTicker",

    # === Server ===
    "server_time": "/openApi/swap/v2/server/time",

    # === ListenKey (WebSocket auth) ===
    "listen_key": "/openApi/user/auth/userDataStream",
}

# BingX API success code
SUCCESS_CODE = 0

# Error codes
ERROR_CODES = {
    100001: "Authentication failed",
    100202: "Insufficient balance",
    100400: "Invalid parameter",
    100440: "Price deviation too large",
    100500: "Internal server error",
    100503: "Server busy",
    80001: "Invalid request",
    80012: "Invalid symbol",
    80014: "Order does not exist",
    80016: "Order already cancelled",
    80017: "Order already filled",
}

# Order sides
SIDE_BUY = "BUY"
SIDE_SELL = "SELL"

# Position sides
POSITION_LONG = "LONG"
POSITION_SHORT = "SHORT"
POSITION_BOTH = "BOTH"

# Order types
ORDER_TYPE_MARKET = "MARKET"
ORDER_TYPE_LIMIT = "LIMIT"
ORDER_TYPE_TRIGGER_MARKET = "TRIGGER_MARKET"
ORDER_TYPE_TRIGGER_LIMIT = "TRIGGER_LIMIT"
ORDER_TYPE_TRAILING_STOP_MARKET = "TRAILING_STOP_MARKET"

# TP/SL conditional order types (used for cancel filtering)
CONDITIONAL_ORDER_TYPES = {
    "TAKE_PROFIT_MARKET",
    "STOP_MARKET",
    "TRAILING_STOP_MARKET",
}

# Order statuses returned by BingX
ORDER_STATUS_NEW = "NEW"
ORDER_STATUS_PENDING = "PENDING"
ORDER_STATUS_PARTIALLY_FILLED = "PARTIALLY_FILLED"
ORDER_STATUS_FILLED = "FILLED"
ORDER_STATUS_CANCELLED = "CANCELLED"
ORDER_STATUS_CANCELED = "CANCELED"

# Margin types
MARGIN_CROSSED = "CROSSED"
MARGIN_ISOLATED = "ISOLATED"

# Default recv window (milliseconds) for timestamp validation
DEFAULT_RECV_WINDOW = 5000
