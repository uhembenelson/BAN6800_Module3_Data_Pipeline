"""Stage 5 - transformation: documented features with explicit derivations.

Each feature records the rule that produced it so the lineage document and the
Great Expectations suite can be generated from the same source of truth.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import Settings

#: Deterministic region naming. Deliberately derived from the region *label*,
#: never from the customer identifier, so the R2 prefix leak cannot return.
REGION_CODES: dict[str, str] = {
    "England": "E92000001",
    "Scotland": "S92000003",
    "Wales": "W92000004",
    "Northern Ireland": "N92000002",
}

FEATURE_CATALOGUE: list[dict[str, str]] = [
    {
        "feature": "tenure_days",
        "source": "date_joined, snapshot_date",
        "rule": "TR-01",
        "description": "Days between joining date and snapshot date, floored at zero",
    },
    {
        "feature": "tenure_months",
        "source": "tenure_days",
        "rule": "TR-02",
        "description": "Tenure in completed months (tenure_days / 30.44)",
    },
    {
        "feature": "age_band",
        "source": "age",
        "rule": "TR-03",
        "description": "Configurable age bands used for fairness slicing, never for offers",
    },
    {
        "feature": "balance_band",
        "source": "balance",
        "rule": "TR-04",
        "description": "Low <15k, Mid 15k-45k, High 45k-90k, Premium >=90k",
    },
    {
        "feature": "high_value_flag",
        "source": "balance",
        "rule": "TR-05",
        "description": "Balance at or above the 75th percentile of the cohort",
    },
    {
        "feature": "region_code",
        "source": "region_dimension (integration stage)",
        "rule": "IN-01",
        "description": "ONS region code from the governed region dimension, never the ID prefix",
    },
    {
        "feature": "marketing_eligible",
        "source": "is_minor",
        "rule": "TR-07",
        "description": "False for minors and for any record failing the consent gate",
    },
    {
        "feature": "churn_label",
        "source": "core banking closure extract",
        "rule": "TR-08",
        "description": "Nullable supervised target - awaiting signed-off churn definition (Sprint 1)",
    },
]


def should_threshold(settings: Settings, balance: pd.Series) -> float:
    """Dollar value of the high-value cut-off for this cohort."""
    percentile = float(settings.transforms["high_value_percentile"])
    return float(balance.quantile(percentile))


def _age_labels(bands: list[list[int]]) -> tuple[list[float], list[str]]:
    edges = [float(band[0]) for band in bands]
    edges.append(float(bands[-1][1]) + 1)
    labels = [f"{band[0]}-{band[1]}" for band in bands[:-1]] + [f"{bands[-1][0]}+"]
    return edges, labels


def transform(settings: Settings, frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Derive every analytical feature from the cleaned frame."""
    out = frame.copy()
    as_of = pd.Timestamp(settings.as_of_date)

    # TR-01 / TR-02 - tenure
    out["snapshot_date"] = as_of.date().isoformat()
    out["tenure_days"] = (as_of - out["date_joined"]).dt.days.clip(lower=0).astype("int64")
    out["tenure_months"] = (out["tenure_days"] / 30.44).round(1)

    # TR-03 - age bands
    edges, labels = _age_labels(settings.transforms["age_bands"])
    out["age_band"] = pd.cut(out["age"], bins=edges, labels=labels, right=False, include_lowest=True).astype("string")

    # TR-04 - balance bands
    bins = [float(edge) for edge in settings.transforms["balance_bands"]]
    band_labels = list(settings.transforms["balance_band_labels"])
    out["balance_band"] = pd.cut(out["balance"], bins=bins, labels=band_labels, right=False).astype("string")

    # TR-05 - high value
    threshold = should_threshold(settings, out["balance"])
    out["high_value_flag"] = out["balance"] >= threshold

    # TR-06 - marketing eligibility (minors excluded from profiling offers)
    out["marketing_eligible"] = ~out["is_minor"]

    # TR-08 - supervised target placeholder
    out["churn_label"] = pd.Series(pd.NA, dtype="boolean")

    out["balance"] = out["balance"].astype("float64").round(2)
    out["age"] = out["age"].astype("int64")

    report: dict[str, Any] = {
        "rows": int(len(out)),
        "features_created": [item["feature"] for item in FEATURE_CATALOGUE],
        "high_value_threshold": round(threshold, 2),
        "age_band_counts": out["age_band"].value_counts().sort_index().to_dict(),
        "balance_band_counts": out["balance_band"].value_counts().sort_index().to_dict(),
        "marketing_eligible": int(out["marketing_eligible"].sum()),
        "churn_label_status": "nullable placeholder - no closure data in the committed extract",
        "region_codes_assigned_at_integration": True,
    }
    return out, report
