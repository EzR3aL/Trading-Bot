"""
Logging configuration for the Bitget Trading Bot.
Provides colored console output and file logging.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import colorlog


def setup_logging(
    log_level: str = "INFO",
    log_file: str = "logs/trading_bot.log",
) -> logging.Logger:
    """
    Set up logging configuration with colored console output and file logging.

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

    # Console handler with colors
    console_handler = colorlog.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

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

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

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
