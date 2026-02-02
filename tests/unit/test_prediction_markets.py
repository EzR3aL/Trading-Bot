"""
Tests for prediction markets integration module.

Tests base classes, arbitrage scanner, and execution engine.
"""

import pytest
from datetime import datetime
from typing import Dict, List, Optional

from src.predictions.base import (
    PredictionMarket,
    PredictionContract,
    MarketOutcome,
    MarketStatus,
    PredictionPlatform,
)
from src.predictions.scanner import (
    PredictionArbScanner,
    PredictionOpportunity,
    OpportunityType,
)
from src.predictions.execution import (
    PredictionExecutor,
    PredictionOrder,
    OrderSide,
    FillResult,
)


# ==================== Helper factories ====================


def make_binary_contract(
    yes_price: float,
    no_price: float,
    yes_liquidity: float = 5000.0,
    no_liquidity: float = 5000.0,
    contract_id: str = "C001",
    question: str = "Will BTC hit $100k?",
) -> PredictionContract:
    """Create a binary prediction contract."""
    return PredictionContract(
        contract_id=contract_id,
        market_id="M001",
        question=question,
        outcomes=[
            MarketOutcome(name="YES", price=yes_price, volume_24h=1000.0,
                          liquidity=yes_liquidity),
            MarketOutcome(name="NO", price=no_price, volume_24h=800.0,
                          liquidity=no_liquidity),
        ],
    )


def make_multi_outcome_contract(
    prices: List[float],
    names: Optional[List[str]] = None,
    liquidity: float = 5000.0,
) -> PredictionContract:
    """Create a multi-outcome prediction contract."""
    if names is None:
        names = [f"Outcome_{i}" for i in range(len(prices))]
    return PredictionContract(
        contract_id="CM001",
        market_id="MM001",
        question="Who will win?",
        outcomes=[
            MarketOutcome(name=n, price=p, volume_24h=500.0, liquidity=liquidity)
            for n, p in zip(names, prices)
        ],
    )


# ==================== MarketOutcome Tests ====================


class TestMarketOutcome:
    """Tests for MarketOutcome dataclass."""

    def test_basic_creation(self):
        outcome = MarketOutcome(name="YES", price=0.65, volume_24h=1000.0)
        assert outcome.name == "YES"
        assert outcome.price == 0.65

    def test_implied_probability(self):
        outcome = MarketOutcome(name="YES", price=0.75)
        assert outcome.implied_probability == 0.75

    def test_implied_probability_clamped(self):
        outcome = MarketOutcome(name="YES", price=1.5)
        assert outcome.implied_probability == 1.0

        outcome_neg = MarketOutcome(name="NO", price=-0.1)
        assert outcome_neg.implied_probability == 0.0

    def test_to_dict(self):
        outcome = MarketOutcome(name="YES", price=0.65, volume_24h=1000.0, liquidity=5000.0)
        d = outcome.to_dict()
        assert d["name"] == "YES"
        assert d["price"] == 0.65
        assert d["implied_probability"] == 0.65
        assert d["volume_24h"] == 1000.0
        assert d["liquidity"] == 5000.0
        assert d["last_traded"] is None


# ==================== PredictionContract Tests ====================


class TestPredictionContract:
    """Tests for PredictionContract dataclass."""

    def test_binary_contract(self):
        c = make_binary_contract(0.60, 0.40)
        assert c.is_binary
        assert c.total_implied_probability == pytest.approx(1.0)

    def test_overround_efficient(self):
        c = make_binary_contract(0.60, 0.40)
        assert c.overround == pytest.approx(1.0)

    def test_overround_arb(self):
        c = make_binary_contract(0.45, 0.45)
        assert c.overround < 1.0

    def test_overround_vig(self):
        c = make_binary_contract(0.55, 0.55)
        assert c.overround > 1.0

    def test_total_volume(self):
        c = make_binary_contract(0.60, 0.40)
        assert c.total_volume == 1800.0  # 1000 + 800

    def test_total_liquidity(self):
        c = make_binary_contract(0.60, 0.40, yes_liquidity=3000, no_liquidity=2000)
        assert c.total_liquidity == 5000.0

    def test_multi_outcome(self):
        c = make_multi_outcome_contract([0.30, 0.30, 0.25, 0.15])
        assert not c.is_binary
        assert c.total_implied_probability == pytest.approx(1.0)
        assert len(c.outcomes) == 4

    def test_to_dict(self):
        c = make_binary_contract(0.60, 0.40)
        d = c.to_dict()
        assert d["contract_id"] == "C001"
        assert d["is_binary"] is True
        assert d["total_implied_probability"] == pytest.approx(1.0)
        assert d["status"] == "open"
        assert len(d["outcomes"]) == 2


