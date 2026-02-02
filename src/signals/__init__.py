"""
Enhanced Signal Stack module for alpha stacking.

Provides a composite scoring system that combines multiple market signals
with configurable weights to produce stronger trade confidence scores.
"""

from src.signals.composite import (
    SignalComposite,
    SignalResult,
    CompositeResult,
)
from src.signals.normalizers import (
    SignalNormalizer,
    normalize_fear_greed,
    normalize_funding_rate,
    normalize_long_short_ratio,
    normalize_open_interest_change,
    normalize_price_momentum,
    normalize_rsi,
    normalize_volume_profile,
    normalize_liquidation_imbalance,
)

__all__ = [
    "SignalComposite",
    "SignalResult",
    "CompositeResult",
    "SignalNormalizer",
    "normalize_fear_greed",
    "normalize_funding_rate",
    "normalize_long_short_ratio",
    "normalize_open_interest_change",
    "normalize_price_momentum",
    "normalize_rsi",
    "normalize_volume_profile",
    "normalize_liquidation_imbalance",
]
