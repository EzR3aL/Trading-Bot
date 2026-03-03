"""
Extra unit tests for BotWorker to improve coverage from ~47% to 80%+.

Covers uncovered lines: initialize() full flow, _calculate_asset_budgets,
_analyze_symbol_locked, _execute_trade edge cases, _monitor_positions,
_check_position, _handle_closed_position, _check_rotation, _force_close_trade,
_get_notifiers, _get_discord_notifier, _check_referral_gate,
_check_builder_approval, and various error paths.
"""

import asyncio
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.bot_worker import BotWorker
from src.strategy.base import SignalDirection, TradeSignal


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_mock_config(**overrides):
    """Create a mock BotConfig with sensible defaults."""
    config = MagicMock()
    config.id = overrides.get("id", 1)
    config.user_id = overrides.get("user_id", 1)
    config.name = overrides.get("name", "Test Bot")
    config.description = overrides.get("description", "")
    config.strategy_type = overrides.get("strategy_type", "test_strategy")
    config.exchange_type = overrides.get("exchange_type", "bitget")
    config.mode = overrides.get("mode", "demo")
    config.trading_pairs = overrides.get("trading_pairs", json.dumps(["BTCUSDT"]))
    config.leverage = overrides.get("leverage", 4)
    config.position_size_percent = overrides.get("position_size_percent", 7.5)
    config.max_trades_per_day = overrides.get("max_trades_per_day", 2)
    config.take_profit_percent = overrides.get("take_profit_percent", 4.0)
    config.stop_loss_percent = overrides.get("stop_loss_percent", 1.5)
    config.daily_loss_limit_percent = overrides.get("daily_loss_limit_percent", 5.0)
    config.schedule_type = overrides.get("schedule_type", "market_sessions")
    config.schedule_config = overrides.get("schedule_config", None)
    config.strategy_params = overrides.get("strategy_params", None)
    config.discord_webhook_url = overrides.get("discord_webhook_url", None)
    config.telegram_bot_token = overrides.get("telegram_bot_token", None)
    config.telegram_chat_id = overrides.get("telegram_chat_id", None)
    config.rotation_enabled = overrides.get("rotation_enabled", False)
    config.rotation_interval_minutes = overrides.get("rotation_interval_minutes", None)
    config.rotation_start_time = overrides.get("rotation_start_time", None)
    config.is_enabled = overrides.get("is_enabled", True)
    config.per_asset_config = overrides.get("per_asset_config", None)
    config.whatsapp_phone_number_id = overrides.get("whatsapp_phone_number_id", None)
    config.whatsapp_access_token = overrides.get("whatsapp_access_token", None)
    config.whatsapp_recipient = overrides.get("whatsapp_recipient", None)
    return config


def _make_mock_balance(available=10000.0, total=10000.0):
    balance = MagicMock()
    balance.available = available
    balance.total = total
    balance.unrealized_pnl = 0
    return balance


def _make_mock_order(order_id="order_001", price=95000.0, side="long"):
    order = MagicMock()
    order.order_id = order_id
    order.price = price
    order.side = side
    order.status = "filled"
    return order


def _make_mock_signal(direction=SignalDirection.LONG, symbol="BTCUSDT",
                      entry_price=95000.0, target_price=97000.0,
                      stop_loss=94000.0, confidence=75):
    return TradeSignal(
        direction=direction,
        confidence=confidence,
        symbol=symbol,
        entry_price=entry_price,
        target_price=target_price,
        stop_loss=stop_loss,
        reason="Test signal",
        metrics_snapshot={"test": True},
        timestamp=datetime.now(timezone.utc),
    )


def _make_mock_trade(**overrides):
    """Create a mock TradeRecord."""
    trade = MagicMock()
    trade.id = overrides.get("id", 1)
    trade.bot_config_id = overrides.get("bot_config_id", 1)
    trade.user_id = overrides.get("user_id", 1)
    trade.symbol = overrides.get("symbol", "BTCUSDT")
    trade.side = overrides.get("side", "long")
    trade.size = overrides.get("size", 0.01)
    trade.entry_price = overrides.get("entry_price", 95000.0)
    trade.exit_price = overrides.get("exit_price", None)
    trade.take_profit = overrides.get("take_profit", 97000.0)
    trade.stop_loss = overrides.get("stop_loss", 94000.0)
    trade.leverage = overrides.get("leverage", 4)
    trade.confidence = overrides.get("confidence", 75)
    trade.reason = overrides.get("reason", "Test")
    trade.order_id = overrides.get("order_id", "order_001")
    trade.close_order_id = overrides.get("close_order_id", None)
    trade.status = overrides.get("status", "open")
    trade.pnl = overrides.get("pnl", None)
    trade.pnl_percent = overrides.get("pnl_percent", None)
    trade.fees = overrides.get("fees", 0)
    trade.funding_paid = overrides.get("funding_paid", 0)
    trade.builder_fee = overrides.get("builder_fee", 0)
    trade.entry_time = overrides.get("entry_time", datetime.now(timezone.utc) - timedelta(hours=1))
    trade.exit_time = overrides.get("exit_time", None)
    trade.exit_reason = overrides.get("exit_reason", None)
    trade.demo_mode = overrides.get("demo_mode", True)
    trade.exchange = overrides.get("exchange", "bitget")
    return trade


def _make_db_session():
    """Create a mock DB session with sync methods (add, delete, etc.) as MagicMock."""
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    return session


