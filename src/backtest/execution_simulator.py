"""
Execution Simulator — Realistic trade execution costs for backtesting.

Replaces the BacktestEngine's hardcoded cost model with exchange-aware
calculations that mirror the live execution layer.

Current backtest (engine._close_trade):
  - Slippage: Fixed 0.03% on entry + exit
  - Fees: Flat 0.04% x 2 = 0.08% round trip
  - Funding: position x rate x 0.33 (intraday) or x 1 (multi-day)

ExecutionSimulator:
  - Slippage: Volatility-based f(candle_range) — higher in volatile markets
  - Fees: Exchange-specific taker rates (Bitget 0.06%, Hyperliquid 0.035%)
  - Funding: Exact 8h window counting between entry/exit timestamps

Live reference:
  - Bitget: client.get_trade_total_fees(), client.get_funding_fees()
  - Hyperliquid: client.get_trade_total_fees(), 5% max slippage tolerance
  - Both: Funding charged at 00:00, 08:00, 16:00 UTC
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------ #
#  Fee Schedules per Exchange (Futures / Perpetuals)                   #
# ------------------------------------------------------------------ #

FEE_SCHEDULES: Dict[str, Dict[str, Dict[str, float]]] = {
    "bitget": {
        "standard": {"taker": 0.0006, "maker": 0.0002},    # VIP0: 0.06% / 0.02%
        "vip1":     {"taker": 0.0004, "maker": 0.00016},
        "vip2":     {"taker": 0.00036, "maker": 0.00014},
    },
    "hyperliquid": {
        "standard": {"taker": 0.00035, "maker": 0.0001},   # 0.035% / 0.01%
        "vip1":     {"taker": 0.00025, "maker": 0.00005},
    },
    "binance": {
        "standard": {"taker": 0.0004, "maker": 0.0002},    # 0.04% / 0.02%
        "vip1":     {"taker": 0.00036, "maker": 0.00016},
    },
}

EIGHT_HOURS_SECONDS = 8 * 3600  # 28800


@dataclass
class FillResult:
    """Result of a simulated order fill."""
    effective_price: float
    slippage_percent: float  # As fraction (0.0003 = 0.03%)


class ExecutionSimulator:
    """
    Simulates exchange execution costs for backtesting.

    Drop-in cost calculator that replaces hardcoded values in
    BacktestEngine._close_trade() with realistic exchange models.

    Usage:
        sim = ExecutionSimulator(exchange="bitget")

        # Entry fill with volatility-based slippage
        fill = sim.apply_entry_slippage(price, "long", candle_range)

        # Trade PnL with all costs
        result = sim.calculate_trade_pnl(
            entry_price, exit_price, "long", position_value, leverage,
            funding_rate, entry_ts, exit_ts, entry_range, exit_range
        )
    """

    def __init__(
        self,
        exchange: str = "bitget",
        fee_tier: str = "standard",
        base_slippage: float = 0.0001,             # 0.01% minimum (bid-ask spread)
        volatility_slippage_factor: float = 0.05,  # 5% of candle range
        max_slippage: float = 0.005,                # Cap at 0.5%
        builder_fee_rate: float = 0.0,              # Hyperliquid builder fee
    ):
        self.exchange = exchange.lower()
        self.fee_tier = fee_tier
        self.base_slippage = base_slippage
        self.volatility_slippage_factor = volatility_slippage_factor
        self.max_slippage = max_slippage
        self.builder_fee_rate = builder_fee_rate

        # Resolve fee rates from schedule
        exchange_fees = FEE_SCHEDULES.get(self.exchange, FEE_SCHEDULES["bitget"])
        tier_fees = exchange_fees.get(self.fee_tier, exchange_fees["standard"])
        self.taker_fee_rate = tier_fees["taker"]
        self.maker_fee_rate = tier_fees["maker"]

        logger.info(
            f"ExecutionSimulator initialized: exchange={self.exchange}, "
            f"tier={self.fee_tier}, taker={self.taker_fee_rate*100:.3f}%, "
            f"base_slip={self.base_slippage*100:.3f}%"
        )

    # ------------------------------------------------------------------ #
    #  Slippage Model                                                     #
    # ------------------------------------------------------------------ #

    def calculate_slippage_percent(self, candle_range_pct: float) -> float:
        """
        Calculate slippage as a fraction based on candle volatility.

        Formula: slippage = base + factor x (high - low) / close

        Examples (1h BTC candle):
          Calm market  (0.2% range): 0.01% + 5% x 0.2% = 0.02%
          Normal market (1% range):  0.01% + 5% x 1.0% = 0.06%
          Volatile      (3% range):  0.01% + 5% x 3.0% = 0.16%
        """
        slip = self.base_slippage + self.volatility_slippage_factor * candle_range_pct
        return min(slip, self.max_slippage)

    def apply_entry_slippage(
        self, price: float, direction: str, candle_range_pct: float
    ) -> FillResult:
        """
        Apply slippage to entry price (market order fill).

        Longs fill higher (worse), shorts fill lower (worse).
        """
        slip = self.calculate_slippage_percent(candle_range_pct)

        if direction == "long":
            effective = price * (1 + slip)
        else:
            effective = price * (1 - slip)

        return FillResult(effective_price=effective, slippage_percent=slip)

    def apply_exit_slippage(
        self, price: float, direction: str, candle_range_pct: float,
        is_trigger: bool = False,
    ) -> FillResult:
        """
        Apply slippage to exit price.

        Longs exit lower (worse), shorts exit higher (worse).
        Trigger orders (TP/SL) have reduced slippage since they
        activate at a specific price level.
        """
        slip = self.calculate_slippage_percent(candle_range_pct)

        if is_trigger:
            slip *= 0.5  # TP/SL triggers fill closer to target price

        if direction == "long":
            effective = price * (1 - slip)
        else:
            effective = price * (1 + slip)

        return FillResult(effective_price=effective, slippage_percent=slip)

    # ------------------------------------------------------------------ #
    #  Fee Model                                                          #
    # ------------------------------------------------------------------ #

    def calculate_fees(self, position_value: float) -> float:
        """
        Calculate round-trip trading fees (entry + exit).

        Uses taker rate since backtest assumes market orders.
        Includes builder fee for Hyperliquid if configured.
        """
        round_trip = position_value * self.taker_fee_rate * 2

        if self.builder_fee_rate > 0:
            round_trip += position_value * self.builder_fee_rate * 2

        return round_trip

    # ------------------------------------------------------------------ #
    #  Funding Model                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def count_funding_windows(
        entry_timestamp: datetime, exit_timestamp: datetime
    ) -> int:
        """
        Count 8h funding settlements between entry and exit.

        Funding is charged at 00:00, 08:00, 16:00 UTC.
        Counts windows where: entry < window_time <= exit

        The epoch (1970-01-01 00:00 UTC) aligns with funding boundaries,
        so timestamp / 28800 gives the funding period number.

        Examples:
            07:30 -> 08:30 = 1 window  (08:00)
            07:30 -> 16:30 = 2 windows (08:00, 16:00)
            08:00 -> 16:00 = 1 window  (16:00, entry boundary excluded)
            09:00 -> 15:00 = 0 windows
        """
        if entry_timestamp >= exit_timestamp:
            return 0

        entry_ts = entry_timestamp.timestamp()
        exit_ts = exit_timestamp.timestamp()

        # First funding boundary strictly after entry
        first_boundary = math.ceil(entry_ts / EIGHT_HOURS_SECONDS)
        if first_boundary * EIGHT_HOURS_SECONDS == entry_ts:
            first_boundary += 1  # Exclude exact entry boundary

        # Last funding boundary at or before exit
        last_boundary = math.floor(exit_ts / EIGHT_HOURS_SECONDS)

        if first_boundary > last_boundary:
            return 0

        return last_boundary - first_boundary + 1

    def calculate_funding(
        self,
        position_value: float,
        funding_rate: float,
        entry_timestamp: datetime,
        exit_timestamp: datetime,
    ) -> float:
        """
        Calculate total funding fees based on exact 8h windows crossed.

        Each window crossing costs: |position_value x funding_rate|
        The funding_rate from HistoricalDataPoint is per-settlement (per 8h).

        This replaces the old heuristic:
          - Intraday:  rate x 0.33 (underestimates most trades)
          - Multi-day:  rate x 1.0  (massively underestimates, should be x windows)
        """
        windows = self.count_funding_windows(entry_timestamp, exit_timestamp)

        if windows == 0:
            return 0.0

        return abs(position_value * funding_rate) * windows

    # ------------------------------------------------------------------ #
    #  Complete Trade PnL                                                 #
    # ------------------------------------------------------------------ #

    def calculate_trade_pnl(
        self,
        entry_price: float,
        exit_price: float,
        direction: str,
        position_value: float,
        leverage: int,
        funding_rate: float,
        entry_timestamp: Optional[datetime] = None,
        exit_timestamp: Optional[datetime] = None,
        entry_candle_range: float = 0.0,
        exit_candle_range: float = 0.0,
        exit_is_trigger: bool = False,
    ) -> Dict[str, float]:
        """
        Calculate complete trade PnL with realistic costs.

        Combines slippage, fees, and funding into a single result.

        Returns:
            Dict with keys: pnl, pnl_percent, fees, funding_paid, net_pnl,
                            effective_entry, effective_exit
        """
        # Slippage on entry and exit
        entry_fill = self.apply_entry_slippage(entry_price, direction, entry_candle_range)
        exit_fill = self.apply_exit_slippage(exit_price, direction, exit_candle_range, exit_is_trigger)

        effective_entry = entry_fill.effective_price
        effective_exit = exit_fill.effective_price

        # PnL from price movement (after slippage)
        if direction == "long":
            price_pnl = (effective_exit - effective_entry) / entry_price
        else:
            price_pnl = (effective_entry - effective_exit) / entry_price

        pnl_percent = price_pnl * 100 * leverage
        pnl = position_value * (price_pnl * leverage)

        # Fees
        fees = self.calculate_fees(position_value)

        # Funding
        if entry_timestamp and exit_timestamp:
            funding_paid = self.calculate_funding(
                position_value, funding_rate, entry_timestamp, exit_timestamp
            )
        else:
            # Fallback: legacy estimation if timestamps unavailable
            funding_paid = abs(position_value * funding_rate) * 0.33

        net_pnl = pnl - fees - funding_paid

        return {
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "fees": fees,
            "funding_paid": funding_paid,
            "net_pnl": net_pnl,
            "effective_entry": effective_entry,
            "effective_exit": effective_exit,
        }