# ==================== PredictionMarket Tests ====================


class TestPredictionMarket:
    """Tests for PredictionMarket dataclass."""

    def test_basic_creation(self):
        m = PredictionMarket(
            market_id="M001",
            platform="polymarket",
            title="BTC Price Markets",
            category="crypto",
        )
        assert m.market_id == "M001"
        assert m.platform == "polymarket"

    def test_total_volume(self):
        c1 = make_binary_contract(0.60, 0.40, contract_id="C1")
        c2 = make_binary_contract(0.70, 0.30, contract_id="C2")
        m = PredictionMarket(
            market_id="M001", platform="polymarket",
            title="Test", category="crypto",
            contracts=[c1, c2],
        )
        assert m.total_volume == 3600.0  # 1800 * 2

    def test_to_dict(self):
        c = make_binary_contract(0.60, 0.40)
        m = PredictionMarket(
            market_id="M001", platform="polymarket",
            title="Test", category="crypto",
            contracts=[c],
        )
        d = m.to_dict()
        assert d["market_id"] == "M001"
        assert d["platform"] == "polymarket"
        assert len(d["contracts"]) == 1


# ==================== MarketStatus Tests ====================


class TestMarketStatus:
    """Tests for MarketStatus enum."""

    def test_values(self):
        assert MarketStatus.OPEN == "open"
        assert MarketStatus.CLOSED == "closed"
        assert MarketStatus.RESOLVED == "resolved"
        assert MarketStatus.DISPUTED == "disputed"


# ==================== PredictionArbScanner Tests ====================


