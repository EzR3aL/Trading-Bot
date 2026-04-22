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
        client._info_exec = client._info
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
        client._info_exec = client._info
        client._info.post.return_value = 0

        result = await client.check_builder_fee_approval()
        assert result is None

    @pytest.mark.asyncio
    async def test_check_approval_returns_none_when_no_builder(self):
        """check_builder_fee_approval returns None when builder not configured
        and no explicit builder_address parameter is passed."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client._builder = None

        result = await client.check_builder_fee_approval()
        assert result is None

    @pytest.mark.asyncio
    async def test_check_approval_accepts_explicit_builder_address(self):
        """Regression for #138: when self._builder is None, an explicit
        builder_address kwarg must be used instead of returning None.

        This path is required by the mainnet read client used in
        confirm_builder_approval, which does not populate self._builder
        because the builder config lives in the DB, not ENV."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client.wallet_address = "0xuser"
        client._builder = None  # simulates mainnet read client
        client._info = MagicMock()
        client._info_exec = client._info
        client._info.post.return_value = 10

        result = await client.check_builder_fee_approval(
            builder_address="0xBuilderFromDB",
        )
        assert result == 10
        # Verify the builder address from the kwarg was actually used
        client._info.post.assert_called_once_with(
            "/info",
            {
                "type": "maxBuilderFee",
                "user": "0xuser",
                "builder": "0xbuilderfromdb",  # lowercased
            },
        )

    @pytest.mark.asyncio
    async def test_check_approval_explicit_builder_overrides_self(self):
        """Explicit builder_address takes precedence over self._builder."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client.wallet_address = "0xuser"
        client._builder = {"b": "0xold_builder", "f": 10}
        client._info = MagicMock()
        client._info_exec = client._info
        client._info.post.return_value = 10

        result = await client.check_builder_fee_approval(
            builder_address="0xNew_Builder",
        )
        assert result == 10
        args = client._info.post.call_args
        assert args[0][1]["builder"] == "0xnew_builder"

    @pytest.mark.asyncio
    async def test_check_approval_handles_api_error(self):
        """check_builder_fee_approval returns None on API errors."""
        from src.exchanges.hyperliquid.client import HyperliquidClient

        client = object.__new__(HyperliquidClient)
        client.wallet_address = "0xuser"
        client._builder = {"b": "0xbuilder", "f": 10}
        client._info = MagicMock()
        client._info_exec = client._info
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
        # SDK expects max_fee_rate as percentage string (EIP-712 signing)
        client._exchange.approve_builder_fee.assert_called_once_with(
            builder="0xbuilder", max_fee_rate="0.010%",
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
        client._info_exec = client._info
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
        client._info_exec = client._info
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
        # fee = 201000 * (10 / 100_000) = 20.1
        fee = client.calculate_builder_fee(
            entry_price=50000.0, exit_price=50500.0, size=2.0
        )
        assert fee == 20.1

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
        # fee = 202 * (5 / 100_000) = 0.0101
        fee = client.calculate_builder_fee(
            entry_price=100.0, exit_price=102.0, size=1.0
        )
        assert fee == 0.0101


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


# ── Hyperliquid pre_start_checks: referral gate ───────────────────
#
# Historical note: these tests previously drove the legacy
# ``BotWorker._check_referral_gate`` / ``_check_builder_approval``
# mixin methods, which were removed when ``HyperliquidClient.pre_start_checks``
# became the single source of truth (#ARCH-H2). The behaviour locked in
# by each test is unchanged — just the entry point moved.


def _make_hl_client(
    *,
    builder_config=None,
    demo_mode=False,
    wallet_address="0xuser",
):
    """Build a minimal HyperliquidClient without running ``__init__``.

    The real constructor pulls in the eth_account / hyperliquid SDK and
    opens network clients; ``object.__new__`` gives us a bare instance
    where we can stub the handful of attributes ``pre_start_checks``
    actually reads. Matches the pattern already used by the existing
    ``TestBuilderFeeApproval`` tests in this file.
    """
    from src.exchanges.hyperliquid.client import HyperliquidClient

    client = object.__new__(HyperliquidClient)
    client.wallet_address = wallet_address
    client._builder = builder_config
    client.demo_mode = demo_mode
    client._info = MagicMock()
    client._info_exec = client._info
    client._rate_limiter = None
    # Default wallet validation → always OK so the wallet gate does
    # not swamp referral/builder assertions.
    client.validate_wallet = AsyncMock(return_value={"valid": True, "balance": 100.0, "main_wallet": wallet_address, "api_wallet": wallet_address, "is_agent_wallet": False, "error": None})
    return client


def _mock_db_with_conn(conn):
    """Return an AsyncMock DB that yields ``conn`` for every SELECT."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = conn
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


