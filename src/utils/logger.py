"""
Logging configuration for the Bitget Trading Bot.
Provides colored console output, file logging, and optional JSON output.
"""

import json as json_lib
import logging
import logging.handlers
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import colorlog

# Patterns that match sensitive data in log messages
_REDACT_PATTERNS = [
    # API keys and secrets (hex/base64 strings 16+ chars after common prefixes)
    re.compile(r"(api[_-]?key|api[_-]?secret|passphrase|password|token|secret|authorization)['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9+/=_-]{16,})", re.IGNORECASE),
    # Bearer tokens
    re.compile(r"(Bearer\s+)([A-Za-z0-9._-]{20,})", re.IGNORECASE),
    # JWT tokens (header.payload.signature)
    re.compile(r"(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"),
]


class RedactionFilter(logging.Filter):
    """Filter that redacts sensitive values from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact(a) if isinstance(a, str) else a for a in record.args)
        return True

    @staticmethod
    def _redact(text: str) -> str:
        for pattern in _REDACT_PATTERNS:
            text = pattern.sub(lambda m: m.group(0)[:len(m.group(0)) - len(m.group(m.lastindex))] + "***REDACTED***" if m.lastindex else "***REDACTED***", text)
        return text


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json_lib.dumps(log_entry)


def setup_logging(
    log_level: str = "INFO",
    log_file: str = "logs/trading_bot.log",
) -> logging.Logger:
    """
    Set up logging configuration with colored console output and file logging.

    Set LOG_FORMAT=json environment variable to enable structured JSON logging
    for production deployments (e.g. log aggregators like ELK, Datadog).

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to the log file

    Returns:
        Configured root logger
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers
    root_logger.handlers = []

    # Add redaction filter to prevent secrets from leaking into logs
    root_logger.addFilter(RedactionFilter())

    # JSON mode: explicit LOG_FORMAT=json, or auto-enabled in production
    environment = os.getenv("ENVIRONMENT", "development").lower()
    log_format = os.getenv("LOG_FORMAT", "").lower()
    use_json = log_format == "json" or (not log_format and environment == "production")

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout) if use_json else colorlog.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    if use_json:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_format = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red,bg_white",
            },
        )
        console_handler.setFormatter(console_format)

    root_logger.addHandler(console_handler)

    # File handler with rotation (100 MB per file, 10 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, encoding="utf-8", maxBytes=100_000_000, backupCount=10,
    )
    file_handler.setLevel(logging.DEBUG)

    if use_json:
        file_handler.setFormatter(JSONFormatter())
    else:
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)

    root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class TradeLogger:
    """
    Specialized logger for trade operations.
    Writes structured trade logs for analysis and Discord notifications.
    """

    def __init__(self, log_dir: str = "logs/trades"):
        """Initialize the trade logger."""
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger("TradeLogger")

    def _get_trade_log_path(self) -> Path:
        """Get the path for today's trade log."""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"trades_{today}.log"

    def log_trade_entry(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        leverage: int,
        confidence: int,
        reason: str,
        order_id: str,
    ) -> None:
        """
        Log a trade entry.

        Args:
            symbol: Trading pair
            side: long or short
            size: Position size
            entry_price: Entry price
            leverage: Leverage used
            confidence: Strategy confidence (0-100)
            reason: Reason for the trade
            order_id: Exchange order ID
        """
        timestamp = datetime.now().isoformat()
        trade_data = {
            "timestamp": timestamp,
            "type": "ENTRY",
            "symbol": symbol,
            "side": side.upper(),
            "size": size,
            "entry_price": entry_price,
            "leverage": leverage,
            "confidence": confidence,
            "reason": reason,
            "order_id": order_id,
        }

        self.logger.info(f"TRADE ENTRY: {trade_data}")

        # Append to daily trade log
        with open(self._get_trade_log_path(), "a") as f:
            import json
            f.write(json.dumps(trade_data) + "\n")

    def log_trade_exit(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        exit_price: float,
        pnl: float,
        pnl_percent: float,
        fees: float,
        funding_paid: float,
        reason: str,
        order_id: str,
    ) -> None:
        """
        Log a trade exit.

        Args:
            symbol: Trading pair
            side: long or short
            size: Position size
            entry_price: Entry price
            exit_price: Exit price
            pnl: Absolute profit/loss
            pnl_percent: Percentage profit/loss
            fees: Trading fees paid
            funding_paid: Funding payments
            reason: Exit reason (TP, SL, manual, etc.)
            order_id: Exchange order ID
        """
        timestamp = datetime.now().isoformat()
        trade_data = {
            "timestamp": timestamp,
            "type": "EXIT",
            "symbol": symbol,
            "side": side.upper(),
            "size": size,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "fees": fees,
            "funding_paid": funding_paid,
            "reason": reason,
            "order_id": order_id,
        }

        self.logger.info(f"TRADE EXIT: {trade_data}")

        # Append to daily trade log
        with open(self._get_trade_log_path(), "a") as f:
            import json
            f.write(json.dumps(trade_data) + "\n")

    def get_daily_trades(self, date: str = None) -> list:
        """
        Get all trades for a specific date.

        Args:
            date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            List of trade records
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        log_path = self.log_dir / f"trades_{date}.log"
        if not log_path.exists():
            return []

        trades = []
        with open(log_path, "r") as f:
            import json
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))

        return trades

    def get_daily_stats(self, date: str = None) -> dict:
        """
        Calculate daily trading statistics.

        Args:
            date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            Dictionary with daily stats
        """
        trades = self.get_daily_trades(date)

        exits = [t for t in trades if t["type"] == "EXIT"]

        if not exits:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "total_fees": 0.0,
                "total_funding": 0.0,
                "net_pnl": 0.0,
            }

        winning = [t for t in exits if t["pnl"] > 0]
        losing = [t for t in exits if t["pnl"] <= 0]

        total_pnl = sum(t["pnl"] for t in exits)
        total_fees = sum(t["fees"] for t in exits)
        total_funding = sum(t["funding_paid"] for t in exits)

        return {
            "total_trades": len(exits),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": len(winning) / len(exits) * 100 if exits else 0.0,
            "total_pnl": total_pnl,
            "total_fees": total_fees,
            "total_funding": total_funding,
            "net_pnl": total_pnl - total_fees - total_funding,
        }