def _mock_session_ctx(mock_session):
    """Return a context manager that yields mock_session."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Initialize full flow tests (lines 111-243)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestInitializeFullFlow:
    """Tests for the full initialize() method including exchange client creation."""

    async def test_initialize_demo_mode_success(self):
        """Full init flow for demo mode with all components."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="demo")
        conn = MagicMock()
        conn.demo_api_key_encrypted = "enc_key"
        conn.demo_api_secret_encrypted = "enc_secret"
        conn.demo_passphrase_encrypted = "enc_pass"

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        mock_client = AsyncMock()
        mock_client.get_account_balance = AsyncMock(return_value=_make_mock_balance())

        mock_strategy = MagicMock()

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.bot_worker.create_exchange_client", return_value=mock_client), \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"), \
             patch("src.bot.bot_worker.StrategyRegistry") as mock_registry, \
             patch("src.bot.bot_worker.RiskManager") as mock_rm_cls:
            mock_registry.create.return_value = mock_strategy
            mock_rm_instance = MagicMock()
            mock_rm_cls.return_value = mock_rm_instance

            result = await worker.initialize()

        assert result is True
        assert worker._client is not None
        assert worker._demo_client is mock_client

    async def test_initialize_live_mode_success(self):
        """Full init flow for live mode."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="live")
        conn = MagicMock()
        conn.api_key_encrypted = "enc_key"
        conn.api_secret_encrypted = "enc_secret"
        conn.passphrase_encrypted = "enc_pass"
        conn.demo_api_key_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        mock_client = AsyncMock()
        mock_client.get_account_balance = AsyncMock(return_value=_make_mock_balance())

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.bot_worker.create_exchange_client", return_value=mock_client), \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"), \
             patch("src.bot.bot_worker.StrategyRegistry") as mock_registry, \
             patch("src.bot.bot_worker.RiskManager") as mock_rm_cls:
            mock_registry.create.return_value = MagicMock()
            mock_rm_cls.return_value = MagicMock()

            result = await worker.initialize()

        assert result is True
        assert worker._live_client is mock_client
        assert worker._client is mock_client

    async def test_initialize_both_mode_success(self):
        """Full init flow for both mode creates two clients."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="both")
        conn = MagicMock()
        conn.demo_api_key_encrypted = "enc_demo_key"
        conn.demo_api_secret_encrypted = "enc_demo_secret"
        conn.demo_passphrase_encrypted = None
        conn.api_key_encrypted = "enc_live_key"
        conn.api_secret_encrypted = "enc_live_secret"
        conn.passphrase_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        demo_client = AsyncMock()
        live_client = AsyncMock()
        clients = [demo_client, live_client]

        demo_client.get_account_balance = AsyncMock(return_value=_make_mock_balance())

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.bot_worker.create_exchange_client", side_effect=clients), \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"), \
             patch("src.bot.bot_worker.StrategyRegistry") as mock_registry, \
             patch("src.bot.bot_worker.RiskManager") as mock_rm_cls:
            mock_registry.create.return_value = MagicMock()
            mock_rm_cls.return_value = MagicMock()

            result = await worker.initialize()

        assert result is True
        assert worker._demo_client is demo_client
        assert worker._live_client is live_client
        # Primary client should be demo when both exist
        assert worker._client is demo_client

    async def test_initialize_demo_mode_missing_demo_keys(self):
        """Demo mode fails when demo API keys are missing."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="demo")
        conn = MagicMock()
        conn.demo_api_key_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)):
            result = await worker.initialize()

        assert result is False
        assert "demo API keys" in worker.error_message

    async def test_initialize_live_mode_missing_live_keys(self):
        """Live mode fails when live API keys are missing."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="live")
        conn = MagicMock()
        conn.api_key_encrypted = None
        conn.demo_api_key_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)):
            result = await worker.initialize()

        assert result is False
        assert "live API keys" in worker.error_message

    async def test_initialize_llm_strategy_loads_api_key(self):
        """LLM strategy type loads LLM connection for API key injection."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="demo", strategy_type="llm_signal")
        conn = MagicMock()
        conn.demo_api_key_encrypted = "enc_key"
        conn.demo_api_secret_encrypted = "enc_secret"
        conn.demo_passphrase_encrypted = None

        llm_conn = MagicMock()
        llm_conn.api_key_encrypted = "enc_llm_key"

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            elif call_count == 3:
                result.scalar_one_or_none.return_value = llm_conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        mock_client = AsyncMock()
        mock_client.get_account_balance = AsyncMock(return_value=_make_mock_balance())

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.bot_worker.create_exchange_client", return_value=mock_client), \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"), \
             patch("src.bot.bot_worker.StrategyRegistry") as mock_registry, \
             patch("src.bot.bot_worker.RiskManager") as mock_rm_cls:
            mock_registry.create.return_value = MagicMock()
            mock_rm_cls.return_value = MagicMock()

            result = await worker.initialize()

        assert result is True

    async def test_initialize_llm_strategy_no_llm_connection(self):
        """LLM strategy fails when no LLM connection exists."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="demo", strategy_type="llm_signal")
        conn = MagicMock()
        conn.demo_api_key_encrypted = "enc_key"
        conn.demo_api_secret_encrypted = "enc_secret"
        conn.demo_passphrase_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            elif call_count == 3:
                result.scalar_one_or_none.return_value = None
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        mock_client = AsyncMock()

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.bot_worker.create_exchange_client", return_value=mock_client), \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"):
            result = await worker.initialize()

        assert result is False
        assert "LLM provider" in worker.error_message

    async def test_initialize_with_strategy_params_json(self):
        """Strategy params are parsed from JSON."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(
            mode="demo",
            strategy_params=json.dumps({"lookback": 14}),
        )
        conn = MagicMock()
        conn.demo_api_key_encrypted = "enc_key"
        conn.demo_api_secret_encrypted = "enc_secret"
        conn.demo_passphrase_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        mock_client = AsyncMock()
        mock_client.get_account_balance = AsyncMock(return_value=_make_mock_balance())

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.bot_worker.create_exchange_client", return_value=mock_client), \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"), \
             patch("src.bot.bot_worker.StrategyRegistry") as mock_registry, \
             patch("src.bot.bot_worker.RiskManager") as mock_rm_cls:
            mock_registry.create.return_value = MagicMock()
            mock_rm_cls.return_value = MagicMock()

            result = await worker.initialize()

        assert result is True
        # Verify strategy was created with merged params
        call_args = mock_registry.create.call_args
        params = call_args[1]["params"]
        assert params["lookback"] == 14

    async def test_initialize_with_per_asset_config(self):
        """Per-asset config is parsed and passed to RiskManager."""
        worker = BotWorker(bot_config_id=1)
        per_asset = json.dumps({
            "BTCUSDT": {"max_trades": 3, "loss_limit": 2.5},
            "ETHUSDT": {"max_trades": 5},
        })
        config = _make_mock_config(mode="demo", per_asset_config=per_asset)
        conn = MagicMock()
        conn.demo_api_key_encrypted = "enc_key"
        conn.demo_api_secret_encrypted = "enc_secret"
        conn.demo_passphrase_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        mock_client = AsyncMock()
        mock_client.get_account_balance = AsyncMock(return_value=_make_mock_balance())

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.bot_worker.create_exchange_client", return_value=mock_client), \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"), \
             patch("src.bot.bot_worker.StrategyRegistry") as mock_registry, \
             patch("src.bot.bot_worker.RiskManager") as mock_rm_cls:
            mock_registry.create.return_value = MagicMock()
            mock_rm_cls.return_value = MagicMock()

            result = await worker.initialize()

        assert result is True
        rm_call_kwargs = mock_rm_cls.call_args[1]
        assert rm_call_kwargs["per_symbol_limits"] is not None
        assert "BTCUSDT" in rm_call_kwargs["per_symbol_limits"]

    async def test_initialize_per_asset_config_invalid_json(self):
        """Invalid per-asset config JSON is handled gracefully."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="demo", per_asset_config="{invalid json}")
        conn = MagicMock()
        conn.demo_api_key_encrypted = "enc_key"
        conn.demo_api_secret_encrypted = "enc_secret"
        conn.demo_passphrase_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        mock_client = AsyncMock()
        mock_client.get_account_balance = AsyncMock(return_value=_make_mock_balance())

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.bot_worker.create_exchange_client", return_value=mock_client), \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"), \
             patch("src.bot.bot_worker.StrategyRegistry") as mock_registry, \
             patch("src.bot.bot_worker.RiskManager") as mock_rm_cls:
            mock_registry.create.return_value = MagicMock()
            mock_rm_cls.return_value = MagicMock()

            result = await worker.initialize()

        assert result is True

    async def test_initialize_balance_fetch_fails_uses_zero(self):
        """When balance fetch fails, initialize_day is called with 0."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="demo")
        conn = MagicMock()
        conn.demo_api_key_encrypted = "enc_key"
        conn.demo_api_secret_encrypted = "enc_secret"
        conn.demo_passphrase_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        mock_client = AsyncMock()
        mock_client.get_account_balance = AsyncMock(side_effect=Exception("Network error"))

        mock_rm = MagicMock()

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.bot_worker.create_exchange_client", return_value=mock_client), \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"), \
             patch("src.bot.bot_worker.StrategyRegistry") as mock_registry, \
             patch("src.bot.bot_worker.RiskManager", return_value=mock_rm):
            mock_registry.create.return_value = MagicMock()

            result = await worker.initialize()

        assert result is True
        mock_rm.initialize_day.assert_called_with(0)

    async def test_initialize_generic_exception_sets_error(self):
        """Generic exception during initialization sets error status."""
        worker = BotWorker(bot_config_id=1)

        with patch("src.bot.bot_worker.get_session", side_effect=Exception("DB down")):
            result = await worker.initialize()

        assert result is False
        assert worker.status == "error"
        assert "DB down" in worker.error_message


# ---------------------------------------------------------------------------
# _calculate_asset_budgets tests (lines 363-402)
# ---------------------------------------------------------------------------

class TestCalculateAssetBudgets:
    """Tests for the _calculate_asset_budgets method."""

    def test_equal_split_no_per_asset_config(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(per_asset_config=None)

        budgets = worker._calculate_asset_budgets(10000.0, ["BTCUSDT", "ETHUSDT"])

        assert budgets["BTCUSDT"] == 5000.0
        assert budgets["ETHUSDT"] == 5000.0

    def test_fixed_position_pct(self):
        per_asset = json.dumps({
            "BTCUSDT": {"position_pct": 60},
            "ETHUSDT": {"position_pct": 40},
        })
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(per_asset_config=per_asset)

        budgets = worker._calculate_asset_budgets(10000.0, ["BTCUSDT", "ETHUSDT"])

        assert budgets["BTCUSDT"] == 6000.0
        assert budgets["ETHUSDT"] == 4000.0

    def test_mixed_fixed_and_unfixed(self):
        per_asset = json.dumps({
            "BTCUSDT": {"position_pct": 70},
        })
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(per_asset_config=per_asset)

        budgets = worker._calculate_asset_budgets(10000.0, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

        assert budgets["BTCUSDT"] == 7000.0
        assert budgets["ETHUSDT"] == 1500.0
        assert budgets["SOLUSDT"] == 1500.0

    def test_invalid_json_per_asset_config(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(per_asset_config="{invalid}")

        budgets = worker._calculate_asset_budgets(10000.0, ["BTCUSDT"])

        assert budgets["BTCUSDT"] == 10000.0

    def test_per_asset_config_as_dict(self):
        """When per_asset_config is already a dict (not a string)."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            per_asset_config={"BTCUSDT": {"position_pct": 50}},
        )

        budgets = worker._calculate_asset_budgets(10000.0, ["BTCUSDT", "ETHUSDT"])

        assert budgets["BTCUSDT"] == 5000.0
        assert budgets["ETHUSDT"] == 5000.0

    def test_zero_position_pct_treated_as_unfixed(self):
        per_asset = json.dumps({"BTCUSDT": {"position_pct": 0}})
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(per_asset_config=per_asset)

        budgets = worker._calculate_asset_budgets(10000.0, ["BTCUSDT"])

        assert budgets["BTCUSDT"] == 10000.0


