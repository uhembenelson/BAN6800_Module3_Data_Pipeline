"""Stage 6 - integration: conformed dimensions, then the gold output.

Two analytical products are published:

``gold_customer_profile``
    The analysis table Module 4 will train on. One row per pseudonymous
    customer, one column per governed feature.

``marketing_campaign_view``
    The dashboard / campaign feed: only marketing-eligible, high-value
    customers, already enriched with the rules-based recommended product.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import Settings

GOLD_COLUMNS: list[str] = [
    "customer_key",
    "crm_ref",
    "gender",
    "age",
    "age_band",
    "region",
    "region_code",
    "job_classification",
    "date_joined",
    "tenure_days",
    "tenure_months",
    "balance",
    "balance_band",
    "is_minor",
    "marketing_eligible",
    "high_value_flag",
    "churn_label",
    "snapshot_date",
    "age_imputed",
    "balance_imputed",
    "balance_outlier",
    "region_population_share",
    "min_group_size_ok",
    "recommended_product_family",
    "human_approval_required",
]

MARKETING_VIEW_COLUMNS: list[str] = [
    "customer_key",
    "crm_ref",
    "region",
    "age_band",
    "balance_band",
    "high_value_flag",
    "recommended_product_family",
    "human_approval_required",
]


def load_reference(settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the governed reference dimensions from ``reference/``."""
    region_dim = pd.read_csv(settings.paths.reference / "region_dimension.csv")
    product_dim = pd.read_csv(settings.paths.reference / "product_holding_dimension.csv")
    return region_dim, product_dim


def integrate(
    settings: Settings, frame: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Join dimensions, apply the recommendation rules and return both outputs."""
    region_dim, product_dim = load_reference(settings)

    # Cohort size per region is measured from the data, not taken on trust from
    # the dimension - the minimum-group-size rule must be evidence-based.
    counts = (
        frame.groupby("region", as_index=False)
        .size()
        .rename(columns={"size": "record_count"})
    )
    joined = frame.merge(counts, on="region", how="left", validate="many_to_one")
    joined = joined.merge(region_dim, on="region", how="left", validate="many_to_one")
    joined = joined.rename(columns={"population_share": "region_population_share"})
    joined["min_group_size_ok"] = joined["record_count"] >= int(settings.integration["minimum_group_size"])

    joined = joined.merge(
        product_dim, on=["balance_band", "job_classification"], how="left", validate="many_to_one"
    )
    joined["recommended_product_family"] = joined["recommended_product_family"].fillna(
        "Manual review - no approved rule"
    )
    joined["human_approval_required"] = (
        joined["human_approval_required"].astype("boolean").fillna(True).astype(bool)
    )

    missing_columns = [column for column in GOLD_COLUMNS if column not in joined.columns]
    if missing_columns:
        raise ValueError(f"Integration failed to produce gold columns: {missing_columns}")

    gold = joined[GOLD_COLUMNS].copy()
    gold["date_joined"] = pd.to_datetime(gold["date_joined"])

    marketing = joined.loc[
        joined["marketing_eligible"] & joined["high_value_flag"], MARKETING_VIEW_COLUMNS
    ].copy()

    report: dict[str, Any] = {
        "rows_gold": int(len(gold)),
        "rows_marketing_view": int(len(marketing)),
        "dimensions_joined": ["region_dimension", "product_holding_dimension"],
        "join_validation": "many_to_one on region and on (balance_band, job_classification)",
        "unmatched_region_rows": int(gold["region_population_share"].isna().sum()),
        "unmatched_product_rows": int((gold["recommended_product_family"] == "Manual review - no approved rule").sum()),
        "human_approval_required_rows": int(marketing["human_approval_required"].sum()),
        "outputs": {
            "gold_customer_profile": len(gold),
            "marketing_campaign_view": len(marketing),
        },
    }
    return gold, marketing, report


def publish(
    settings: Settings, gold: pd.DataFrame, marketing: pd.DataFrame
) -> dict[str, str]:
    """Write the analytical products to ``data/processed``."""
    processed = settings.paths.processed
    processed.mkdir(parents=True, exist_ok=True)
    paths = {
        "gold_csv": str(processed / "gold_customer_profile.csv"),
        "gold_parquet": str(processed / "gold_customer_profile.parquet"),
        "marketing_csv": str(processed / "marketing_campaign_view.csv"),
    }
    gold.to_csv(paths["gold_csv"], index=False)
    try:
        gold.to_parquet(paths["gold_parquet"], index=False)
    except Exception:  # pragma: no cover - parquet engine is optional
        paths.pop("gold_parquet")
    marketing.to_csv(paths["marketing_csv"], index=False)
    return paths
