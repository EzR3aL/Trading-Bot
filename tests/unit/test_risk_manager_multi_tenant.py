"""
Unit tests for multi-tenant RiskManager isolation.

Tests that risk managers for different users/bots maintain
separate state and don't interfere with each other.
"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path

# Set up test environment
import base64
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-purposes-only-32chars"
test_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ["ENCRYPTION_MASTER_KEY"] = test_key

from src.risk.risk_manager import RiskManager, DailyStats


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestMultiTenantIsolation:
    """Tests for multi-tenant isolation."""

    def test_separate_data_directories(self, temp_data_dir):
        """Test that different users get separate data directories."""
        rm1 = RiskManager(
            user_id=1,
            bot_instance_id=1,
            data_dir=temp_data_dir,
        )
        rm2 = RiskManager(
            user_id=2,
            bot_instance_id=1,
            data_dir=temp_data_dir,
        )

        assert rm1.data_dir != rm2.data_dir
        assert "user_1" in str(rm1.data_dir)
        assert "user_2" in str(rm2.data_dir)

    def test_same_user_different_bots(self, temp_data_dir):
        """Test that different bots for same user get separate directories."""
        rm1 = RiskManager(
            user_id=1,
            bot_instance_id=1,
            data_dir=temp_data_dir,
        )
        rm2 = RiskManager(
            user_id=1,
            bot_instance_id=2,
            data_dir=temp_data_dir,
        )

        assert rm1.data_dir != rm2.data_dir
        assert "bot_1" in str(rm1.data_dir)
        assert "bot_2" in str(rm2.data_dir)

    def test_stats_isolation(self, temp_data_dir):
        """Test that daily stats are isolated between instances."""
        rm1 = RiskManager(
            user_id=1,
            bot_instance_id=1,
            data_dir=temp_data_dir,
            max_trades_per_day=5,
        )
        rm2 = RiskManager(
            user_id=2,
            bot_instance_id=1,
            data_dir=temp_data_dir,
            max_trades_per_day=10,
        )

        # Initialize days with different balances
        rm1.initialize_day(10000.0)
        rm2.initialize_day(20000.0)

        # User 1 records trades
        rm1.record_trade_entry(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=50000.0,
            leverage=5,
            confidence=75,
            reason="Test trade",
            order_id="order_1",
        )

        # User 2 should have no trades
        assert rm1.get_daily_stats().trades_executed == 1
        assert rm2.get_daily_stats().trades_executed == 0

    def test_config_per_instance(self, temp_data_dir):
        """Test that config is isolated per instance."""
        rm1 = RiskManager(
            user_id=1,
            bot_instance_id=1,
            data_dir=temp_data_dir,
            max_trades_per_day=5,
            daily_loss_limit_percent=3.0,
        )
        rm2 = RiskManager(
            user_id=2,
            bot_instance_id=1,
            data_dir=temp_data_dir,
            max_trades_per_day=10,
            daily_loss_limit_percent=5.0,
        )

        config1 = rm1.get_config()
        config2 = rm2.get_config()

        assert config1["user_id"] == 1
        assert config2["user_id"] == 2
        assert config1["max_trades_per_day"] == 5
        assert config2["max_trades_per_day"] == 10
        assert config1["daily_loss_limit_percent"] == 3.0
        assert config2["daily_loss_limit_percent"] == 5.0

    def test_trade_limits_independent(self, temp_data_dir):
        """Test that trade limits are independent between instances."""
        rm1 = RiskManager(
            user_id=1,
            bot_instance_id=1,
            data_dir=temp_data_dir,
            max_trades_per_day=2,
        )
        rm2 = RiskManager(
            user_id=2,
            bot_instance_id=1,
            data_dir=temp_data_dir,
            max_trades_per_day=2,
        )

        rm1.initialize_day(10000.0)
        rm2.initialize_day(10000.0)

        # User 1 hits their limit
        for i in range(2):
            rm1.record_trade_entry(
                symbol="BTCUSDT",
                side="long",
                size=0.01,
                entry_price=50000.0,
                leverage=5,
                confidence=75,
                reason=f"Trade {i+1}",
                order_id=f"order_{i+1}",
            )

        # User 1 cannot trade anymore
        can_trade_1, reason_1 = rm1.can_trade()
        assert not can_trade_1
        assert "limit" in reason_1.lower()

        # User 2 can still trade
        can_trade_2, reason_2 = rm2.can_trade()
        assert can_trade_2


class TestRiskStatus:
    """Tests for risk status API."""

    def test_get_risk_status(self, temp_data_dir):
        """Test getting comprehensive risk status."""
        rm = RiskManager(
            user_id=1,
            bot_instance_id=1,
            data_dir=temp_data_dir,
            max_trades_per_day=5,
            daily_loss_limit_percent=3.0,
        )
        rm.initialize_day(10000.0)

        status = rm.get_risk_status()

        assert status["can_trade"] is True
        assert status["config"]["user_id"] == 1
        assert status["config"]["bot_instance_id"] == 1
        assert status["remaining_trades"] == 5
        assert status["daily_stats"] is not None

    def test_update_config(self, temp_data_dir):
        """Test updating risk config dynamically."""
        rm = RiskManager(
            user_id=1,
            bot_instance_id=1,
            data_dir=temp_data_dir,
            max_trades_per_day=5,
        )

        rm.update_config(max_trades_per_day=10)
        assert rm.max_trades == 10

        rm.update_config(daily_loss_limit_percent=2.0)
        assert rm.daily_loss_limit == 2.0


class TestLegacyCompatibility:
    """Tests for backward compatibility without multi-tenant params."""

    def test_works_without_user_id(self, temp_data_dir):
        """Test that RiskManager works without user_id/bot_instance_id."""
        rm = RiskManager(
            data_dir=temp_data_dir,
            max_trades_per_day=5,
        )

        assert rm.user_id is None
        assert rm.bot_instance_id is None
        assert rm.data_dir == Path(temp_data_dir)

        rm.initialize_day(10000.0)
        can_trade, _ = rm.can_trade()
        assert can_trade is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
