"""Before/after data-quality profiling.

This is the evidence that the cleaning stage did something measurable: the same
profiler runs on the interim dataset and on the gold dataset, and the two
profiles are diffed.

Two subtleties the first run of this pipeline exposed, and which the profiler
now handles explicitly:

* ``churn_label`` is null **by design** - it is a placeholder awaiting the
  signed-off churn definition. Counting it as a defect would make a correct
  pipeline look broken.
* the surrogate reference ``crm_ref`` is regenerated for every row, so a
  perfectly duplicated customer record is no longer a duplicate *row*. Duplicate
  detection therefore runs on the pseudonymous business key, not the full row.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

#: Nulls in these columns are intentional and must not be counted as defects.
NULLABLE_BY_DESIGN = {"churn_label"}

KEY_COLUMN = "customer_key"


def profile(frame: pd.DataFrame, label: str) -> dict[str, Any]:
    """Summarise shape, nulls, ranges and domains for one dataset state."""
    counted = [column for column in frame.columns if column not in NULLABLE_BY_DESIGN]
    nulls = frame[counted].isna().sum()
    key_duplicates = int(frame[KEY_COLUMN].duplicated().sum()) if KEY_COLUMN in frame.columns else 0

    result: dict[str, Any] = {
        "label": label,
        "rows": int(len(frame)),
        "columns": int(frame.shape[1]),
        "duplicate_rows": int(frame.duplicated().sum()),
        "duplicate_business_keys": key_duplicates,
        "total_missing_cells": int(nulls.sum()),
        "columns_with_nulls": {column: int(count) for column, count in nulls.items() if count},
        "columns_excluded_from_null_count": [
            column for column in frame.columns if column in NULLABLE_BY_DESIGN
        ],
        "column_list": list(frame.columns),
    }

    numeric: dict[str, dict[str, float]] = {}
    for column in frame.select_dtypes(include="number").columns:
        series = frame[column].dropna()
        if series.empty:
            continue
        numeric[column] = {
            "min": round(float(series.min()), 2),
            "median": round(float(series.median()), 2),
            "max": round(float(series.max()), 2),
            "mean": round(float(series.mean()), 2),
        }
    result["numeric_summary"] = numeric

    categorical: dict[str, dict[str, int]] = {}
    for column in ("gender", "region", "job_classification", "age_band", "balance_band"):
        if column in frame.columns:
            counts = frame[column].astype("string").value_counts(dropna=False)
            categorical[column] = {str(key): int(value) for key, value in counts.items()}
    result["category_counts"] = categorical
    return result


def compare(before: pd.DataFrame, after: pd.DataFrame) -> dict[str, Any]:
    """Build the quality report that the deck and the manifest both consume."""
    before_profile = profile(before, "interim")
    after_profile = profile(after, "gold")

    shared = [
        column
        for column in before.columns
        if column in after.columns and column not in NULLABLE_BY_DESIGN
    ]
    missing_before = int(before[shared].isna().sum().sum())
    missing_after = int(after[shared].isna().sum().sum())

    checks = [
        {
            "check": "Record count",
            "before": before_profile["rows"],
            "after": after_profile["rows"],
            "status": "PASS" if after_profile["rows"] >= 5000 else "FAIL",
            "note": "contractual floor is 5,000",
        },
        {
            "check": "Duplicate business keys",
            "before": before_profile["duplicate_business_keys"],
            "after": after_profile["duplicate_business_keys"],
            "status": "PASS" if after_profile["duplicate_business_keys"] == 0 else "FAIL",
            "note": "one row per pseudonymous customer",
        },
        {
            "check": "Missing cells (shared columns)",
            "before": missing_before,
            "after": missing_after,
            "status": "PASS" if missing_after == 0 else "FAIL",
            "note": "churn_label excluded - null by design",
        },
        {
            "check": "Duplicate full rows",
            "before": before_profile["duplicate_rows"],
            "after": after_profile["duplicate_rows"],
            "status": "PASS" if after_profile["duplicate_rows"] == 0 else "FAIL",
            "note": "crm_ref is regenerated per row, so the key check is authoritative",
        },
        {
            "check": "Columns",
            "before": before_profile["columns"],
            "after": after_profile["columns"],
            "status": "PASS",
            "note": "derived features and dimension attributes added",
        },
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "before": before_profile,
        "after": after_profile,
        "delta": {
            "rows": after_profile["rows"] - before_profile["rows"],
            "missing_cells_resolved": max(0, missing_before - missing_after),
            "duplicate_keys_removed": before_profile["duplicate_business_keys"]
            - after_profile["duplicate_business_keys"],
            "columns_added": after_profile["columns"] - before_profile["columns"],
        },
        "shared_columns_compared": shared,
        "checks": checks,
        "all_checks_pass": all(check["status"] == "PASS" for check in checks),
    }


def persist(report: dict[str, Any], artifacts: Path) -> Path:
    artifacts.mkdir(parents=True, exist_ok=True)
    path = artifacts / "quality_report.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path