# ---------------------------------------------------------------------------
# _analyze_symbol_locked tests (lines 453-486)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAnalyzeSymbolLocked:
    """Tests for _analyze_symbol_locked."""

    async def test_skips_when_open_position_exists(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._strategy = AsyncMock()
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, "")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = _make_mock_trade()

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._analyze_symbol_locked("BTCUSDT")

        worker._strategy.generate_signal.assert_not_awaited()

    async def test_generates_signal_when_no_open_position(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, "")

        mock_strategy = AsyncMock()
        mock_strategy.generate_signal.return_value = _make_mock_signal()
        mock_strategy.should_trade.return_value = (False, "Signal too weak")
        worker._strategy = mock_strategy

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._analyze_symbol_locked("BTCUSDT")

        mock_strategy.generate_signal.assert_awaited_once()

    async def test_force_skips_position_check(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, "")

        mock_strategy = AsyncMock()
        mock_strategy.generate_signal.return_value = _make_mock_signal()
        mock_strategy.should_trade.return_value = (False, "Signal too weak")
        worker._strategy = mock_strategy

        # No get_session needed when force=True
        await worker._analyze_symbol_locked("BTCUSDT", force=True)

        mock_strategy.generate_signal.assert_awaited_once()

    async def test_executes_on_demo_client(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(mode="demo")
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, "")

        signal = _make_mock_signal()
        mock_strategy = AsyncMock()
        mock_strategy.generate_signal.return_value = signal
        mock_strategy.should_trade.return_value = (True, "OK")
        worker._strategy = mock_strategy

        worker._demo_client = AsyncMock()
        worker._execute_trade = AsyncMock()

        await worker._analyze_symbol_locked("BTCUSDT", force=True)

        worker._execute_trade.assert_any_await(signal, worker._demo_client, demo_mode=True, asset_budget=None)

    async def test_executes_on_both_clients(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(mode="both")
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, "")

        signal = _make_mock_signal()
        mock_strategy = AsyncMock()
        mock_strategy.generate_signal.return_value = signal
        mock_strategy.should_trade.return_value = (True, "OK")
        worker._strategy = mock_strategy

        worker._demo_client = AsyncMock()
        worker._live_client = AsyncMock()
        worker._execute_trade = AsyncMock()

        await worker._analyze_symbol_locked("BTCUSDT", force=True)

        assert worker._execute_trade.await_count == 2

    async def test_executes_on_live_client_only(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(mode="live")
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, "")

        signal = _make_mock_signal()
        mock_strategy = AsyncMock()
        mock_strategy.generate_signal.return_value = signal
        mock_strategy.should_trade.return_value = (True, "OK")
        worker._strategy = mock_strategy

        worker._live_client = AsyncMock()
        worker._demo_client = None
        worker._execute_trade = AsyncMock()

        await worker._analyze_symbol_locked("BTCUSDT", force=True)

        worker._execute_trade.assert_awaited_once()

    async def test_passes_asset_budget(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(mode="demo")
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, "")

        signal = _make_mock_signal()
        mock_strategy = AsyncMock()
        mock_strategy.generate_signal.return_value = signal
        mock_strategy.should_trade.return_value = (True, "OK")
        worker._strategy = mock_strategy

        worker._demo_client = AsyncMock()
        worker._execute_trade = AsyncMock()

        await worker._analyze_symbol_locked("BTCUSDT", force=True, asset_budget=5000.0)

        worker._execute_trade.assert_awaited_once_with(
            signal, worker._demo_client, demo_mode=True, asset_budget=5000.0
        )


