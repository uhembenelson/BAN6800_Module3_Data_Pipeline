"""Starter helpers for governed churn prediction."""

from __future__ import annotations


def score_to_risk_band(score: float) -> str:
    """Map a probability-like score to a reviewable adviser risk band."""
    if not 0.0 <= score <= 1.0:
        raise ValueError("score must be between 0 and 1")
    if score >= 0.75:
        return "high"
    if score >= 0.40:
        return "medium"
    return "low"


def build_churn_model(scale_pos_weight: float = 1.0):
    """Create the proposed XGBoost classifier without synthetic oversampling."""
    from xgboost import XGBClassifier

    return XGBClassifier(
        objective="binary:logistic",
        eval_metric="auc",
        scale_pos_weight=scale_pos_weight,
        random_state=42,
    )
