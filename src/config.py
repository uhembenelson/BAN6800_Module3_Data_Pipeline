"""Typed configuration for the BAN6800 Module 3 customer data pipeline.

The pipeline reads a single declarative YAML file so that the Prefect DAG, the
Great Expectations suite, the bias suite and the governance documents cannot
drift apart. Two values are secrets and are therefore environment-driven:
the SHA-256 salt and the run seed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "pipeline.yaml"


@dataclass(frozen=True)
class Paths:
    """Every filesystem location the pipeline is allowed to touch."""

    root: Path
    raw: Path
    interim: Path
    processed: Path
    artifacts: Path
    figures: Path
    reference: Path

    @classmethod
    def from_root(cls, root: Path) -> "Paths":
        return cls(
            root=root,
            raw=root / "data" / "raw",
            interim=root / "data" / "interim",
            processed=root / "data" / "processed",
            artifacts=root / "artifacts",
            figures=root / "artifacts" / "figures",
            reference=root / "reference",
        )

    def ensure(self) -> None:
        for path in (self.raw, self.interim, self.processed, self.artifacts, self.figures):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    """Resolved configuration handed to every task in the DAG."""

    paths: Paths
    raw_config: dict[str, Any] = field(repr=False)

    # convenience accessors -------------------------------------------------
    @property
    def run(self) -> dict[str, Any]:
        return self.raw_config["run"]

    @property
    def ingestion(self) -> dict[str, Any]:
        return self.raw_config["ingestion"]

    @property
    def augmentation(self) -> dict[str, Any]:
        return self.raw_config["augmentation"]

    @property
    def anonymisation(self) -> dict[str, Any]:
        return self.raw_config["anonymisation"]

    @property
    def cleaning(self) -> dict[str, Any]:
        return self.raw_config["cleaning"]

    @property
    def transforms(self) -> dict[str, Any]:
        return self.raw_config["transforms"]

    @property
    def integration(self) -> dict[str, Any]:
        return self.raw_config["integration"]

    @property
    def validation(self) -> dict[str, Any]:
        return self.raw_config["validation"]

    @property
    def bias(self) -> dict[str, Any]:
        return self.raw_config["bias"]

    @property
    def governance(self) -> dict[str, Any]:
        return self.raw_config["governance"]

    @property
    def seed(self) -> int:
        return int(os.getenv("PIPELINE_SEED", self.run["random_seed"]))

    @property
    def as_of_date(self) -> str:
        return os.getenv("PIPELINE_AS_OF", self.run["as_of_date"])

    @property
    def raw_data_path(self) -> Path:
        configured = Path(self.ingestion["raw_path"])
        return configured if configured.is_absolute() else self.paths.root / configured

    @property
    def hash_salt(self) -> str:
        """Salted hashing needs a secret; a documented dev fallback keeps CI green."""
        value = os.getenv(self.anonymisation["salt_env_var"])
        if value:
            return value
        return str(self.anonymisation["dev_salt_fallback"])

    @property
    def using_dev_salt(self) -> bool:
        return not os.getenv(self.anonymisation["salt_env_var"])


def load_settings(config_path: Path | None = None, root: Path | None = None) -> Settings:
    """Read ``config/pipeline.yaml`` and resolve paths relative to the repo root."""
    repo_root = Path(root) if root else REPO_ROOT
    path = Path(config_path) if config_path else repo_root / "config" / "pipeline.yaml"
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"Configuration at {path} did not parse into a mapping")
    settings = Settings(paths=Paths.from_root(repo_root), raw_config=raw)
    settings.paths.ensure()
    return settings
