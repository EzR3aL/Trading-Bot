"""Unit tests for HyperliquidGates component (ARCH-H1 Phase 1 PR-2, #277)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.components.hyperliquid_gates import GateResult, HyperliquidGates


def _make_gates(user_id: int = 1, exchange_type: str = "hyperliquid") -> HyperliquidGates:
    config = MagicMock()
    config.user_id = user_id
    config.exchange_type = exchange_type
    return HyperliquidGates(bot_config_id=42, config_getter=lambda: config)


class TestGateResult:
    def test_passed_factory(self):
        r = GateResult.passed()
        assert r.ok is True
        assert r.error_message is None

    def test_blocked_factory(self):
        r = GateResult.blocked("nope")
        assert r.ok is False
        assert r.error_message == "nope"


@pytest.mark.asyncio
class TestCheckReferral:
    async def test_no_referral_code_configured_passes(self):
        gates = _make_gates()
        with patch(
            "src.utils.settings.get_hl_config",
            AsyncMock(return_value={"referral_code": "", "builder_address": "", "builder_fee": 0}),
        ):
            r = await gates.check_referral(MagicMock(), AsyncMock())
        assert r.ok is True

    async def test_non_hl_client_passes(self):
        gates = _make_gates()
        client = MagicMock()  # not a HyperliquidClient
        with patch(
            "src.utils.settings.get_hl_config",
            AsyncMock(return_value={"referral_code": "ABC", "builder_address": "", "builder_fee": 0}),
        ):
            r = await gates.check_referral(client, AsyncMock())
        assert r.ok is True

    async def test_db_flag_verified_fast_path(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        conn = MagicMock(referral_verified=True)
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = conn
        db = AsyncMock()
        db.execute = AsyncMock(return_value=db_result)

        with patch(
            "src.utils.settings.get_hl_config",
            AsyncMock(return_value={"referral_code": "ABC", "builder_address": "", "builder_fee": 0}),
        ):
            r = await gates.check_referral(client, db)
        assert r.ok is True
        client.get_referral_info.assert_not_called()

    async def test_wrong_referrer_blocks(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        client.get_referral_info = AsyncMock(return_value={"referredBy": {"code": "OTHER"}})
        conn = MagicMock(referral_verified=False)
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = conn
        db = AsyncMock()
        db.execute = AsyncMock(return_value=db_result)

        with patch(
            "src.utils.settings.get_hl_config",
            AsyncMock(return_value={"referral_code": "OUR", "builder_address": "", "builder_fee": 0}),
        ):
            r = await gates.check_referral(client, db)
        assert r.ok is False
        assert "Referral-Code" in r.error_message

    async def test_no_referrer_blocks_with_link(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        client.get_referral_info = AsyncMock(return_value={})
        conn = MagicMock(referral_verified=False)
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = conn
        db = AsyncMock()
        db.execute = AsyncMock(return_value=db_result)

        with patch(
            "src.utils.settings.get_hl_config",
            AsyncMock(return_value={"referral_code": "OUR", "builder_address": "", "builder_fee": 0}),
        ):
            r = await gates.check_referral(client, db)
        assert r.ok is False
        assert "https://app.hyperliquid.xyz/join/OUR" in r.error_message

    async def test_inner_exception_blocks_with_retry_message(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("db down"))

        with patch(
            "src.utils.settings.get_hl_config",
            AsyncMock(return_value={"referral_code": "OUR", "builder_address": "", "builder_fee": 0}),
        ):
            r = await gates.check_referral(client, db)
        assert r.ok is False
        assert "Referral-Prüfung fehlgeschlagen" in r.error_message


@pytest.mark.asyncio
class TestCheckBuilderApproval:
    async def test_non_hl_client_passes(self):
        gates = _make_gates()
        r = await gates.check_builder_approval(MagicMock(), AsyncMock())
        assert r.ok is True

    async def test_no_builder_config_passes(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        client.builder_config = None
        r = await gates.check_builder_approval(client, AsyncMock())
        assert r.ok is True

    async def test_db_flag_approved_fast_path(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        client.builder_config = {"b": "0xbuilder", "f": 100}
        conn = MagicMock(builder_fee_approved=True)
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = conn
        db = AsyncMock()
        db.execute = AsyncMock(return_value=db_result)
        r = await gates.check_builder_approval(client, db)
        assert r.ok is True
        client.check_builder_fee_approval.assert_not_called()

    async def test_not_approved_blocks(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        client.builder_config = {"b": "0xbuilder", "f": 100}
        client.demo_mode = False
        client.check_builder_fee_approval = AsyncMock(return_value=0)
        conn = MagicMock(builder_fee_approved=False)
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = conn
        db = AsyncMock()
        db.execute = AsyncMock(return_value=db_result)
        r = await gates.check_builder_approval(client, db)
        assert r.ok is False
        assert "Builder Fee nicht genehmigt" in r.error_message

    async def test_exception_blocks(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        client.builder_config = {"b": "0xbuilder", "f": 100}
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB down"))
        r = await gates.check_builder_approval(client, db)
        assert r.ok is False
        assert "Builder Fee Prüfung fehlgeschlagen" in r.error_message


@pytest.mark.asyncio
class TestCheckWallet:
    async def test_non_hl_client_passes(self):
        gates = _make_gates()
        r = await gates.check_wallet(MagicMock())
        assert r.ok is True

    async def test_valid_wallet_passes(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        client.validate_wallet = AsyncMock(return_value={
            "valid": True, "balance": 100.0, "main_wallet": "0x1234567890abcdef",
        })
        r = await gates.check_wallet(client)
        assert r.ok is True

    async def test_invalid_wallet_blocks(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        client.validate_wallet = AsyncMock(return_value={
            "valid": False, "error": "wallet not funded",
        })
        r = await gates.check_wallet(client)
        assert r.ok is False
        assert r.error_message == "wallet not funded"

    async def test_exception_fails_open(self):
        from src.exchanges.hyperliquid.client import HyperliquidClient
        gates = _make_gates()
        client = MagicMock(spec=HyperliquidClient)
        client.validate_wallet = AsyncMock(side_effect=Exception("timeout"))
        r = await gates.check_wallet(client)
        assert r.ok is True  # fail open


@pytest.mark.asyncio
class TestCheckAffiliateUid:
    async def test_no_exchange_type_passes(self):
        gates = _make_gates(exchange_type=None)
        r = await gates.check_affiliate_uid(AsyncMock())
        assert r.ok is True

    async def test_no_uid_requirement_passes(self):
        gates = _make_gates(exchange_type="bitget")
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=db_result)
        r = await gates.check_affiliate_uid(db)
        assert r.ok is True

    async def test_uid_verified_passes(self):
        gates = _make_gates(exchange_type="bitget")
        link = MagicMock(uid_required=True)
        conn = MagicMock(affiliate_verified=True)
        # first execute -> link, second -> conn
        db_result_link = MagicMock()
        db_result_link.scalar_one_or_none.return_value = link
        db_result_conn = MagicMock()
        db_result_conn.scalar_one_or_none.return_value = conn
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[db_result_link, db_result_conn])
        r = await gates.check_affiliate_uid(db)
        assert r.ok is True

    async def test_uid_not_verified_blocks(self):
        gates = _make_gates(exchange_type="bitget")
        link = MagicMock(uid_required=True)
        conn = MagicMock(affiliate_verified=False)
        db_result_link = MagicMock()
        db_result_link.scalar_one_or_none.return_value = link
        db_result_conn = MagicMock()
        db_result_conn.scalar_one_or_none.return_value = conn
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[db_result_link, db_result_conn])
        r = await gates.check_affiliate_uid(db)
        assert r.ok is False
        assert "Affiliate UID-Verifizierung erforderlich" in r.error_message

    async def test_exception_fails_open(self):
        gates = _make_gates(exchange_type="bitget")
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("db boom"))
        r = await gates.check_affiliate_uid(db)
        assert r.ok is True  # fail open
