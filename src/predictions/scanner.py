"""
Prediction Market Arbitrage Scanner.

Detects mispricing in prediction markets by analyzing:
1. YES+NO underpricing (sum < 1.0 = guaranteed profit)
2. Cross-platform price discrepancies
3. Multi-outcome markets where sum < 1.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from src.predictions.base import PredictionContract, PredictionMarket, MarketOutcome
from src.utils.logger import get_logger

logger = get_logger(__name__)


class OpportunityType(str, Enum):
    """Types of prediction market arbitrage."""
    BINARY_UNDERPRICED = "binary_underpriced"      # YES+NO < 1.0
    BINARY_OVERPRICED = "binary_overpriced"         # YES+NO > 1.0 (sell both)
    MULTI_OUTCOME_ARB = "multi_outcome_arb"         # Sum of all outcomes < 1.0
    CROSS_PLATFORM = "cross_platform"               # Same event, different prices
    CORRELATED_MISPRICING = "correlated_mispricing"  # Dependent events mispriced


@dataclass
class PredictionOpportunity:
    """A detected prediction market arbitrage opportunity."""
    id: str
    opportunity_type: OpportunityType
    platform: str
    market_title: str
    contract_question: str
    contract_id: str
    outcomes: List[Dict]  # [{name, price, action}]
    total_cost: float     # Cost to execute (per $1 of contracts)
    guaranteed_payout: float  # Guaranteed minimum payout
    edge_pct: float       # Profit margin as percentage
    estimated_profit_usd: float  # For reference position
    min_liquidity: float  # Minimum liquidity across outcomes
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict = field(default_factory=dict)

    @property
    def is_profitable(self) -> bool:
        return self.edge_pct > 0

    @property
    def risk_adjusted_edge(self) -> float:
        """Edge adjusted for liquidity risk."""
        if self.min_liquidity <= 0:
            return 0.0
        # Reduce edge if liquidity is low
        liquidity_factor = min(1.0, self.min_liquidity / 1000.0)
        return self.edge_pct * liquidity_factor

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "opportunity_type": self.opportunity_type.value,
            "platform": self.platform,
            "market_title": self.market_title,
            "contract_question": self.contract_question,
            "contract_id": self.contract_id,
            "outcomes": self.outcomes,
            "total_cost": round(self.total_cost, 4),
            "guaranteed_payout": round(self.guaranteed_payout, 4),
            "edge_pct": round(self.edge_pct, 4),
            "risk_adjusted_edge": round(self.risk_adjusted_edge, 4),
            "estimated_profit_usd": round(self.estimated_profit_usd, 2),
            "min_liquidity": round(self.min_liquidity, 2),
            "is_profitable": self.is_profitable,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class PredictionArbScanner:
    """
    Scans prediction markets for arbitrage opportunities.

    Detects mispricing by analyzing outcome probabilities and
    identifying situations where guaranteed profit is possible.
    """

    def __init__(
        self,
        min_edge_pct: float = 0.5,
        min_liquidity: float = 100.0,
        reference_position: float = 1000.0,
        platform_fees: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize the prediction arb scanner.

        Args:
            min_edge_pct: Minimum edge to report (%)
            min_liquidity: Minimum liquidity per outcome ($)
            reference_position: Reference position size for profit estimation ($)
            platform_fees: Platform fee map (platform -> fee %)
        """
        self.min_edge_pct = min_edge_pct
        self.min_liquidity = min_liquidity
        self.reference_position = reference_position
        self.platform_fees = platform_fees or {
            "polymarket": 0.0,   # No trading fees (pays via spread)
            "azuro": 2.0,       # ~2% platform fee
            "overtime": 3.0,    # ~3% fee
            "thales": 1.0,      # ~1% fee
        }

        self._opportunities: List[PredictionOpportunity] = []
        self._next_id = 1
        self._scanned_contracts = 0

    def scan_binary_arb(
        self,
        contracts: List[PredictionContract],
        platform: str = "unknown",
    ) -> List[PredictionOpportunity]:
        """
        Scan binary contracts for YES+NO mispricing.

        In an efficient market, YES + NO = 1.0.
        If YES + NO < 1.0, buying both guarantees profit.
        If YES + NO > 1.0, the market is overpriced (sell opportunity).

        Args:
            contracts: List of binary prediction contracts
            platform: Platform name for fee calculation

        Returns:
            List of detected opportunities
        """
        opportunities = []
        fee_pct = self.platform_fees.get(platform.lower(), 1.0)

        for contract in contracts:
            self._scanned_contracts += 1

            if not contract.is_binary:
                continue

            yes_outcome = contract.outcomes[0]
            no_outcome = contract.outcomes[1]

            total_price = yes_outcome.price + no_outcome.price

            if total_price <= 0:
                continue

            # Binary underpricing: YES + NO < 1.0
            if total_price < 1.0:
                raw_edge = (1.0 - total_price) / total_price * 100
                net_edge = raw_edge - fee_pct

                if net_edge < self.min_edge_pct:
                    continue

                min_liq = min(yes_outcome.liquidity, no_outcome.liquidity)
                if min_liq < self.min_liquidity:
                    continue

                opp = PredictionOpportunity(
                    id=f"PRED-{self._next_id:04d}",
                    opportunity_type=OpportunityType.BINARY_UNDERPRICED,
                    platform=platform,
                    market_title=contract.market_id,
                    contract_question=contract.question,
                    contract_id=contract.contract_id,
                    outcomes=[
                        {"name": yes_outcome.name, "price": yes_outcome.price, "action": "BUY"},
                        {"name": no_outcome.name, "price": no_outcome.price, "action": "BUY"},
                    ],
                    total_cost=total_price,
                    guaranteed_payout=1.0,
                    edge_pct=net_edge,
                    estimated_profit_usd=self.reference_position * (net_edge / 100),
                    min_liquidity=min_liq,
                    metadata={
                        "yes_price": yes_outcome.price,
                        "no_price": no_outcome.price,
                        "raw_edge_pct": round(raw_edge, 4),
                        "fee_pct": fee_pct,
                    },
                )
                self._next_id += 1
                opportunities.append(opp)

        self._opportunities.extend(opportunities)
        return sorted(opportunities, key=lambda x: x.edge_pct, reverse=True)

    def scan_multi_outcome_arb(
        self,
        contracts: List[PredictionContract],
        platform: str = "unknown",
    ) -> List[PredictionOpportunity]:
        """
        Scan multi-outcome contracts for arbitrage.

        If the sum of all outcome prices < 1.0, buying all outcomes
        guarantees a profit on resolution.

        Args:
            contracts: List of prediction contracts
            platform: Platform name for fee calculation

        Returns:
            List of detected opportunities
        """
        opportunities = []
        fee_pct = self.platform_fees.get(platform.lower(), 1.0)

        for contract in contracts:
            self._scanned_contracts += 1

            if len(contract.outcomes) < 2:
                continue

            total_price = sum(o.price for o in contract.outcomes)

            if total_price <= 0:
                continue

            if total_price < 1.0:
                raw_edge = (1.0 - total_price) / total_price * 100
                net_edge = raw_edge - fee_pct

                if net_edge < self.min_edge_pct:
                    continue

                min_liq = min(o.liquidity for o in contract.outcomes)
                if min_liq < self.min_liquidity:
                    continue

                opp = PredictionOpportunity(
                    id=f"PRED-{self._next_id:04d}",
                    opportunity_type=OpportunityType.MULTI_OUTCOME_ARB,
                    platform=platform,
                    market_title=contract.market_id,
                    contract_question=contract.question,
                    contract_id=contract.contract_id,
                    outcomes=[
                        {"name": o.name, "price": o.price, "action": "BUY"}
                        for o in contract.outcomes
                    ],
                    total_cost=total_price,
                    guaranteed_payout=1.0,
                    edge_pct=net_edge,
                    estimated_profit_usd=self.reference_position * (net_edge / 100),
                    min_liquidity=min_liq,
                    metadata={
                        "num_outcomes": len(contract.outcomes),
                        "total_price": round(total_price, 4),
                        "raw_edge_pct": round(raw_edge, 4),
                        "fee_pct": fee_pct,
                    },
                )
                self._next_id += 1
                opportunities.append(opp)

        self._opportunities.extend(opportunities)
        return sorted(opportunities, key=lambda x: x.edge_pct, reverse=True)

    def scan_cross_platform_arb(
        self,
        platform_a_contracts: Dict[str, PredictionContract],
        platform_b_contracts: Dict[str, PredictionContract],
        platform_a: str,
        platform_b: str,
    ) -> List[PredictionOpportunity]:
        """
        Scan for cross-platform arbitrage on the same events.

        If YES on platform A + NO on platform B < 1.0 (or vice versa),
        there's an arb across platforms.

        Args:
            platform_a_contracts: Dict of event_key -> contract from platform A
            platform_b_contracts: Dict of event_key -> contract from platform B
            platform_a: Name of platform A
            platform_b: Name of platform B

        Returns:
            List of cross-platform opportunities
        """
        opportunities = []
        fee_a = self.platform_fees.get(platform_a.lower(), 1.0)
        fee_b = self.platform_fees.get(platform_b.lower(), 1.0)
        combined_fee = fee_a + fee_b

        common_events = set(platform_a_contracts.keys()) & set(platform_b_contracts.keys())

        for event_key in common_events:
            contract_a = platform_a_contracts[event_key]
            contract_b = platform_b_contracts[event_key]
            self._scanned_contracts += 2

            if not (contract_a.is_binary and contract_b.is_binary):
                continue

            yes_a = contract_a.outcomes[0].price
            no_a = contract_a.outcomes[1].price
            yes_b = contract_b.outcomes[0].price
            no_b = contract_b.outcomes[1].price

            # Strategy 1: Buy YES on A, Buy NO on B
            cost_1 = yes_a + no_b
            if cost_1 > 0 and cost_1 < 1.0:
                raw_edge = (1.0 - cost_1) / cost_1 * 100
                net_edge = raw_edge - combined_fee

                if net_edge >= self.min_edge_pct:
                    min_liq = min(
                        contract_a.outcomes[0].liquidity,
                        contract_b.outcomes[1].liquidity,
                    )
                    if min_liq >= self.min_liquidity:
                        opp = PredictionOpportunity(
                            id=f"PRED-{self._next_id:04d}",
                            opportunity_type=OpportunityType.CROSS_PLATFORM,
                            platform=f"{platform_a}+{platform_b}",
                            market_title=contract_a.market_id,
                            contract_question=contract_a.question,
                            contract_id=f"{contract_a.contract_id}|{contract_b.contract_id}",
                            outcomes=[
                                {"name": "YES", "price": yes_a, "action": "BUY",
                                 "platform": platform_a},
                                {"name": "NO", "price": no_b, "action": "BUY",
                                 "platform": platform_b},
                            ],
                            total_cost=cost_1,
                            guaranteed_payout=1.0,
                            edge_pct=net_edge,
                            estimated_profit_usd=self.reference_position * (net_edge / 100),
                            min_liquidity=min_liq,
                            metadata={
                                "strategy": "yes_a_no_b",
                                "platform_a": platform_a,
                                "platform_b": platform_b,
                                "raw_edge_pct": round(raw_edge, 4),
                                "combined_fee_pct": combined_fee,
                            },
                        )
                        self._next_id += 1
                        opportunities.append(opp)

            # Strategy 2: Buy NO on A, Buy YES on B
            cost_2 = no_a + yes_b
            if cost_2 > 0 and cost_2 < 1.0:
                raw_edge = (1.0 - cost_2) / cost_2 * 100
                net_edge = raw_edge - combined_fee

                if net_edge >= self.min_edge_pct:
                    min_liq = min(
                        contract_a.outcomes[1].liquidity,
                        contract_b.outcomes[0].liquidity,
                    )
                    if min_liq >= self.min_liquidity:
                        opp = PredictionOpportunity(
                            id=f"PRED-{self._next_id:04d}",
                            opportunity_type=OpportunityType.CROSS_PLATFORM,
                            platform=f"{platform_a}+{platform_b}",
                            market_title=contract_a.market_id,
                            contract_question=contract_a.question,
                            contract_id=f"{contract_a.contract_id}|{contract_b.contract_id}",
                            outcomes=[
                                {"name": "NO", "price": no_a, "action": "BUY",
                                 "platform": platform_a},
                                {"name": "YES", "price": yes_b, "action": "BUY",
                                 "platform": platform_b},
                            ],
                            total_cost=cost_2,
                            guaranteed_payout=1.0,
                            edge_pct=net_edge,
                            estimated_profit_usd=self.reference_position * (net_edge / 100),
                            min_liquidity=min_liq,
                            metadata={
                                "strategy": "no_a_yes_b",
                                "platform_a": platform_a,
                                "platform_b": platform_b,
                                "raw_edge_pct": round(raw_edge, 4),
                                "combined_fee_pct": combined_fee,
                            },
                        )
                        self._next_id += 1
                        opportunities.append(opp)

        self._opportunities.extend(opportunities)
        return sorted(opportunities, key=lambda x: x.edge_pct, reverse=True)

    def get_all_opportunities(self) -> List[PredictionOpportunity]:
        """Get all detected opportunities."""
        return list(self._opportunities)

    def get_profitable_opportunities(self) -> List[PredictionOpportunity]:
        """Get only profitable opportunities."""
        return [o for o in self._opportunities if o.is_profitable]

    def get_summary(self) -> dict:
        """Get scanner summary."""
        profitable = self.get_profitable_opportunities()
        by_type = {}
        for o in profitable:
            t = o.opportunity_type.value
            by_type[t] = by_type.get(t, 0) + 1

        return {
            "total_opportunities": len(self._opportunities),
            "profitable_opportunities": len(profitable),
            "by_type": by_type,
            "contracts_scanned": self._scanned_contracts,
            "best_opportunity": profitable[0].to_dict() if profitable else None,
            "config": {
                "min_edge_pct": self.min_edge_pct,
                "min_liquidity": self.min_liquidity,
                "reference_position": self.reference_position,
                "platform_fees": self.platform_fees,
            },
        }

    def clear_opportunities(self):
        """Clear all tracked opportunities."""
        self._opportunities.clear()
        self._scanned_contracts = 0
