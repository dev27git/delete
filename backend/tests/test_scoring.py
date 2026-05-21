from app.scoring import WeightedGapInput, calculate_weighted_gap, normalize_gap_ratio


def test_weighted_gap_positive_when_competitor_ahead() -> None:
    gap = calculate_weighted_gap(
        WeightedGapInput(
            importance_weight=1.5,
            concentric_coverage=2,
            concentric_quality=2,
            competitor_coverage=4,
            competitor_quality=4,
            confidence=0.8,
        )
    )
    assert round(gap, 4) == 0.48


def test_weighted_gap_zero_when_concentric_ahead() -> None:
    gap = calculate_weighted_gap(
        WeightedGapInput(
            importance_weight=2.0,
            concentric_coverage=5,
            concentric_quality=5,
            competitor_coverage=3,
            competitor_quality=3,
            confidence=0.7,
        )
    )
    assert gap == 0


def test_normalize_gap_ratio_bounds() -> None:
    ratio = normalize_gap_ratio(weighted_gaps=[0.5, 0.2], max_possible=[1.0, 1.0])
    assert ratio == 0.35
