"""Stage 2 - synthetic augmentation to satisfy the >=5,000 record floor.

Module 1 and Module 2 refused "synthetic hallucinated customer records"; the
Module 3 brief permits supplementation when the committed dataset is below
5,000. That tension is resolved explicitly here and recorded in the run
manifest: generated records are drawn from the *empirical* distributions of the
real extract (bootstrap resampling plus bounded noise), never invented from
scratch, and the generation seed is fixed so the dataset is reproducible.

Deliberate defects are injected at the same time so that the cleaning rules and
the Great Expectations suite are exercised against data that actually breaks -
a validation suite that only ever sees clean data proves nothing.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import Settings

SYNTHETIC_MARKER_PREFIX = "9"  # reserved ID block, 9xxxxxxx


def _sample_categorical(rng: np.random.Generator, source: pd.Series, size: int) -> pd.Series:
    """Bootstrap a categorical column using its empirical frequency."""
    values = source.dropna().astype(str)
    probabilities = values.value_counts(normalize=True)
    drawn = rng.choice(probabilities.index.to_numpy(), size=size, p=probabilities.to_numpy())
    return pd.Series(drawn, dtype="string")


def _sample_numeric(
    rng: np.random.Generator,
    source: pd.Series,
    size: int,
    *,
    lower: float,
    upper: float,
    multiplicative_noise: float = 0.0,
) -> pd.Series:
    """Bootstrap a numeric column and add bounded noise to avoid exact clones."""
    values = source.dropna().to_numpy(dtype=float)
    drawn = rng.choice(values, size=size, replace=True)
    if multiplicative_noise:
        factor = rng.lognormal(mean=0.0, sigma=multiplicative_noise, size=size)
        drawn = drawn * factor
    return pd.Series(np.clip(drawn, lower, upper))


def build_synthetic_block(settings: Settings, real: pd.DataFrame, size: int) -> pd.DataFrame:
    """Generate ``size`` rows that mirror the real extract's marginals."""
    rng = np.random.default_rng(settings.augmentation["seed"])
    frame = pd.DataFrame(index=range(size))

    base_id = int(settings.augmentation["synthetic_id_base"])
    frame["customer_id"] = pd.Series(
        [f"{base_id + i:09d}" for i in range(size)], dtype="string"
    )
    frame["gender"] = _sample_categorical(rng, real["gender"], size)
    frame["region"] = _sample_categorical(rng, real["region"], size)
    frame["job_classification"] = _sample_categorical(rng, real["job_classification"], size)
    frame["age"] = _sample_numeric(rng, real["age"], size, lower=16, upper=64).round().astype("float64")
    frame["balance"] = _sample_numeric(
        rng, real["balance"], size, lower=1.0, upper=250_000.0, multiplicative_noise=0.18
    ).round(2)
    frame["date_joined"] = pd.to_datetime(
        pd.Series(
            rng.choice(real["date_joined"].dropna().to_numpy(), size=size, replace=True)
        )
    ).reset_index(drop=True)
    frame["date_joined_raw"] = frame["date_joined"].dt.strftime("%d.%b.%y").astype("string")
    # Synthetic rows carry no regional prefix by construction, but the column
    # must exist because ingestion creates it for every row.
    frame["id_region_prefix"] = pd.Series(["9"] * size, dtype="string")
    return frame


def inject_noise(settings: Settings, frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Introduce realistic defects so downstream controls have something to catch."""
    rng = np.random.default_rng(settings.augmentation["seed"] + 1)
    noise = settings.augmentation["noise"]
    out = frame.copy()
    n = len(out)
    injected: dict[str, int] = {}

    # 1. Missing values on three attributes.
    for column, key in (
        ("age", "missing_age_rate"),
        ("balance", "missing_balance_rate"),
        ("job_classification", "missing_job_rate"),
    ):
        count = int(round(n * float(noise[key])))
        positions = rng.choice(n, size=count, replace=False)
        out.iloc[positions, out.columns.get_loc(column)] = pd.NA
        injected[key] = count

    # 2. Out-of-range ages (a negative and an impossible positive).
    invalid_ages = int(noise["invalid_age_count"])
    positions = rng.choice(n, size=invalid_ages, replace=False)
    out.iloc[positions[: invalid_ages // 2], out.columns.get_loc("age")] = 200.0
    out.iloc[positions[invalid_ages // 2 :], out.columns.get_loc("age")] = -5.0
    injected["invalid_age_count"] = invalid_ages

    # 3. Negative balances.
    negatives = int(noise["negative_balance_count"])
    positions = rng.choice(n, size=negatives, replace=False)
    out.iloc[positions, out.columns.get_loc("balance")] = -1250.00
    injected["negative_balance_count"] = negatives

    # 4. Malformed joining dates.
    malformed = int(noise["malformed_date_count"])
    positions = rng.choice(n, size=malformed, replace=False)
    out.iloc[positions, out.columns.get_loc("date_joined")] = pd.NaT
    out.iloc[positions, out.columns.get_loc("date_joined_raw")] = "31.Feb.15"
    injected["malformed_date_count"] = malformed

    # 5. Exact duplicate customer records (a classic fan-out defect).
    duplicates = max(1, int(round(n * float(noise["duplicate_rate"]))))
    sample = out.sample(n=duplicates, random_state=settings.augmentation["seed"] + 2)
    out = pd.concat([out, sample], ignore_index=True)
    injected["duplicate_rows"] = duplicates

    return out.reset_index(drop=True), injected


def augment(
    settings: Settings, real: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Top the extract up to the contractual record floor and add defects."""
    config = settings.augmentation
    if not config.get("enabled", False):
        return real.copy(), {"enabled": False}

    target = int(config["target_total_records"]) + int(config["record_buffer"])
    needed = max(0, target - len(real))
    synthetic = build_synthetic_block(settings, real, needed)

    combined = pd.concat([real, synthetic], ignore_index=True, sort=False)
    combined, injected = inject_noise(settings, combined)

    report: dict[str, Any] = {
        "enabled": True,
        "real_records": int(len(real)),
        "synthetic_records": int(needed),
        "target_total_records": int(config["target_total_records"]),
        "generation_seed": int(config["seed"]),
        "method": "bootstrap resampling of empirical marginals + bounded lognormal noise",
        "rows_before_noise_injection": int(len(real) + needed),
        "rows_after_noise_injection": int(len(combined)),
        "defects_injected": injected,
    }
    return combined.reset_index(drop=True), report
