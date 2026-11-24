"""Tests for stage 9 - the Great Expectations gate must actually catch defects.

A validation suite that only ever sees clean data is decoration. These tests
feed the gold suite deliberately broken frames and assert that it fails.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.config import Settings
from src.validation_gx import assert_gate, run_suite


def _clean_frame(rows: int = 5200) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    regions = ["England", "Scotland", "Wales", "Northern Ireland"]
    return pd.DataFrame(
        {
            "customer_key": [f"{index:064x}" for index in range(rows)],
            "gender": rng.choice(["Male", "Female"], rows),
            "age": rng.integers(16, 90, rows),
            "age_band": rng.choice(["16-24", "25-34", "35-44", "45-54", "55-64", "65+"], rows),
            "region": rng.choice(regions, rows, p=[0.54, 0.28, 0.13, 0.05]),
            "region_code": rng.choice(["E92000001", "S92000003", "W92000004", "N92000002"], rows),
            "job_classification": rng.choice(["White Collar", "Blue Collar", "Other"], rows),
            "date_joined": pd.Timestamp("2015-06-01"),
            "tenure_days": rng.integers(0, 360, rows),
            "tenure_months": rng.integers(0, 12, rows),
            "balance": rng.uniform(100, 200000, rows).round(2),
            "balance_band": rng.choice(["Low", "Mid", "High", "Premium"], rows),
            "is_minor": False,
            "marketing_eligible": True,
            "high_value_flag": rng.choice([True, False], rows),
            "churn_label": pd.Series([pd.NA] * rows, dtype="boolean"),
            "snapshot_date": "2015-12-31",
        }
    )


def test_gold_suite_passes_on_a_clean_frame(settings: Settings) -> None:
    report = run_suite(settings, _clean_frame(), gate="gold")
    assert report["success"] is True
    assert report["critical_failures"] == []
    assert report["expectations_failed"] == 0


def test_suite_flags_a_negative_balance(settings: Settings) -> None:
    frame = _clean_frame()
    frame.loc[3, "balance"] = -1250.0
    report = run_suite(settings, frame, gate="gold")
    assert report["success"] is False
    failed = {item["expectation"].lower() for item in report["critical_failures"]}
    assert "expect_column_values_to_be_between" in failed


def test_suite_flags_a_duplicate_customer_key(settings: Settings) -> None:
    frame = _clean_frame()
    frame.loc[1, "customer_key"] = frame.loc[0, "customer_key"]
    report = run_suite(settings, frame, gate="gold")
    assert report["success"] is False
    assert any(
        item["expectation"].lower() == "expect_column_values_to_be_unique"
        for item in report["critical_failures"]
    )


def test_suite_flags_a_missing_age(settings: Settings) -> None:
    frame = _clean_frame()
    frame.loc[5, "age"] = np.nan
    report = run_suite(settings, frame, gate="gold")
    assert report["success"] is False
    assert any(item["column"] == "age" for item in report["critical_failures"])


def test_suite_flags_an_out_of_range_age(settings: Settings) -> None:
    frame = _clean_frame()
    frame.loc[6, "age"] = 200
    report = run_suite(settings, frame, gate="gold")
    assert report["success"] is False


def test_suite_flags_an_unknown_region(settings: Settings) -> None:
    frame = _clean_frame()
    frame.loc[7, "region"] = "Cork"
    report = run_suite(settings, frame, gate="gold")
    assert report["success"] is False


def test_suite_flags_a_record_shortfall(settings: Settings) -> None:
    report = run_suite(settings, _clean_frame(rows=100), gate="gold")
    assert report["success"] is False
    assert any(
        item["expectation"].lower() == "expect_table_row_count_to_be_between"
        for item in report["critical_failures"]
    )


def test_gate_raises_on_critical_failure(settings: Settings) -> None:
    frame = _clean_frame()
    frame.loc[0, "balance"] = -1.0
    report = run_suite(settings, frame, gate="gold")
    with pytest.raises(ValueError, match="validation gate failed"):
        assert_gate(report)


def test_interim_gate_is_advisory(settings: Settings) -> None:
    report = run_suite(settings, _clean_frame(), gate="interim")
    assert all(item["gate"] == "advisory" for item in report["results"])