class TestPredictionArbScanner:
    """Tests for the PredictionArbScanner."""

    def test_default_init(self):
        scanner = PredictionArbScanner()
        assert scanner.min_edge_pct == 0.5
        assert scanner.min_liquidity == 100.0
        assert "polymarket" in scanner.platform_fees

    def test_custom_init(self):
        scanner = PredictionArbScanner(
            min_edge_pct=1.0,
            min_liquidity=500.0,
            reference_position=2000.0,
            platform_fees={"test": 0.5},
        )
        assert scanner.min_edge_pct == 1.0
        assert scanner.reference_position == 2000.0

    # ---- Binary arb ----

    def test_binary_arb_efficient_market(self):
        """YES + NO = 1.0 -> no arb."""
        scanner = PredictionArbScanner(min_edge_pct=0.1)
        contracts = [make_binary_contract(0.60, 0.40)]
        result = scanner.scan_binary_arb(contracts, platform="polymarket")
        assert len(result) == 0

    def test_binary_arb_underpriced(self):
        """YES + NO < 1.0 -> guaranteed arb."""
        scanner = PredictionArbScanner(
            min_edge_pct=0.1,
            min_liquidity=100.0,
            platform_fees={"polymarket": 0.0},
        )
        # YES=0.45, NO=0.45 -> total=0.90 -> 11.11% raw edge
        contracts = [make_binary_contract(0.45, 0.45)]
        result = scanner.scan_binary_arb(contracts, platform="polymarket")
        assert len(result) == 1
        opp = result[0]
        assert opp.opportunity_type == OpportunityType.BINARY_UNDERPRICED
        assert opp.total_cost == pytest.approx(0.90)
        assert opp.guaranteed_payout == 1.0
        assert opp.edge_pct > 10.0
        assert opp.is_profitable

    def test_binary_arb_overpriced_no_detect(self):
        """YES + NO > 1.0 -> scanner only detects underpricing."""
        scanner = PredictionArbScanner(min_edge_pct=0.1)
        contracts = [make_binary_contract(0.55, 0.55)]
        result = scanner.scan_binary_arb(contracts, platform="polymarket")
        assert len(result) == 0

    def test_binary_arb_fees_reduce_edge(self):
        """High fees can eliminate the arb."""
        scanner = PredictionArbScanner(
            min_edge_pct=5.0,
            min_liquidity=100.0,
            platform_fees={"expensive": 15.0},
        )
        # Raw edge ~11.11%, but 15% fee makes it negative
        contracts = [make_binary_contract(0.45, 0.45)]
        result = scanner.scan_binary_arb(contracts, platform="expensive")
        assert len(result) == 0

    def test_binary_arb_low_liquidity_filtered(self):
        """Low liquidity contracts are filtered out."""
        scanner = PredictionArbScanner(
            min_edge_pct=0.1,
            min_liquidity=10000.0,  # High minimum
            platform_fees={"polymarket": 0.0},
        )
        contracts = [make_binary_contract(0.45, 0.45, yes_liquidity=50.0, no_liquidity=50.0)]
        result = scanner.scan_binary_arb(contracts, platform="polymarket")
        assert len(result) == 0

    def test_binary_arb_skips_non_binary(self):
        """Non-binary contracts are skipped."""
        scanner = PredictionArbScanner(min_edge_pct=0.1)
        contracts = [make_multi_outcome_contract([0.20, 0.20, 0.20])]
        result = scanner.scan_binary_arb(contracts, platform="polymarket")
        assert len(result) == 0

    def test_binary_arb_zero_price_skipped(self):
        scanner = PredictionArbScanner(min_edge_pct=0.1)
        contracts = [make_binary_contract(0.0, 0.0)]
        result = scanner.scan_binary_arb(contracts, platform="polymarket")
        assert len(result) == 0

    def test_binary_arb_multiple_contracts(self):
        """Scanner handles multiple contracts in one scan."""
        scanner = PredictionArbScanner(
            min_edge_pct=0.1,
            min_liquidity=100.0,
            platform_fees={"polymarket": 0.0},
        )
        contracts = [
            make_binary_contract(0.45, 0.45, contract_id="C1"),
            make_binary_contract(0.60, 0.40, contract_id="C2"),  # No arb
            make_binary_contract(0.40, 0.40, contract_id="C3"),
        ]
        result = scanner.scan_binary_arb(contracts, platform="polymarket")
        assert len(result) == 2
        assert result[0].edge_pct >= result[1].edge_pct  # Sorted by edge

    # ---- Multi-outcome arb ----

    def test_multi_outcome_arb_efficient(self):
        """Sum = 1.0 -> no arb."""
        scanner = PredictionArbScanner(min_edge_pct=0.1)
        contracts = [make_multi_outcome_contract([0.40, 0.30, 0.20, 0.10])]
        result = scanner.scan_multi_outcome_arb(contracts, platform="polymarket")
        assert len(result) == 0

    def test_multi_outcome_arb_underpriced(self):
        """Sum < 1.0 -> arb."""
        scanner = PredictionArbScanner(
            min_edge_pct=0.1,
            min_liquidity=100.0,
            platform_fees={"polymarket": 0.0},
        )
        # Sum = 0.80 -> 25% raw edge
        contracts = [make_multi_outcome_contract([0.25, 0.25, 0.15, 0.15])]
        result = scanner.scan_multi_outcome_arb(contracts, platform="polymarket")
        assert len(result) == 1
        opp = result[0]
        assert opp.opportunity_type == OpportunityType.MULTI_OUTCOME_ARB
        assert opp.total_cost == pytest.approx(0.80)
        assert opp.edge_pct > 20.0

    def test_multi_outcome_single_outcome_skipped(self):
        """Single outcome contracts are skipped."""
        scanner = PredictionArbScanner(min_edge_pct=0.1)
        c = PredictionContract(
            contract_id="X", market_id="M", question="?",
            outcomes=[MarketOutcome(name="YES", price=0.5)],
        )
        result = scanner.scan_multi_outcome_arb([c], platform="polymarket")
        assert len(result) == 0

    # ---- Cross-platform arb ----

    def test_cross_platform_no_common_events(self):
        scanner = PredictionArbScanner(min_edge_pct=0.1)
        a = {"event_a": make_binary_contract(0.60, 0.40)}
        b = {"event_b": make_binary_contract(0.65, 0.35)}
        result = scanner.scan_cross_platform_arb(a, b, "poly", "azuro")
        assert len(result) == 0

    def test_cross_platform_arb_found(self):
        """Same event, different prices across platforms creates arb."""
        scanner = PredictionArbScanner(
            min_edge_pct=0.1,
            min_liquidity=100.0,
            platform_fees={"poly": 0.0, "azuro": 0.0},
        )
        # poly: YES=0.40, NO=0.60 | azuro: YES=0.70, NO=0.30
        # Strategy: buy YES on poly (0.40) + buy NO on azuro (0.30) = 0.70 < 1.0
        a = {"btc_100k": make_binary_contract(0.40, 0.60)}
        b = {"btc_100k": make_binary_contract(0.70, 0.30)}
        result = scanner.scan_cross_platform_arb(a, b, "poly", "azuro")
        assert len(result) >= 1
        opp = result[0]
        assert opp.opportunity_type == OpportunityType.CROSS_PLATFORM
        assert opp.is_profitable

    def test_cross_platform_checks_both_strategies(self):
        """Scanner checks YES_A+NO_B and NO_A+YES_B."""
        scanner = PredictionArbScanner(
            min_edge_pct=0.1,
            min_liquidity=100.0,
            platform_fees={"a": 0.0, "b": 0.0},
        )
        # Both directions have arb: 0.30+0.30=0.60 < 1.0
        contracts_a = {"evt": make_binary_contract(0.30, 0.30)}
        contracts_b = {"evt": make_binary_contract(0.30, 0.30)}
        result = scanner.scan_cross_platform_arb(contracts_a, contracts_b, "a", "b")
        assert len(result) == 2

    def test_cross_platform_no_arb(self):
        """Prices sum to >= 1.0 across platforms."""
        scanner = PredictionArbScanner(min_edge_pct=0.1)
        a = {"evt": make_binary_contract(0.60, 0.40)}
        b = {"evt": make_binary_contract(0.60, 0.40)}
        result = scanner.scan_cross_platform_arb(a, b, "poly", "azuro")
        assert len(result) == 0

    def test_cross_platform_skips_non_binary(self):
        scanner = PredictionArbScanner(min_edge_pct=0.1)
        a = {"evt": make_multi_outcome_contract([0.20, 0.20, 0.20])}
        b = {"evt": make_binary_contract(0.30, 0.30)}
        result = scanner.scan_cross_platform_arb(a, b, "a", "b")
        assert len(result) == 0

    # ---- State management ----

    def test_get_all_opportunities_empty(self):
        scanner = PredictionArbScanner()
        assert scanner.get_all_opportunities() == []

    def test_clear_opportunities(self):
        scanner = PredictionArbScanner(
            min_edge_pct=0.1, platform_fees={"polymarket": 0.0}, min_liquidity=100.0,
        )
        contracts = [make_binary_contract(0.45, 0.45)]
        scanner.scan_binary_arb(contracts, platform="polymarket")
        assert len(scanner.get_all_opportunities()) > 0
        scanner.clear_opportunities()
        assert len(scanner.get_all_opportunities()) == 0
        assert scanner._scanned_contracts == 0

    def test_get_summary_empty(self):
        scanner = PredictionArbScanner()
        s = scanner.get_summary()
        assert s["total_opportunities"] == 0
        assert s["best_opportunity"] is None
        assert "config" in s

    def test_get_summary_with_data(self):
        scanner = PredictionArbScanner(
            min_edge_pct=0.1, platform_fees={"polymarket": 0.0}, min_liquidity=100.0,
        )
        contracts = [make_binary_contract(0.45, 0.45)]
        scanner.scan_binary_arb(contracts, platform="polymarket")
        s = scanner.get_summary()
        assert s["total_opportunities"] >= 1
        assert s["profitable_opportunities"] >= 1
        assert s["best_opportunity"] is not None
        assert s["contracts_scanned"] >= 1

    def test_accumulates_across_scans(self):
        scanner = PredictionArbScanner(
            min_edge_pct=0.1, platform_fees={"polymarket": 0.0}, min_liquidity=100.0,
        )
        c1 = [make_binary_contract(0.45, 0.45, contract_id="A")]
        c2 = [make_binary_contract(0.40, 0.40, contract_id="B")]
        r1 = scanner.scan_binary_arb(c1, platform="polymarket")
        r2 = scanner.scan_binary_arb(c2, platform="polymarket")
        assert len(scanner.get_all_opportunities()) == len(r1) + len(r2)

    def test_incremental_ids(self):
        scanner = PredictionArbScanner(
            min_edge_pct=0.1, platform_fees={"polymarket": 0.0}, min_liquidity=100.0,
        )
        contracts = [
            make_binary_contract(0.45, 0.45, contract_id="A"),
            make_binary_contract(0.40, 0.40, contract_id="B"),
        ]
        scanner.scan_binary_arb(contracts, platform="polymarket")
        ids = [o.id for o in scanner.get_all_opportunities()]
        assert all(id_.startswith("PRED-") for id_ in ids)
        assert len(set(ids)) == len(ids)  # All unique


