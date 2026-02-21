"""
Mock Historical Data Generator for Backtesting.

Generates realistic historical data when external APIs are not available.
Based on typical crypto market patterns over the last 6 months.
"""

import math
import random
from datetime import datetime, timedelta
from typing import List

from src.backtest.historical_data import HistoricalDataPoint


def generate_mock_historical_data(days: int = 180, seed: int = 42, interval: str = "1d") -> List[HistoricalDataPoint]:
    """
    Generate realistic mock historical data for backtesting.

    Simulates crypto market data across all tracked metrics.
    Supports intraday intervals — daily indicator data (FGI, L/S, etc.)
    is repeated for all candles within the same day.

    Args:
        days: Number of days to generate
        seed: Random seed for reproducibility
        interval: Candle interval (1m, 5m, 15m, 30m, 1h, 4h, 1d)

    Returns:
        List of HistoricalDataPoint objects
    """
    random.seed(seed)
    data_points = []

    # Interval configuration
    CANDLES_PER_DAY = {"1m": 1440, "5m": 288, "15m": 96, "30m": 48, "1h": 24, "4h": 6, "1d": 1}
    INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
    cpd = CANDLES_PER_DAY.get(interval, 1)
    step_minutes = INTERVAL_MINUTES.get(interval, 1440)
    total_candles = days * cpd

    # Scale per-candle price change relative to daily
    change_scale = 1.0 / math.sqrt(cpd) if cpd > 1 else 1.0

    # Starting values
    btc_price = 65000.0
    eth_price = 3200.0
    fear_greed = 50
    ls_ratio = 1.0
    oi_value = 18_000_000_000.0  # ~$18B Open Interest
    usdt_mcap = 120_000_000_000.0  # ~$120B USDT market cap
    btc_hashrate = 650.0  # EH/s
    dxy_value = 104.0  # DXY index
    ffr_value = 5.25  # Fed Funds Rate

    # Market phases
    phase_duration = max(days // 5, 1)
    current_phase = 0

    start_date = datetime.now() - timedelta(days=days)

    # Track daily returns for volatility calculation
    daily_returns = []
    prev_day_btc_price = btc_price

    # Daily indicator values (regenerated once per day)
    daily_vals = {}

    for candle_idx in range(total_candles):
        current_date = start_date + timedelta(minutes=candle_idx * step_minutes)
        date_str = current_date.strftime("%Y-%m-%d")
        day_index = candle_idx // cpd
        candle_in_day = candle_idx % cpd

        # Regenerate daily-level indicators at the start of each new day
        if candle_in_day == 0:
            if day_index > 0 and day_index % phase_duration == 0:
                current_phase = (current_phase + 1) % 5

            # Phase-dependent parameters (daily granularity)
            if current_phase == 0:  # Accumulation
                daily_btc_change = random.uniform(-2, 3)
                fear_greed_target = random.randint(40, 60)
                ls_ratio_target = random.uniform(0.9, 1.1)
                oi_change = random.uniform(-2, 3)
                taker_ratio_target = random.uniform(0.95, 1.05)
                top_trader_ls_target = random.uniform(0.9, 1.1)
                stable_flow_target = random.uniform(-500_000_000, 500_000_000)
                hashrate_change = random.uniform(0, 1)
                dxy_change = random.uniform(-0.3, 0.3)
            elif current_phase == 1:  # Bull run
                daily_btc_change = random.uniform(-1, 5)
                fear_greed_target = random.randint(55, 75)
                ls_ratio_target = random.uniform(1.1, 1.8)
                oi_change = random.uniform(0, 5)
                taker_ratio_target = random.uniform(1.0, 1.3)
                top_trader_ls_target = random.uniform(1.1, 1.6)
                stable_flow_target = random.uniform(0, 2_000_000_000)
                hashrate_change = random.uniform(0.5, 2)
                dxy_change = random.uniform(-0.5, 0.1)
            elif current_phase == 2:  # Distribution (extreme greed)
                daily_btc_change = random.uniform(-3, 4)
                fear_greed_target = random.randint(70, 90)
                ls_ratio_target = random.uniform(1.5, 2.5)
                oi_change = random.uniform(-1, 3)
                taker_ratio_target = random.uniform(1.1, 1.5)
                top_trader_ls_target = random.uniform(1.3, 2.0)
                stable_flow_target = random.uniform(-1_000_000_000, 1_000_000_000)
                hashrate_change = random.uniform(-0.5, 1)
                dxy_change = random.uniform(-0.2, 0.4)
            elif current_phase == 3:  # Bear market
                daily_btc_change = random.uniform(-5, 2)
                fear_greed_target = random.randint(25, 45)
                ls_ratio_target = random.uniform(0.6, 1.0)
                oi_change = random.uniform(-5, 0)
                taker_ratio_target = random.uniform(0.7, 0.95)
                top_trader_ls_target = random.uniform(0.6, 1.0)
                stable_flow_target = random.uniform(-2_000_000_000, 0)
                hashrate_change = random.uniform(-1, 0.5)
                dxy_change = random.uniform(0, 0.5)
            else:  # Capitulation (extreme fear)
                daily_btc_change = random.uniform(-6, 3)
                fear_greed_target = random.randint(10, 30)
                ls_ratio_target = random.uniform(0.3, 0.7)
                oi_change = random.uniform(-8, -2)
                taker_ratio_target = random.uniform(0.5, 0.8)
                top_trader_ls_target = random.uniform(0.4, 0.8)
                stable_flow_target = random.uniform(-3_000_000_000, -500_000_000)
                hashrate_change = random.uniform(-2, 0)
                dxy_change = random.uniform(0.1, 0.6)

            # Update daily indicators
            fear_greed = int(fear_greed * 0.7 + fear_greed_target * 0.3)
            fear_greed = max(5, min(95, fear_greed + random.randint(-5, 5)))

            ls_ratio = ls_ratio * 0.7 + ls_ratio_target * 0.3
            ls_ratio = max(0.3, min(3.0, ls_ratio + random.uniform(-0.1, 0.1)))

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

            # Funding rates
            if ls_ratio > 1.5:
                funding_btc = random.uniform(0.0003, 0.0015)
            elif ls_ratio < 0.7:
                funding_btc = random.uniform(-0.001, -0.0001)
            else:
                funding_btc = random.uniform(-0.0003, 0.0005)
            funding_eth = funding_btc * random.uniform(0.8, 1.2)

            # Open Interest
            oi_value *= (1 + oi_change / 100)
            oi_value = max(5_000_000_000, oi_value)

            # Taker ratio with smoothing
            if data_points:
                taker_ratio = 0.7 * data_points[-1].taker_buy_sell_ratio + 0.3 * taker_ratio_target
            else:
                taker_ratio = taker_ratio_target
            taker_ratio = max(0.3, min(2.0, taker_ratio + random.uniform(-0.05, 0.05)))

            # Top trader L/S
            if data_points:
                top_ls = 0.7 * data_points[-1].top_trader_long_short_ratio + 0.3 * top_trader_ls_target
            else:
                top_ls = top_trader_ls_target
            top_ls = max(0.3, min(3.0, top_ls + random.uniform(-0.1, 0.1)))

            # Bitget funding
            funding_bitget = funding_btc * random.uniform(0.85, 1.15) + random.uniform(-0.0001, 0.0001)

            # Stablecoin flows
            stablecoin_flow = stable_flow_target * random.uniform(0.5, 1.5)
            usdt_mcap += stablecoin_flow / 7
            usdt_mcap = max(50_000_000_000, usdt_mcap)

            # BTC dominance
            if current_phase in (1, 2):
                btc_dom = random.uniform(48, 58)
            elif current_phase in (3, 4):
                btc_dom = random.uniform(52, 62)
            else:
                btc_dom = random.uniform(45, 55)

            total_mcap = btc_price * 19_700_000 / (btc_dom / 100)

            # Hashrate
            btc_hashrate *= (1 + hashrate_change / 100)
            btc_hashrate = max(300, btc_hashrate)

            # DXY
            dxy_value += dxy_change
            dxy_value = max(90, min(115, dxy_value))

            # Fed Funds Rate
            if random.random() < 0.005:  # pragma: no cover
                ffr_value += random.choice([-0.25, 0.25])
                ffr_value = max(0, min(10, ffr_value))

            # Track daily return for volatility
            if day_index > 0:
                daily_ret = (btc_price - prev_day_btc_price) / prev_day_btc_price if prev_day_btc_price > 0 else 0
                daily_returns.append(daily_ret)
            prev_day_btc_price = btc_price

            # Volatility (rolling 20-day std)
            if len(daily_returns) >= 20:
                window = daily_returns[-20:]
                mean_r = sum(window) / len(window)
                var = sum((r - mean_r) ** 2 for r in window) / (len(window) - 1)
                hist_vol = math.sqrt(var) * math.sqrt(365) * 100
            else:
                hist_vol = random.uniform(30, 80)

            # Store daily values for reuse across intraday candles
            daily_vals = {
                "fear_greed": fear_greed, "classification": classification,
                "ls_ratio": ls_ratio, "funding_btc": funding_btc, "funding_eth": funding_eth,
                "oi_value": oi_value, "oi_change": oi_change,
                "taker_ratio": taker_ratio, "top_ls": top_ls, "funding_bitget": funding_bitget,
                "stablecoin_flow": stablecoin_flow, "usdt_mcap": usdt_mcap,
                "btc_dom": btc_dom, "total_mcap": total_mcap,
                "btc_hashrate": btc_hashrate, "dxy_value": dxy_value, "ffr_value": ffr_value,
                "hist_vol": hist_vol, "daily_btc_change": daily_btc_change,
            }

        # Per-candle price movement (scaled for interval)
        # Open = previous close (realistic OHLC)
        btc_open = btc_price
        eth_open = eth_price

        btc_change = random.uniform(-2, 3) * change_scale if cpd > 1 else daily_vals["daily_btc_change"]
        btc_price *= (1 + btc_change / 100)
        eth_change = btc_change * random.uniform(0.8, 1.3)
        eth_price *= (1 + eth_change / 100)

        # OHLC
        btc_volatility = abs(btc_change) * 0.5 + random.uniform(0.5, 2) * change_scale
        btc_high = max(btc_open, btc_price) * (1 + btc_volatility / 200)
        btc_low = min(btc_open, btc_price) * (1 - btc_volatility / 200)

        eth_volatility = btc_volatility * 1.2
        eth_high = max(eth_open, eth_price) * (1 + eth_volatility / 200)
        eth_low = min(eth_open, eth_price) * (1 - eth_volatility / 200)

        btc_volume = btc_price * random.uniform(50000, 200000) / cpd
        eth_volume = eth_price * random.uniform(30000, 120000) / cpd

        data_point = HistoricalDataPoint(
            timestamp=current_date,
            date_str=date_str,
            fear_greed_index=daily_vals["fear_greed"],
            fear_greed_classification=daily_vals["classification"],
            long_short_ratio=round(daily_vals["ls_ratio"], 4),
            funding_rate_btc=round(daily_vals["funding_btc"], 6),
            funding_rate_eth=round(daily_vals["funding_eth"], 6),
            btc_price=round(btc_price, 2),
            eth_price=round(eth_price, 2),
            btc_open=round(btc_open, 2),
            eth_open=round(eth_open, 2),
            btc_high=round(btc_high, 2),
            btc_low=round(btc_low, 2),
            eth_high=round(eth_high, 2),
            eth_low=round(eth_low, 2),
            btc_24h_change=round(btc_change, 2),
            eth_24h_change=round(btc_change * random.uniform(0.8, 1.3), 2),
            # Extended fields (daily values, forward-filled for intraday)
            open_interest_btc=round(daily_vals["oi_value"], 2),
            open_interest_change_24h=round(daily_vals["oi_change"], 2),
            taker_buy_sell_ratio=round(daily_vals["taker_ratio"], 4),
            top_trader_long_short_ratio=round(daily_vals["top_ls"], 4),
            funding_rate_bitget=round(daily_vals["funding_bitget"], 6),
            stablecoin_flow_7d=round(daily_vals["stablecoin_flow"], 2),
            usdt_market_cap=round(daily_vals["usdt_mcap"], 2),
            btc_dominance=round(daily_vals["btc_dom"], 2),
            total_crypto_market_cap=round(daily_vals["total_mcap"], 2),
            dxy_index=round(daily_vals["dxy_value"], 2),
            fed_funds_rate=round(daily_vals["ffr_value"], 2),
            btc_hashrate=round(daily_vals["btc_hashrate"], 2),
            historical_volatility=round(daily_vals["hist_vol"], 2),
            btc_volume=round(btc_volume, 2),
            eth_volume=round(eth_volume, 2),
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
        "data_sources": [
            "Mock Data Generator",
            "Fear & Greed (simulated)",
            "Open Interest (simulated)",
            "Taker Buy/Sell (simulated)",
            "Top Trader L/S (simulated)",
            "Stablecoin Flows (simulated)",
            "BTC Hashrate (simulated)",
            "DXY Index (simulated)",
            "Historical Volatility (calculated)",
        ],
    }