class TestHyperliquidPreStartChecksReferralGate:
    @pytest.mark.asyncio
    async def test_referral_gate_blocks_unreferred_user(self):
        """pre_start_checks emits a failing 'referral' gate when user is not referred."""
        client = _make_hl_client()
        client.get_referral_info = AsyncMock(return_value={"referredBy": None})
        mock_db = _mock_db_with_conn(None)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "MYCODE", "builder_address": "", "builder_fee": 10}
            results = await client.pre_start_checks(user_id=1, db=mock_db)

        referral = [r for r in results if r.key == "referral"]
        assert len(referral) == 1
        assert referral[0].ok is False
        assert "Referral" in referral[0].message

    @pytest.mark.asyncio
    async def test_referral_gate_allows_referred_user(self):
        """pre_start_checks emits no 'referral' failure when user is properly referred."""
        client = _make_hl_client()
        client.get_referral_info = AsyncMock(return_value={"referredBy": "MYCODE"})

        mock_conn = MagicMock()
        mock_conn.referral_verified = False
        mock_conn.builder_fee_approved = False
        mock_db = _mock_db_with_conn(mock_conn)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "MYCODE", "builder_address": "", "builder_fee": 10}
            results = await client.pre_start_checks(user_id=1, db=mock_db)

        assert not any(r.key == "referral" and not r.ok for r in results)

    @pytest.mark.asyncio
    async def test_referral_gate_skipped_when_no_code(self):
        """pre_start_checks skips the referral gate entirely when no code is configured."""
        client = _make_hl_client()
        client.get_referral_info = AsyncMock()  # should NOT be called
        mock_db = _mock_db_with_conn(None)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "", "builder_address": "", "builder_fee": 10}
            results = await client.pre_start_checks(user_id=1, db=mock_db)

        assert not any(r.key == "referral" for r in results)
        client.get_referral_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_referral_gate_passes_on_db_flag(self):
        """pre_start_checks skips the live referral API when the DB flag is already set."""
        client = _make_hl_client()
        client.get_referral_info = AsyncMock()  # must NOT be called

        mock_conn = MagicMock()
        mock_conn.referral_verified = True
        mock_conn.builder_fee_approved = False
        mock_db = _mock_db_with_conn(mock_conn)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "MYCODE", "builder_address": "", "builder_fee": 10}
            results = await client.pre_start_checks(user_id=1, db=mock_db)

        assert not any(r.key == "referral" and not r.ok for r in results)
        client.get_referral_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_referral_gate_blocks_on_api_error(self):
        """pre_start_checks emits a failing 'referral' gate when the HL API raises."""
        client = _make_hl_client()
        client.get_referral_info = AsyncMock(side_effect=Exception("network error"))
        mock_db = _mock_db_with_conn(None)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "MYCODE", "builder_address": "", "builder_fee": 10}
            results = await client.pre_start_checks(user_id=1, db=mock_db)

        assert any(r.key == "referral" and not r.ok for r in results)


# ── Hyperliquid pre_start_checks: builder-fee gate ────────────────