# ==================== PredictionOpportunity Tests ====================


class TestPredictionOpportunity:
    """Tests for PredictionOpportunity dataclass."""

    def test_is_profitable(self):
        opp = PredictionOpportunity(
            id="PRED-0001", opportunity_type=OpportunityType.BINARY_UNDERPRICED,
            platform="polymarket", market_title="M1", contract_question="?",
            contract_id="C1", outcomes=[], total_cost=0.90,
            guaranteed_payout=1.0, edge_pct=11.11,
            estimated_profit_usd=111.1, min_liquidity=5000.0,
        )
        assert opp.is_profitable

    def test_not_profitable(self):
        opp = PredictionOpportunity(
            id="PRED-0001", opportunity_type=OpportunityType.BINARY_UNDERPRICED,
            platform="polymarket", market_title="M1", contract_question="?",
            contract_id="C1", outcomes=[], total_cost=1.05,
            guaranteed_payout=1.0, edge_pct=-4.76,
            estimated_profit_usd=-47.6, min_liquidity=5000.0,
        )
        assert not opp.is_profitable

    def test_risk_adjusted_edge_high_liquidity(self):
        opp = PredictionOpportunity(
            id="PRED-0001", opportunity_type=OpportunityType.BINARY_UNDERPRICED,
            platform="polymarket", market_title="M1", contract_question="?",
            contract_id="C1", outcomes=[], total_cost=0.90,
            guaranteed_payout=1.0, edge_pct=10.0,
            estimated_profit_usd=100.0, min_liquidity=5000.0,
        )
        assert opp.risk_adjusted_edge == pytest.approx(10.0)  # liquidity > 1000

    def test_risk_adjusted_edge_low_liquidity(self):
        opp = PredictionOpportunity(
            id="PRED-0001", opportunity_type=OpportunityType.BINARY_UNDERPRICED,
            platform="polymarket", market_title="M1", contract_question="?",
            contract_id="C1", outcomes=[], total_cost=0.90,
            guaranteed_payout=1.0, edge_pct=10.0,
            estimated_profit_usd=100.0, min_liquidity=500.0,
        )
        assert opp.risk_adjusted_edge == pytest.approx(5.0)  # 500/1000 * 10

    def test_risk_adjusted_edge_zero_liquidity(self):
        opp = PredictionOpportunity(
            id="PRED-0001", opportunity_type=OpportunityType.BINARY_UNDERPRICED,
            platform="polymarket", market_title="M1", contract_question="?",
            contract_id="C1", outcomes=[], total_cost=0.90,
            guaranteed_payout=1.0, edge_pct=10.0,
            estimated_profit_usd=100.0, min_liquidity=0.0,
        )
        assert opp.risk_adjusted_edge == 0.0

    def test_to_dict(self):
        opp = PredictionOpportunity(
            id="PRED-0001", opportunity_type=OpportunityType.BINARY_UNDERPRICED,
            platform="polymarket", market_title="M1", contract_question="?",
            contract_id="C1", outcomes=[{"name": "YES", "price": 0.45, "action": "BUY"}],
            total_cost=0.90, guaranteed_payout=1.0, edge_pct=11.11,
            estimated_profit_usd=111.1, min_liquidity=5000.0,
        )
        d = opp.to_dict()
        assert d["id"] == "PRED-0001"
        assert d["opportunity_type"] == "binary_underpriced"
        assert d["is_profitable"] is True
        assert "risk_adjusted_edge" in d


