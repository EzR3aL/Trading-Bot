"""Weex-specific constants and URLs.

Weex uses /capi/v2/ endpoints on api-contract.weex.com.
Demo mode uses the same URL but different symbol names:
  Live:  cmt_btcusdt   (BTC-USDT)
  Demo:  cmt_btcsusdt  (BTC-SUSDT)
"""

BASE_URL = "https://api-contract.weex.com"

WS_PUBLIC_URL = "wss://ws.weex.com/v2/ws/public"
WS_PRIVATE_URL = "wss://ws.weex.com/v2/ws/private"

SUCCESS_CODE = "00000"

# API Endpoints (Weex CAPI v2)
ENDPOINTS = {
    "account_assets": "/capi/v2/account/assets",
    "account_info": "/capi/v2/account/getAccount",
    "all_positions": "/capi/v2/account/position/allPosition",
    "single_position": "/capi/v2/account/position/singlePosition",
    "set_leverage": "/capi/v2/account/leverage",
    "ticker": "/capi/v2/market/ticker",
    "contracts": "/capi/v2/market/contracts",
    "funding_rate": "/capi/v2/market/funding_rate",
    "candles": "/capi/v2/market/candles",
    "open_interest": "/capi/v2/market/open_interest",
    "place_order": "/capi/v2/order/placeOrder",
    "cancel_order": "/capi/v2/order/cancel_order",
    "close_positions": "/capi/v2/order/closePositions",
    "order_detail": "/capi/v2/order/detail",
    "orders_current": "/capi/v2/order/current",
    "orders_history": "/capi/v2/order/history",
    "order_fills": "/capi/v2/order/fills",
}

# Order direction types (Weex-specific)
ORDER_TYPE_OPEN_LONG = "1"
ORDER_TYPE_OPEN_SHORT = "2"
ORDER_TYPE_CLOSE_LONG = "3"
ORDER_TYPE_CLOSE_SHORT = "4"

# Margin modes
MARGIN_CROSS = 1
MARGIN_ISOLATED = 3