class TestHyperliquidPreStartChecksBuilderGate:
    @pytest.mark.asyncio
    async def test_builder_check_blocks_when_not_approved(self):
        """pre_start_checks emits a failing 'builder_fee' gate when on-chain approval is missing."""
        client = _make_hl_client(builder_config={"b": "0xbuilder", "f": 10})
        client.check_builder_fee_approval = AsyncMock(return_value=None)

        mock_conn = MagicMock()
        mock_conn.builder_fee_approved = False
        mock_db = _mock_db_with_conn(mock_conn)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "", "builder_address": "", "builder_fee": 10}
            results = await client.pre_start_checks(user_id=1, db=mock_db)

        builder = [r for r in results if r.key == "builder_fee"]
        assert len(builder) == 1
        assert builder[0].ok is False
        assert "Builder Fee" in builder[0].message
        client.check_builder_fee_approval.assert_called_once()

    @pytest.mark.asyncio
    async def test_builder_check_passes_when_approved_on_chain(self):
        """pre_start_checks emits no 'builder_fee' failure when approval is found on-chain."""
        client = _make_hl_client(builder_config={"b": "0xbuilder", "f": 10})
        client.check_builder_fee_approval = AsyncMock(return_value=10)

        mock_conn = MagicMock()
        mock_conn.builder_fee_approved = False
        mock_db = _mock_db_with_conn(mock_conn)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "", "builder_address": "", "builder_fee": 10}
            results = await client.pre_start_checks(user_id=1, db=mock_db)

        assert not any(r.key == "builder_fee" and not r.ok for r in results)

    @pytest.mark.asyncio
    async def test_builder_check_passes_on_db_flag(self):
        """pre_start_checks skips the on-chain approval call when the DB flag is set."""
        client = _make_hl_client(builder_config={"b": "0xbuilder", "f": 10})
        client.check_builder_fee_approval = AsyncMock()  # must NOT be called

        mock_conn = MagicMock()
        mock_conn.builder_fee_approved = True
        mock_db = _mock_db_with_conn(mock_conn)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "", "builder_address": "", "builder_fee": 10}
            results = await client.pre_start_checks(user_id=1, db=mock_db)

        assert not any(r.key == "builder_fee" and not r.ok for r in results)
        client.check_builder_fee_approval.assert_not_called()

    @pytest.mark.asyncio
    async def test_builder_check_skipped_for_non_hl_client(self):
        """The builder-fee gate is HL-specific — non-HL clients never surface it.

        This test locks in BotWorker's routing contract: it delegates
        ``pre_start_checks`` to whatever client is attached, and the
        base ``ExchangeClient.pre_start_checks`` (used by Bitget, Weex,
        Bitunix, BingX) never emits a ``builder_fee`` gate.
        """
        from src.exchanges.base import ExchangeClient

        # A concrete stand-in for a non-HL client that uses the base
        # ``pre_start_checks`` implementation and declares itself as a
        # non-hyperliquid exchange.
        client = MagicMock(spec=ExchangeClient)
        client.exchange_name = "bitget"
        base_impl = ExchangeClient.pre_start_checks.__get__(client, type(client))
        client.pre_start_checks = base_impl
        # ``_check_affiliate_uid_gate`` is invoked by the base impl; stub
        # it to return None (no affiliate requirement) so the result list
        # is simply empty.
        client._check_affiliate_uid_gate = AsyncMock(return_value=None)

        mock_db = AsyncMock()
        results = await client.pre_start_checks(user_id=1, db=mock_db)

        assert not any(getattr(r, "key", None) == "builder_fee" for r in results)

    @pytest.mark.asyncio
    async def test_builder_check_skipped_when_no_builder_config(self):
        """pre_start_checks emits no 'builder_fee' gate when the client has no builder config."""
        client = _make_hl_client(builder_config=None)
        client.check_builder_fee_approval = AsyncMock()  # must NOT be called

        mock_db = _mock_db_with_conn(None)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "", "builder_address": "", "builder_fee": 10}
            results = await client.pre_start_checks(user_id=1, db=mock_db)

        assert not any(r.key == "builder_fee" for r in results)
        client.check_builder_fee_approval.assert_not_called()

    @pytest.mark.asyncio
    async def test_builder_check_blocks_on_error(self):
        """pre_start_checks emits a failing 'builder_fee' gate when the approval check raises."""
        client = _make_hl_client(builder_config={"b": "0xbuilder", "f": 10})
        client.check_builder_fee_approval = AsyncMock(side_effect=Exception("db down"))

        mock_conn = MagicMock()
        mock_conn.builder_fee_approved = False
        mock_db = _mock_db_with_conn(mock_conn)

        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {"referral_code": "", "builder_address": "", "builder_fee": 10}
            results = await client.pre_start_checks(user_id=1, db=mock_db)

        assert any(r.key == "builder_fee" and not r.ok for r in results)


# ── Constants ──────────────────────────────────────────────────────


class TestConstants:
    def test_default_builder_fee(self):
        """DEFAULT_BUILDER_FEE should be 10 (0.01%)."""
        from src.exchanges.hyperliquid.constants import DEFAULT_BUILDER_FEE
        assert DEFAULT_BUILDER_FEE == 10
