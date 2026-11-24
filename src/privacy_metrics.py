"""Privacy risk metrics for the published dataset.

Anonymising the identifier is necessary but not sufficient: a record can still
be singled out from its quasi-identifier combination. This module measures how
many customers share the same quasi-identifier profile - the k-anonymity of the
released table - and compares alternative granularities so the release decision
is a documented trade-off rather than an assertion.

The first run measured **k = 1** at full granularity (region + age band +
gender + job classification). That is reported, not hidden: the findings drive
the generalisation recommendation in ``docs/anonymization_plan.md``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

#: Candidate release granularities, from most to least identifying.
GRANULARITY_SCENARIOS: dict[str, list[str]] = {
    "full": ["region", "age_band", "gender", "job_classification"],
    "drop_job_classification": ["region", "age_band", "gender"],
    "region_and_age": ["region", "age_band"],
    "region_only": ["region"],
}


def measure_k_anonymity(
    frame: pd.DataFrame,
    quasi_identifiers: list[str] | None = None,
    *,
    disclosure_threshold: int = 5,
) -> dict[str, Any]:
    """Return the equivalence-class size distribution for one release set."""
    identifiers = [
        column for column in (quasi_identifiers or GRANULARITY_SCENARIOS["full"]) if column in frame.columns
    ]
    if not identifiers:
        return {"available": False, "reason": "no quasi-identifier columns present"}

    classes = frame.groupby(identifiers, observed=True).size().rename("class_size").reset_index()
    total = int(len(frame))
    if total == 0 or classes.empty:
        return {"available": False, "reason": "empty frame"}

    sizes = classes["class_size"]
    at_risk = classes.loc[sizes < disclosure_threshold]
    at_risk_records = int(at_risk["class_size"].sum())
    minimum = int(sizes.min())

    return {
        "available": True,
        "quasi_identifiers": identifiers,
        "records": total,
        "equivalence_classes": int(len(classes)),
        "min_class_size": minimum,
        "median_class_size": float(sizes.median()),
        "max_class_size": int(sizes.max()),
        "disclosure_threshold": disclosure_threshold,
        "classes_below_threshold": int(len(at_risk)),
        "records_in_small_classes": at_risk_records,
        "share_in_small_classes": round(at_risk_records / total, 4),
        "k_anonymity": minimum,
        "k_anonymity_met": bool(minimum >= disclosure_threshold),
        "interpretation": (
            f"the smallest equivalence class contains {minimum} customer"
            f"{'' if minimum == 1 else 's'}; threshold for release is {disclosure_threshold}"
        ),
    }


def granularity_scenarios(
    frame: pd.DataFrame, *, disclosure_threshold: int = 5
) -> dict[str, Any]:
    """Measure k-anonymity across candidate release granularities."""
    results = {
        name: measure_k_anonymity(frame, columns, disclosure_threshold=disclosure_threshold)
        for name, columns in GRANULARITY_SCENARIOS.items()
    }
    compliant = [name for name, result in results.items() if result.get("k_anonymity_met")]
    return {
        "threshold": disclosure_threshold,
        "scenarios": results,
        "compliant_scenarios": compliant,
        "recommendation": (
            compliant[0]
            if compliant
            else "no candidate granularity meets the threshold; apply suppression"
        ),
        "note": (
            "Coarser granularity raises k but removes analytical utility. The recommended "
            "release set is the least-generalised option that still clears the threshold."
        ),
    }


def full_report(frame: pd.DataFrame, *, disclosure_threshold: int = 5) -> dict[str, Any]:
    """Everything the governance pack needs for the release decision."""
    base = measure_k_anonymity(frame, disclosure_threshold=disclosure_threshold)
    return {
        "released_table": base,
        "granularity_analysis": granularity_scenarios(frame, disclosure_threshold=disclosure_threshold),
        "residual_risk": (
            "the gold table is a pseudonymised internal analytical product, not an "
            "external release; small equivalence classes are governed by access "
            "control rather than by suppression"
            if not base.get("k_anonymity_met")
            else "the released granularity meets the k-anonymity threshold"
        ),
    }


def persist(report: dict[str, Any], path) -> str:
    """Write the privacy metrics next to the other run artefacts."""
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return str(path)
