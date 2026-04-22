"""Tests for Hyperliquid EIP-712 payload validator (#257, SEC-005/SEC-008)."""

from __future__ import annotations

import pytest

from src.exchanges.hyperliquid.constants import (
    MAINNET_CHAIN_ID,
    MAX_BUILDER_FEE_PCT,
    MAX_BUILDER_FEE_TENTHS_BPS,
    MIN_BUILDER_FEE_PCT,
    MIN_BUILDER_FEE_TENTHS_BPS,
    TESTNET_CHAIN_ID,
)
from src.exchanges.hyperliquid.eip712_validator import (
    EIP712ValidationError,
    assert_builder_fee_pct,
    assert_builder_fee_tenths_bps,
    assert_chain_id,
    assert_primary_type,
    parse_builder_fee_pct,
    validate_approve_builder_fee,
)


VALID_BUILDER = "0x1234567890abcdef1234567890abcdef12345678"


class TestAssertChainId:
    def test_mainnet_accepts_arbitrum_one(self):
        assert_chain_id(MAINNET_CHAIN_ID, demo_mode=False)  # no raise

    def test_testnet_accepts_arbitrum_sepolia(self):
        assert_chain_id(TESTNET_CHAIN_ID, demo_mode=True)  # no raise

    def test_mainnet_rejects_testnet_chain(self):
        with pytest.raises(EIP712ValidationError, match="chain_id mismatch"):
            assert_chain_id(TESTNET_CHAIN_ID, demo_mode=False)

    def test_testnet_rejects_mainnet_chain(self):
        with pytest.raises(EIP712ValidationError, match="chain_id mismatch"):
            assert_chain_id(MAINNET_CHAIN_ID, demo_mode=True)

    def test_rejects_arbitrary_chain(self):
        with pytest.raises(EIP712ValidationError, match="chain_id mismatch"):
            assert_chain_id(1, demo_mode=False)  # Ethereum mainnet is NOT HL's chain

    def test_rejects_zero(self):
        with pytest.raises(EIP712ValidationError):
            assert_chain_id(0, demo_mode=False)


class TestAssertPrimaryType:
    @pytest.mark.parametrize("pt", [
        "Order", "Cancel", "CancelByCloid", "ModifyOrder",
        "UpdateLeverage", "UpdateIsolatedMargin", "ApproveBuilderFee",
    ])
    def test_accepts_whitelisted(self, pt):
        assert_primary_type(pt)  # no raise

    def test_rejects_approve_agent_despite_being_a_real_hl_type(self):
        # ApproveAgent is a valid HL EIP-712 type but NOT in our whitelist —
        # it grants trading authority to a third party, which the bot must
        # never sign. SafeExchange also blocks approve_agent by name; this
        # is the EIP-712 layer.
        with pytest.raises(EIP712ValidationError, match="not allowed"):
            assert_primary_type("ApproveAgent")

    def test_rejects_transfer_types(self):
        with pytest.raises(EIP712ValidationError):
            assert_primary_type("UsdSend")
        with pytest.raises(EIP712ValidationError):
            assert_primary_type("Withdraw")

    def test_rejects_empty(self):
        with pytest.raises(EIP712ValidationError):
            assert_primary_type("")

    def test_rejects_case_mismatch(self):
        # Whitelist is case-sensitive — EIP-712 types are case-sensitive.
        with pytest.raises(EIP712ValidationError):
            assert_primary_type("order")


class TestParseBuilderFeePct:
    @pytest.mark.parametrize("raw,expected", [
        ("0.001%", 0.001),
        ("0.01%", 0.01),
        ("0.1%", 0.1),
        ("0.050%", 0.050),
        ("0.01", 0.01),        # without %
        (" 0.01% ", 0.01),     # whitespace
    ])
    def test_valid_shapes(self, raw, expected):
        assert parse_builder_fee_pct(raw) == expected

    def test_rejects_int(self):
        with pytest.raises(EIP712ValidationError, match="must be str"):
            parse_builder_fee_pct(10)  # type: ignore[arg-type]

    def test_rejects_none(self):
        with pytest.raises(EIP712ValidationError):
            parse_builder_fee_pct(None)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [
        "abc", "0.01%%", "1e-3", "-0.01%", "%", "",
    ])
    def test_rejects_malformed(self, bad):
        with pytest.raises(EIP712ValidationError):
            parse_builder_fee_pct(bad)


