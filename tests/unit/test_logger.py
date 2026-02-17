"""Tests for the logger utility."""

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.logger import get_logger, setup_logging, TradeLogger


class TestGetLogger:
    """Tests for get_logger."""

    def test_returns_logger_instance(self):
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_returns_same_logger(self):
        l1 = get_logger("same_name")
        l2 = get_logger("same_name")
        assert l1 is l2


class TestSetupLogging:
    """Tests for setup_logging."""

    @pytest.fixture(autouse=True)
    def _cleanup_handlers(self):
        """Close and remove file handlers after each test to avoid ResourceWarnings."""
        yield
        root = logging.getLogger()
        for h in list(root.handlers):
            if isinstance(h, logging.FileHandler):
                h.close()
                root.removeHandler(h)

    def test_setup_returns_root_logger(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logger = setup_logging(log_level="DEBUG", log_file=log_file)
        assert isinstance(logger, logging.Logger)
        assert logger.level == logging.DEBUG

    def test_setup_creates_log_directory(self, tmp_path):
        log_file = str(tmp_path / "subdir" / "test.log")
        setup_logging(log_file=log_file)
        assert Path(log_file).parent.exists()

    def test_setup_info_level(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logger = setup_logging(log_level="INFO", log_file=log_file)
        assert logger.level == logging.INFO

    def test_setup_warning_level(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logger = setup_logging(log_level="WARNING", log_file=log_file)
        assert logger.level == logging.WARNING

    def test_setup_adds_handlers(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logger = setup_logging(log_file=log_file)
        assert len(logger.handlers) == 2  # console + file

    def test_setup_clears_previous_handlers(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        setup_logging(log_file=log_file)
        setup_logging(log_file=log_file)
        root = logging.getLogger()
        assert len(root.handlers) == 2  # Should not accumulate


class TestTradeLogger:
    """Tests for TradeLogger."""

    def test_init_creates_directory(self, tmp_path):
        log_dir = str(tmp_path / "trade_logs")
        tl = TradeLogger(log_dir=log_dir)
        assert Path(log_dir).exists()

    def test_log_trade_entry(self, tmp_path):
        log_dir = str(tmp_path / "trade_logs")
        tl = TradeLogger(log_dir=log_dir)
        tl.log_trade_entry(
            symbol="BTCUSDT",
            side="long",
            size=0.001,
            entry_price=50000.0,
            leverage=10,
            confidence=85,
            reason="Strong signal",
            order_id="ORD001",
        )
        log_path = tl._get_trade_log_path()
        assert log_path.exists()
        with open(log_path, "r") as f:
            data = json.loads(f.readline())
        assert data["type"] == "ENTRY"
        assert data["symbol"] == "BTCUSDT"
        assert data["side"] == "LONG"
        assert data["size"] == 0.001

    def test_log_trade_exit(self, tmp_path):
        log_dir = str(tmp_path / "trade_logs")
        tl = TradeLogger(log_dir=log_dir)
        tl.log_trade_exit(
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3000.0,
            exit_price=2900.0,
            pnl=10.0,
            pnl_percent=3.33,
            fees=0.5,
            funding_paid=0.1,
            reason="Take profit",
            order_id="ORD002",
        )
        log_path = tl._get_trade_log_path()
        with open(log_path, "r") as f:
            data = json.loads(f.readline())
        assert data["type"] == "EXIT"
        assert data["pnl"] == 10.0
        assert data["exit_price"] == 2900.0

    def test_get_daily_trades_empty(self, tmp_path):
        log_dir = str(tmp_path / "trade_logs")
        tl = TradeLogger(log_dir=log_dir)
        trades = tl.get_daily_trades("2024-01-01")
        assert trades == []

    def test_get_daily_trades_with_data(self, tmp_path):
        log_dir = str(tmp_path / "trade_logs")
        tl = TradeLogger(log_dir=log_dir)
        # Write some entries
        tl.log_trade_entry(
            symbol="BTC", side="long", size=1, entry_price=50000,
            leverage=10, confidence=90, reason="test", order_id="1",
        )
        tl.log_trade_exit(
            symbol="BTC", side="long", size=1, entry_price=50000,
            exit_price=51000, pnl=100, pnl_percent=2.0, fees=1,
            funding_paid=0.5, reason="TP", order_id="2",
        )
        trades = tl.get_daily_trades()
        assert len(trades) == 2
        assert trades[0]["type"] == "ENTRY"
        assert trades[1]["type"] == "EXIT"

    def test_get_daily_stats_empty(self, tmp_path):
        log_dir = str(tmp_path / "trade_logs")
        tl = TradeLogger(log_dir=log_dir)
        stats = tl.get_daily_stats("2024-01-01")
        assert stats["total_trades"] == 0
        assert stats["net_pnl"] == 0.0

    def test_get_daily_stats_with_trades(self, tmp_path):
        log_dir = str(tmp_path / "trade_logs")
        tl = TradeLogger(log_dir=log_dir)
        # Write a winning and losing exit
        tl.log_trade_exit(
            symbol="BTC", side="long", size=1, entry_price=50000,
            exit_price=51000, pnl=100, pnl_percent=2.0, fees=5,
            funding_paid=1, reason="TP", order_id="1",
        )
        tl.log_trade_exit(
            symbol="ETH", side="short", size=1, entry_price=3000,
            exit_price=3100, pnl=-50, pnl_percent=-1.67, fees=3,
            funding_paid=0.5, reason="SL", order_id="2",
        )
        stats = tl.get_daily_stats()
        assert stats["total_trades"] == 2
        assert stats["winning_trades"] == 1
        assert stats["losing_trades"] == 1
        assert stats["win_rate"] == 50.0
        assert stats["total_pnl"] == 50.0
        assert stats["total_fees"] == 8.0
        assert stats["total_funding"] == 1.5
        assert stats["net_pnl"] == 50.0 - 8.0 - 1.5

    def test_get_trade_log_path(self, tmp_path):
        log_dir = str(tmp_path / "trade_logs")
        tl = TradeLogger(log_dir=log_dir)
        path = tl._get_trade_log_path()
        assert "trades_" in str(path)
        assert str(path).endswith(".log")
