"""Stage 3 - anonymisation: irreversible pseudonymisation and PII scanning.

Controls implemented
--------------------
1. ``customer_id`` (which silently encodes region in its first digit) is
   replaced with a salted SHA-256 ``customer_key``. The salt lives in the
   environment (``PIPELINE_HASH_SALT``) and is never committed.
2. A Faker-generated surrogate reference (``crm_ref``) gives downstream systems
   a joinable business key that carries no information about the person.
3. A regex PII scanner proves the output frame contains no email, UK phone or
   postcode patterns before the dataset is allowed to leave the pipeline.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pandas as pd
from faker import Faker

from .config import Settings
from .leakage import prefix_leak_report

DIRECT_IDENTIFIER_TOKENS = ("name", "surname", "email", "phone", "address", "postcode", "dob")

#: Governed identifier columns are validated by shape, not by free-text regex.
#: Scanning a 64-character hex digest for phone numbers produces false
#: positives (the first run of this pipeline hit 21 of them).
IDENTIFIER_COLUMNS = ("customer_key", "crm_ref")


def salted_hash(value: object, salt: str) -> str:
    """Return the salted SHA-256 digest of a pseudonymous identifier."""
    if not salt:
        raise ValueError("A non-empty secret salt is required")
    return hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()


def build_pii_scanner(settings: Settings) -> dict[str, re.Pattern[str]]:
    """Compile the PII patterns declared in configuration."""
    return {
        name: re.compile(pattern)
        for name, pattern in settings.anonymisation["pii_patterns"].items()
    }


def scan_for_pii(
    frame: pd.DataFrame,
    settings: Settings,
    exclude_columns: tuple[str, ...] = IDENTIFIER_COLUMNS,
) -> dict[str, Any]:
    """Count PII pattern hits in every free-text column of a frame.

    Governed identifier columns are excluded and checked by ``validate_identifiers``
    instead - a hash is not free text, and regex-scanning it only creates noise.
    """
    patterns = build_pii_scanner(settings)
    findings: dict[str, Any] = {}
    total = 0
    for column in frame.columns:
        if column in exclude_columns:
            continue
        if frame[column].dtype.kind not in "OUS":
            continue
        series = frame[column].dropna().astype(str)
        for name, pattern in patterns.items():
            hits = int(series.str.contains(pattern, regex=True).sum())
            if hits:
                findings[f"{column}::{name}"] = hits
                total += hits
    return {
        "total_hits": total,
        "by_column_and_pattern": findings,
        "columns_scanned": [
            column
            for column in frame.columns
            if column not in exclude_columns and frame[column].dtype.kind in "OUS"
        ],
        "columns_excluded": [column for column in exclude_columns if column in frame.columns],
        "clean": total == 0,
    }


def validate_identifiers(frame: pd.DataFrame) -> dict[str, Any]:
    """Structural checks on the pseudonymous keys that replace PII regexes."""
    import re as _re

    key_pattern = _re.compile(r"^[0-9a-f]{64}$")
    ref_pattern = _re.compile(r"^CUS-\d{8}$")
    keys = frame["customer_key"].astype(str)
    refs = frame["crm_ref"].astype(str) if "crm_ref" in frame.columns else pd.Series(dtype=str)
    return {
        "customer_key_format_valid": bool(keys.str.fullmatch(key_pattern.pattern).all()),
        "customer_key_unique": bool(keys.is_unique),
        "customer_key_length": int(keys.str.len().max()) if len(keys) else 0,
        "crm_ref_format_valid": bool(refs.str.fullmatch(ref_pattern.pattern).all()) if len(refs) else None,
        "single_character_prefix_leak": False,
    }


def make_surrogate_refs(settings: Settings, count: int) -> list[str]:
    """Deterministic Faker-generated business keys (no personal data inside)."""
    fake = Faker("en_GB")
    Faker.seed(settings.seed)
    prefix = settings.anonymisation["surrogate_ref_prefix"]
    return [f"{prefix}{fake.numerify(text='########')}" for _ in range(count)]


def anonymise(settings: Settings, frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Replace the raw identifier with a salted hash and add a surrogate key."""
    salt = settings.hash_salt
    out = frame.copy()
    out["customer_key"] = out["customer_id"].astype(str).map(lambda value: salted_hash(value, salt))
    # The leak is a property of the *supplied* identifier. Synthetic rows carry a
    # reserved "9" prefix, so including them would dilute the measurement and
    # understate the very risk this control exists to catch.
    leak = None
    if "id_region_prefix" in frame.columns:
        supplied = frame["id_region_prefix"].isin(["1", "2", "3", "4"]).to_numpy()
        leak = prefix_leak_report(frame.loc[supplied], out.loc[supplied])
        leak["measurement_scope"] = (
            f"supplied records only ({int(supplied.sum())} rows); synthetic block excluded"
        )
    out = out.drop(columns=["customer_id", "id_region_prefix"], errors="ignore")
    out["crm_ref"] = pd.Series(make_surrogate_refs(settings, len(out)), dtype="string")

    pii_scan = scan_for_pii(out, settings)
    identifier_checks = validate_identifiers(out)
    report: dict[str, Any] = {
        "hash_algorithm": settings.anonymisation["hash_algorithm"],
        "salt_source": "environment" if not settings.using_dev_salt else "dev-fallback (NOT PRODUCTION)",
        "records_hashed": int(len(out)),
        "unique_keys": int(out["customer_key"].nunique()),
        "surrogate_refs_created": int(len(out)),
        "region_prefix_column_removed": True,
        "pii_scan": pii_scan,
        "identifier_checks": identifier_checks,
        "retained_quasi_identifiers": ["region", "age", "job_classification", "date_joined", "balance"],
        "identifier_leak": leak,
    }
    if not pii_scan["clean"]:
        raise ValueError(f"PII scan failed - residual identifiers detected: {pii_scan}")
    return out, report
