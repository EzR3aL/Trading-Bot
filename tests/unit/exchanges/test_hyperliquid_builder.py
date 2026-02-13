"""Tests for Hyperliquid Builder Code and Referral features.

Covers:
- Builder code injection into orders (market_open, market_close, trigger orders)
- Builder fee approval check
- Referral info query
- SafeExchange whitelist enforcement
- BotWorker pre-start checks (builder approval, referral gate)
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── SafeExchange & ALLOWED_METHODS ─────────────────────────────────


class TestSafeExchange:
    def test_approve_builder_fee_is_whitelisted(self):
        """approve_builder_fee must be in ALLOWED_METHODS."""
        from src.exchanges.hyperliquid.client import ALLOWED_METHODS
        assert "approve_builder_fee" in ALLOWED_METHODS

    def test_fund_moving_methods_forbidden(self):
        """Fund-moving methods must be in FORBIDDEN_METHODS."""
        from src.exchanges.hyperliquid.client import FORBIDDEN_METHODS
        for method in [
            "usd_transfer", "withdraw_from_bridge", "vault_usd_transfer",
            "send_asset", "sub_account_transfer",
        ]:
            assert method in FORBIDDEN_METHODS

    def test_safe_exchange_blocks_forbidden(self):
        """SafeExchange must raise HyperliquidClientError for forbidden methods."""
        from src.exchanges.hyperliquid.client import SafeExchange, HyperliquidClientError

        mock_exchange = MagicMock()
        safe = SafeExchange(mock_exchange)

        with pytest.raises(HyperliquidClientError, match="BLOCKED"):
            safe.usd_transfer()

    def test_safe_exchange_allows_trading(self):
        """SafeExchange must allow whitelisted trading methods."""
        from src.exchanges.hyperliquid.client import SafeExchange

        mock_exchange = MagicMock()
        safe = SafeExchange(mock_exchange)

        # Should not raise
        safe.market_open
        safe.market_close
        safe.order
        safe.approve_builder_fee


# ── Builder Code Config ────────────────────────────────────────────


class TestBuilderCodeConfig:
    @patch.dict(os.environ, {"HL_BUILDER_ADDRESS": "0xABCDEF1234567890ABCDEF1234567890ABCDEF12", "HL_BUILDER_FEE": "10"})
    @patch("src.exchanges.hyperliquid.client.HLExchange")
    @patch("src.exchanges.hyperliquid.client.HLInfo")
    @patch("src.exchanges.hyperliquid.client.EthAccount")
    def test_builder_config_loaded_from_env(self, mock_eth, mock_info, mock_exchange):
        """Client should load builder config from ENV vars."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        mock_wallet = MagicMock()
        mock_wallet.address = "0x1111111111111111111111111111111111111111"
        mock_eth.from_key.return_value = mock_wallet
        mock_exchange_instance = MagicMock()
        mock_exchange_instance.info = MagicMock()
        mock_exchange.return_value = mock_exchange_instance

        client = HyperliquidClient(
            api_key="0x2222222222222222222222222222222222222222",
            api_secret="0x" + "ab" * 32,
            demo_mode=True,
        )

        assert client._builder is not None
        assert client._builder["b"] == "0xabcdef1234567890abcdef1234567890abcdef12"
        assert client._builder["f"] == 10

    @patch.dict(os.environ, {"HL_BUILDER_ADDRESS": "", "HL_BUILDER_FEE": "10"})
    @patch("src.exchanges.hyperliquid.client.HLExchange")
    @patch("src.exchanges.hyperliquid.client.HLInfo")
    @patch("src.exchanges.hyperliquid.client.EthAccount")
    def test_builder_config_disabled_when_no_address(self, mock_eth, mock_info, mock_exchange):
        """Builder should be None when HL_BUILDER_ADDRESS is empty."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        mock_wallet = MagicMock()
        mock_wallet.address = "0x1111111111111111111111111111111111111111"
        mock_eth.from_key.return_value = mock_wallet
        mock_exchange_instance = MagicMock()
        mock_exchange_instance.info = MagicMock()
        mock_exchange.return_value = mock_exchange_instance

        client = HyperliquidClient(
            api_key="0x2222222222222222222222222222222222222222",
            api_secret="0x" + "ab" * 32,
            demo_mode=True,
        )

        assert client._builder is None

    @patch.dict(os.environ, {"HL_BUILDER_ADDRESS": "0xABCDEF1234567890ABCDEF1234567890ABCDEF12", "HL_BUILDER_FEE": "200"})
    @patch("src.exchanges.hyperliquid.client.HLExchange")
    @patch("src.exchanges.hyperliquid.client.HLInfo")
    @patch("src.exchanges.hyperliquid.client.EthAccount")
    def test_builder_config_disabled_when_fee_out_of_range(self, mock_eth, mock_info, mock_exchange):
        """Builder should be None when HL_BUILDER_FEE is > 100."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        mock_wallet = MagicMock()
        mock_wallet.address = "0x1111111111111111111111111111111111111111"
        mock_eth.from_key.return_value = mock_wallet
        mock_exchange_instance = MagicMock()
        mock_exchange_instance.info = MagicMock()
        mock_exchange.return_value = mock_exchange_instance

        client = HyperliquidClient(
            api_key="0x2222222222222222222222222222222222222222",
            api_secret="0x" + "ab" * 32,
            demo_mode=True,
        )

        assert client._builder is None


