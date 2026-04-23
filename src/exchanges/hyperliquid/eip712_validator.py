"""EIP-712 payload validators for Hyperliquid (SEC-005, SEC-008).

Defense-in-depth: every signed action funnels through these validators before
the SDK sees it. The SDK's own bounds are trusted for non-critical fields;
we only pin what is safety-critical:

* ``chain_id`` — prevents cross-chain replay of a signed action
* ``primaryType`` — prevents a manipulated SDK from smuggling a different
  action-shape under an allow-listed method name
* builder-fee bounds — historical incident: fee was 10x too high; this
  refuses anything outside the documented HL range

Validators raise :class:`EIP712ValidationError` on any mismatch. Callers
must let the error propagate; catching and swallowing defeats the purpose.
"""

from __future__ import annotations

import re
from typing import Optional

from src.exceptions import ExchangeError
from src.exchanges.hyperliquid.constants import (
    ALLOWED_PRIMARY_TYPES,
    MAINNET_CHAIN_ID,
    MAX_BUILDER_FEE_PCT,
    MAX_BUILDER_FEE_TENTHS_BPS,
    MIN_BUILDER_FEE_PCT,
    MIN_BUILDER_FEE_TENTHS_BPS,
    TESTNET_CHAIN_ID,
)


class EIP712ValidationError(ExchangeError):
    """Raised when a Hyperliquid EIP-712 payload fails validation."""

    def __init__(self, message: str):
        super().__init__("hyperliquid", message)


# Matches "0.1%", "0.010%", "0.1" — percentages only, no scientific notation.
_PCT_RE = re.compile(r"^\s*(?P<num>\d+(?:\.\d+)?)\s*%?\s*$")


def assert_chain_id(chain_id: int, *, demo_mode: bool) -> None:
    """Raise if ``chain_id`` does not match the expected network.

    Args:
        chain_id: value to verify.
        demo_mode: when true, only testnet chain-id is accepted.
    """
    expected = TESTNET_CHAIN_ID if demo_mode else MAINNET_CHAIN_ID
    if int(chain_id) != expected:
        raise EIP712ValidationError(
            f"chain_id mismatch: got {chain_id}, expected {expected} "
            f"({'testnet' if demo_mode else 'mainnet'})"
        )


def assert_primary_type(primary_type: str) -> None:
    """Raise if ``primary_type`` is not in the whitelist."""
    if primary_type not in ALLOWED_PRIMARY_TYPES:
        raise EIP712ValidationError(
            f"primaryType '{primary_type}' is not allowed. "
            f"Allowed: {sorted(ALLOWED_PRIMARY_TYPES)}"
        )


def parse_builder_fee_pct(value: str) -> float:
    """Parse a HL max-fee-rate string ('0.1%', '0.01', ...) to a float percent.

    Raises :class:`EIP712ValidationError` on malformed input.
    """
    if not isinstance(value, str):
        raise EIP712ValidationError(
            f"builder_fee max_fee_rate must be str, got {type(value).__name__}"
        )
    match = _PCT_RE.match(value)
    if not match:
        raise EIP712ValidationError(
            f"builder_fee max_fee_rate '{value}' is not a valid percentage"
        )
    return float(match.group("num"))


def assert_builder_fee_tenths_bps(fee: int) -> None:
    """Bounds-check a builder fee in tenths-of-basis-points (HL integer form).

    Accepts 1..100 inclusive. Raises for anything else.
    """
    if not isinstance(fee, int) or isinstance(fee, bool):
        raise EIP712ValidationError(
            f"builder_fee must be int, got {type(fee).__name__}"
        )
    if fee < MIN_BUILDER_FEE_TENTHS_BPS or fee > MAX_BUILDER_FEE_TENTHS_BPS:
        raise EIP712ValidationError(
            f"builder_fee={fee} out of range "
            f"[{MIN_BUILDER_FEE_TENTHS_BPS}..{MAX_BUILDER_FEE_TENTHS_BPS}] "
            "(tenths of basis points, HL perps cap = 0.1%)"
        )


def assert_builder_fee_pct(value: str) -> float:
    """Parse + bounds-check a HL max-fee-rate string. Returns the parsed %."""
    pct = parse_builder_fee_pct(value)
    if pct < MIN_BUILDER_FEE_PCT or pct > MAX_BUILDER_FEE_PCT:
        raise EIP712ValidationError(
            f"builder_fee {pct}% out of range "
            f"[{MIN_BUILDER_FEE_PCT}%..{MAX_BUILDER_FEE_PCT}%]"
        )
    return pct


def validate_approve_builder_fee(
    *,
    builder: str,
    max_fee_rate: str,
    demo_mode: bool,
    chain_id: Optional[int] = None,
) -> None:
    """Full validator for the ``approve_builder_fee`` SDK call.

    Checks: builder address shape, fee bounds, (optional) chain-id pin,
    primaryType. Raises on any failure.
    """
    if not isinstance(builder, str) or not builder.startswith("0x") or len(builder) != 42:
        raise EIP712ValidationError(
            f"builder address '{builder}' is not a valid 0x-prefixed 20-byte hex"
        )
    assert_builder_fee_pct(max_fee_rate)
    if chain_id is not None:
        assert_chain_id(chain_id, demo_mode=demo_mode)
    assert_primary_type("ApproveBuilderFee")
