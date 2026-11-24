"""Quantify the customer-ID region leak before and after hashing.

Module 2 RAID entry R2 warned that the ``Customer ID`` prefix exposes region
(1=England, 2=Scotland, 3=Wales, 4=Northern Ireland). This module turns that
warning into a measurement: Cramer's V between the identifier derivative and
the region label. Cramer's V of 1.0 means the identifier *is* the region.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def cramers_v(left: pd.Series, right: pd.Series) -> float:
    """Bias-corrected Cramer's V for two categorical series."""
    mask = left.notna() & right.notna()
    table = pd.crosstab(left[mask], right[mask])
    if table.size == 0 or table.shape[0] < 2 or table.shape[1] < 2:
        return 0.0
    observed = table.to_numpy(dtype=float)
    total = observed.sum()
    if total == 0:
        return 0.0
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / total
    with np.errstate(divide="ignore", invalid="ignore"):
        chi2 = np.nansum((observed - expected) ** 2 / expected)
    phi2 = chi2 / total
    rows, cols = observed.shape
    phi2_corrected = max(0.0, phi2 - (cols - 1) * (rows - 1) / (total - 1))
    rows_corrected = rows - (rows - 1) ** 2 / (total - 1)
    cols_corrected = cols - (cols - 1) ** 2 / (total - 1)
    denominator = min(rows_corrected - 1, cols_corrected - 1)
    if denominator <= 0:
        return 0.0
    return float(np.sqrt(phi2_corrected / denominator))


def measure_region_leak(prefix_series: pd.Series, region_series: pd.Series) -> dict[str, float | str]:
    """Score how much a single identifier character reveals about region."""
    association = cramers_v(prefix_series.astype("string"), region_series.astype("string"))
    if association >= 0.95:
        verdict = "CRITICAL - identifier fully determines region"
    elif association >= 0.30:
        verdict = "HIGH - identifier strongly correlates with region"
    elif association > 0.10:
        verdict = "MODERATE - weak regional signal remains"
    else:
        verdict = "CLEAN - no usable regional signal"
    return {"cramers_v": round(association, 6), "verdict": verdict}


def prefix_leak_report(before: pd.DataFrame, after: pd.DataFrame) -> dict[str, object]:
    """Compare the raw prefix leak with the hashed key's leading hex character."""
    before_score = measure_region_leak(before["id_region_prefix"], before["region"])
    after_score = measure_region_leak(after["customer_key"].str.slice(0, 1), after["region"])
    return {
        "risk_id": "R2 (Module 2 RAID log) / ETH-01",
        "before_hashing": before_score,
        "after_hashing": after_score,
        "identifier_behaviour": {
            "raw": "first digit of Customer ID maps 1:1 to region",
            "hashed": "leading hex character of SHA-256 digest is uniformly distributed",
        },
        "remediation": "salted SHA-256 at stage 3; prefix column dropped from the dataset",
        "residual_risk": "region retained as an explicit, governed fairness attribute only",
    }
