"""Explainability and fairness thresholds from the delivery plan."""

from __future__ import annotations


FAIRNESS_THRESHOLDS = {
    "disparate_impact_ratio_min": 0.80,
    "disparate_impact_ratio_max": 1.25,
    "equal_opportunity_gap_max": 0.05,
    "calibration_gap_max": 0.05,
}


def within_disparate_impact_range(ratio: float) -> bool:
    """Check the agreed demographic-parity ratio range."""
    return 0.80 <= ratio <= 1.25
