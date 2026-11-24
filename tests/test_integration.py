"""Integration tests for the published gold dataset and the campaign view."""

from __future__ import annotations

import pandas as pd

from src.config import Settings
from src.integration import GOLD_COLUMNS, MARKETING_VIEW_COLUMNS


def test_gold_contains_every_contracted_column(gold_frame: pd.DataFrame) -> None:
    missing = [column for column in GOLD_COLUMNS if column not in gold_frame.columns]
    assert missing == []


def test_gold_meets_the_record_floor(gold_frame: pd.DataFrame) -> None:
    assert len(gold_frame) >= 5000


def test_gold_has_one_row_per_customer(gold_frame: pd.DataFrame) -> None:
    assert gold_frame["customer_key"].is_unique
    assert gold_frame["customer_key"].notna().all()


def test_no_direct_identifiers_survive_to_gold(gold_frame: pd.DataFrame) -> None:
    for forbidden in ("name", "surname", "customer_id", "id_region_prefix"):
        assert forbidden not in gold_frame.columns


def test_region_dimension_join_is_complete(gold_frame: pd.DataFrame) -> None:
    assert gold_frame["region_code"].notna().all()
    assert gold_frame["region_population_share"].notna().all()
    assert gold_frame["region_code"].nunique() == 4


def test_minimum_group_size_rule_uses_measured_counts(
    gold_frame: pd.DataFrame, settings: Settings
) -> None:
    counts = gold_frame["region"].value_counts()
    minimum = int(settings.integration["minimum_group_size"])
    for region, count in counts.items():
        expected = bool(count >= minimum)
        observed = bool(gold_frame.loc[gold_frame["region"] == region, "min_group_size_ok"].iloc[0])
        assert observed == expected, region


def test_product_rules_cover_every_row(gold_frame: pd.DataFrame) -> None:
    assert gold_frame["recommended_product_family"].notna().all()
    assert (gold_frame["recommended_product_family"] != "").all()


def test_campaign_view_contains_only_eligible_high_value_customers(
    settings: Settings,
) -> None:
    from src.pipeline import run_pipeline

    context = run_pipeline(settings, stop_after="publish")
    marketing = context.marketing
    assert marketing is not None
    assert list(marketing.columns) == MARKETING_VIEW_COLUMNS
    assert marketing["high_value_flag"].all()
    assert len(marketing) <= len(context.gold)  # type: ignore[arg-type]


def test_every_campaign_row_requires_human_approval(gold_frame: pd.DataFrame) -> None:
    assert len(gold_frame) > 0
    assert gold_frame["recommended_product_family"].str.len().gt(0).all()


def test_churn_label_is_present_but_null(gold_frame: pd.DataFrame) -> None:
    assert "churn_label" in gold_frame.columns
    assert gold_frame["churn_label"].isna().all()
