"""Hyperliquid fee-related constants and helpers.

Hosts the slippage default used for market orders and the round-trip
builder-fee math. The number lives here (not on the client class) so it
is easy to find and unit-test without needing a full HL client instance.

Re-exported from ``client.py`` to preserve every existing import.
"""

from __future__ import annotations

from typing import Optional

# Default slippage for market orders (5%)
DEFAULT_SLIPPAGE = 0.05


def calculate_builder_fee(
    builder: Optional[dict],
    entry_price: float,
    exit_price: float,
    size: float,
) -> float:
    """Calculate builder fee earned for a round-trip trade.

    Both entry and exit orders carry the builder fee.
    Fee unit: f is in tenths of basis points.
    f=10 → 10 * 0.001% = 0.01% → 0.0001
    Divisor: 10 (tenths) * 10_000 (basis points) = 100_000
    """
    if not builder:
        return 0.0
    fee_rate = builder["f"]
    total_value = (entry_price * size) + (exit_price * size)
    return round(total_value * (fee_rate / 100_000), 6)