# ---------------------------------------------------------------------------
# _execute_trade extended tests (lines 499-504, 514-522, 527, 535-536, 575-576, 622-647)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExecuteTradeExtended:
    """Extended tests for _execute_trade covering per-asset config, TP/SL overrides, etc."""

    async def test_per_asset_config_leverage_override(self):
        """Per-asset leverage overrides global leverage."""
        worker = BotWorker(bot_config_id=1)
        per_asset = json.dumps({"BTCUSDT": {"leverage": 10}})
        worker._config = _make_mock_config(per_asset_config=per_asset, leverage=4)
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.place_market_order.return_value = _make_mock_order()
        mock_client.get_fill_price.return_value = 95100.0

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        mock_session = _make_db_session()
        with patch("src.bot.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, mock_client, demo_mode=True)

        # Verify leverage 10 was used
        mock_client.set_leverage.assert_awaited_once()
        args, kwargs = mock_client.set_leverage.call_args
        assert args == ("BTCUSDT", 10)

    async def test_tp_sl_passthrough_from_config(self):
        """User-configured TP/SL from bot config is sent to exchange."""
        worker = BotWorker(bot_config_id=1)
        per_asset = json.dumps({"BTCUSDT": {"tp": 5, "sl": 2}})
        worker._config = _make_mock_config(per_asset_config=per_asset)
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.place_market_order.return_value = _make_mock_order()
        mock_client.get_fill_price.return_value = 95100.0

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        # Signal comes in with TP/SL set by strategy (overridden by config)
        signal = _make_mock_signal(direction=SignalDirection.LONG, entry_price=100000.0)
        signal.target_price = 105000.0
        signal.stop_loss = 98000.0

        mock_session = _make_db_session()
        with patch("src.bot.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, mock_client, demo_mode=True)

        # Bot-level TP=4%, SL=1.5% → TP/SL sent to exchange (not cleared)
        call_kwargs = mock_client.place_market_order.call_args[1]
        assert call_kwargs["take_profit"] == pytest.approx(104000.0)  # 100000 * 1.04
        assert call_kwargs["stop_loss"] == pytest.approx(98500.0)     # 100000 * 0.985

    async def test_tp_sl_none_when_no_config(self):
        """Without TP/SL in config, None is passed to exchange."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            take_profit_percent=None,
            stop_loss_percent=None,
            per_asset_config=None,
        )
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.place_market_order.return_value = _make_mock_order()
        mock_client.get_fill_price.return_value = 95100.0

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal(
            direction=SignalDirection.LONG, entry_price=100000.0,
            target_price=None, stop_loss=None,
        )

        mock_session = _make_db_session()
        with patch("src.bot.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, mock_client, demo_mode=True)

        call_kwargs = mock_client.place_market_order.call_args[1]
        assert call_kwargs["take_profit"] is None
        assert call_kwargs["stop_loss"] is None

    async def test_asset_budget_full_budget_mode(self):
        """When asset_budget is set and position_size_percent is None, use full budget."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(position_size_percent=None)
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        mock_client.place_market_order.return_value = _make_mock_order()
        mock_client.get_fill_price.return_value = 95100.0

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        worker._risk_manager = mock_rm

        signal = _make_mock_signal(entry_price=95000.0)

        mock_session = _make_db_session()
        with patch("src.bot.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, mock_client, demo_mode=True, asset_budget=5000.0)

        # Full budget: position_usdt = 5000, should not call calculate_position_size
        mock_rm.calculate_position_size.assert_not_called()

    async def test_asset_budget_always_uses_direct_sizing(self):
        """When asset_budget is set, always use direct sizing (even if position_size_percent exists)."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(position_size_percent=7.5)
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        mock_client.place_market_order.return_value = _make_mock_order()
        mock_client.get_fill_price.return_value = 95100.0

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        mock_session = _make_db_session()
        with patch("src.bot.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, mock_client, demo_mode=True, asset_budget=5000.0)

        # asset_budget takes priority — direct sizing, no RiskManager call
        mock_rm.calculate_position_size.assert_not_called()

    async def test_fill_price_fallback_when_fetch_fails(self):
        """When get_fill_price fails, falls back to order price or entry price."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.place_market_order.return_value = _make_mock_order(price=95500.0)
        mock_client.get_fill_price.side_effect = Exception("API error")

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        mock_session = _make_db_session()
        with patch("src.bot.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, mock_client, demo_mode=True)

        # Trade should still be recorded with order.price as fill
        mock_rm.record_trade_entry.assert_called_once()

    async def test_notification_dispatch_with_discord(self):
        """Notifications are sent when configured."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_notifier = AsyncMock()
        mock_notifier.__aenter__ = AsyncMock(return_value=mock_notifier)
        mock_notifier.__aexit__ = AsyncMock(return_value=False)
        worker._get_notifiers = AsyncMock(return_value=[mock_notifier])

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.place_market_order.return_value = _make_mock_order()
        mock_client.get_fill_price.return_value = 95100.0

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        mock_session = _make_db_session()
        with patch("src.bot.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, mock_client, demo_mode=True)

        mock_notifier.send_trade_entry.assert_awaited_once()

    async def test_notification_failure_does_not_crash(self):
        """Notification errors are caught and logged."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_notifier = AsyncMock()
        mock_notifier.__aenter__ = AsyncMock(return_value=mock_notifier)
        mock_notifier.__aexit__ = AsyncMock(return_value=False)
        mock_notifier.send_trade_entry.side_effect = Exception("Discord down")
        worker._get_notifiers = AsyncMock(return_value=[mock_notifier])

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.place_market_order.return_value = _make_mock_order()
        mock_client.get_fill_price.return_value = 95100.0

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        mock_session = _make_db_session()
        with patch("src.bot.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, mock_client, demo_mode=True)

        # Trade should still be recorded even though notification failed
        assert worker.trades_today == 1

    async def test_get_notifiers_setup_failure(self):
        """_get_notifiers error is caught in _execute_trade."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(side_effect=Exception("Notifier setup failed"))

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.place_market_order.return_value = _make_mock_order()
        mock_client.get_fill_price.return_value = 95100.0

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        mock_session = _make_db_session()
        with patch("src.bot.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, mock_client, demo_mode=True)

        assert worker.trades_today == 1

    async def test_generic_execution_error(self):
        """Non-minimum-amount errors are logged as trade execution failure."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.set_leverage.side_effect = Exception("Exchange unreachable")

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        await worker._execute_trade(signal, mock_client, demo_mode=True)

        assert worker.trades_today == 0

    async def test_per_asset_config_invalid_json_in_execute(self):
        """Invalid per_asset_config JSON is handled in _execute_trade."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(per_asset_config="{broken}")
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.place_market_order.return_value = _make_mock_order()
        mock_client.get_fill_price.return_value = None

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        mock_session = _make_db_session()
        with patch("src.bot.trade_executor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._execute_trade(signal, mock_client, demo_mode=True)

        assert worker.trades_today == 1


# ---------------------------------------------------------------------------
# _monitor_positions and _check_position tests (lines 671-694)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMonitorAndCheckPosition:
    """Tests for _monitor_positions and _check_position."""

    async def test_monitor_iterates_open_trades(self):
        worker = BotWorker(bot_config_id=1)
        trade1 = _make_mock_trade(id=1)
        trade2 = _make_mock_trade(id=2)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade1, trade2]

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        worker._check_position = AsyncMock()

        with patch("src.bot.position_monitor.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._monitor_positions()

        assert worker._check_position.await_count == 2

    async def test_check_position_no_client(self):
        """When no client available for trade mode, returns early."""
        worker = BotWorker(bot_config_id=1)
        worker._demo_client = None
        worker._live_client = None

        trade = _make_mock_trade(demo_mode=True)
        session = AsyncMock()

        await worker._check_position(trade, session)
        # Should not raise

    async def test_check_position_position_still_open(self):
        """When position exists on exchange, no closure handling."""
        worker = BotWorker(bot_config_id=1)
        mock_client = AsyncMock()
        position = MagicMock()
        position.side = "long"
        mock_client.get_position.return_value = position
        worker._demo_client = mock_client

        trade = _make_mock_trade(demo_mode=True, side="long")
        session = AsyncMock()

        worker._handle_closed_position = AsyncMock()

        await worker._check_position(trade, session)

        worker._handle_closed_position.assert_not_awaited()

    async def test_check_position_position_closed_on_exchange(self):
        """When position is None, handle as closed."""
        worker = BotWorker(bot_config_id=1)
        mock_client = AsyncMock()
        mock_client.get_position.return_value = None
        worker._demo_client = mock_client

        trade = _make_mock_trade(demo_mode=True)
        session = AsyncMock()

        worker._handle_closed_position = AsyncMock()

        await worker._check_position(trade, session)

        worker._handle_closed_position.assert_awaited_once_with(trade, mock_client, session)

    async def test_check_position_side_mismatch(self):
        """When position side doesn't match trade side, treat as closed."""
        worker = BotWorker(bot_config_id=1)
        mock_client = AsyncMock()
        position = MagicMock()
        position.side = "short"
        mock_client.get_position.return_value = position
        worker._demo_client = mock_client

        trade = _make_mock_trade(demo_mode=True, side="long")
        session = AsyncMock()

        worker._handle_closed_position = AsyncMock()

        await worker._check_position(trade, session)

        worker._handle_closed_position.assert_awaited_once()

    async def test_check_position_exchange_error(self):
        """Exchange error during position check is caught."""
        worker = BotWorker(bot_config_id=1)
        mock_client = AsyncMock()
        mock_client.get_position.side_effect = Exception("Exchange error")
        worker._demo_client = mock_client

        trade = _make_mock_trade(demo_mode=True)
        session = AsyncMock()

        # Should not raise
        await worker._check_position(trade, session)

    async def test_check_position_uses_live_client(self):
        """Live trades use the live client."""
        worker = BotWorker(bot_config_id=1)
        mock_live = AsyncMock()
        mock_live.get_position.return_value = None
        worker._demo_client = None
        worker._live_client = mock_live

        trade = _make_mock_trade(demo_mode=False)
        session = AsyncMock()
        worker._handle_closed_position = AsyncMock()

        await worker._check_position(trade, session)

        mock_live.get_position.assert_awaited_once()
        worker._handle_closed_position.assert_awaited_once()


# ---------------------------------------------------------------------------
# _handle_closed_position tests (lines 698-817)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHandleClosedPosition:
    """Tests for _handle_closed_position."""

    async def test_long_trade_profit_take_profit_hit(self):
        """Long trade closed near take profit is labeled TAKE_PROFIT."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        ticker = MagicMock()
        ticker.last_price = 97000.0
        mock_client.get_ticker.return_value = ticker
        mock_client.get_trade_total_fees.return_value = 5.0
        mock_client.get_funding_fees.return_value = 1.0

        trade = _make_mock_trade(
            side="long", entry_price=95000.0, take_profit=97000.0,
            stop_loss=94000.0, size=0.01, order_id="o1",
        )
        # Remove calculate_builder_fee from the client mock
        del mock_client.calculate_builder_fee

        session = AsyncMock()

        await worker._handle_closed_position(trade, mock_client, session)

        assert trade.status == "closed"
        assert trade.exit_reason == "TAKE_PROFIT"
        assert trade.pnl > 0
        mock_rm.record_trade_exit.assert_called_once()

    async def test_short_trade_stop_loss_hit(self):
        """Short trade closed near stop loss is labeled STOP_LOSS."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        ticker = MagicMock()
        ticker.last_price = 96000.0
        mock_client.get_ticker.return_value = ticker
        mock_client.get_trade_total_fees.return_value = 3.0
        mock_client.get_funding_fees.return_value = 0.5
        del mock_client.calculate_builder_fee

        trade = _make_mock_trade(
            side="short", entry_price=95000.0, take_profit=93000.0,
            stop_loss=96000.0, size=0.01, order_id="o1",
        )
        session = AsyncMock()

        await worker._handle_closed_position(trade, mock_client, session)

        assert trade.exit_reason == "STOP_LOSS"
        assert trade.pnl < 0

    async def test_external_close(self):
        """Trade closed at price far from TP/SL is labeled EXTERNAL_CLOSE."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        ticker = MagicMock()
        ticker.last_price = 95500.0  # Between TP and SL, far from both
        mock_client.get_ticker.return_value = ticker
        mock_client.get_trade_total_fees.return_value = 2.0
        mock_client.get_funding_fees.return_value = 0.0
        del mock_client.calculate_builder_fee

        trade = _make_mock_trade(
            side="long", entry_price=95000.0, take_profit=97000.0,
            stop_loss=93000.0, size=0.01, order_id="o1",
        )
        session = AsyncMock()

        await worker._handle_closed_position(trade, mock_client, session)

        assert trade.exit_reason == "EXTERNAL_CLOSE"

    async def test_no_ticker_uses_entry_price(self):
        """When ticker is None, uses entry_price as exit_price."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.get_ticker.return_value = None
        mock_client.get_trade_total_fees.return_value = 0
        mock_client.get_funding_fees.return_value = 0
        del mock_client.calculate_builder_fee

        trade = _make_mock_trade(side="long", entry_price=95000.0, size=0.01, order_id="o1")
        session = AsyncMock()

        await worker._handle_closed_position(trade, mock_client, session)

        assert trade.exit_price == 95000.0
        assert trade.pnl == 0.0

    async def test_fees_fetch_error_sets_zero(self):
        """When fee fetching fails, fees are set to 0."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        ticker = MagicMock()
        ticker.last_price = 96000.0
        mock_client.get_ticker.return_value = ticker
        mock_client.get_trade_total_fees.side_effect = Exception("API error")
        mock_client.get_funding_fees.side_effect = Exception("API error")
        del mock_client.calculate_builder_fee

        trade = _make_mock_trade(side="long", order_id="o1")
        session = AsyncMock()

        await worker._handle_closed_position(trade, mock_client, session)

        assert trade.fees == 0
        assert trade.funding_paid == 0
        assert trade.status == "closed"

    async def test_builder_fee_calculation(self):
        """Builder fee is calculated when client has the method."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        ticker = MagicMock()
        ticker.last_price = 96000.0
        mock_client.get_ticker.return_value = ticker
        mock_client.get_trade_total_fees.return_value = 5.0
        mock_client.get_funding_fees.return_value = 1.0
        mock_client.calculate_builder_fee = MagicMock(return_value=2.5)

        trade = _make_mock_trade(side="long", order_id="o1")
        session = AsyncMock()

        await worker._handle_closed_position(trade, mock_client, session)

        assert trade.builder_fee == 2.5

    async def test_handle_closed_exception(self):
        """General exception in _handle_closed_position is caught."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_client = AsyncMock()
        mock_client.get_ticker.side_effect = Exception("Network error")

        trade = _make_mock_trade()
        session = AsyncMock()

        # Should not raise
        await worker._handle_closed_position(trade, mock_client, session)

    async def test_notification_on_close(self):
        """Notification is sent on position close."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_notifier = AsyncMock()
        mock_notifier.__aenter__ = AsyncMock(return_value=mock_notifier)
        mock_notifier.__aexit__ = AsyncMock(return_value=False)
        worker._get_notifiers = AsyncMock(return_value=[mock_notifier])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        ticker = MagicMock()
        ticker.last_price = 96000.0
        mock_client.get_ticker.return_value = ticker
        mock_client.get_trade_total_fees.return_value = 0
        mock_client.get_funding_fees.return_value = 0
        del mock_client.calculate_builder_fee

        trade = _make_mock_trade(side="long", order_id="o1")
        session = AsyncMock()

        await worker._handle_closed_position(trade, mock_client, session)

        mock_notifier.send_trade_exit.assert_awaited_once()

    async def test_trade_without_entry_time_skips_funding(self):
        """Trade without entry_time skips funding fee fetch."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        ticker = MagicMock()
        ticker.last_price = 96000.0
        mock_client.get_ticker.return_value = ticker
        mock_client.get_trade_total_fees.return_value = 0
        del mock_client.calculate_builder_fee

        trade = _make_mock_trade(side="long", entry_time=None, order_id="o1")
        session = AsyncMock()

        await worker._handle_closed_position(trade, mock_client, session)

        mock_client.get_funding_fees.assert_not_awaited()


# ---------------------------------------------------------------------------
# _check_rotation tests (lines 823-936)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCheckRotation:
    """Tests for _check_rotation."""

    async def test_rotation_safe_catches_errors(self):
        worker = BotWorker(bot_config_id=1)
        worker._check_rotation = AsyncMock(side_effect=RuntimeError("boom"))

        await worker._check_rotation_safe()
        # Should not raise

    async def test_no_rotation_when_not_configured(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(rotation_interval_minutes=None)

        await worker._check_rotation()
        # Should return early, no error

    async def test_no_open_trades_rotation_only_triggers_analysis(self):
        """In rotation_only mode with no open trades, triggers new analysis."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            schedule_type="rotation_only",
            rotation_interval_minutes=60,
            trading_pairs=json.dumps(["BTCUSDT"]),
        )

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        worker._client = mock_client

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        worker._analyze_symbol = AsyncMock()

        with patch("src.bot.rotation_manager.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._check_rotation()

        worker._analyze_symbol.assert_awaited_once()

    async def test_no_open_trades_non_rotation_mode_returns(self):
        """In non-rotation_only mode with no open trades, does nothing."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            schedule_type="interval",
            rotation_interval_minutes=60,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.bot.rotation_manager.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._check_rotation()

    async def test_elapsed_rotation_closes_and_reopens(self):
        """Trade older than rotation_interval is closed and re-analyzed."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            rotation_interval_minutes=60,
            rotation_start_time=None,
            trading_pairs=json.dumps(["BTCUSDT"]),
        )

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        worker._risk_manager = mock_rm

        # Trade opened 2 hours ago
        trade = _make_mock_trade(
            entry_time=datetime.now(timezone.utc) - timedelta(hours=2),
            demo_mode=True,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        worker._demo_client = mock_client

        worker._force_close_trade = AsyncMock(return_value=True)
        worker._analyze_symbol = AsyncMock()

        with patch("src.bot.rotation_manager.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._check_rotation()

        worker._force_close_trade.assert_awaited_once()
        worker._analyze_symbol.assert_awaited_once()

    async def test_anchored_rotation_should_rotate(self):
        """Anchored rotation: trade opened before last boundary should rotate."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            rotation_interval_minutes=60,
            rotation_start_time="00:00",
            trading_pairs=json.dumps(["BTCUSDT"]),
        )

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        worker._risk_manager = mock_rm

        # Trade opened 3 hours ago
        trade = _make_mock_trade(
            entry_time=datetime.now(timezone.utc) - timedelta(hours=3),
            demo_mode=True,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        worker._demo_client = mock_client

        worker._force_close_trade = AsyncMock(return_value=True)
        worker._analyze_symbol = AsyncMock()

        with patch("src.bot.rotation_manager.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._check_rotation()

        worker._force_close_trade.assert_awaited_once()

    async def test_rotation_risk_blocks_reopen(self):
        """After rotation close, risk check blocks re-opening."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            rotation_interval_minutes=60,
            rotation_start_time=None,
            trading_pairs=json.dumps(["BTCUSDT"]),
        )

        mock_rm = MagicMock()
        # First call for the loop check, second for reopen
        mock_rm.can_trade.side_effect = [(True, ""), (False, "Daily loss limit")]
        worker._risk_manager = mock_rm

        trade = _make_mock_trade(
            entry_time=datetime.now(timezone.utc) - timedelta(hours=2),
            demo_mode=True,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        worker._demo_client = AsyncMock()
        worker._force_close_trade = AsyncMock(return_value=True)
        worker._analyze_symbol = AsyncMock()

        with patch("src.bot.rotation_manager.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._check_rotation()

        worker._force_close_trade.assert_awaited_once()
        worker._analyze_symbol.assert_not_awaited()

    async def test_rotation_close_fails_skips_reopen(self):
        """When force_close_trade returns False, skip re-opening."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            rotation_interval_minutes=60,
            rotation_start_time=None,
        )

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        trade = _make_mock_trade(
            entry_time=datetime.now(timezone.utc) - timedelta(hours=2),
            demo_mode=True,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        worker._demo_client = AsyncMock()
        worker._force_close_trade = AsyncMock(return_value=False)
        worker._analyze_symbol = AsyncMock()

        with patch("src.bot.rotation_manager.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._check_rotation()

        worker._analyze_symbol.assert_not_awaited()

    async def test_rotation_trade_no_entry_time_skipped(self):
        """Trade without entry_time is skipped in rotation check."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(rotation_interval_minutes=60)

        trade = _make_mock_trade(entry_time=None)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        worker._force_close_trade = AsyncMock()

        with patch("src.bot.rotation_manager.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._check_rotation()

        worker._force_close_trade.assert_not_awaited()

    async def test_rotation_reanalysis_error_caught(self):
        """Error during re-analysis after rotation is caught."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            rotation_interval_minutes=60,
            trading_pairs=json.dumps(["BTCUSDT"]),
        )

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        worker._risk_manager = mock_rm

        trade = _make_mock_trade(
            entry_time=datetime.now(timezone.utc) - timedelta(hours=2),
            demo_mode=True,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_client = AsyncMock()
        mock_client.get_account_balance.side_effect = Exception("balance error")
        worker._demo_client = mock_client

        worker._force_close_trade = AsyncMock(return_value=True)

        with patch("src.bot.rotation_manager.get_session", return_value=_mock_session_ctx(mock_session)):
            await worker._check_rotation()

        # Should not raise despite the error


# ---------------------------------------------------------------------------
# _force_close_trade tests (lines 946-1074)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestForceCloseTrade:
    """Tests for _force_close_trade."""

    async def test_successful_close_with_order_price(self):
        """Successful force close uses order price for PnL."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        order = _make_mock_order(price=96000.0)
        mock_client = AsyncMock()
        mock_client.close_position.return_value = order

        trade = _make_mock_trade(side="long", entry_price=95000.0, size=0.01)
        session = AsyncMock()

        result = await worker._force_close_trade(trade, mock_client, session)

        assert result is True
        assert trade.status == "closed"
        assert trade.exit_reason == "ROTATION"
        assert trade.exit_price == 96000.0
        assert trade.pnl > 0

    async def test_close_position_returns_none_already_closed(self):
        """When close_position returns None, marks as ROTATION_ALREADY_CLOSED."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.close_position.return_value = None
        ticker = MagicMock()
        ticker.last_price = 96000.0
        mock_client.get_ticker.return_value = ticker

        trade = _make_mock_trade(side="long", entry_price=95000.0, size=0.01)
        session = AsyncMock()

        result = await worker._force_close_trade(trade, mock_client, session)

        assert result is True
        assert trade.exit_reason == "ROTATION_ALREADY_CLOSED"
        mock_rm.record_trade_exit.assert_called_once()

    async def test_close_position_none_ticker_fails(self):
        """When close returns None and ticker also fails, uses entry_price."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.close_position.return_value = None
        mock_client.get_ticker.side_effect = Exception("API error")

        trade = _make_mock_trade(side="short", entry_price=95000.0, size=0.01)
        session = AsyncMock()

        result = await worker._force_close_trade(trade, mock_client, session)

        assert result is True
        assert trade.exit_price == 95000.0
        assert trade.pnl == 0.0

    async def test_close_order_zero_price_uses_ticker(self):
        """When order.price is 0, falls back to ticker."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        order = _make_mock_order(price=0)
        mock_client = AsyncMock()
        mock_client.close_position.return_value = order
        ticker = MagicMock()
        ticker.last_price = 96500.0
        mock_client.get_ticker.return_value = ticker

        trade = _make_mock_trade(side="long", entry_price=95000.0, size=0.01)
        session = AsyncMock()

        result = await worker._force_close_trade(trade, mock_client, session)

        assert result is True
        assert trade.exit_price == 96500.0

    async def test_close_short_trade_pnl(self):
        """Short trade PnL is calculated correctly."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        order = _make_mock_order(price=94000.0)
        mock_client = AsyncMock()
        mock_client.close_position.return_value = order

        trade = _make_mock_trade(side="short", entry_price=95000.0, size=0.01)
        session = AsyncMock()

        result = await worker._force_close_trade(trade, mock_client, session)

        assert result is True
        # Short PnL: (entry - exit) * size = (95000 - 94000) * 0.01 = 10
        assert trade.pnl == 10.0

    async def test_no_position_error_marks_already_closed(self):
        """'no position' exchange error marks trade as ROTATION_ALREADY_CLOSED."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.close_position.side_effect = Exception("no position found")

        trade = _make_mock_trade()
        session = AsyncMock()

        result = await worker._force_close_trade(trade, mock_client, session)

        assert result is True
        assert trade.exit_reason == "ROTATION_ALREADY_CLOSED"
        assert trade.pnl == 0

    async def test_position_not_exist_error(self):
        """'position not exist' exchange error marks as ROTATION_ALREADY_CLOSED."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.close_position.side_effect = Exception("position not exist on exchange")

        trade = _make_mock_trade()
        session = AsyncMock()

        result = await worker._force_close_trade(trade, mock_client, session)

        assert result is True
        assert trade.exit_reason == "ROTATION_ALREADY_CLOSED"

    async def test_generic_close_error_returns_false(self):
        """Unknown error during force close returns False."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.close_position.side_effect = Exception("Unknown exchange error")

        trade = _make_mock_trade()
        session = AsyncMock()

        result = await worker._force_close_trade(trade, mock_client, session)

        assert result is False

    async def test_force_close_notification_on_success(self):
        """Notification is sent after successful rotation close."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_notifier = AsyncMock()
        mock_notifier.__aenter__ = AsyncMock(return_value=mock_notifier)
        mock_notifier.__aexit__ = AsyncMock(return_value=False)
        worker._get_notifiers = AsyncMock(return_value=[mock_notifier])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        order = _make_mock_order(price=96000.0)
        mock_client = AsyncMock()
        mock_client.close_position.return_value = order

        trade = _make_mock_trade(side="long", entry_price=95000.0, size=0.01)
        session = AsyncMock()

        result = await worker._force_close_trade(trade, mock_client, session)

        assert result is True
        mock_notifier.send_trade_exit.assert_awaited_once()

    async def test_force_close_notification_error_handled(self):
        """Notification error during force close does not crash."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_notifier = AsyncMock()
        mock_notifier.__aenter__ = AsyncMock(return_value=mock_notifier)
        mock_notifier.__aexit__ = AsyncMock(return_value=False)
        mock_notifier.send_trade_exit.side_effect = Exception("notif fail")
        worker._get_notifiers = AsyncMock(return_value=[mock_notifier])

        mock_rm = MagicMock()
        worker._risk_manager = mock_rm

        order = _make_mock_order(price=96000.0)
        mock_client = AsyncMock()
        mock_client.close_position.return_value = order

        trade = _make_mock_trade(side="long", entry_price=95000.0, size=0.01)
        session = AsyncMock()

        result = await worker._force_close_trade(trade, mock_client, session)

        assert result is True


# ---------------------------------------------------------------------------
# _get_notifiers and _get_discord_notifier tests (lines 1082-1083, 1091, 1094-1100)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetNotifiersExtended:
    """Extended tests for notifier loading."""

    async def test_discord_notifier_exception_returns_none(self):
        """Discord notifier creation error returns None."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(discord_webhook_url="enc_url")

        with patch("src.bot.notifications.decrypt_value", side_effect=Exception("Decrypt error")):
            result = await worker._get_discord_notifier()

        assert result is None

    async def test_telegram_notifier_loaded(self):
        """Telegram notifier is loaded when configured."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            discord_webhook_url=None,
            telegram_bot_token="enc_token",
            telegram_chat_id="123456",
        )

        mock_telegram_cls = MagicMock()
        mock_telegram_instance = MagicMock()
        mock_telegram_cls.return_value = mock_telegram_instance

        with patch("src.bot.notifications.decrypt_value", return_value="decrypted_token"), \
             patch("src.notifications.telegram_notifier.TelegramNotifier", mock_telegram_cls):
            notifiers = await worker._get_notifiers()

        assert len(notifiers) == 1

    async def test_telegram_notifier_exception_handled(self):
        """Telegram notifier creation error is handled."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            discord_webhook_url=None,
            telegram_bot_token="enc_token",
            telegram_chat_id="123456",
        )

        with patch("src.bot.notifications.decrypt_value", side_effect=Exception("Decrypt error")):
            notifiers = await worker._get_notifiers()

        assert notifiers == []

    async def test_both_notifiers_loaded(self):
        """Both Discord and Telegram notifiers are loaded when both configured."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            discord_webhook_url="enc_webhook",
            telegram_bot_token="enc_token",
            telegram_chat_id="123456",
        )

        with patch("src.bot.notifications.decrypt_value", return_value="decrypted_value"), \
             patch("src.bot.notifications.DiscordNotifier") as mock_discord:
            mock_discord.return_value = MagicMock()
            notifiers = await worker._get_notifiers()

        assert len(notifiers) == 2


# ---------------------------------------------------------------------------
# _check_builder_approval tests (lines 1173-1225)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCheckBuilderApproval:
    """Tests for _check_builder_approval."""

    async def test_no_builder_config_passes(self):
        """Client with no builder_config passes builder check."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        # Import the actual HyperliquidClient for isinstance check
        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient
            mock_client = MagicMock(spec=HyperliquidClient)
            mock_client.builder_config = None

            db = AsyncMock()

            result = await worker._check_builder_approval(mock_client, db)

            assert result is True
        except ImportError:
            pytest.skip("HyperliquidClient not available")

    async def test_builder_approved_in_db(self):
        """Builder approval found in DB returns True immediately."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient
            mock_client = MagicMock(spec=HyperliquidClient)
            mock_client.builder_config = {"f": 0.001}

            conn = MagicMock()
            conn.builder_fee_approved = True

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = conn

            db = AsyncMock()
            db.execute = AsyncMock(return_value=mock_result)

            result = await worker._check_builder_approval(mock_client, db)

            assert result is True
        except ImportError:
            pytest.skip("HyperliquidClient not available")

    async def test_builder_not_approved_blocks(self):
        """Builder not approved on-chain blocks the bot."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient
            mock_client = MagicMock(spec=HyperliquidClient)
            mock_client.builder_config = {"f": 0.001}
            mock_client.check_builder_fee_approval = AsyncMock(return_value=None)

            conn = MagicMock()
            conn.builder_fee_approved = False

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = conn

            db = AsyncMock()
            db.execute = AsyncMock(return_value=mock_result)

            result = await worker._check_builder_approval(mock_client, db)

            assert result is False
            assert worker.status == "error"
        except ImportError:
            pytest.skip("HyperliquidClient not available")

    async def test_builder_check_exception_blocks(self):
        """Exception during builder check blocks the bot."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient
            mock_client = MagicMock(spec=HyperliquidClient)
            mock_client.builder_config = {"f": 0.001}

            db = AsyncMock()
            db.execute = AsyncMock(side_effect=Exception("DB error"))

            result = await worker._check_builder_approval(mock_client, db)

            assert result is False
            assert worker.status == "error"
        except ImportError:
            pytest.skip("HyperliquidClient not available")


# ---------------------------------------------------------------------------
# _check_referral_gate tests (lines 1103-1171)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCheckReferralGate:
    """Tests for _check_referral_gate."""

    async def test_no_referral_code_passes(self):
        """When no referral code configured, always passes."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_client = AsyncMock()
        db = AsyncMock()

        mock_hl_cfg = {"referral_code": "", "builder_address": "", "builder_fee": 0}

        with patch("src.bot.bot_worker.get_session"), \
             patch("src.utils.settings.get_hl_config", return_value=mock_hl_cfg):
            result = await worker._check_referral_gate(mock_client, db)

        assert result is True

    async def test_non_hyperliquid_client_passes(self):
        """Non-Hyperliquid client always passes referral check."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_client = AsyncMock()
        db = AsyncMock()

        mock_hl_cfg = {"referral_code": "ABC123", "builder_address": "", "builder_fee": 0}

        with patch("src.utils.settings.get_hl_config", return_value=mock_hl_cfg):
            result = await worker._check_referral_gate(mock_client, db)

        assert result is True


# ---------------------------------------------------------------------------
# Stop edge case tests (lines 349-350)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStopEdgeCases:
    """Additional stop() tests."""

    async def test_stop_with_live_client_error(self):
        """Live client close error is silenced."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._scheduler = MagicMock()
        worker._scheduler.running = True
        worker._strategy = AsyncMock()
        worker._demo_client = None

        mock_live = AsyncMock()
        mock_live.close.side_effect = RuntimeError("live close failed")
        worker._live_client = mock_live

        await worker.stop()

        assert worker.status == "stopped"

    async def test_stop_without_scheduler(self):
        """Stop when scheduler is None."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._scheduler = None
        worker._strategy = None
        worker._demo_client = None
        worker._live_client = None

        await worker.stop()

        assert worker.status == "stopped"

    async def test_stop_scheduler_not_running(self):
        """Stop when scheduler exists but not running."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._scheduler = MagicMock()
        worker._scheduler.running = False
        worker._strategy = None
        worker._demo_client = None
        worker._live_client = None

        await worker.stop()

        worker._scheduler.shutdown.assert_not_called()
        assert worker.status == "stopped"


# ---------------------------------------------------------------------------
# _analyze_and_trade edge cases (lines 431-432)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAnalyzeAndTradeEdgeCases:
    """Edge cases for _analyze_and_trade."""

    async def test_symbol_analysis_error_continues_to_next(self):
        """Error in one symbol doesn't stop analysis of next symbols."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            trading_pairs=json.dumps(["BTCUSDT", "ETHUSDT"]),
        )

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        worker._client = mock_client

        call_count = [0]
        async def mock_analyze(symbol, **kwargs):
            call_count[0] += 1
            if symbol == "BTCUSDT":
                raise Exception("Analysis failed")

        worker._analyze_symbol = mock_analyze

        await worker._analyze_and_trade()

        assert call_count[0] == 2
        assert worker.last_analysis is not None

    async def test_per_symbol_risk_check_skips_symbol(self):
        """Per-symbol risk check skips specific symbols."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            trading_pairs=json.dumps(["BTCUSDT", "ETHUSDT"]),
        )

        def can_trade_effect(symbol=None):
            if symbol is None:
                return (True, "")
            if symbol == "BTCUSDT":
                return (False, "Symbol trade limit reached")
            return (True, "")

        mock_rm = MagicMock()
        mock_rm.can_trade.side_effect = can_trade_effect
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        worker._client = mock_client

        worker._analyze_symbol = AsyncMock()

        await worker._analyze_and_trade()

        # Only ETHUSDT should be analyzed
        assert worker._analyze_symbol.await_count == 1


# ---------------------------------------------------------------------------
# Hyperliquid-specific init tests (lines 111-118, 210-217)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHyperliquidInit:
    """Tests for Hyperliquid-specific initialization paths."""

    async def test_hyperliquid_extra_kwargs(self):
        """Hyperliquid exchange type loads builder config."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="demo", exchange_type="hyperliquid")
        conn = MagicMock()
        conn.demo_api_key_encrypted = "enc_key"
        conn.demo_api_secret_encrypted = "enc_secret"
        conn.demo_passphrase_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        mock_client = AsyncMock()
        mock_client.get_account_balance = AsyncMock(return_value=_make_mock_balance())

        hl_cfg = {"builder_address": "0x123", "builder_fee": 0.001, "referral_code": ""}

        with patch("src.bot.bot_worker.get_session", return_value=_mock_session_ctx(mock_session)), \
             patch("src.bot.bot_worker.create_exchange_client", return_value=mock_client) as mock_create, \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"), \
             patch("src.bot.bot_worker.StrategyRegistry") as mock_registry, \
             patch("src.bot.bot_worker.RiskManager") as mock_rm_cls, \
             patch("src.utils.settings.get_hl_config", return_value=hl_cfg):
            mock_registry.create.return_value = MagicMock()
            mock_rm_cls.return_value = MagicMock()

            # Mock _check_builder_approval and _check_referral_gate
            worker._check_builder_approval = AsyncMock(return_value=True)
            worker._check_referral_gate = AsyncMock(return_value=True)

            result = await worker.initialize()

        assert result is True
        # Verify create_exchange_client was called with builder config
        create_call = mock_create.call_args
        assert create_call[1]["builder_address"] == "0x123"

    async def test_hyperliquid_builder_approval_fails(self):
        """Hyperliquid bot fails when builder approval fails."""
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config(mode="demo", exchange_type="hyperliquid")
        conn = MagicMock()
        conn.demo_api_key_encrypted = "enc_key"
        conn.demo_api_secret_encrypted = "enc_secret"
        conn.demo_passphrase_encrypted = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            elif call_count == 2:
                result.scalar_one_or_none.return_value = conn
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute

        mock_client = AsyncMock()
        hl_cfg = {"builder_address": "0x123", "builder_fee": 0.001, "referral_code": ""}

        # _check_builder_approval uses its own get_session call
        mock_hl_session = AsyncMock()

        async def mock_check_builder(client, session):
            worker.error_message = "Builder Fee not approved"
            worker.status = "error"
            return False

        with patch("src.bot.bot_worker.get_session") as mock_get_session, \
             patch("src.bot.bot_worker.create_exchange_client", return_value=mock_client), \
             patch("src.bot.bot_worker.decrypt_value", return_value="decrypted"), \
             patch("src.bot.bot_worker.StrategyRegistry") as mock_registry, \
             patch("src.bot.bot_worker.RiskManager") as mock_rm_cls, \
             patch("src.utils.settings.get_hl_config", return_value=hl_cfg):

            # First call = main init session, second = HL checks session
            mock_get_session.side_effect = [
                _mock_session_ctx(mock_session),
                _mock_session_ctx(mock_hl_session),
            ]
            mock_registry.create.return_value = MagicMock()
            mock_rm_cls.return_value = MagicMock()

            worker._check_builder_approval = AsyncMock(return_value=False)

            result = await worker.initialize()

        assert result is False


# ---------------------------------------------------------------------------
# Schedule setup edge cases
# ---------------------------------------------------------------------------

class TestScheduleSetupEdgeCases:
    """Additional schedule setup tests."""

    def test_rotation_enabled_with_interval(self):
        """Rotation job is added when rotation_enabled and interval set."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            schedule_type="interval",
            schedule_config=json.dumps({"interval_minutes": 30}),
            rotation_enabled=True,
            rotation_interval_minutes=120,
            rotation_start_time="08:00",
        )
        worker._scheduler = MagicMock()

        worker._setup_schedule()

        # analysis + monitor + rotation + daily_summary = 4
        assert worker._scheduler.add_job.call_count == 4

    def test_schedule_config_json_parsed(self):
        """Schedule config JSON is parsed correctly."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            schedule_type="custom_cron",
            schedule_config=json.dumps({"hours": [6, 12, 18]}),
        )
        worker._scheduler = MagicMock()

        worker._setup_schedule()

        assert worker._scheduler.add_job.call_count == 3


# ---------------------------------------------------------------------------
# _analyze_symbol (lock wrapper) test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAnalyzeSymbol:
    """Tests for _analyze_symbol which wraps _analyze_symbol_locked with a lock."""

    async def test_analyze_symbol_acquires_lock(self):
        worker = BotWorker(bot_config_id=1)
        worker._analyze_symbol_locked = AsyncMock()

        await worker._analyze_symbol("BTCUSDT", force=True, asset_budget=5000.0)

        worker._analyze_symbol_locked.assert_awaited_once_with("BTCUSDT", True, asset_budget=5000.0)

    async def test_analyze_symbol_prevents_concurrent(self):
        """Concurrent calls for the same symbol are serialized."""
        worker = BotWorker(bot_config_id=1)

        call_order = []
        async def mock_locked(symbol, force=False, asset_budget=None):
            call_order.append(f"start_{symbol}")
            await asyncio.sleep(0.01)
            call_order.append(f"end_{symbol}")

        worker._analyze_symbol_locked = mock_locked

        await asyncio.gather(
            worker._analyze_symbol("BTCUSDT"),
            worker._analyze_symbol("BTCUSDT"),
        )

        # Verify serialized: first must complete before second starts
        assert call_order[0] == "start_BTCUSDT"
        assert call_order[1] == "end_BTCUSDT"
        assert call_order[2] == "start_BTCUSDT"
        assert call_order[3] == "end_BTCUSDT"


# ---------------------------------------------------------------------------
# _analyze_and_trade_safe — auto-recovery & success reset tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAnalyzeAndTradeSafe:
    """Tests for _analyze_and_trade_safe error tracking and auto-recovery."""

    async def test_success_resets_consecutive_errors(self):
        """Successful analysis resets the error counter."""
        worker = BotWorker(bot_config_id=1)
        worker._consecutive_errors = 3
        worker.error_message = "previous error"
        worker._analyze_and_trade = AsyncMock()

        await worker._analyze_and_trade_safe()

        assert worker._consecutive_errors == 0
        assert worker.error_message is None

    async def test_auto_recovery_after_five_errors(self):
        """After 5 consecutive errors, bot pauses and resets counter to 3."""
        worker = BotWorker(bot_config_id=1)
        worker._consecutive_errors = 4  # Next error will be the 5th
        worker.status = "running"
        worker._analyze_and_trade = AsyncMock(side_effect=Exception("fail"))
        # _analyze_and_trade_safe accesses self._config.name for notifications
        worker._config = MagicMock()
        worker._config.name = "TestBot"

        with patch("src.bot.bot_worker.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await worker._analyze_and_trade_safe()

        assert worker._consecutive_errors == 3  # Reset to allow 2 more retries
        assert worker.status == "running"
        mock_sleep.assert_awaited_once_with(60)

    async def test_error_below_threshold_does_not_pause(self):
        """Errors below threshold increment counter without pausing."""
        worker = BotWorker(bot_config_id=1)
        worker._consecutive_errors = 0
        worker._analyze_and_trade = AsyncMock(side_effect=Exception("fail"))

        await worker._analyze_and_trade_safe()

        assert worker._consecutive_errors == 1
        assert worker.error_message == "fail"
        assert worker.status != "error"


# ---------------------------------------------------------------------------
# _analyze_symbol_locked — TOCTOU risk check & signal deduplication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAnalyzeSymbolLockedTOCTOU:
    """Tests for TOCTOU risk check and signal deduplication in _analyze_symbol_locked."""

    async def test_toctou_risk_check_skips_when_blocked(self):
        """Inside-lock risk check skips symbol even when outer check passed."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (False, "limit reached inside lock")
        worker._strategy = AsyncMock()

        await worker._analyze_symbol_locked("BTCUSDT", force=True)

        # Strategy should never be called if risk check fails
        worker._strategy.generate_signal.assert_not_awaited()

    async def test_signal_deduplication_skips_duplicate_within_60s(self):
        """Duplicate signal within 60s window is skipped."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(mode="demo")
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, "")

        signal = _make_mock_signal()
        mock_strategy = AsyncMock()
        mock_strategy.generate_signal.return_value = signal
        mock_strategy.should_trade.return_value = (True, "OK")
        worker._strategy = mock_strategy
        worker._demo_client = AsyncMock()
        worker._execute_trade = AsyncMock()

        # Pre-populate dedup cache with a recent entry
        dedup_key = f"BTCUSDT:{signal.direction.value}:{signal.entry_price:.2f}"
        worker._last_signal_keys = {dedup_key: datetime.now(timezone.utc)}

        await worker._analyze_symbol_locked("BTCUSDT", force=True)

        # Trade should NOT execute because of deduplication
        worker._execute_trade.assert_not_awaited()

    async def test_signal_deduplication_allows_after_60s(self):
        """Signal after 60s dedup window is allowed."""
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(mode="demo")
        worker._risk_manager = MagicMock()
        worker._risk_manager.can_trade.return_value = (True, "")

        signal = _make_mock_signal()
        mock_strategy = AsyncMock()
        mock_strategy.generate_signal.return_value = signal
        mock_strategy.should_trade.return_value = (True, "OK")
        worker._strategy = mock_strategy
        worker._demo_client = AsyncMock()
        worker._execute_trade = AsyncMock()

        # Pre-populate dedup cache with an OLD entry (>60s ago)
        dedup_key = f"BTCUSDT:{signal.direction.value}:{signal.entry_price:.2f}"
        worker._last_signal_keys = {dedup_key: datetime.now(timezone.utc) - timedelta(seconds=120)}

        await worker._analyze_symbol_locked("BTCUSDT", force=True)

        # Trade SHOULD execute
        worker._execute_trade.assert_awaited()
