"""Schema validation and privacy-safe customer identifier handling."""

from __future__ import annotations

import hashlib

import pandas as pd


REQUIRED_PROFILE_COLUMNS = {
    "customer_id",
    "gender",
    "age",
    "region",
    "job_classification",
    "date_joined",
    "balance",
}


def validate_profile_schema(frame: pd.DataFrame) -> None:
    """Raise a clear error when a required profile column is absent."""
    missing = REQUIRED_PROFILE_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")


def hash_customer_id(customer_id: str, salt: str) -> str:
    """Return a salted SHA-256 digest for a customer identifier."""
    if not salt:
        raise ValueError("A non-empty secret salt is required")
    value = f"{salt}:{customer_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()
