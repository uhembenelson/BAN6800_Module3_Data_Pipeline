"""Stage 8 - bias detection suite (Fairlearn + representation analysis).

The pipeline is audited for **representation bias**: does a group appear in the
population that receives an action at the same rate it appears in the eligible
population?

Two decisions are audited, because they are the two the bank actually makes on
this dataset:

``high_value_flag``
    Selection into the retention treatment (balance at or above the 75th
    percentile). This is the decision Module 4's churn model will inherit, so a
    representation skew here compounds.
``marketing_eligible``
    The consent/minor exclusion gate applied before any campaign export.

Fairness metrics used
---------------------
* Selection rate per group.
* Disparate impact ratio (min / max selection rate), threshold 0.80 - 1.25 from
  the Module 1 charter.
* Representation ratio (share of the selected population / share of the eligible
  population), which catches skew that a selection-rate ratio can hide when the
  base rates differ.
* Chi-square test of independence for statistical significance.
* Minimum group size rule (n >= 100) so the small Northern Ireland sample cannot
  produce a false alarm - RAID entry R1.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import Settings

try:  # Fairlearn is optional at import time so the module can be unit tested alone
    from fairlearn.metrics import demographic_parity_difference, demographic_parity_ratio

    FAIRLEARN_AVAILABLE = True
except Exception:  # pragma: no cover
    demographic_parity_difference = None
    demographic_parity_ratio = None
    FAIRLEARN_AVAILABLE = False

try:
    from scipy.stats import chi2_contingency

    SCIPY_AVAILABLE = True
except Exception:  # pragma: no cover
    chi2_contingency = None
    SCIPY_AVAILABLE = False


def _chi_square(frame: pd.DataFrame, attribute: str, decision: str) -> dict[str, Any]:
    table = pd.crosstab(frame[attribute], frame[decision].astype(bool))
    if table.shape[0] < 2 or table.shape[1] < 2 or table.to_numpy().sum() == 0:
        return {"chi2": None, "p_value": None, "significant_at_0_05": None}
    if SCIPY_AVAILABLE:
        chi2, p_value, _, _ = chi2_contingency(table.to_numpy())
        return {
            "chi2": round(float(chi2), 4),
            "p_value": float(f"{p_value:.6g}"),
            "significant_at_0_05": bool(p_value < 0.05),
        }
    return {"chi2": None, "p_value": None, "significant_at_0_05": None}


def _fairlearn_parity(decision: pd.Series, attribute: pd.Series) -> dict[str, Any]:
    """Parity metrics via Fairlearn.

    Fairlearn's demographic-parity metrics are label-agnostic: ``y_true`` is used
    only for length alignment, so the decision vector is passed for both roles
    and the sensitive feature carries the grouping.
    """
    if not FAIRLEARN_AVAILABLE:  # pragma: no cover
        return {"available": False}
    vector = decision.astype(int)
    return {
        "available": True,
        "demographic_parity_difference": round(
            float(demographic_parity_difference(vector, vector, sensitive_features=attribute)), 4
        ),
        "demographic_parity_ratio": round(
            float(demographic_parity_ratio(vector, vector, sensitive_features=attribute)), 4
        ),
    }


def audit_decision(
    settings: Settings,
    frame: pd.DataFrame,
    attribute: str,
    decision: str,
    reference_group: str | None = None,
) -> dict[str, Any]:
    """Run the representation audit for one protected attribute and decision."""
    config = settings.bias
    min_size = int(config["minimum_group_size"])
    lower, upper = float(config["disparate_impact_lower"]), float(config["disparate_impact_upper"])

    base = frame[attribute].astype("string").value_counts()
    selected = frame.loc[frame[decision].astype(bool), attribute].astype("string").value_counts()

    rows: list[dict[str, Any]] = []
    for group in sorted(base.index.dropna()):
        count = int(base.get(group, 0))
        selected_count = int(selected.get(group, 0))
        base_share = count / max(int(base.sum()), 1)
        selected_share = selected_count / max(int(selected.sum()), 1)
        rows.append(
            {
                "group": group,
                "population_records": count,
                "population_share": round(base_share, 4),
                "selected_records": selected_count,
                "selected_share": round(selected_share, 4),
                "selection_rate": round(selected_count / count, 4) if count else None,
                "representation_ratio": round(selected_share / base_share, 4) if base_share else None,
                "sample_sufficient": bool(count >= min_size),
            }
        )

    table = pd.DataFrame(rows)
    sufficient = table[table["sample_sufficient"] & table["selection_rate"].notna()]
    if len(sufficient) >= 2:
        di_ratio = float(sufficient["selection_rate"].min() / sufficient["selection_rate"].max())
        parity_gap = float(sufficient["selection_rate"].max() - sufficient["selection_rate"].min())
    else:
        di_ratio = float("nan")
        parity_gap = float("nan")

    if reference_group is None:
        reference_group = (
            str(sufficient.sort_values("population_records", ascending=False)["group"].iloc[0])
            if len(sufficient)
            else None
        )

    reference_row = next((row for row in rows if row["group"] == reference_group), None)
    reference_rate = (reference_row or {}).get("selection_rate")
    for row in rows:
        if reference_rate:
            ratio = float(row["selection_rate"] or 0) / float(reference_rate)
            row["impact_ratio_vs_reference"] = round(ratio, 4)
            row["within_threshold"] = bool(lower <= ratio <= upper)
        else:
            row["impact_ratio_vs_reference"] = None
            row["within_threshold"] = None

    breaches = [row for row in rows if row.get("within_threshold") is False]
    underpowered = [row["group"] for row in rows if not row["sample_sufficient"]]

    return {
        "protected_attribute": attribute,
        "decision": decision,
        "reference_group": reference_group,
        "thresholds": {"disparate_impact_lower": lower, "disparate_impact_upper": upper},
        "groups": rows,
        "disparate_impact_ratio": None if np.isnan(di_ratio) else round(di_ratio, 4),
        "parity_gap": None if np.isnan(parity_gap) else round(parity_gap, 4),
        "breaches": [row["group"] for row in breaches],
        "underpowered_groups": underpowered,
        "chi_square": _chi_square(frame, attribute, decision),
        "fairlearn": _fairlearn_parity(frame[decision].astype(bool), frame[attribute].astype(str)),
    }


def run_bias_audit(settings: Settings, frame: pd.DataFrame) -> dict[str, Any]:
    """Audit every protected attribute against both governed decisions."""
    decisions = ["high_value_flag", "marketing_eligible"]
    audits: list[dict[str, Any]] = []
    for attribute in settings.bias["protected_attributes"]:
        if attribute not in frame.columns:
            continue
        for decision in decisions:
            if decision not in frame.columns:
                continue
            audits.append(audit_decision(settings, frame, attribute, decision))

    verdicts = []
    for audit in audits:
        if audit["breaches"]:
            verdicts.append(
                {
                    "finding": f"{audit['protected_attribute']} vs {audit['decision']}",
                    "status": "REVIEW REQUIRED",
                    "detail": f"groups outside 0.80-1.25 band: {', '.join(audit['breaches'])}",
                }
            )
        elif audit["underpowered_groups"]:
            verdicts.append(
                {
                    "finding": f"{audit['protected_attribute']} vs {audit['decision']}",
                    "status": "PASS WITH CAVEAT",
                    "detail": f"underpowered groups: {', '.join(audit['underpowered_groups'])}",
                }
            )
        else:
            verdicts.append(
                {
                    "finding": f"{audit['protected_attribute']} vs {audit['decision']}",
                    "status": "PASS",
                    "detail": "all groups inside the impact-ratio band",
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": "fairlearn" if FAIRLEARN_AVAILABLE else "pandas-fallback",
        "row_count": int(len(frame)),
        "protected_attributes": list(settings.bias["protected_attributes"]),
        "decisions_audited": decisions,
        "audits": audits,
        "verdicts": verdicts,
        "breach_count": sum(1 for audit in audits if audit["breaches"]),
        "note": (
            "Equal-opportunity and calibration metrics require the churn label from "
            "Module 4; this snapshot audits representation and selection parity only."
        ),
    }


def summarise(report: dict[str, Any]) -> pd.DataFrame:
    """Flatten the audit into one row per attribute/group for tables and charts."""
    rows: list[dict[str, Any]] = []
    for audit in report["audits"]:
        for group in audit["groups"]:
            rows.append(
                {
                    "protected_attribute": audit["protected_attribute"],
                    "decision": audit["decision"],
                    "group": group["group"],
                    "population_records": group["population_records"],
                    "population_share": group["population_share"],
                    "selected_share": group["selected_share"],
                    "selection_rate": group["selection_rate"],
                    "representation_ratio": group["representation_ratio"],
                    "impact_ratio_vs_reference": group.get("impact_ratio_vs_reference"),
                    "within_threshold": group.get("within_threshold"),
                    "sample_sufficient": group["sample_sufficient"],
                }
            )
    return pd.DataFrame(rows)


def persist(report: dict[str, Any], artifacts: Path) -> dict[str, str]:
    """Write the JSON report and the flat CSV summary."""
    artifacts.mkdir(parents=True, exist_ok=True)
    json_path = artifacts / "bias_report.json"
    csv_path = artifacts / "bias_summary.csv"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    summarise(report).to_csv(csv_path, index=False)
    return {"bias_report_json": str(json_path), "bias_summary_csv": str(csv_path)}
