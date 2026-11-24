"""Unit tests for stage 3 - anonymisation and the identifier-leak fix."""

from __future__ import annotations

import pandas as pd
import pytest

from src.anonymisation import anonymise, salted_hash, scan_for_pii
from src.config import Settings
from src.leakage import cramers_v, measure_region_leak


def test_salted_hash_is_repeatable() -> None:
    assert salted_hash("100000001", "salt") == salted_hash("100000001", "salt")


def test_salted_hash_changes_with_salt() -> None:
    assert salted_hash("100000001", "salt-a") != salted_hash("100000001", "salt-b")


def test_salted_hash_hides_the_input() -> None:
    digest = salted_hash("100000001", "salt")
    assert digest != "100000001"
    assert len(digest) == 64


def test_salted_hash_requires_a_salt() -> None:
    with pytest.raises(ValueError):
        salted_hash("100000001", "")


def test_anonymise_removes_the_raw_identifier(raw_frame: pd.DataFrame, settings: Settings) -> None:
    out, report = anonymise(settings, raw_frame)
    assert "customer_id" not in out.columns
    assert "crm_ref" in out.columns
    assert out["customer_key"].is_unique
    assert report["records_hashed"] == len(out)


def test_anonymise_breaks_the_region_leak(raw_frame: pd.DataFrame, settings: Settings) -> None:
    out, report = anonymise(settings, raw_frame)
    before = report["identifier_leak"]["before_hashing"]["cramers_v"]
    after = report["identifier_leak"]["after_hashing"]["cramers_v"]
    assert before > 0.95, "the raw prefix should fully determine region"
    assert after < 0.10, "the hashed key must not carry a regional signal"


def test_pii_scanner_catches_an_email(settings: Settings) -> None:
    frame = pd.DataFrame({"call_note": ["contact me at jane.doe@example.com please"]})
    result = scan_for_pii(frame, settings)
    assert result["clean"] is False
    assert result["total_hits"] >= 1


def test_pii_scanner_catches_a_postcode(settings: Settings) -> None:
    frame = pd.DataFrame({"call_note": ["lives near SW1A 1AA"]})
    assert scan_for_pii(frame, settings)["clean"] is False


def test_pii_scanner_accepts_a_clean_frame(raw_frame: pd.DataFrame, settings: Settings) -> None:
    out, report = anonymise(settings, raw_frame)
    assert report["pii_scan"]["clean"] is True
    assert report["pii_scan"]["total_hits"] == 0


def test_cramers_v_detects_perfect_association() -> None:
    left = pd.Series(list("aabbcc"))
    right = pd.Series(list("xxyyzz"))
    assert cramers_v(left, right) == pytest.approx(1.0, abs=1e-6)


def test_measure_region_leak_verdict() -> None:
    prefixes = pd.Series(["1"] * 20 + ["2"] * 20 + ["3"] * 20 + ["4"] * 20)
    regions = pd.Series(
        ["England"] * 20 + ["Scotland"] * 20 + ["Wales"] * 20 + ["Northern Ireland"] * 20
    )
    verdict = measure_region_leak(prefixes, regions)
    assert verdict["cramers_v"] > 0.95
    assert "CRITICAL" in verdict["verdict"]


def test_two_cell_series_does_not_crash_the_association_measure() -> None:
    """Cramer's V is bias-corrected, so a 2-record sample returns a safe value."""
    score = measure_region_leak(pd.Series(["1", "2"]), pd.Series(["England", "Scotland"]))
    assert 0.0 <= score["cramers_v"] <= 1.0
