"""Weex-specific constants and URLs.

Weex V3 API launched 2026-03-09. Trading endpoints migrated to /capi/v3/.
Account, position, leverage, and market endpoints remain on /capi/v2/ until
Weex publishes V3 equivalents.

Demo mode uses the same URL with paptrading header.
V3 uses plain symbols (BTCUSDT) instead of V2's cmt_btcusdt format.
"""

BASE_URL = "https://api-contract.weex.com"

WS_PUBLIC_URL = "wss://ws.weex.com/v2/ws/public"
WS_PRIVATE_URL = "wss://ws.weex.com/v2/ws/private"

SUCCESS_CODE = "00000"

# API Endpoints — V3 where available, V2 as fallback
ENDPOINTS = {
    # === Account (still V2 — no V3 docs published) ===
    "account_assets": "/capi/v2/account/assets",
    "account_info": "/capi/v2/account/getAccount",
    # === Positions (still V2) ===
    "all_positions": "/capi/v2/account/position/allPosition",
    "single_position": "/capi/v2/account/position/singlePosition",
    # === Leverage (still V2) ===
    "set_leverage": "/capi/v2/account/leverage",
    # === Market (still V2 for ticker/candles/funding) ===
    "ticker": "/capi/v2/market/ticker",
    "contracts": "/capi/v3/market/exchangeInfo",
    "funding_rate": "/capi/v2/market/funding_rate",
    "candles": "/capi/v2/market/candles",
    "open_interest": "/capi/v2/market/open_interest",
    # === Trading (V3) ===
    "place_order": "/capi/v3/order",
    "cancel_order": "/capi/v2/order/cancel_order",
    "close_positions": "/capi/v3/closePositions",
    "order_detail": "/capi/v2/order/detail",
    "orders_current": "/capi/v2/order/current",
    "orders_history": "/capi/v3/order/history",
    "order_fills": "/capi/v2/order/fills",
    # === TP/SL & Trigger (V3) ===
    "place_tpsl_order": "/capi/v3/placeTpSlOrder",
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
