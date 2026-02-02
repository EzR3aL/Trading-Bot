"""
Signal Normalizers for the Enhanced Signal Stack.

Each normalizer converts a raw market data point into a standardized
signal value ranging from -1.0 (strong short) to +1.0 (strong long).

Convention:
  +1.0 = Strong long signal
  +0.5 = Moderate long signal
   0.0 = Neutral (no signal)
  -0.5 = Moderate short signal
  -1.0 = Strong short signal
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SignalNormalizer:
    """Result of normalizing a raw signal value."""
    name: str
    raw_value: float
    normalized: float  # -1.0 to +1.0
    strength: str  # "strong", "moderate", "weak", "neutral"
    description: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "raw_value": self.raw_value,
            "normalized": round(self.normalized, 4),
            "strength": self.strength,
            "description": self.description,
        }


def _classify_strength(value: float) -> str:
    """Classify signal strength from normalized value."""
    abs_val = abs(value)
    if abs_val >= 0.7:
        return "strong"
    elif abs_val >= 0.4:
        return "moderate"
    elif abs_val >= 0.15:
        return "weak"
    return "neutral"


def normalize_fear_greed(
    index: int,
    extreme_fear: int = 20,
    extreme_greed: int = 80,
) -> SignalNormalizer:
    """
    Normalize Fear & Greed Index (contrarian).

    Extreme fear -> buy signal (long)
    Extreme greed -> sell signal (short)

    Args:
        index: Fear & Greed value (0-100)
        extreme_fear: Threshold for extreme fear
        extreme_greed: Threshold for extreme greed
    """
    index = max(0, min(100, index))

    # Map 0-100 to +1 to -1 (contrarian: low fear = buy, high greed = sell)
    # 0 (max fear) -> +1.0, 50 (neutral) -> 0.0, 100 (max greed) -> -1.0
    normalized = 1.0 - (index / 50.0)
    normalized = max(-1.0, min(1.0, normalized))

    # Amplify extremes
    if index <= extreme_fear:
        normalized = min(1.0, normalized * 1.3)
        desc = f"Extreme fear ({index}) - contrarian long signal"
    elif index >= extreme_greed:
        normalized = max(-1.0, normalized * 1.3)
        desc = f"Extreme greed ({index}) - contrarian short signal"
    elif index < 40:
        desc = f"Fear ({index}) - mild long bias"
    elif index > 60:
        desc = f"Greed ({index}) - mild short bias"
    else:
        desc = f"Neutral sentiment ({index})"

    return SignalNormalizer(
        name="fear_greed",
        raw_value=float(index),
        normalized=normalized,
        strength=_classify_strength(normalized),
        description=desc,
    )


def normalize_funding_rate(
    rate: float,
    high_threshold: float = 0.0005,
    low_threshold: float = -0.0002,
) -> SignalNormalizer:
    """
    Normalize funding rate (contrarian).

    High positive rate -> shorts collect, longs pay -> contrarian short
    Negative rate -> longs collect -> contrarian long

    Args:
        rate: Funding rate (decimal, e.g., 0.001 = 0.1%)
        high_threshold: Rate above which is considered high
        low_threshold: Rate below which is considered negative
    """
    # Scale to -1..1 using thresholds as reference points
    if rate > 0:
        # Positive rate: scale relative to high_threshold
        # At high_threshold -> -0.5, at 2x -> -1.0
        normalized = -(rate / (high_threshold * 2))
    else:
        # Negative rate: scale relative to low_threshold
        normalized = -(rate / (abs(low_threshold) * 2))

    normalized = max(-1.0, min(1.0, normalized))

    if rate > high_threshold:
        desc = f"High funding ({rate*100:.4f}%) - contrarian short"
    elif rate < low_threshold:
        desc = f"Negative funding ({rate*100:.4f}%) - contrarian long"
    else:
        desc = f"Normal funding ({rate*100:.4f}%)"

    return SignalNormalizer(
        name="funding_rate",
        raw_value=rate,
        normalized=normalized,
        strength=_classify_strength(normalized),
        description=desc,
    )


def normalize_long_short_ratio(
    ratio: float,
    crowded_longs: float = 2.5,
    crowded_shorts: float = 0.4,
) -> SignalNormalizer:
    """
    Normalize Long/Short Account Ratio (contrarian).

    High ratio -> crowded longs -> contrarian short
    Low ratio -> crowded shorts -> contrarian long

    Args:
        ratio: Long/Short ratio (>1 means more longs)
        crowded_longs: Threshold for crowded longs
        crowded_shorts: Threshold for crowded shorts
    """
    if ratio >= 1.0:
        # More longs than shorts: bearish (contrarian)
        # At crowded_longs -> -0.7, above -> approaches -1.0
        normalized = -min(1.0, (ratio - 1.0) / (crowded_longs - 1.0) * 0.7)
    else:
        # More shorts than longs: bullish (contrarian)
        # At crowded_shorts -> +0.7, below -> approaches +1.0
        normalized = min(1.0, (1.0 - ratio) / (1.0 - crowded_shorts) * 0.7)

    if ratio >= crowded_longs:
        desc = f"Crowded longs ({ratio:.2f}) - contrarian short"
    elif ratio <= crowded_shorts:
        desc = f"Crowded shorts ({ratio:.2f}) - contrarian long"
    else:
        desc = f"Balanced positioning ({ratio:.2f})"

    return SignalNormalizer(
        name="long_short_ratio",
        raw_value=ratio,
        normalized=normalized,
        strength=_classify_strength(normalized),
        description=desc,
    )


def normalize_open_interest_change(
    oi_change_pct: float,
    rising_threshold: float = 5.0,
    falling_threshold: float = -5.0,
) -> SignalNormalizer:
    """
    Normalize Open Interest change percentage.

    Rising OI + rising price = trend confirmation (follow trend)
    Rising OI + falling price = bearish pressure
    Falling OI = position unwinding (potential reversal)

    Args:
        oi_change_pct: 24h OI change percentage
        rising_threshold: % change considered significant rise
        falling_threshold: % change considered significant drop
    """
    # OI change alone is directionally ambiguous; normalize as trend strength
    # High positive OI change = strong conviction (market adding positions)
    # Negative OI change = unwinding (weakening trend)
    if oi_change_pct > 0:
        normalized = min(1.0, oi_change_pct / (rising_threshold * 2))
    else:
        normalized = max(-1.0, oi_change_pct / (abs(falling_threshold) * 2))

    if oi_change_pct > rising_threshold:
        desc = f"OI rising sharply ({oi_change_pct:+.1f}%) - strong conviction"
    elif oi_change_pct < falling_threshold:
        desc = f"OI falling sharply ({oi_change_pct:+.1f}%) - position unwinding"
    else:
        desc = f"OI stable ({oi_change_pct:+.1f}%)"

    return SignalNormalizer(
        name="open_interest_change",
        raw_value=oi_change_pct,
        normalized=normalized,
        strength=_classify_strength(normalized),
        description=desc,
    )


def normalize_price_momentum(
    change_24h_pct: float,
    strong_move: float = 5.0,
) -> SignalNormalizer:
    """
    Normalize 24h price momentum.

    Strong upward move -> long signal
    Strong downward move -> short signal

    Args:
        change_24h_pct: 24h price change percentage
        strong_move: % change considered a strong move
    """
    normalized = change_24h_pct / (strong_move * 2)
    normalized = max(-1.0, min(1.0, normalized))

    if change_24h_pct > strong_move:
        desc = f"Strong upward momentum ({change_24h_pct:+.1f}%)"
    elif change_24h_pct < -strong_move:
        desc = f"Strong downward momentum ({change_24h_pct:+.1f}%)"
    else:
        desc = f"Moderate momentum ({change_24h_pct:+.1f}%)"

    return SignalNormalizer(
        name="price_momentum",
        raw_value=change_24h_pct,
        normalized=normalized,
        strength=_classify_strength(normalized),
        description=desc,
    )


def normalize_rsi(
    rsi: float,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> SignalNormalizer:
    """
    Normalize RSI (contrarian at extremes, trend-following in middle).

    RSI < 30 -> oversold -> long signal
    RSI > 70 -> overbought -> short signal
    30-70 -> neutral/mild trend following

    Args:
        rsi: RSI value (0-100)
        oversold: Oversold threshold
        overbought: Overbought threshold
    """
    rsi = max(0.0, min(100.0, rsi))

    # Map 0-100 to +1 to -1 (contrarian at extremes)
    normalized = 1.0 - (rsi / 50.0)
    normalized = max(-1.0, min(1.0, normalized))

    # Amplify extremes
    if rsi <= oversold:
        normalized = min(1.0, normalized * 1.3)
        desc = f"Oversold RSI ({rsi:.1f}) - buy signal"
    elif rsi >= overbought:
        normalized = max(-1.0, normalized * 1.3)
        desc = f"Overbought RSI ({rsi:.1f}) - sell signal"
    elif rsi < 45:
        desc = f"Low RSI ({rsi:.1f}) - mild long bias"
    elif rsi > 55:
        desc = f"High RSI ({rsi:.1f}) - mild short bias"
    else:
        desc = f"Neutral RSI ({rsi:.1f})"

    return SignalNormalizer(
        name="rsi",
        raw_value=rsi,
        normalized=normalized,
        strength=_classify_strength(normalized),
        description=desc,
    )


def normalize_volume_profile(
    buy_volume_ratio: float,
    threshold: float = 0.6,
) -> SignalNormalizer:
    """
    Normalize buy/sell volume ratio.

    High buy volume ratio -> bullish
    High sell volume ratio -> bearish

    Args:
        buy_volume_ratio: Buy volume / Total volume (0.0-1.0)
        threshold: Ratio above which is considered significant
    """
    buy_volume_ratio = max(0.0, min(1.0, buy_volume_ratio))

    # Map 0.0-1.0 to -1.0 to +1.0
    normalized = (buy_volume_ratio - 0.5) * 2.0
    normalized = max(-1.0, min(1.0, normalized))

    if buy_volume_ratio >= threshold:
        desc = f"High buy volume ({buy_volume_ratio*100:.0f}%) - bullish"
    elif buy_volume_ratio <= (1 - threshold):
        desc = f"High sell volume ({(1-buy_volume_ratio)*100:.0f}%) - bearish"
    else:
        desc = f"Balanced volume ({buy_volume_ratio*100:.0f}% buys)"

    return SignalNormalizer(
        name="volume_profile",
        raw_value=buy_volume_ratio,
        normalized=normalized,
        strength=_classify_strength(normalized),
        description=desc,
    )


def normalize_liquidation_imbalance(
    long_liquidations: float,
    short_liquidations: float,
) -> SignalNormalizer:
    """
    Normalize liquidation imbalance (contrarian).

    More long liquidations -> longs being wiped out -> contrarian long (bottom signal)
    More short liquidations -> shorts being wiped out -> contrarian short (top signal)

    Args:
        long_liquidations: Long liquidation volume (USD)
        short_liquidations: Short liquidation volume (USD)
    """
    total = long_liquidations + short_liquidations

    if total == 0:
        return SignalNormalizer(
            name="liquidation_imbalance",
            raw_value=0.0,
            normalized=0.0,
            strength="neutral",
            description="No liquidation data",
        )

    # Ratio: positive when more longs liquidated (contrarian long signal)
    long_ratio = long_liquidations / total
    imbalance = (long_ratio - 0.5) * 2.0  # -1 to +1

    # Contrarian: if longs are being liquidated -> buy signal
    normalized = imbalance
    normalized = max(-1.0, min(1.0, normalized))

    if long_ratio > 0.65:
        desc = f"Long liquidation cascade ({long_ratio*100:.0f}%) - contrarian long"
    elif long_ratio < 0.35:
        desc = f"Short liquidation cascade ({(1-long_ratio)*100:.0f}%) - contrarian short"
    else:
        desc = f"Balanced liquidations ({long_ratio*100:.0f}% longs)"

    return SignalNormalizer(
        name="liquidation_imbalance",
        raw_value=imbalance,
        normalized=normalized,
        strength=_classify_strength(normalized),
        description=desc,
    )
