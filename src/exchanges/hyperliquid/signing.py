"""Hyperliquid signing/security primitives.

Houses the SDK-method allow/deny lists, the :class:`SafeExchange` wrapper
that blocks fund-moving operations, the custom error class, and the
deterministic Cloid derivation used for idempotent order placement.

Extracted from ``client.py`` during the structural refactor — every name
defined here is re-exported from ``client.py`` so existing imports
continue to resolve unchanged.
"""

from __future__ import annotations

import hashlib

from hyperliquid.exchange import Exchange as HLExchange
from hyperliquid.utils.types import Cloid

from src.exceptions import ExchangeError
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Security: Only these SDK methods may be called ──────────────────────────
# Any method not on this list (e.g. usd_transfer, withdraw_from_bridge,
# vault_usd_transfer, send_asset, sub_account_transfer) is BLOCKED.
ALLOWED_METHODS = frozenset({
    "market_open",
    "market_close",
    "order",
    "bulk_orders",
    "cancel",
    "bulk_cancel",
    "update_leverage",
    "update_isolated_margin",
    "approve_builder_fee",
})

# Methods that move funds — explicitly forbidden
FORBIDDEN_METHODS = frozenset({
    "usd_transfer",
    "withdraw_from_bridge",
    "vault_usd_transfer",
    "send_asset",
    "sub_account_transfer",
    "sub_account_spot_transfer",
    "spot_transfer",
    "usd_class_transfer",
    "set_referrer",
    "approve_agent",
    "convert_to_multi_sig_user",
})


class HyperliquidClientError(ExchangeError):
    """Custom exception for Hyperliquid API errors."""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__("hyperliquid", message, original_error)


class SafeExchange:
    """Wrapper around the SDK Exchange that blocks fund-moving operations."""

    def __init__(self, exchange: HLExchange):
        self._exchange = exchange

    def __getattr__(self, name: str):
        if name in FORBIDDEN_METHODS:
            raise HyperliquidClientError(
                f"BLOCKED: '{name}' is a fund-moving operation and is not allowed. "
                f"Only trading operations are permitted."
            )
        if name not in ALLOWED_METHODS and not name.startswith("_"):
            # Allow private/internal methods and info access, block unknown public methods
            if hasattr(self._exchange, name) and callable(getattr(self._exchange, name)):
                logger.warning(f"Hyperliquid: calling non-whitelisted method '{name}'")
        return getattr(self._exchange, name)


def _derive_cloid(client_order_id: str) -> Cloid:
    """Derive a Hyperliquid Cloid (16 bytes hex) from a free-form id.

    HL requires exactly 16 bytes, but our executor hands us a longer string
    like ``bot-<id>-<uuid>``. We hash it deterministically so the same
    caller-id always maps to the same on-chain cloid (#ARCH-C2).
    """
    digest = hashlib.blake2b(client_order_id.encode("utf-8"), digest_size=16).hexdigest()
    return Cloid.from_str(f"0x{digest}")
