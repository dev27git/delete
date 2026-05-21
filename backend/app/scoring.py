from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True)
class WeightedGapInput:
    importance_weight: float
    concentric_coverage: int
    concentric_quality: int
    competitor_coverage: int
    competitor_quality: int
    confidence: float


def calculate_weighted_gap(item: WeightedGapInput) -> float:
    concentric_score = (item.concentric_coverage + item.concentric_quality) / 10.0
    competitor_score = (item.competitor_coverage + item.competitor_quality) / 10.0
    raw_gap = max(0.0, competitor_score - concentric_score)
    return item.importance_weight * raw_gap * item.confidence


def normalize_gap_ratio(weighted_gaps: Iterable[float], max_possible: Iterable[float]) -> float:
    total_gap = sum(weighted_gaps)
    max_gap = sum(max_possible)
    if max_gap <= 0:
        return 0.0
    return min(1.0, total_gap / max_gap)