# ==================== OpportunityType Tests ====================


class TestOpportunityType:
    """Tests for OpportunityType enum."""

    def test_values(self):
        assert OpportunityType.BINARY_UNDERPRICED == "binary_underpriced"
        assert OpportunityType.BINARY_OVERPRICED == "binary_overpriced"
        assert OpportunityType.MULTI_OUTCOME_ARB == "multi_outcome_arb"
        assert OpportunityType.CROSS_PLATFORM == "cross_platform"
        assert OpportunityType.CORRELATED_MISPRICING == "correlated_mispricing"


# ==================== PredictionOrder Tests ====================


class TestPredictionOrder:
    """Tests for PredictionOrder dataclass."""

    def test_notional_value(self):
        order = PredictionOrder(
            order_id="PORD-0001", contract_id="C1",
            outcome="YES", side=OrderSide.BUY,
            price=0.45, size=100.0,
        )
        assert order.notional_value == pytest.approx(45.0)

    def test_max_fill_price_buy(self):
        order = PredictionOrder(
            order_id="PORD-0001", contract_id="C1",
            outcome="YES", side=OrderSide.BUY,
            price=0.50, size=100.0, max_slippage_pct=2.0,
        )
        assert order.max_fill_price == pytest.approx(0.51)  # 0.50 * 1.02

    def test_max_fill_price_sell(self):
        order = PredictionOrder(
            order_id="PORD-0001", contract_id="C1",
            outcome="YES", side=OrderSide.SELL,
            price=0.50, size=100.0,
        )
        assert order.max_fill_price == 0.50  # No increase for sells

    def test_min_fill_price_sell(self):
        order = PredictionOrder(
            order_id="PORD-0001", contract_id="C1",
            outcome="YES", side=OrderSide.SELL,
            price=0.50, size=100.0, max_slippage_pct=2.0,
        )
        assert order.min_fill_price == pytest.approx(0.49)  # 0.50 * 0.98

    def test_min_fill_price_buy(self):
        order = PredictionOrder(
            order_id="PORD-0001", contract_id="C1",
            outcome="YES", side=OrderSide.BUY,
            price=0.50, size=100.0,
        )
        assert order.min_fill_price == 0.0  # No floor for buys

    def test_to_dict(self):
        order = PredictionOrder(
            order_id="PORD-0001", contract_id="C1",
            outcome="YES", side=OrderSide.BUY,
            price=0.50, size=100.0,
        )
        d = order.to_dict()
        assert d["order_id"] == "PORD-0001"
        assert d["side"] == "buy"
        assert d["notional_value"] == 50.0


