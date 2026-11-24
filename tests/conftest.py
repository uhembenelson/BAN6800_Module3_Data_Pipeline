"""Shared fixtures.

Tests run against a throwaway copy of the repository layout so a test run can
never overwrite the artefacts produced by a real pipeline run.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import Settings, load_settings  # noqa: E402


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """A complete settings object pointing at an isolated copy of the repo."""
    root = tmp_path_factory.mktemp("pipeline_repo")
    (root / "config").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "config" / "pipeline.yaml", root / "config" / "pipeline.yaml")

    (root / "data" / "raw").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "data" / "raw" / "P6_UK_Bank_Customer_Profile.csv",
        root / "data" / "raw" / "P6_UK_Bank_Customer_Profile.csv",
    )

    (root / "reference").mkdir(parents=True)
    for reference_file in (REPO_ROOT / "reference").glob("*.csv"):
        shutil.copy(reference_file, root / "reference" / reference_file.name)

    return load_settings(root=root)


@pytest.fixture(scope="session")
def raw_frame(settings: Settings) -> pd.DataFrame:
    """The real extract, de-identified, exactly as stage 1 produces it."""
    from src.ingestion import ingest

    frame, _ = ingest(settings)
    return frame


@pytest.fixture()
def messy_frame() -> pd.DataFrame:
    """A tiny frame carrying one defect of every class the cleaning stage owns."""
    return pd.DataFrame(
        {
            "customer_key": ["a" * 64, "b" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64],
            "crm_ref": ["CUS-1", "CUS-2", "CUS-2", "CUS-3", "CUS-4", "CUS-5"],
            "gender": ["Male", "Female", "Female", "Female", "Male", "Male"],
            "age": [34.0, 200.0, 45.0, -5.0, None, 17.0],
            "region": [
                "England",
                "Scotland",
                "Scotland",
                "Wales",
                "Northern Ireland",
                "England",
            ],
            "job_classification": ["White Collar", None, "Blue Collar", "Other", "Other", "Other"],
            "date_joined": pd.to_datetime(
                ["2015-01-05", "2015-02-05", "2015-03-05", "2015-04-05", None, "2015-06-05"]
            ),
            "date_joined_raw": ["05.Jan.15", "05.Feb.15", "05.Mar.15", "05.Apr.15", "bad", "05.Jun.15"],
            "balance": [25000.0, -1250.0, 48000.0, 9000.0, None, 120000.0],
            "id_region_prefix": ["1", "2", "2", "3", "4", "1"],
        }
    )


@pytest.fixture(scope="session")
def gold_frame(settings: Settings) -> pd.DataFrame:
    """The full pipeline output, built once and shared by the integration tests."""
    from src.pipeline import run_pipeline

    context = run_pipeline(settings)
    assert context.gold is not None
    return context.gold
