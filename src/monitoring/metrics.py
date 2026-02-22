"""
Central Prometheus metric definitions.

All metrics are defined here so they can be imported
from a single place across the application.
"""

import os

from prometheus_client import Counter, Gauge, Histogram, Info

# Application info
APP_INFO = Info("trading_bot", "Trading Bot application info")

# HTTP request metrics
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# Bot metrics
BOTS_RUNNING = Gauge("bots_running_total", "Number of currently running bots")
BOTS_BY_STATUS = Gauge("bots_by_status", "Bots grouped by status", ["status"])
BOT_CONSECUTIVE_ERRORS = Gauge(
    "bot_consecutive_errors", "Consecutive errors per bot", ["bot_id"]
)

# Trade metrics
TRADES_TOTAL = Counter(
    "trades_total", "Total trades executed", ["side", "exchange"]
)
TRADE_PNL = Histogram(
    "trade_pnl_percent",
    "Trade PnL percentage",
    buckets=[-10, -5, -2, -1, 0, 1, 2, 5, 10, 25],
)
TRADE_FAILURES = Counter(
    "trade_failures_total",
    "Total failed trade execution attempts",
    ["exchange", "error_type"],
)

# System metrics
DB_QUERY_DURATION = Histogram(
    "db_query_duration_seconds", "Database query duration", ["operation"]
)
WEBSOCKET_CONNECTIONS = Gauge(
    "websocket_connections_active", "Active WebSocket connections"
)
PROCESS_MEMORY_BYTES = Gauge(
    "app_memory_bytes", "Application memory size in bytes"
)
DISK_USAGE_PERCENT = Gauge(
    "disk_usage_percent", "Disk usage percentage for data directory"
)