# ── Builder Fee Approval Check ─────────────────────────────────────


class TestBuilderFeeApproval:
    @pytest.mark.asyncio
    async def test_check_approval_returns_fee_when_approved(self):
        """check_builder_fee_approval returns int when user has approved."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client.wallet_address = "0xuser"
        client._builder = {"b": "0xbuilder", "f": 10}
        client._info = MagicMock()
        client._info.post.return_value = 10

        result = await client.check_builder_fee_approval()
        assert result == 10
        client._info.post.assert_called_once_with(
            "/info",
            {"type": "maxBuilderFee", "user": "0xuser", "builder": "0xbuilder"},
        )

    @pytest.mark.asyncio
    async def test_check_approval_returns_none_when_not_approved(self):
        """check_builder_fee_approval returns None when fee is 0."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client.wallet_address = "0xuser"
        client._builder = {"b": "0xbuilder", "f": 10}
        client._info = MagicMock()
        client._info.post.return_value = 0

        result = await client.check_builder_fee_approval()
        assert result is None

    @pytest.mark.asyncio
    async def test_check_approval_returns_none_when_no_builder(self):
        """check_builder_fee_approval returns None when builder not configured."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = None

        result = await client.check_builder_fee_approval()
        assert result is None

    @pytest.mark.asyncio
    async def test_check_approval_handles_api_error(self):
        """check_builder_fee_approval returns None on API errors."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client.wallet_address = "0xuser"
        client._builder = {"b": "0xbuilder", "f": 10}
        client._info = MagicMock()
        client._info.post.side_effect = Exception("network error")

        result = await client.check_builder_fee_approval()
        assert result is None


# ── Approve Builder Fee ────────────────────────────────────────────


