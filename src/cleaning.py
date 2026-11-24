"""Stage 4 - cleaning: deterministic, reproducible data-quality rules.

Every rule is identified (CQ-01 ...) so the validation suite, the cleaning
report and the presentation can cite the same code. Nothing here is
interactive: given the same input and configuration the output is identical.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import Settings


def _rule(name: str, description: str, count: int, rows_before: int) -> dict[str, Any]:
    return {
        "rule": name,
        "description": description,
        "records_affected": int(count),
        "rows_before": int(rows_before),
    }


def drop_exact_duplicates(frame: pd.DataFrame, report: list[dict[str, Any]]) -> pd.DataFrame:
    """CQ-01: remove rows duplicated across every business column."""
    before = len(frame)
    subset = [column for column in frame.columns if column != "crm_ref"]
    out = frame.drop_duplicates(subset=subset, keep="first")
    report.append(_rule("CQ-01", "Exact duplicate customer records removed", before - len(out), before))
    return out


def drop_duplicate_keys(frame: pd.DataFrame, report: list[dict[str, Any]]) -> pd.DataFrame:
    """CQ-02: one row per pseudonymous customer; first occurrence wins."""
    before = len(frame)
    out = frame.drop_duplicates(subset=["customer_key"], keep="first")
    report.append(_rule("CQ-02", "Duplicate customer_key collapsed to one record", before - len(out), before))
    return out


def repair_ages(frame: pd.DataFrame, settings: Settings, report: list[dict[str, Any]]) -> pd.DataFrame:
    """CQ-03: ages outside the contractual band become null, then imputed."""
    before = len(frame)
    config = settings.cleaning
    out = frame.copy()
    out["age"] = pd.to_numeric(out["age"], errors="coerce")
    # CQ-03 counts only values that are *present but impossible*; nulls are a
    # different defect class and are handled by CQ-04. Lumping them together
    # hides how much of the data was actually corrupt.
    invalid = out["age"].notna() & (
        (out["age"] < config["age_min"]) | (out["age"] > config["age_max"])
    )
    out.loc[invalid, "age"] = np.nan
    report.append(
        _rule("CQ-03", f"Age present but outside {config['age_min']}-{config['age_max']} rejected", invalid.sum(), before)
    )

    missing = out["age"].isna()
    if missing.any():
        median = out["age"].median()
        out.loc[missing, "age"] = median
        out["age_imputed"] = missing
        report.append(_rule("CQ-04", "Missing age imputed with cohort median", missing.sum(), before))
    else:
        out["age_imputed"] = False
    out["age"] = out["age"].round().astype("int64")
    return out


def repair_balances(frame: pd.DataFrame, settings: Settings, report: list[dict[str, Any]]) -> pd.DataFrame:
    """CQ-05/06: non-positive balances are nulled, imputed, then outlier-flagged."""
    before = len(frame)
    out = frame.copy()
    out["balance"] = pd.to_numeric(out["balance"], errors="coerce")
    invalid = out["balance"].notna() & (out["balance"] <= 0)
    out.loc[invalid, "balance"] = np.nan
    report.append(_rule("CQ-05", "Non-positive balance rejected to null", invalid.sum(), before))

    missing = out["balance"].isna()
    if missing.any():
        median = float(out["balance"].median())
        out.loc[missing, "balance"] = median
        out["balance_imputed"] = missing
        report.append(_rule("CQ-06", "Missing balance imputed with cohort median", missing.sum(), before))
    else:
        out["balance_imputed"] = False

    multiplier = float(settings.cleaning["outlier_iqr_multiplier"])
    q1, q3 = out["balance"].quantile([0.25, 0.75])
    iqr = q3 - q1
    upper = q3 + multiplier * iqr
    outlier = out["balance"] > upper
    out["balance_outlier"] = outlier
    report.append(
        _rule("CQ-07", f"Balance above IQR fence {upper:,.0f} flagged (retained)", outlier.sum(), before)
    )
    out["balance"] = out["balance"].round(2)
    return out


def repair_categories(frame: pd.DataFrame, settings: Settings, report: list[dict[str, Any]]) -> pd.DataFrame:
    """CQ-08: missing categorical values take an explicit 'Unknown' level."""
    before = len(frame)
    out = frame.copy()
    fallback = settings.cleaning["job_class_fallback"]
    missing = out["job_classification"].isna()
    out.loc[missing, "job_classification"] = fallback
    out["job_classification"] = out["job_classification"].astype("string").str.strip().str.title()
    report.append(_rule("CQ-08", f"Missing job classification set to '{fallback}'", missing.sum(), before))

    for column in ("gender", "region"):
        blank = out[column].isna()
        if blank.any():
            report.append(_rule("CQ-09", f"Rows with missing {column} dropped", blank.sum(), before))
            out = out.loc[~blank]
    return out


def repair_dates(frame: pd.DataFrame, report: list[dict[str, Any]]) -> pd.DataFrame:
    """CQ-10: unparseable joining dates are dropped - tenure cannot be invented."""
    before = len(frame)
    out = frame.copy()
    unparseable = out["date_joined"].isna()
    out = out.loc[~unparseable]
    report.append(_rule("CQ-10", "Unparseable date_joined dropped", unparseable.sum(), before))
    out["date_joined"] = pd.to_datetime(out["date_joined"])
    return out


def clean(settings: Settings, frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply every cleaning rule in a fixed order and return the rule log."""
    report: list[dict[str, Any]] = []
    rows_in = len(frame)

    out = drop_exact_duplicates(frame, report)
    out = drop_duplicate_keys(out, report)
    out = repair_ages(out, settings, report)
    out = repair_balances(out, settings, report)
    out = repair_categories(out, settings, report)
    out = repair_dates(out, report)

    out = out.reset_index(drop=True)
    out["is_minor"] = out["age"] < int(settings.cleaning["minority_age"])

    summary: dict[str, Any] = {
        "rows_in": rows_in,
        "rows_out": int(len(out)),
        "rows_dropped": int(rows_in - len(out)),
        "rules": report,
        "total_records_affected": int(sum(rule["records_affected"] for rule in report)),
        "duplicates_found": int(sum(r["records_affected"] for r in report if r["rule"] in {"CQ-01", "CQ-02"})),
        "missing_values_resolved": int(
            sum(r["records_affected"] for r in report if r["rule"] in {"CQ-04", "CQ-06", "CQ-08"})
        ),
        "invalid_values_rejected": int(
            sum(r["records_affected"] for r in report if r["rule"] in {"CQ-03", "CQ-05", "CQ-10"})
        ),
        "outliers_flagged": int(sum(r["records_affected"] for r in report if r["rule"] == "CQ-07")),
        "minor_customers_flagged": int(out["is_minor"].sum()),
    }
    return out, summary