class TestAssertBuilderFeeTenthsBps:
    @pytest.mark.parametrize("fee", [1, 10, 50, 100])
    def test_accepts_in_range(self, fee):
        assert_builder_fee_tenths_bps(fee)  # no raise

    def test_rejects_zero(self):
        with pytest.raises(EIP712ValidationError, match="out of range"):
            assert_builder_fee_tenths_bps(0)

    def test_rejects_above_max(self):
        with pytest.raises(EIP712ValidationError, match="out of range"):
            assert_builder_fee_tenths_bps(MAX_BUILDER_FEE_TENTHS_BPS + 1)

    def test_rejects_10x_regression(self):
        # Regression guard: before SEC-008 the fee was once 10x too high
        # (100 "tenths of bps" interpreted as "percent" style). 1000 would
        # be rejected here.
        with pytest.raises(EIP712ValidationError, match="out of range"):
            assert_builder_fee_tenths_bps(1000)

    def test_rejects_negative(self):
        with pytest.raises(EIP712ValidationError):
            assert_builder_fee_tenths_bps(-1)

    def test_rejects_non_int(self):
        with pytest.raises(EIP712ValidationError, match="must be int"):
            assert_builder_fee_tenths_bps(10.0)  # type: ignore[arg-type]

    def test_rejects_bool(self):
        # bool is a subclass of int in Python — explicitly rejected.
        with pytest.raises(EIP712ValidationError):
            assert_builder_fee_tenths_bps(True)  # type: ignore[arg-type]


class TestAssertBuilderFeePct:
    @pytest.mark.parametrize("raw", ["0.001%", "0.01%", "0.1%", "0.050%"])
    def test_accepts_in_range(self, raw):
        assert_builder_fee_pct(raw)  # no raise

    def test_rejects_above_max(self):
        with pytest.raises(EIP712ValidationError, match="out of range"):
            assert_builder_fee_pct("0.5%")  # 5x over cap

    def test_rejects_10x_regression_percent(self):
        # Matches the historical incident in percent form.
        with pytest.raises(EIP712ValidationError, match="out of range"):
            assert_builder_fee_pct("1.0%")

    def test_rejects_below_min(self):
        with pytest.raises(EIP712ValidationError, match="out of range"):
            assert_builder_fee_pct("0.0001%")


class TestValidateApproveBuilderFee:
    def test_happy_path_mainnet(self):
        validate_approve_builder_fee(
            builder=VALID_BUILDER,
            max_fee_rate="0.01%",
            demo_mode=False,
            chain_id=MAINNET_CHAIN_ID,
        )

    def test_happy_path_testnet(self):
        validate_approve_builder_fee(
            builder=VALID_BUILDER,
            max_fee_rate="0.01%",
            demo_mode=True,
            chain_id=TESTNET_CHAIN_ID,
        )

    def test_rejects_wrong_chain_for_mainnet(self):
        with pytest.raises(EIP712ValidationError, match="chain_id"):
            validate_approve_builder_fee(
                builder=VALID_BUILDER,
                max_fee_rate="0.01%",
                demo_mode=False,
                chain_id=TESTNET_CHAIN_ID,
            )

    def test_rejects_fee_above_cap(self):
        with pytest.raises(EIP712ValidationError, match="out of range"):
            validate_approve_builder_fee(
                builder=VALID_BUILDER,
                max_fee_rate="1.0%",
                demo_mode=False,
                chain_id=MAINNET_CHAIN_ID,
            )

    @pytest.mark.parametrize("bad_builder", [
        "",
        "1234567890abcdef1234567890abcdef12345678",  # missing 0x
        "0x123",                                      # too short
        "0x" + "a" * 41,                              # wrong length
        None,
    ])
    def test_rejects_malformed_builder(self, bad_builder):
        with pytest.raises(EIP712ValidationError, match="builder address"):
            validate_approve_builder_fee(
                builder=bad_builder,  # type: ignore[arg-type]
                max_fee_rate="0.01%",
                demo_mode=False,
                chain_id=MAINNET_CHAIN_ID,
            )

    def test_chain_id_optional(self):
        # When chain_id is None the pin is skipped (used by callers that
        # have not yet resolved the SDK's chain). Other checks still run.
        validate_approve_builder_fee(
            builder=VALID_BUILDER,
            max_fee_rate="0.01%",
            demo_mode=False,
            chain_id=None,
        )


class TestConstantsWireFormat:
    """Pin the numeric constants so a typo in constants.py fails CI."""

    def test_mainnet_chain_id_is_arbitrum_one(self):
        assert MAINNET_CHAIN_ID == 42161

    def test_testnet_chain_id_is_arbitrum_sepolia(self):
        assert TESTNET_CHAIN_ID == 421614

    def test_builder_fee_bounds(self):
        assert MIN_BUILDER_FEE_TENTHS_BPS == 1
        assert MAX_BUILDER_FEE_TENTHS_BPS == 100
        assert MIN_BUILDER_FEE_PCT == pytest.approx(0.001)
        assert MAX_BUILDER_FEE_PCT == pytest.approx(0.1)
