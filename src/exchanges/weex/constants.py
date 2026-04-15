"""Weex-specific constants and URLs.

Weex V3 API launched 2026-03-09; demo support added 2026-04-09.
The remaining V2 endpoints (ticker, set_leverage, order detail/current/fills)
have no published V3 equivalent yet — they stay on V2 until Weex publishes
new docs. Issue tracker: #114.

V3 uses plain symbols (BTCUSDT). V2 still uses the cmt_btcusdt format —
helpers `_to_api_symbol` / `_from_api_symbol` only apply to V2 endpoints.

Demo mode adds the `paptrading: 1` request header (same URL).
"""

BASE_URL = "https://api-contract.weex.com"

WS_PUBLIC_URL = "wss://ws.weex.com/v2/ws/public"
WS_PRIVATE_URL = "wss://ws.weex.com/v2/ws/private"

SUCCESS_CODE = "00000"

# API Endpoints — V3 where published, V2 as fallback for unmigrated features.
ENDPOINTS = {
    # === Account (V3) ===
    "account_assets": "/capi/v3/account/balance",
    "account_info": "/capi/v2/account/getAccount",  # no V3 equivalent
    # === Positions (V3) ===
    "all_positions": "/capi/v3/account/position/allPosition",
    "single_position": "/capi/v3/account/position/singlePosition",
    # === Leverage (still V2 — no V3 endpoint published) ===
    "set_leverage": "/capi/v2/account/leverage",
    # === Market (V3) ===
    "ticker": "/capi/v2/market/ticker",  # V3 path unverified — see issue #114
    "contracts": "/capi/v3/market/exchangeInfo",
    "funding_rate": "/capi/v3/market/premiumIndex",
    "candles": "/capi/v3/market/klines",
    "open_interest": "/capi/v3/market/openInterest",
    # === Trading (V3) ===
    "place_order": "/capi/v3/order",
    "cancel_order": "/capi/v3/order",  # V3 uses DELETE method
    "close_positions": "/capi/v3/closePositions",
    "order_detail": "/capi/v2/order/detail",  # V3 path unverified
    "orders_current": "/capi/v2/order/current",  # V3 path unverified
    "orders_history": "/capi/v3/order/history",
    "order_fills": "/capi/v2/order/fills",  # V3 fills via /capi/v3/userTrades
    # === TP/SL & Trigger (V3) ===
    "place_tpsl_order": "/capi/v3/placeTpSlOrder",
    "cancel_tpsl_order": "/capi/v3/cancelTpSlOrder",
    "pending_tpsl_orders": "/capi/v3/pendingTpSlOrders",
    "place_trigger_order": "/capi/v3/placePendingOrder",
    # === Fee/Income (V3) ===
    "user_trades": "/capi/v3/userTrades",
    "account_income": "/capi/v3/account/income",
}

# V3 uses BUY/SELL + LONG/SHORT instead of numeric type codes
# Kept for V2 fallback compatibility
ORDER_TYPE_OPEN_LONG = "1"
ORDER_TYPE_OPEN_SHORT = "2"
ORDER_TYPE_CLOSE_LONG = "3"
ORDER_TYPE_CLOSE_SHORT = "4"

# Margin modes (V2 format — V2 endpoints still use these)
MARGIN_CROSS = 1
MARGIN_ISOLATED = 3
