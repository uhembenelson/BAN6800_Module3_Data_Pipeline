"""Unit tests for stages 5 and 7 - feature derivation."""

from __future__ import annotations

import pandas as pd
import pytest

from src.cleaning import clean
from src.config import Settings
from src.transforms import transform


@pytest.fixture()
def featured(messy_frame: pd.DataFrame, settings: Settings) -> tuple[pd.DataFrame, dict]:
    cleaned, _ = clean(settings, messy_frame)
    return transform(settings, cleaned)


def test_tenure_is_never_negative(featured: tuple[pd.DataFrame, dict]) -> None:
    frame, _ = featured
    assert (frame["tenure_days"] >= 0).all()


def test_tenure_uses_the_configured_snapshot(featured: tuple[pd.DataFrame, dict]) -> None:
    frame, _ = featured
    assert set(frame["snapshot_date"]) == {"2015-12-31"}
    assert (frame["date_joined"] <= pd.Timestamp("2015-12-31")).all()


def test_age_bands_are_all_populated_within_range(featured: tuple[pd.DataFrame, dict]) -> None:
    frame, _ = featured
    assert frame["age_band"].notna().all()
    assert frame["age"].between(16, 100).all()


def test_balance_bands_follow_the_configuration(featured: tuple[pd.DataFrame, dict]) -> None:
    frame, _ = featured
    allowed = {"Low", "Mid", "High", "Premium"}
    assert set(frame["balance_band"].dropna().unique()).issubset(allowed)


def test_high_value_flag_matches_the_threshold(featured: tuple[pd.DataFrame, dict]) -> None:
    frame, report = featured
    threshold = report["high_value_threshold"]
    assert (frame.loc[frame["high_value_flag"], "balance"] >= threshold).all()


def test_marketing_eligibility_excludes_minors(featured: tuple[pd.DataFrame, dict]) -> None:
    frame, _ = featured
    minors = frame.loc[frame["is_minor"]]
    assert (minors["marketing_eligible"] == False).all()  # noqa: E712 - explicit boolean check


def test_churn_label_is_a_nullable_boolean(featured: tuple[pd.DataFrame, dict]) -> None:
    frame, report = featured
    assert str(frame["churn_label"].dtype) == "boolean"
    assert frame["churn_label"].isna().all()
    assert "placeholder" in report["churn_label_status"]


def test_transformation_is_idempotent_in_value_terms(
    messy_frame: pd.DataFrame, settings: Settings
) -> None:
    cleaned, _ = clean(settings, messy_frame)
    first, _ = transform(settings, cleaned.copy())
    second, _ = transform(settings, cleaned.copy())
    pd.testing.assert_frame_equal(first, second)