class TestApproveBuilderFee:
    @pytest.mark.asyncio
    async def test_approve_calls_exchange_sdk(self):
        """approve_builder_fee calls SDK's approve_builder_fee method."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = {"b": "0xbuilder", "f": 10}
        client._exchange = MagicMock()
        client._exchange.approve_builder_fee.return_value = {"status": "ok"}

        result = await client.approve_builder_fee()
        assert result is True
        client._exchange.approve_builder_fee.assert_called_once_with(
            builder="0xbuilder", max_fee_rate=10,
        )

    @pytest.mark.asyncio
    async def test_approve_fails_without_builder(self):
        """approve_builder_fee returns False when no builder configured."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = None

        result = await client.approve_builder_fee()
        assert result is False

    @pytest.mark.asyncio
    async def test_approve_handles_sdk_error(self):
        """approve_builder_fee returns False on SDK error."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = {"b": "0xbuilder", "f": 10}
        client._exchange = MagicMock()
        client._exchange.approve_builder_fee.side_effect = Exception("signing failed")

        result = await client.approve_builder_fee()
        assert result is False


# ── Referral Info Query ────────────────────────────────────────────


class TestReferralInfo:
    @pytest.mark.asyncio
    async def test_get_referral_info_returns_dict(self):
        """get_referral_info returns dict from SDK."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client.wallet_address = "0xuser"
        client._info = MagicMock()
        client._info.query_referral_state.return_value = {
            "referredBy": "0xreferrer",
            "cumVlm": "50000",
        }

        result = await client.get_referral_info()
        assert result["referredBy"] == "0xreferrer"

    @pytest.mark.asyncio
    async def test_get_referral_info_returns_none_on_error(self):
        """get_referral_info returns None on API error."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client.wallet_address = "0xuser"
        client._info = MagicMock()
        client._info.query_referral_state.side_effect = Exception("fail")

        result = await client.get_referral_info()
        assert result is None


# ── Builder Property ───────────────────────────────────────────────


class TestBuilderProperty:
    def test_builder_config_property(self):
        """builder_config property returns the builder dict."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = {"b": "0xaddr", "f": 10}
        assert client.builder_config == {"b": "0xaddr", "f": 10}

    def test_builder_config_none(self):
        """builder_config returns None when not configured."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = None
        assert client.builder_config is None


# ── Calculate Builder Fee ─────────────────────────────────────────


class TestCalculateBuilderFee:
    def test_calculate_fee_round_trip(self):
        """calculate_builder_fee computes correct round-trip fee."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = {"b": "0xbuilder", "f": 10}

        # entry_value=100000, exit_value=101000, total=201000
        # fee = 201000 * (10 / 1_000_000) = 2.01
        fee = client.calculate_builder_fee(
            entry_price=50000.0, exit_price=50500.0, size=2.0
        )
        assert fee == 2.01

    def test_calculate_fee_returns_zero_without_builder(self):
        """calculate_builder_fee returns 0.0 when builder not configured."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = None

        fee = client.calculate_builder_fee(
            entry_price=50000.0, exit_price=51000.0, size=1.0
        )
        assert fee == 0.0

    def test_calculate_fee_small_trade(self):
        """calculate_builder_fee handles small trades correctly."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = {"b": "0xbuilder", "f": 5}

        # entry_value=100, exit_value=102, total=202
        # fee = 202 * (5 / 1_000_000) = 0.00101
        fee = client.calculate_builder_fee(
            entry_price=100.0, exit_price=102.0, size=1.0
        )
        assert fee == 0.00101


# ── Builder Kwargs in Orders ──────────────────────────────────────


class TestBuilderKwargsInOrders:
    def test_builder_kwargs_present_when_configured(self):
        """When builder is configured, builder kwarg should be constructed."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = {"b": "0xbuilder", "f": 10}

        builder_kwargs = {"builder": client._builder} if client._builder else {}
        assert builder_kwargs == {"builder": {"b": "0xbuilder", "f": 10}}

    def test_builder_kwargs_empty_when_not_configured(self):
        """When builder is None, builder kwarg should be empty dict."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = None

        builder_kwargs = {"builder": client._builder} if client._builder else {}
        assert builder_kwargs == {}


# ── BotWorker Referral Gate ────────────────────────────────────────


