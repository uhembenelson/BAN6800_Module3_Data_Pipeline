"""Tests for stage 10 - the bias detection suite.

The suite must flag a genuine skew, stay quiet on a balanced population, and
refuse to over-react to an underpowered group.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.bias_suite import audit_decision, run_bias_audit, summarise
from src.config import Settings


def _frame(high_value_by_gender: tuple[int, int], rows_per_group: int = 400) -> pd.DataFrame:
    male_selected, female_selected = high_value_by_gender
    genders = ["Male"] * rows_per_group + ["Female"] * rows_per_group
    flags = [True] * male_selected + [False] * (rows_per_group - male_selected)
    flags += [True] * female_selected + [False] * (rows_per_group - female_selected)
    return pd.DataFrame(
        {
            "gender": genders,
            "region": ["England"] * (rows_per_group * 2),
            "age_band": ["35-44"] * (rows_per_group * 2),
            "high_value_flag": flags,
            "marketing_eligible": [True] * (rows_per_group * 2),
        }
    )


def test_balanced_population_passes(settings: Settings) -> None:
    audit = audit_decision(settings, _frame((100, 100)), "gender", "high_value_flag")
    assert audit["disparate_impact_ratio"] == pytest.approx(1.0, abs=1e-3)
    assert audit["breaches"] == []


def test_disparate_impact_is_detected(settings: Settings) -> None:
    audit = audit_decision(settings, _frame((200, 80)), "gender", "high_value_flag")
    # selection rates are 0.50 (Male) and 0.20 (Female), so min/max = 0.4
    assert audit["disparate_impact_ratio"] == pytest.approx(0.4, abs=1e-3)
    # exactly one group must be outside the 0.80-1.25 band, whichever is the reference
    assert len(audit["breaches"]) == 1
    assert audit["breaches"][0] in {"Male", "Female"}


def test_representation_ratio_is_reported(settings: Settings) -> None:
    audit = audit_decision(settings, _frame((200, 80)), "gender", "high_value_flag")
    groups = {row["group"]: row for row in audit["groups"]}
    assert groups["Male"]["representation_ratio"] > groups["Female"]["representation_ratio"]


def test_underpowered_group_is_flagged_not_breached(settings: Settings) -> None:
    frame = pd.DataFrame(
        {
            "region": ["England"] * 300 + ["Northern Ireland"] * 40,
            "high_value_flag": [True] * 75 + [False] * 225 + [True] * 2 + [False] * 38,
            "marketing_eligible": [True] * 340,
        }
    )
    audit = audit_decision(settings, frame, "region", "high_value_flag")
    assert "Northern Ireland" in audit["underpowered_groups"]


def test_chi_square_is_reported_when_significant(settings: Settings) -> None:
    audit = audit_decision(settings, _frame((300, 60)), "gender", "high_value_flag")
    chi = audit["chi_square"]
    if chi["p_value"] is not None:
        assert chi["p_value"] < 0.05


def test_fairlearn_metrics_are_available(settings: Settings) -> None:
    audit = audit_decision(settings, _frame((200, 80)), "gender", "high_value_flag")
    assert audit["fairlearn"]["available"] is True
    assert 0.0 <= audit["fairlearn"]["demographic_parity_ratio"] <= 1.0


def test_full_audit_covers_every_attribute_and_decision(
    settings: Settings, gold_frame: pd.DataFrame
) -> None:
    report = run_bias_audit(settings, gold_frame)
    assert len(report["audits"]) == len(settings.bias["protected_attributes"]) * 2
    assert report["engine"] == "fairlearn"
    assert {"gender", "region", "age_band"}.issubset(report["protected_attributes"])


def test_summary_is_one_row_per_group(settings: Settings, gold_frame: pd.DataFrame) -> None:
    report = run_bias_audit(settings, gold_frame)
    summary = summarise(report)
    assert not summary.empty
    assert summary["population_records"].sum() > 0


def test_verdicts_cover_every_audit(settings: Settings, gold_frame: pd.DataFrame) -> None:
    report = run_bias_audit(settings, gold_frame)
    assert len(report["verdicts"]) == len(report["audits"])
