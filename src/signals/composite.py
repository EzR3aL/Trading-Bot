"""
Composite Signal Scoring System.

Combines multiple normalized signals with configurable weights
to produce a single composite score for trade decisions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.signals.normalizers import SignalNormalizer
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default signal weights
DEFAULT_WEIGHTS = {
    "fear_greed": 0.20,
    "funding_rate": 0.15,
    "long_short_ratio": 0.20,
    "open_interest_change": 0.10,
    "price_momentum": 0.10,
    "rsi": 0.10,
    "volume_profile": 0.08,
    "liquidation_imbalance": 0.07,
}


@dataclass
class SignalResult:
    """Individual signal contribution to the composite."""
    name: str
    raw_value: float
    normalized: float
    weight: float
    weighted_value: float
    strength: str
    description: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "raw_value": self.raw_value,
            "normalized": round(self.normalized, 4),
            "weight": round(self.weight, 4),
            "weighted_value": round(self.weighted_value, 4),
            "strength": self.strength,
            "description": self.description,
        }


@dataclass
class CompositeResult:
    """Result of composite signal calculation."""
    score: float  # -1.0 to +1.0
    direction: str  # "long" or "short"
    confidence: int  # 0-100
    signal_count: int
    active_signals: int  # Non-neutral signals
    signals: List[SignalResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    agreement_ratio: float = 0.0  # How many signals agree with direction

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "direction": self.direction,
            "confidence": self.confidence,
            "signal_count": self.signal_count,
            "active_signals": self.active_signals,
            "agreement_ratio": round(self.agreement_ratio, 4),
            "signals": [s.to_dict() for s in self.signals],
            "timestamp": self.timestamp.isoformat(),
        }


class SignalComposite:
    """
    Composite signal scoring system.

    Combines multiple normalized market signals with configurable weights
    to produce a single directional score and confidence level.

    Score ranges from -1.0 (strong short) to +1.0 (strong long).
    Confidence is derived from score magnitude and signal agreement.
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        min_confidence: int = 50,
        max_confidence: int = 95,
    ):
        """
        Initialize the composite signal calculator.

        Args:
            weights: Signal weights (must sum to 1.0, or will be normalized)
            min_confidence: Minimum confidence output
            max_confidence: Maximum confidence output
        """
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self.min_confidence = min_confidence
        self.max_confidence = max_confidence

        # Normalize weights to sum to 1.0
        total = sum(self.weights.values())
        if total > 0 and abs(total - 1.0) > 0.01:
            self.weights = {k: v / total for k, v in self.weights.items()}

    def calculate(
        self,
        signals: Dict[str, SignalNormalizer],
    ) -> CompositeResult:
        """
        Calculate composite score from individual signals.

        Args:
            signals: Dict of signal_name -> SignalNormalizer

        Returns:
            CompositeResult with score, direction, confidence, and details
        """
        results = []
        weighted_sum = 0.0
        total_weight = 0.0

        for name, signal in signals.items():
            weight = self.weights.get(name, 0.0)
            if weight <= 0:
                continue

            weighted_value = signal.normalized * weight
            weighted_sum += weighted_value
            total_weight += weight

            results.append(SignalResult(
                name=name,
                raw_value=signal.raw_value,
                normalized=signal.normalized,
                weight=weight,
                weighted_value=weighted_value,
                strength=signal.strength,
                description=signal.description,
            ))

        # Normalize by total weight of active signals
        if total_weight > 0:
            score = weighted_sum / total_weight
        else:
            score = 0.0

        score = max(-1.0, min(1.0, score))

        # Determine direction
        direction = "long" if score >= 0 else "short"

        # Count active (non-neutral) signals
        active_signals = sum(1 for r in results if r.strength != "neutral")

        # Calculate agreement ratio
        agreement_ratio = self._calculate_agreement(results, direction)

        # Calculate confidence
        confidence = self._calculate_confidence(
            score, active_signals, len(results), agreement_ratio
        )

        return CompositeResult(
            score=score,
            direction=direction,
            confidence=confidence,
            signal_count=len(results),
            active_signals=active_signals,
            signals=results,
            agreement_ratio=agreement_ratio,
        )

    def get_weights(self) -> Dict[str, float]:
        """Get current signal weights."""
        return dict(self.weights)

    def set_weight(self, signal_name: str, weight: float):
        """
        Set weight for a specific signal.

        Args:
            signal_name: Signal name
            weight: New weight value (will be re-normalized with others)
        """
        self.weights[signal_name] = max(0.0, weight)
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    def get_signal_breakdown(self, result: CompositeResult) -> List[dict]:
        """
        Get a sorted breakdown of signal contributions.

        Args:
            result: CompositeResult to analyze

        Returns:
            List of signal dicts sorted by absolute weighted contribution
        """
        breakdown = []
        for sig in result.signals:
            breakdown.append({
                "name": sig.name,
                "contribution": round(abs(sig.weighted_value), 4),
                "direction": "long" if sig.normalized > 0 else "short" if sig.normalized < 0 else "neutral",
                "agrees_with_composite": (
                    (sig.normalized > 0 and result.score > 0) or
                    (sig.normalized < 0 and result.score < 0)
                ),
                "weight_pct": f"{sig.weight * 100:.1f}%",
                "strength": sig.strength,
            })

        breakdown.sort(key=lambda x: x["contribution"], reverse=True)
        return breakdown

    def _calculate_agreement(self, results: List[SignalResult], direction: str) -> float:
        """Calculate what fraction of signals agree with the composite direction."""
        if not results:
            return 0.0

        agreeing = 0
        active = 0
        for r in results:
            if r.strength == "neutral":
                continue
            active += 1
            if direction == "long" and r.normalized > 0:
                agreeing += 1
            elif direction == "short" and r.normalized < 0:
                agreeing += 1

        if active == 0:
            return 0.0

        return agreeing / active

    def _calculate_confidence(
        self,
        score: float,
        active_signals: int,
        total_signals: int,
        agreement_ratio: float,
    ) -> int:
        """
        Calculate confidence level from score magnitude and signal agreement.

        Base confidence from score magnitude, boosted by agreement.
        """
        abs_score = abs(score)

        # Base confidence from score magnitude (maps 0->50, 1->95)
        base = self.min_confidence + abs_score * (self.max_confidence - self.min_confidence)

        # Agreement boost: if >80% of signals agree, boost confidence
        if agreement_ratio >= 0.8 and active_signals >= 3:
            base = min(base * 1.1, self.max_confidence)
        # Disagreement penalty: if <50% agree, reduce confidence
        elif agreement_ratio < 0.5 and active_signals >= 3:
            base *= 0.85

        # Signal count factor: more signals = more reliable
        if total_signals >= 5:
            base = min(base * 1.05, self.max_confidence)
        elif total_signals <= 2:
            base *= 0.9

        return max(self.min_confidence, min(self.max_confidence, int(base)))