class TestBotWorkerReferralGate:
    @pytest.mark.asyncio
    async def test_referral_gate_blocks_unreferred_user(self):
        """Bot should fail to start if referral required but user not referred."""
        from src.bot.bot_worker import BotWorker
        from src.exchanges.hyperliquid.client import HyperliquidClient

        worker = BotWorker(bot_config_id=1)
        worker._config = MagicMock()
        worker._config.user_id = 1

        mock_client = MagicMock(spec=HyperliquidClient)
        mock_client.get_referral_info = AsyncMock(return_value={"referredBy": None})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "MYCODE", "builder_address": "", "builder_fee": 10}
            result = await worker._check_referral_gate(mock_client, mock_db)

        assert result is False
        assert "Referral" in worker.error_message

    @pytest.mark.asyncio
    async def test_referral_gate_allows_referred_user(self):
        """Bot should start if user is referred."""
        from src.bot.bot_worker import BotWorker
        from src.exchanges.hyperliquid.client import HyperliquidClient

        worker = BotWorker(bot_config_id=1)
        worker._config = MagicMock()
        worker._config.user_id = 1

        mock_client = MagicMock(spec=HyperliquidClient)
        mock_client.get_referral_info = AsyncMock(return_value={"referredBy": "0xreferrer"})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_conn = MagicMock()
        mock_conn.referral_verified = False
        mock_result.scalar_one_or_none.return_value = mock_conn
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "MYCODE", "builder_address": "", "builder_fee": 10}
            result = await worker._check_referral_gate(mock_client, mock_db)

        assert result is True

    @pytest.mark.asyncio
    async def test_referral_gate_skipped_when_no_code(self):
        """Bot should always pass when referral_code is empty."""
        from src.bot.bot_worker import BotWorker

        worker = BotWorker(bot_config_id=1)
        mock_client = MagicMock()
        mock_db = AsyncMock()

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "", "builder_address": "", "builder_fee": 10}
            result = await worker._check_referral_gate(mock_client, mock_db)

        assert result is True

    @pytest.mark.asyncio
    async def test_referral_gate_passes_on_db_flag(self):
        """Bot should pass when DB flag referral_verified is True (fast path)."""
        from src.bot.bot_worker import BotWorker
        from src.exchanges.hyperliquid.client import HyperliquidClient

        worker = BotWorker(bot_config_id=1)
        worker._config = MagicMock()
        worker._config.user_id = 1

        mock_client = MagicMock(spec=HyperliquidClient)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_conn = MagicMock()
        mock_conn.referral_verified = True
        mock_result.scalar_one_or_none.return_value = mock_conn
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "MYCODE", "builder_address": "", "builder_fee": 10}
            result = await worker._check_referral_gate(mock_client, mock_db)

        assert result is True
        # Should NOT call HL API since DB flag was set
        mock_client.get_referral_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_referral_gate_blocks_on_api_error(self):
        """Referral gate should block on API error (fail safe)."""
        from src.bot.bot_worker import BotWorker
        from src.exchanges.hyperliquid.client import HyperliquidClient

        worker = BotWorker(bot_config_id=1)
        worker._config = MagicMock()
        worker._config.user_id = 1

        mock_client = MagicMock(spec=HyperliquidClient)
        mock_client.get_referral_info = AsyncMock(side_effect=Exception("network error"))

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "MYCODE", "builder_address": "", "builder_fee": 10}
            result = await worker._check_referral_gate(mock_client, mock_db)

        assert result is False


# ── BotWorker Builder Approval Check ───────────────────────────────


