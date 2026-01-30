"""
WebSocket clients for real-time market data.

- BinanceWebSocket: Global market data (prices, funding rates, L/S ratio)
- BitgetWebSocket: Execution prices and position updates
"""

from src.websocket.binance_ws import BinanceWebSocket
from src.websocket.bitget_ws import BitgetWebSocket

__all__ = ["BinanceWebSocket", "BitgetWebSocket"]
