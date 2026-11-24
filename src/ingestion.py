"""Stage 1 - ingestion: read the raw extract, enforce schema, drop direct PII.

Raw file: ``data/raw/P6_UK_Bank_Customer_Profile.csv`` (P6 UK Bank Customer
Profile Data, 4,014 records, one snapshot dated 05.Jan.15 - 30.Dec.15).

This module never writes customer values to the audit log; it records counts,
column names and rule identifiers only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .config import Settings

#: Header in the supplied extract -> canonical snake_case name used downstream.
RAW_COLUMN_MAP: dict[str, str] = {
    "Customer ID": "customer_id",
    "Name": "name",
    "Surname": "surname",
    "Gender": "gender",
    "Age": "age",
    "Region": "region",
    "Job Classification": "job_classification",
    "Date Joined": "date_joined",
    "Balance": "balance",
}


class SchemaError(ValueError):
    """Raised when the raw extract does not match the contracted schema."""


def normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename supplier headers to canonical names and tidy free text."""
    renamed = {
        column: RAW_COLUMN_MAP.get(str(column).strip(), str(column).strip().lower().replace(" ", "_"))
        for column in frame.columns
    }
    out = frame.rename(columns=renamed)
    for column in out.select_dtypes(include="object"):
        out[column] = out[column].astype("string").str.strip()
        out[column] = out[column].replace({"": pd.NA})
    return out


def validate_schema(frame: pd.DataFrame, required: list[str]) -> None:
    """Fail fast when a contracted column is absent - never guess."""
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise SchemaError(f"Missing required columns: {', '.join(sorted(missing))}")


def read_raw(path: Path, date_format: str) -> pd.DataFrame:
    """Read the CSV with the supplier's date format and canonical headers."""
    if not path.exists():
        raise FileNotFoundError(f"Raw extract not found at {path}")
    frame = pd.read_csv(path, dtype={"Customer ID": "string", "Name": "string", "Surname": "string"})
    frame = normalise_columns(frame)
    frame["customer_id"] = frame["customer_id"].astype("string").str.strip()
    frame["date_joined_raw"] = frame["date_joined"]
    frame["date_joined"] = pd.to_datetime(frame["date_joined"], format=date_format, errors="coerce")
    frame["age"] = pd.to_numeric(frame["age"], errors="coerce")
    frame["balance"] = pd.to_numeric(frame["balance"], errors="coerce")
    return frame


def drop_direct_identifiers(frame: pd.DataFrame, identifiers: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Remove columns that identify a natural person outright (UK GDPR Art. 4)."""
    present = [column for column in identifiers if column in frame.columns]
    return frame.drop(columns=present), present


def extract_region_from_id(frame: pd.DataFrame) -> pd.Series:
    """Document the leak we are about to close.

    The first digit of ``Customer ID`` maps 1:1 to region (1=England,
    2=Scotland, 3=Wales, 4=Northern Ireland). This helper exists so the leakage
    test can quantify the risk *before* hashing and prove it is gone *after*.
    """
    return frame["customer_id"].astype("string").str.slice(0, 1)


def ingest(settings: Settings) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load, validate and de-identify the raw extract in one auditable step."""
    frame = read_raw(settings.raw_data_path, settings.ingestion["date_format"])
    validate_schema(frame, list(settings.ingestion["required_columns"]))

    leak_prefix = extract_region_from_id(frame)
    frame["id_region_prefix"] = leak_prefix  # kept until hashing, then dropped

    frame, dropped = drop_direct_identifiers(frame, list(settings.ingestion["direct_identifiers"]))
    report: dict[str, Any] = {
        "source_file": settings.raw_data_path.name,
        "rows_in": int(len(frame)),
        "columns_in": list(frame.columns),
        "direct_identifiers_removed": dropped,
        "invalid_dates_at_ingest": int(frame["date_joined"].isna().sum()),
        "region_prefix_leak_detected": True,
    }
    return frame, report
