"""Preprocessing helpers for segmentation and future churn modelling."""

from __future__ import annotations

import pandas as pd


DIRECT_IDENTIFIERS = ("name", "surname")


def remove_direct_identifiers(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove direct identifiers before analytics processing."""
    return frame.drop(columns=[c for c in DIRECT_IDENTIFIERS if c in frame], errors="ignore")


def require_churn_label(frame: pd.DataFrame) -> None:
    """Prevent supervised modelling before a governed churn label exists."""
    if "churn_label" not in frame.columns:
        raise ValueError("churn_label is required for churn-model training")