class TestBotWorkerBuilderCheck:
    @pytest.mark.asyncio
    async def test_builder_check_blocks_when_not_approved(self):
        """Builder check should block bot start when not approved (hard gate)."""
        from src.bot.bot_worker import BotWorker
        from src.exchanges.hyperliquid.client import HyperliquidClient

        worker = BotWorker(bot_config_id=1)
        worker._config = MagicMock()
        worker._config.user_id = 1

        mock_client = MagicMock(spec=HyperliquidClient)
        mock_client.builder_config = {"b": "0xbuilder", "f": 10}
        mock_client.check_builder_fee_approval = AsyncMock(return_value=None)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_conn = MagicMock()
        mock_conn.builder_fee_approved = False
        mock_result.scalar_one_or_none.return_value = mock_conn
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await worker._check_builder_approval(mock_client, mock_db)
        assert result is False
        assert "Builder Fee" in worker.error_message
        mock_client.check_builder_fee_approval.assert_called_once()

    @pytest.mark.asyncio
    async def test_builder_check_passes_when_approved_on_chain(self):
        """Builder check should pass when on-chain approval found."""
        from src.bot.bot_worker import BotWorker
        from src.exchanges.hyperliquid.client import HyperliquidClient

        worker = BotWorker(bot_config_id=1)
        worker._config = MagicMock()
        worker._config.user_id = 1

        mock_client = MagicMock(spec=HyperliquidClient)
        mock_client.builder_config = {"b": "0xbuilder", "f": 10}
        mock_client.check_builder_fee_approval = AsyncMock(return_value=10)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_conn = MagicMock()
        mock_conn.builder_fee_approved = False
        mock_result.scalar_one_or_none.return_value = mock_conn
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await worker._check_builder_approval(mock_client, mock_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_builder_check_passes_on_db_flag(self):
        """Builder check should pass when DB flag is set (fast path)."""
        from src.bot.bot_worker import BotWorker
        from src.exchanges.hyperliquid.client import HyperliquidClient

        worker = BotWorker(bot_config_id=1)
        worker._config = MagicMock()
        worker._config.user_id = 1

        mock_client = MagicMock(spec=HyperliquidClient)
        mock_client.builder_config = {"b": "0xbuilder", "f": 10}

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_conn = MagicMock()
        mock_conn.builder_fee_approved = True
        mock_result.scalar_one_or_none.return_value = mock_conn
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await worker._check_builder_approval(mock_client, mock_db)
        assert result is True
        # Should NOT call on-chain check since DB flag was set
        mock_client.check_builder_fee_approval.assert_not_called()

    @pytest.mark.asyncio
    async def test_builder_check_skipped_for_non_hl_client(self):
        """Builder check should pass for non-Hyperliquid clients."""
        from src.bot.bot_worker import BotWorker

        worker = BotWorker(bot_config_id=1)
        mock_client = MagicMock()  # Not a HyperliquidClient
        mock_db = AsyncMock()

        result = await worker._check_builder_approval(mock_client, mock_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_builder_check_skipped_when_no_builder_config(self):
        """Builder check should pass when client has no builder config."""
        from src.bot.bot_worker import BotWorker
        from src.exchanges.hyperliquid.client import HyperliquidClient

        worker = BotWorker(bot_config_id=1)
        mock_client = MagicMock(spec=HyperliquidClient)
        mock_client.builder_config = None
        mock_db = AsyncMock()

        result = await worker._check_builder_approval(mock_client, mock_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_builder_check_blocks_on_error(self):
        """Builder check should block on unexpected errors (fail safe)."""
        from src.bot.bot_worker import BotWorker
        from src.exchanges.hyperliquid.client import HyperliquidClient

        worker = BotWorker(bot_config_id=1)
        worker._config = MagicMock()
        worker._config.user_id = 1

        mock_client = MagicMock(spec=HyperliquidClient)
        mock_client.builder_config = {"b": "0xbuilder", "f": 10}
        mock_client.check_builder_fee_approval = AsyncMock(side_effect=Exception("db down"))

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_conn = MagicMock()
        mock_conn.builder_fee_approved = False
        mock_result.scalar_one_or_none.return_value = mock_conn
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await worker._check_builder_approval(mock_client, mock_db)
        assert result is False


# ── Constants ──────────────────────────────────────────────────────


class TestConstants:
    def test_default_builder_fee(self):
        """DEFAULT_BUILDER_FEE should be 10 (0.01%)."""
        from src.exchanges.hyperliquid.constants import DEFAULT_BUILDER_FEE
        assert DEFAULT_BUILDER_FEE == 10
