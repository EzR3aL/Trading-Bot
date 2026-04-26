"""Bitget signing/auth primitives.

Houses the custom error class. The HMAC-SHA256 signature and header
construction stay on the client class itself because tests patch
``src.exchanges.bitget.client.time`` to pin the timestamp; relocating
them here would break that patch path.

Re-exported from ``client.py`` so existing imports continue to resolve.
"""

from __future__ import annotations

from src.exceptions import ExchangeError


class BitgetClientError(ExchangeError):
    """Custom exception for Bitget API errors."""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__("bitget", message, original_error)
