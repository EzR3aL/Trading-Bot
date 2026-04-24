"""
Central Prometheus metric definitions.

All metrics are defined here so they can be imported
from a single place across the application.
"""


from prometheus_client import Counter, Gauge, Histogram, Info

# Application info
APP_INFO = Info("trading_bot", "Trading Bot application info")

# HTTP request metrics live in src/observability/metrics.py as of #327
# PR-2 and are emitted by src/api/middleware/metrics.py against a
# dedicated CollectorRegistry (#337 removed the legacy middleware that
# wrote to the default registry here).

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

# Database connection pool metrics
DB_POOL_SIZE = Gauge(
    "db_pool_size", "Total database connection pool size"
)
DB_POOL_CHECKED_OUT = Gauge(
    "db_pool_checked_out", "Number of connections currently checked out from pool"
)

# Circuit breaker metrics (1 = open, 0 = closed, 0.5 = half_open)
CIRCUIT_BREAKER_STATE = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 0.5=half_open, 1=open)",
    ["service"],
)

# Backup metrics
BACKUP_LAST_SUCCESS_TIMESTAMP = Gauge(
    "backup_last_success_timestamp",
    "Unix timestamp of last successful backup",
)
BACKUP_STATUS = Gauge(
    "backup_status",
    "Last backup status (1=success, 0=failure)",
)

# Risk management metrics
TRADING_HALTED = Gauge(
    "trading_halted",
    "Whether trading is halted due to daily loss limit (1=halted, 0=active)",
    ["bot_id"],
)
