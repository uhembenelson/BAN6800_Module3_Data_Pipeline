"""Unit tests for stage 1 - ingestion and schema enforcement."""

from __future__ import annotations

import pandas as pd
import pytest

from src.config import Settings
from src.ingestion import (
    SchemaError,
    drop_direct_identifiers,
    extract_region_from_id,
    ingest,
    normalise_columns,
    validate_schema,
)

REQUIRED = ["customer_id", "gender", "age", "region", "job_classification", "date_joined", "balance"]


def test_normalise_columns_maps_supplier_headers() -> None:
    frame = pd.DataFrame(columns=["Customer ID", "Job Classification", "Date Joined"])
    out = normalise_columns(frame)
    assert list(out.columns) == ["customer_id", "job_classification", "date_joined"]


def test_validate_schema_accepts_contracted_columns() -> None:
    validate_schema(pd.DataFrame(columns=REQUIRED), REQUIRED)


def test_validate_schema_rejects_missing_column() -> None:
    with pytest.raises(SchemaError, match="Missing required columns"):
        validate_schema(pd.DataFrame(columns=["customer_id"]), REQUIRED)


def test_drop_direct_identifiers_removes_names() -> None:
    frame = pd.DataFrame({"name": ["a"], "surname": ["b"], "age": [30]})
    out, dropped = drop_direct_identifiers(frame, ["name", "surname"])
    assert dropped == ["name", "surname"]
    assert list(out.columns) == ["age"]


def test_region_prefix_mapping_is_deterministic(raw_frame: pd.DataFrame) -> None:
    """The R2 leak: prefix 1..4 maps 1:1 to the four UK regions."""
    prefixes = extract_region_from_id(raw_frame)
    mapping = pd.crosstab(prefixes, raw_frame["region"])
    assert mapping.shape == (4, 4)
    # exactly one non-zero cell per row
    assert (mapping > 0).sum(axis=1).eq(1).all()
    assert mapping.loc["1", "England"] > 0
    assert mapping.loc["4", "Northern Ireland"] > 0


def test_ingest_drops_name_and_surname(settings: Settings) -> None:
    frame, report = ingest(settings)
    assert "name" not in frame.columns
    assert "surname" not in frame.columns
    assert report["direct_identifiers_removed"] == ["name", "surname"]
    assert report["rows_in"] == 4014


def test_ingest_parses_every_date(settings: Settings) -> None:
    frame, report = ingest(settings)
    assert report["invalid_dates_at_ingest"] == 0
    assert frame["date_joined"].between("2015-01-05", "2015-12-30").all()
