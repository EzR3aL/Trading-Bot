"""
Cross-Exchange Arbitrage Scanner.

Scans for price discrepancies and funding rate differences
across multiple exchanges to identify arbitrage opportunities.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from src.exchanges.base import ExchangeTicker, ExchangeFundingRate
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ArbType(str, Enum):
    """Types of arbitrage opportunities."""
    SPOT_SPOT = "spot_spot"          # Price diff between exchanges
    FUNDING_DIFF = "funding_diff"    # Different funding rates
    FUTURES_BASIS = "futures_basis"   # Spot vs futures price gap


@dataclass
class ArbOpportunity:
    """Represents a cross-exchange arbitrage opportunity."""
    id: str
    arb_type: ArbType
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    spread_pct: float
    estimated_profit_pct: float  # After fees
    estimated_profit_usd: float  # For reference position size
    fees_pct: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict = field(default_factory=dict)

    @property
    def is_profitable(self) -> bool:
        return self.estimated_profit_pct > 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "arb_type": self.arb_type.value,
            "symbol": self.symbol,
            "buy_exchange": self.buy_exchange,
            "sell_exchange": self.sell_exchange,
            "buy_price": self.buy_price,
            "sell_price": self.sell_price,
            "spread_pct": round(self.spread_pct, 6),
            "estimated_profit_pct": round(self.estimated_profit_pct, 6),
            "estimated_profit_usd": round(self.estimated_profit_usd, 4),
            "fees_pct": round(self.fees_pct, 6),
            "is_profitable": self.is_profitable,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class ArbScanner:
    """
    Scans for cross-exchange arbitrage opportunities.

    Compares prices and funding rates across exchanges to find
    exploitable discrepancies after accounting for fees.
    """

    # Default fee assumptions per exchange (taker fees)
    DEFAULT_FEES = {
        "bitget": 0.06,   # 0.06%
        "binance": 0.04,  # 0.04%
        "okx": 0.05,      # 0.05%
        "bybit": 0.06,    # 0.06%
    }

    def __init__(
        self,
        min_spread_pct: float = 0.1,
        min_profit_pct: float = 0.02,
        reference_position: float = 10000.0,
        exchange_fees: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize the arbitrage scanner.

        Args:
            min_spread_pct: Minimum price spread to consider (%)
            min_profit_pct: Minimum profit after fees (%)
            reference_position: Position size for profit estimation (USD)
            exchange_fees: Custom fee map (exchange -> taker fee %)
        """
        self.min_spread_pct = min_spread_pct
        self.min_profit_pct = min_profit_pct
        self.reference_position = reference_position
        self.exchange_fees = exchange_fees or dict(self.DEFAULT_FEES)

        self._opportunities: List[ArbOpportunity] = []
        self._next_id = 1

    def scan_spot_arb(
        self,
        tickers: Dict[str, ExchangeTicker],
    ) -> List[ArbOpportunity]:
        """
        Scan for spot-spot price arbitrage across exchanges.

        Args:
            tickers: Dict of exchange_name -> ExchangeTicker for same symbol

        Returns:
            List of profitable opportunities
        """
        if len(tickers) < 2:
            return []

        opportunities = []
        exchanges = list(tickers.items())

        for i, (name_a, ticker_a) in enumerate(exchanges):
            for name_b, ticker_b in exchanges[i + 1:]:
                # Check A buy -> B sell
                opp = self._check_pair(
                    ticker_a.symbol, name_a, ticker_a.ask,
                    name_b, ticker_b.bid,
                )
                if opp:
                    opportunities.append(opp)

                # Check B buy -> A sell
                opp = self._check_pair(
                    ticker_b.symbol, name_b, ticker_b.ask,
                    name_a, ticker_a.bid,
                )
                if opp:
                    opportunities.append(opp)

        self._opportunities.extend(opportunities)
        return sorted(opportunities, key=lambda x: x.estimated_profit_pct, reverse=True)

    def scan_funding_arb(
        self,
        funding_rates: Dict[str, ExchangeFundingRate],
    ) -> List[ArbOpportunity]:
        """
        Scan for funding rate differential arbitrage.

        When funding rates differ between exchanges, you can
        be short on the high-rate exchange and long on the low-rate exchange.

        Args:
            funding_rates: Dict of exchange_name -> ExchangeFundingRate

        Returns:
            List of funding rate arb opportunities
        """
        if len(funding_rates) < 2:
            return []

        opportunities = []
        exchanges = list(funding_rates.items())

        for i, (name_a, rate_a) in enumerate(exchanges):
            for name_b, rate_b in exchanges[i + 1:]:
                diff = abs(rate_a.rate - rate_b.rate)
                diff_pct = diff * 100

                if diff_pct < self.min_spread_pct / 10:  # Lower threshold for funding
                    continue

                # Short the higher rate exchange, long the lower
                if rate_a.rate > rate_b.rate:
                    short_exchange = name_a
                    long_exchange = name_b
                    short_rate = rate_a.rate
                    long_rate = rate_b.rate
                else:
                    short_exchange = name_b
                    long_exchange = name_a
                    short_rate = rate_b.rate
                    long_rate = rate_a.rate

                # Profit = rate difference * 3 periods/day (annualize for daily)
                daily_profit_pct = diff * 3 * 100

                fees = self._get_combined_fees(long_exchange, short_exchange)
                net_profit_pct = daily_profit_pct - fees

                if net_profit_pct <= 0:
                    continue

                opp = ArbOpportunity(
                    id=f"XARB-{self._next_id:04d}",
                    arb_type=ArbType.FUNDING_DIFF,
                    symbol=rate_a.symbol,
                    buy_exchange=long_exchange,
                    sell_exchange=short_exchange,
                    buy_price=long_rate,
                    sell_price=short_rate,
                    spread_pct=diff_pct,
                    estimated_profit_pct=net_profit_pct,
                    estimated_profit_usd=self.reference_position * (net_profit_pct / 100),
                    fees_pct=fees,
                    metadata={
                        "long_funding_rate": long_rate,
                        "short_funding_rate": short_rate,
                        "rate_diff": diff,
                        "daily_profit_pct": round(daily_profit_pct, 4),
                    },
                )
                self._next_id += 1
                opportunities.append(opp)

        self._opportunities.extend(opportunities)
        return sorted(opportunities, key=lambda x: x.estimated_profit_pct, reverse=True)

    def get_all_opportunities(self) -> List[ArbOpportunity]:
        """Get all identified opportunities."""
        return list(self._opportunities)

    def get_profitable_opportunities(self) -> List[ArbOpportunity]:
        """Get only profitable opportunities."""
        return [o for o in self._opportunities if o.is_profitable]

    def get_summary(self) -> dict:
        """Get scanner summary."""
        profitable = self.get_profitable_opportunities()
        spot_arbs = [o for o in profitable if o.arb_type == ArbType.SPOT_SPOT]
        funding_arbs = [o for o in profitable if o.arb_type == ArbType.FUNDING_DIFF]

        return {
            "total_opportunities": len(self._opportunities),
            "profitable_opportunities": len(profitable),
            "spot_arb_count": len(spot_arbs),
            "funding_arb_count": len(funding_arbs),
            "best_opportunity": profitable[0].to_dict() if profitable else None,
            "config": {
                "min_spread_pct": self.min_spread_pct,
                "min_profit_pct": self.min_profit_pct,
                "reference_position": self.reference_position,
                "exchange_fees": self.exchange_fees,
            },
        }

    def clear_opportunities(self):
        """Clear all tracked opportunities."""
        self._opportunities.clear()

    def _check_pair(
        self,
        symbol: str,
        buy_exchange: str,
        buy_price: float,
        sell_exchange: str,
        sell_price: float,
    ) -> Optional[ArbOpportunity]:
        """Check if a buy/sell pair represents a profitable arb."""
        if buy_price <= 0 or sell_price <= 0:
            return None

        spread_pct = ((sell_price - buy_price) / buy_price) * 100

        if spread_pct < self.min_spread_pct:
            return None

        fees = self._get_combined_fees(buy_exchange, sell_exchange)
        profit_pct = spread_pct - fees

        if profit_pct < self.min_profit_pct:
            return None

        profit_usd = self.reference_position * (profit_pct / 100)

        opp = ArbOpportunity(
            id=f"XARB-{self._next_id:04d}",
            arb_type=ArbType.SPOT_SPOT,
            symbol=symbol,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            buy_price=buy_price,
            sell_price=sell_price,
            spread_pct=spread_pct,
            estimated_profit_pct=profit_pct,
            estimated_profit_usd=profit_usd,
            fees_pct=fees,
        )
        self._next_id += 1
        return opp

    def _get_combined_fees(self, exchange_a: str, exchange_b: str) -> float:
        """Get combined taker fees for two exchanges."""
        fee_a = self.exchange_fees.get(exchange_a.lower(), 0.1)
        fee_b = self.exchange_fees.get(exchange_b.lower(), 0.1)
        return fee_a + fee_b
