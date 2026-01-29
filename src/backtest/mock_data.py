"""
Mock Historical Data Generator for Backtesting.

Generates realistic historical data when external APIs are not available.
Based on typical crypto market patterns over the last 6 months.
"""

import random
from datetime import datetime, timedelta
from typing import List

from src.backtest.historical_data import HistoricalDataPoint


def generate_mock_historical_data(days: int = 180, seed: int = 42) -> List[HistoricalDataPoint]:
    """
    Generate realistic mock historical data for backtesting.

    This simulates 6 months of crypto market data with:
    - Realistic price movements (BTC: ~40k-110k range, ETH: ~2k-4k range)
    - Fear & Greed cycles (typically 20-80 with occasional extremes)
    - L/S ratio fluctuations (typically 0.8-1.5 with occasional extremes)
    - Realistic funding rates (-0.1% to +0.2%)

    Args:
        days: Number of days to generate
        seed: Random seed for reproducibility

    Returns:
        List of HistoricalDataPoint objects
    """
    random.seed(seed)
    data_points = []

    # Starting values (approximate values from August 2025)
    btc_price = 65000.0
    eth_price = 3200.0
    fear_greed = 50
    ls_ratio = 1.0

    # Market phases (simulate bull/bear cycles)
    # Phase 0: Accumulation (neutral)
    # Phase 1: Bull run (greed, high L/S)
    # Phase 2: Distribution (extreme greed)
    # Phase 3: Bear market (fear, low L/S)
    # Phase 4: Capitulation (extreme fear)
    phase_duration = days // 5
    current_phase = 0

    start_date = datetime.now() - timedelta(days=days)

    for i in range(days):
        current_date = start_date + timedelta(days=i)
        date_str = current_date.strftime("%Y-%m-%d")

        # Update phase
        if i > 0 and i % phase_duration == 0:
            current_phase = (current_phase + 1) % 5

        # Generate data based on phase
        if current_phase == 0:  # Accumulation
            btc_change = random.uniform(-2, 3)
            fear_greed_target = random.randint(40, 60)
            ls_ratio_target = random.uniform(0.9, 1.1)

        elif current_phase == 1:  # Bull run
            btc_change = random.uniform(-1, 5)
            fear_greed_target = random.randint(55, 75)
            ls_ratio_target = random.uniform(1.1, 1.8)

        elif current_phase == 2:  # Distribution (extreme greed)
            btc_change = random.uniform(-3, 4)
            fear_greed_target = random.randint(70, 90)  # Extreme greed
            ls_ratio_target = random.uniform(1.5, 2.5)  # Crowded longs

        elif current_phase == 3:  # Bear market
            btc_change = random.uniform(-5, 2)
            fear_greed_target = random.randint(25, 45)
            ls_ratio_target = random.uniform(0.6, 1.0)

        else:  # Capitulation (extreme fear)
            btc_change = random.uniform(-6, 3)
            fear_greed_target = random.randint(10, 30)  # Extreme fear
            ls_ratio_target = random.uniform(0.3, 0.7)  # Crowded shorts

        # Apply changes with smoothing
        btc_price *= (1 + btc_change / 100)
        eth_price = btc_price * random.uniform(0.045, 0.055)  # ETH/BTC ratio

        # Smooth fear/greed and L/S ratio transitions
        fear_greed = int(fear_greed * 0.7 + fear_greed_target * 0.3)
        fear_greed = max(5, min(95, fear_greed + random.randint(-5, 5)))

        ls_ratio = ls_ratio * 0.7 + ls_ratio_target * 0.3
        ls_ratio = max(0.3, min(3.0, ls_ratio + random.uniform(-0.1, 0.1)))

        # Calculate high/low based on volatility
        btc_volatility = abs(btc_change) * 0.5 + random.uniform(1, 3)
        btc_high = btc_price * (1 + btc_volatility / 100)
        btc_low = btc_price * (1 - btc_volatility / 100)

        eth_volatility = btc_volatility * 1.2  # ETH more volatile
        eth_high = eth_price * (1 + eth_volatility / 100)
        eth_low = eth_price * (1 - eth_volatility / 100)

        # Funding rates correlate with sentiment
        if ls_ratio > 1.5:
            funding_btc = random.uniform(0.0003, 0.0015)  # Positive (longs pay)
        elif ls_ratio < 0.7:
            funding_btc = random.uniform(-0.001, -0.0001)  # Negative (shorts pay)
        else:
            funding_btc = random.uniform(-0.0003, 0.0005)

        funding_eth = funding_btc * random.uniform(0.8, 1.2)

        # Classification
        if fear_greed < 25:
            classification = "Extreme Fear"
        elif fear_greed < 40:
            classification = "Fear"
        elif fear_greed < 60:
            classification = "Neutral"
        elif fear_greed < 75:
            classification = "Greed"
        else:
            classification = "Extreme Greed"

        data_point = HistoricalDataPoint(
            timestamp=current_date,
            date_str=date_str,
            fear_greed_index=fear_greed,
            fear_greed_classification=classification,
            long_short_ratio=round(ls_ratio, 4),
            funding_rate_btc=round(funding_btc, 6),
            funding_rate_eth=round(funding_eth, 6),
            btc_price=round(btc_price, 2),
            eth_price=round(eth_price, 2),
            btc_high=round(btc_high, 2),
            btc_low=round(btc_low, 2),
            eth_high=round(eth_high, 2),
            eth_low=round(eth_low, 2),
            btc_24h_change=round(btc_change, 2),
            eth_24h_change=round(btc_change * random.uniform(0.8, 1.3), 2),
        )

        data_points.append(data_point)

    return data_points


def get_mock_data_summary(data_points: List[HistoricalDataPoint]) -> dict:
    """Get summary statistics of mock data."""
    if not data_points:
        return {}

    btc_prices = [d.btc_price for d in data_points]
    fgi_values = [d.fear_greed_index for d in data_points]
    ls_ratios = [d.long_short_ratio for d in data_points]

    extreme_fear_days = sum(1 for d in data_points if d.fear_greed_index < 25)
    extreme_greed_days = sum(1 for d in data_points if d.fear_greed_index > 75)
    crowded_long_days = sum(1 for d in data_points if d.long_short_ratio > 2.0)
    crowded_short_days = sum(1 for d in data_points if d.long_short_ratio < 0.5)

    return {
        "period": f"{data_points[0].date_str} to {data_points[-1].date_str}",
        "days": len(data_points),
        "btc_start": data_points[0].btc_price,
        "btc_end": data_points[-1].btc_price,
        "btc_min": min(btc_prices),
        "btc_max": max(btc_prices),
        "fgi_avg": sum(fgi_values) / len(fgi_values),
        "ls_avg": sum(ls_ratios) / len(ls_ratios),
        "extreme_fear_days": extreme_fear_days,
        "extreme_greed_days": extreme_greed_days,
        "crowded_long_days": crowded_long_days,
        "crowded_short_days": crowded_short_days,
    }