# ==================== FillResult Tests ====================


class TestFillResult:
    """Tests for FillResult dataclass."""

    def test_total_cost(self):
        fill = FillResult(
            order_id="PORD-0001", filled=True,
            fill_price=0.46, fill_size=100.0,
            slippage_pct=0.5, fees_paid=0.5,
        )
        assert fill.total_cost == pytest.approx(46.5)  # 0.46*100 + 0.5

    def test_failed_fill(self):
        fill = FillResult(
            order_id="PORD-0001", filled=False,
            error="Slippage exceeded",
        )
        assert not fill.filled
        assert fill.total_cost == 0.0

    def test_to_dict(self):
        fill = FillResult(
            order_id="PORD-0001", filled=True,
            fill_price=0.46, fill_size=100.0,
        )
        d = fill.to_dict()
        assert d["filled"] is True
        assert "timestamp" in d


# ==================== PredictionExecutor Tests ====================


class TestPredictionExecutor:
    """Tests for PredictionExecutor."""

    def test_default_init(self):
        executor = PredictionExecutor()
        assert executor.max_slippage_pct == 2.0
        assert executor.max_position_usd == 500.0

    def test_custom_init(self):
        executor = PredictionExecutor(
            max_slippage_pct=1.0,
            max_position_usd=1000.0,
            min_edge_after_slippage=0.5,
        )
        assert executor.max_slippage_pct == 1.0
        assert executor.max_position_usd == 1000.0

    def test_create_arb_orders(self):
        executor = PredictionExecutor(max_position_usd=500.0)
        outcomes = [
            {"name": "YES", "price": 0.45, "action": "BUY"},
            {"name": "NO", "price": 0.45, "action": "BUY"},
        ]
        orders = executor.create_arb_orders("C1", outcomes, 500.0)
        assert len(orders) == 2
        assert orders[0].side == OrderSide.BUY
        assert orders[1].side == OrderSide.BUY
        assert orders[0].outcome == "YES"
        assert orders[1].outcome == "NO"

    def test_create_arb_orders_caps_size(self):
        executor = PredictionExecutor(max_position_usd=200.0)
        outcomes = [
            {"name": "YES", "price": 0.45, "action": "BUY"},
        ]
        orders = executor.create_arb_orders("C1", outcomes, 1000.0)
        assert orders[0].size == 200.0

    def test_create_arb_orders_incremental_ids(self):
        executor = PredictionExecutor()
        outcomes = [{"name": "YES", "price": 0.5, "action": "BUY"}]
        o1 = executor.create_arb_orders("C1", outcomes, 100.0)
        o2 = executor.create_arb_orders("C2", outcomes, 100.0)
        assert o1[0].order_id != o2[0].order_id

    def test_validate_execution_valid(self):
        executor = PredictionExecutor(max_position_usd=500.0, min_edge_after_slippage=0.1)
        orders = [
            PredictionOrder("P1", "C1", "YES", OrderSide.BUY, 0.45, 200.0),
            PredictionOrder("P2", "C1", "NO", OrderSide.BUY, 0.45, 200.0),
        ]
        result = executor.validate_execution(orders, edge_pct=10.0)
        assert result["valid"] is True
        assert len(result["issues"]) == 0

    def test_validate_execution_position_too_large(self):
        executor = PredictionExecutor(max_position_usd=100.0)
        orders = [
            PredictionOrder("P1", "C1", "YES", OrderSide.BUY, 0.45, 500.0),
            PredictionOrder("P2", "C1", "NO", OrderSide.BUY, 0.45, 500.0),
        ]
        result = executor.validate_execution(orders, edge_pct=10.0)
        assert result["valid"] is False
        assert any("exceeds max" in i for i in result["issues"])

    def test_validate_execution_edge_too_low_after_slippage(self):
        executor = PredictionExecutor(
            max_slippage_pct=3.0,
            max_position_usd=10000.0,
            min_edge_after_slippage=1.0,
        )
        orders = [
            PredictionOrder("P1", "C1", "YES", OrderSide.BUY, 0.45, 100.0),
            PredictionOrder("P2", "C1", "NO", OrderSide.BUY, 0.45, 100.0),
        ]
        # Edge 5% - worst case slippage 3%*2=6% = -1% < 1.0% min
        result = executor.validate_execution(orders, edge_pct=5.0)
        assert result["valid"] is False
        assert any("below minimum" in i for i in result["issues"])

    def test_validate_execution_invalid_price(self):
        executor = PredictionExecutor(max_position_usd=10000.0)
        orders = [
            PredictionOrder("P1", "C1", "YES", OrderSide.BUY, 1.5, 100.0),  # Invalid
        ]
        result = executor.validate_execution(orders, edge_pct=10.0)
        assert result["valid"] is False
        assert any("Invalid price" in i for i in result["issues"])

    def test_simulate_fill_success(self):
        executor = PredictionExecutor()
        order = PredictionOrder("P1", "C1", "YES", OrderSide.BUY, 0.50, 100.0, max_slippage_pct=2.0)
        fill = executor.simulate_fill(order, actual_price=0.50)
        assert fill.filled is True
        assert fill.fill_price == 0.50
        assert fill.fill_size == 100.0
        assert fill.slippage_pct == 0.0

    def test_simulate_fill_with_slippage(self):
        executor = PredictionExecutor()
        order = PredictionOrder("P1", "C1", "YES", OrderSide.BUY, 0.50, 100.0, max_slippage_pct=5.0)
        fill = executor.simulate_fill(order, actual_price=0.51)
        assert fill.filled is True
        assert fill.slippage_pct == pytest.approx(2.0)  # (0.51-0.50)/0.50 * 100

    def test_simulate_fill_slippage_exceeded(self):
        executor = PredictionExecutor()
        order = PredictionOrder("P1", "C1", "YES", OrderSide.BUY, 0.50, 100.0, max_slippage_pct=1.0)
        fill = executor.simulate_fill(order, actual_price=0.55)
        assert fill.filled is False
        assert "exceeds max" in fill.error

    def test_simulate_fill_partial(self):
        executor = PredictionExecutor()
        order = PredictionOrder("P1", "C1", "YES", OrderSide.BUY, 0.50, 100.0)
        fill = executor.simulate_fill(order, partial_fill_ratio=0.5)
        assert fill.filled is True
        assert fill.fill_size == 50.0

    def test_simulate_fill_sell_slippage(self):
        executor = PredictionExecutor()
        order = PredictionOrder("P1", "C1", "YES", OrderSide.SELL, 0.50, 100.0, max_slippage_pct=5.0)
        fill = executor.simulate_fill(order, actual_price=0.48)
        assert fill.filled is True
        assert fill.slippage_pct == pytest.approx(4.0)  # (0.50-0.48)/0.50 * 100

    def test_simulate_fill_default_price(self):
        executor = PredictionExecutor()
        order = PredictionOrder("P1", "C1", "YES", OrderSide.BUY, 0.50, 100.0)
        fill = executor.simulate_fill(order)
        assert fill.filled is True
        assert fill.fill_price == 0.50

    def test_get_execution_stats_empty(self):
        executor = PredictionExecutor()
        stats = executor.get_execution_stats()
        assert stats["total_orders"] == 0
        assert stats["total_fills"] == 0
        assert stats["fill_rate"] == 0.0

    def test_get_execution_stats_with_fills(self):
        executor = PredictionExecutor()
        order = PredictionOrder("P1", "C1", "YES", OrderSide.BUY, 0.50, 100.0)
        executor._order_history.append(order)
        executor.simulate_fill(order, actual_price=0.50)
        stats = executor.get_execution_stats()
        assert stats["total_orders"] == 1
        assert stats["successful_fills"] == 1
        assert stats["fill_rate"] == 1.0

    def test_get_summary(self):
        executor = PredictionExecutor()
        summary = executor.get_summary()
        assert "config" in summary
        assert "stats" in summary
        assert summary["config"]["max_slippage_pct"] == 2.0
