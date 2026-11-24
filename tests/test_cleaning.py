"""Unit tests for stage 6 - the deterministic cleaning rules."""

from __future__ import annotations

import pandas as pd
import pytest

from src.cleaning import clean
from src.config import Settings


def test_duplicates_are_removed(messy_frame: pd.DataFrame, settings: Settings) -> None:
    out, report = clean(settings, messy_frame)
    assert report["duplicates_found"] >= 1
    assert out["customer_key"].is_unique


def test_rows_with_unparseable_dates_are_dropped(messy_frame: pd.DataFrame, settings: Settings) -> None:
    out, report = clean(settings, messy_frame)
    assert out["date_joined"].notna().all()
    assert report["rows_dropped"] >= 1


def test_impossible_ages_are_brought_inside_the_band(
    messy_frame: pd.DataFrame, settings: Settings
) -> None:
    out, _ = clean(settings, messy_frame)
    assert out["age"].between(16, 100).all()
    assert not out["age"].isin([200, -5]).any()


def test_negative_balances_are_repaired(messy_frame: pd.DataFrame, settings: Settings) -> None:
    out, _ = clean(settings, messy_frame)
    assert (out["balance"] > 0).all()
    assert out["balance"].notna().all()


def test_minors_are_flagged_not_deleted(messy_frame: pd.DataFrame, settings: Settings) -> None:
    out, report = clean(settings, messy_frame)
    assert out["is_minor"].sum() >= 1
    assert report["minor_customers_flagged"] == int(out["is_minor"].sum())


def test_missing_job_classification_becomes_unknown(
    messy_frame: pd.DataFrame, settings: Settings
) -> None:
    out, _ = clean(settings, messy_frame)
    assert "Unknown" in set(out["job_classification"].unique())
    assert out["job_classification"].notna().all()


def test_imputation_is_flagged(messy_frame: pd.DataFrame, settings: Settings) -> None:
    out, _ = clean(settings, messy_frame)
    assert out["age_imputed"].any()
    assert out["balance_imputed"].any()


def test_cleaning_is_deterministic(messy_frame: pd.DataFrame, settings: Settings) -> None:
    first, _ = clean(settings, messy_frame)
    second, _ = clean(settings, messy_frame)
    pd.testing.assert_frame_equal(first, second)


def test_report_totals_are_internally_consistent(messy_frame: pd.DataFrame, settings: Settings) -> None:
    out, report = clean(settings, messy_frame)
    assert report["rows_out"] == len(out)
    assert report["rows_in"] - report["rows_out"] == report["rows_dropped"]
