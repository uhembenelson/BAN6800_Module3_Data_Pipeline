import pytest

from src.churn_predictor import score_to_risk_band
from src.explainability import within_disparate_impact_range


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.10, "low"), (0.40, "medium"), (0.74, "medium"), (0.75, "high")],
)
def test_score_to_risk_band(score, expected):
    assert score_to_risk_band(score) == expected


def test_score_range_is_validated():
    with pytest.raises(ValueError):
        score_to_risk_band(1.1)


def test_disparate_impact_threshold():
    assert within_disparate_impact_range(1.0)
    assert not within_disparate_impact_range(0.70)
