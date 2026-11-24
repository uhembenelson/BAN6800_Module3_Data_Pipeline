"""Orchestrator-agnostic pipeline core.

Every stage is a plain function ``ctx -> ctx``. The Prefect DAG
(``flows/bank_pipeline_flow.py``) wraps these functions in ``@task`` decorators;
``flows/local_runner.py`` calls them in a loop for CI. Because the logic does
not live inside a decorator, it can be unit tested without an orchestrator
running - which is exactly what the pytest suite does.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import (
    anonymisation,
    augmentation,
    bias_suite,
    cleaning,
    ingestion,
    integration,
    leakage,
    lineage,
    privacy_metrics,
    quality_report,
    reporting,
    transforms,
    validation_gx,
)
from .audit import PrivacyAuditTrail, new_run_id
from .config import Settings, load_settings

STAGE_ORDER = [
    "ingest",
    "augment",
    "anonymise",
    "snapshot",
    "validate_interim",
    "clean",
    "transform",
    "integrate",
    "validate_gold",
    "bias",
    "publish",
    "report",
]


def file_sha256(path: Path) -> str:
    """Content hash of an input file - the data-versioning control."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _versions() -> dict[str, str]:
    versions = {"python": sys.version.split()[0], "platform": platform.platform()}
    for name in ("pandas", "numpy", "great_expectations", "fairlearn", "prefect", "pytest"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", "unknown")
        except Exception:  # pragma: no cover
            versions[name] = "not installed"
    return versions


@dataclass
class PipelineContext:
    """Mutable state carried between stages - mirrors what Prefect passes along."""

    settings: Settings
    run_id: str
    audit: PrivacyAuditTrail
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    stage_counts: dict[str, int] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    reports: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    raw: pd.DataFrame | None = None
    interim: pd.DataFrame | None = None
    interim_snapshot: pd.DataFrame | None = None
    gold: pd.DataFrame | None = None
    marketing: pd.DataFrame | None = None
    status: str = "running"

    # convenience -----------------------------------------------------------
    @property
    def artifacts_dir(self) -> Path:
        return self.settings.paths.artifacts


def start_run(settings: Settings | None = None) -> PipelineContext:
    """Create the run identity and open the privacy audit trail."""
    settings = settings or load_settings()
    run_id = new_run_id()
    audit = PrivacyAuditTrail(
        log_path=settings.paths.artifacts / "privacy_audit.log",
        run_id=run_id,
        actor=settings.run["actor"],
        legal_basis=settings.governance["lawful_basis"],
    )
    context = PipelineContext(settings=settings, run_id=run_id, audit=audit)
    audit.record(
        "pipeline.start",
        dataset="uk_bank_customer_pipeline",
        detail={
            "config_hash": file_sha256(Path(settings.paths.root) / "config" / "pipeline.yaml"),
            "source_sha256": file_sha256(settings.raw_data_path),
            "seed": settings.seed,
            "as_of_date": settings.as_of_date,
            "salt_source": "environment" if not settings.using_dev_salt else "dev-fallback",
        },
    )
    return context


def _time(context: PipelineContext, stage: str, started: float, rows: int) -> None:
    context.timings[stage] = round(time.perf_counter() - started, 3)
    context.stage_counts[stage] = rows


def stage_ingest(context: PipelineContext) -> PipelineContext:
    """Stage 1 - read the raw extract and remove direct identifiers."""
    settings = context.settings
    started = time.perf_counter()
    with context.audit.stage("stage1.ingest", "raw/P6_UK_Bank_Customer_Profile.csv") as audit:
        frame, report = ingestion.ingest(settings)
        audit["rows_in"] = report["rows_in"]
        audit["rows_out"] = len(frame)
        audit["columns"] = tuple(frame.columns)
        audit["detail"] = {"pii_columns_removed": report["direct_identifiers_removed"]}
    context.raw = frame
    context.reports["ingest"] = report
    _time(context, "ingest", started, len(frame))
    return context


def stage_augment(context: PipelineContext) -> PipelineContext:
    """Stage 2 - top up to the 5,000-record floor and inject known defects."""
    started = time.perf_counter()
    with context.audit.stage("stage2.augment", "data/interim/augmented") as audit:
        frame, report = augmentation.augment(context.settings, context.raw)  # type: ignore[arg-type]
        audit["rows_in"] = len(context.raw)  # type: ignore[arg-type]
        audit["rows_out"] = len(frame)
        audit["detail"] = {
            "synthetic_records": report.get("synthetic_records", 0),
            "seed": report.get("generation_seed"),
            "defects_injected": report.get("defects_injected", {}),
        }
    context.interim = frame
    context.reports["augment"] = report
    _time(context, "augment", started, len(frame))
    return context


def stage_anonymise(context: PipelineContext) -> PipelineContext:
    """Stage 3 - salted hashing, surrogate refs, PII scan, leak measurement."""
    started = time.perf_counter()
    with context.audit.stage("stage3.anonymise", "data/interim/anonymised") as audit:
        before = context.interim
        frame, report = anonymisation.anonymise(context.settings, before)  # type: ignore[arg-type]
        audit["rows_in"] = len(before)  # type: ignore[arg-type]
        audit["rows_out"] = len(frame)
        audit["columns"] = tuple(frame.columns)
        audit["detail"] = {
            "pii_scan_total_hits": report["pii_scan"]["total_hits"],
            "salt_source": report["salt_source"],
        }
    context.interim = frame
    context.reports["anonymise"] = report
    _time(context, "anonymise", started, len(frame))
    return context


def stage_snapshot(context: PipelineContext) -> PipelineContext:
    """Persist the interim dataset so Gate A validates exactly what was produced."""
    interim = context.interim
    assert interim is not None
    path = context.settings.paths.interim / "bank_customer_interim.csv"
    context.interim_snapshot = interim.copy()
    interim.to_csv(path, index=False)
    context.artifacts["interim_csv"] = str(path)
    context.audit.record(
        "stage4.snapshot.write",
        dataset="data/interim/bank_customer_interim.csv",
        records=len(interim),
        detail={"columns_written": len(interim.columns)},
    )
    context.stage_counts["snapshot"] = len(interim)
    return context


def stage_validate_interim(context: PipelineContext) -> PipelineContext:
    """Stage 5 - Gate A: advisory validation of the pre-cleaning dataset."""
    started = time.perf_counter()
    interim = context.interim
    assert interim is not None
    with context.audit.stage("stage5.validate_interim", "data/interim/bank_customer_interim.csv") as audit:
        report = validation_gx.run_suite(context.settings, interim, gate="interim")
        path = validation_gx.persist(report, context.artifacts_dir / "validation_interim.json")
        audit["rows_in"] = len(interim)
        audit["rows_out"] = len(interim)
        audit["detail"] = {
            "expectations_passed": report["expectations_passed"],
            "expectations_failed": report["expectations_failed"],
            "gate": "advisory",
        }
    context.reports["validate_interim"] = report
    context.artifacts["validation_interim_json"] = str(path)
    _time(context, "validate_interim", started, len(interim))
    return context


def stage_clean(context: PipelineContext) -> PipelineContext:
    """Stage 6 - apply the deterministic cleaning rules."""
    started = time.perf_counter()
    with context.audit.stage("stage6.clean", "data/interim/bank_customer_clean.csv") as audit:
        frame, report = cleaning.clean(context.settings, context.interim)  # type: ignore[arg-type]
        report["identifier_leak"] = context.reports["anonymise"]["identifier_leak"]
        audit["rows_in"] = len(context.interim)  # type: ignore[arg-type]
        audit["rows_out"] = len(frame)
        audit["detail"] = {
            "rows_dropped": report["rows_dropped"],
            "duplicates_found": report["duplicates_found"],
            "missing_values_resolved": report["missing_values_resolved"],
        }
    context.interim = frame
    context.reports["clean"] = report
    _time(context, "clean", started, len(frame))
    return context


def stage_transform(context: PipelineContext) -> PipelineContext:
    """Stage 7 - derive the analytical features."""
    started = time.perf_counter()
    with context.audit.stage("stage7.transform", "data/interim/bank_customer_features.csv") as audit:
        frame, report = transforms.transform(context.settings, context.interim)  # type: ignore[arg-type]
        audit["rows_in"] = len(context.interim)  # type: ignore[arg-type]
        audit["rows_out"] = len(frame)
        audit["columns"] = tuple(report["features_created"])
        audit["detail"] = {"high_value_threshold": report["high_value_threshold"]}
    context.interim = frame
    context.reports["transform"] = report
    _time(context, "transform", started, len(frame))
    return context


def stage_integrate(context: PipelineContext) -> PipelineContext:
    """Stage 8 - join governed dimensions and build both published products."""
    started = time.perf_counter()
    with context.audit.stage("stage8.integrate", "data/processed/gold_customer_profile") as audit:
        gold, marketing, report = integration.integrate(context.settings, context.interim)  # type: ignore[arg-type]
        audit["rows_in"] = len(context.interim)  # type: ignore[arg-type]
        audit["rows_out"] = len(gold)
        audit["detail"] = report["outputs"]
    context.gold = gold
    context.marketing = marketing
    context.reports["integrate"] = report
    _time(context, "integrate", started, len(gold))
    return context


def stage_validate_gold(context: PipelineContext) -> PipelineContext:
    """Stage 9 - Gate B: blocking validation of the gold dataset."""
    started = time.perf_counter()
    gold = context.gold
    assert gold is not None
    with context.audit.stage("stage9.validate_gold", "data/processed/gold_customer_profile") as audit:
        report = validation_gx.run_suite(context.settings, gold, gate="gold")
        path = validation_gx.persist(report, context.artifacts_dir / "validation_gold.json")
        audit["rows_in"] = len(gold)
        audit["rows_out"] = len(gold)
        audit["detail"] = {
            "expectations_passed": report["expectations_passed"],
            "expectations_failed": report["expectations_failed"],
            "gate": "blocking",
        }
    validation_gx.assert_gate(report, fail_on_error=context.settings.validation["gate_b_fail_on_error"])
    context.reports["validate_gold"] = report
    context.artifacts["validation_gold_json"] = str(path)
    _time(context, "validate_gold", started, len(gold))
    return context


def stage_bias(context: PipelineContext) -> PipelineContext:
    """Stage 10 - representation-bias audit across protected attributes."""
    started = time.perf_counter()
    gold = context.gold
    assert gold is not None
    with context.audit.stage("stage10.bias", "data/processed/gold_customer_profile") as audit:
        report = bias_suite.run_bias_audit(context.settings, gold)
        paths = bias_suite.persist(report, context.artifacts_dir)
        audit["rows_in"] = len(gold)
        audit["rows_out"] = len(gold)
        audit["detail"] = {
            "breaches": report["breach_count"],
            "protected_attributes": report["protected_attributes"],
            "engine": report["engine"],
        }
    context.reports["bias"] = report
    context.artifacts.update(paths)
    _time(context, "bias", started, len(gold))
    return context


def stage_publish(context: PipelineContext) -> PipelineContext:
    """Stage 11 - write the analytical products and the quality comparison."""
    gold = context.gold
    marketing = context.marketing
    interim = context.interim
    assert gold is not None and marketing is not None and interim is not None

    with context.audit.stage("stage11.publish", "data/processed") as audit:
        paths = integration.publish(context.settings, gold, marketing)
        assert context.interim_snapshot is not None
        quality = quality_report.compare(context.interim_snapshot, gold)
        audit["rows_in"] = len(gold)
        audit["rows_out"] = len(gold) + len(marketing)
        audit["detail"] = {"files_written": list(paths)}

    context.artifacts.update(paths)
    context.reports["quality"] = quality
    context.artifacts["quality_report_json"] = str(
        quality_report.persist(quality, context.artifacts_dir)
    )
    context.stage_counts["publish"] = len(gold)
    return context


def stage_report(context: PipelineContext) -> PipelineContext:
    """Stage 12 - lineage, charts and the run manifest."""
    started = time.perf_counter()
    gold = context.gold
    assert gold is not None

    with context.audit.stage("stage12.report", "artifacts") as audit:
        lineage_paths = lineage.write_lineage_doc(
            context.settings, context.artifacts_dir, Path(context.settings.paths.root) / "docs"
        )
        privacy = privacy_metrics.full_report(gold)
        context.reports["privacy_metrics"] = privacy
        privacy_path = privacy_metrics.persist(
            privacy, context.artifacts_dir / "privacy_metrics.json"
        )
        bias_summary = bias_suite.summarise(context.reports["bias"])
        figures = reporting.produce_all(
            context.settings.paths.figures,
            funnel=[
                ("raw extract", context.stage_counts.get("ingest", 0)),
                ("after augmentation", context.stage_counts.get("augment", 0)),
                ("after cleaning", context.stage_counts.get("clean", 0)),
                ("gold output", context.stage_counts.get("publish", 0)),
            ],
            interim_validation=context.reports["validate_interim"],
            gold_validation=context.reports["validate_gold"],
            bias_summary=bias_summary,
            gold=gold,
            threshold=float(context.reports["transform"]["high_value_threshold"]),
            cleaning_summary=context.reports["clean"],
            privacy=privacy,
        )
        audit["detail"] = {
            "figures": len(figures),
            "k_anonymity": privacy["released_table"].get("k_anonymity"),
        }

    stage_reports_path = context.artifacts_dir / "stage_reports.json"
    stage_reports_path.write_text(
        json.dumps(context.reports, indent=2, default=str), encoding="utf-8"
    )
    context.artifacts["stage_reports_json"] = str(stage_reports_path)
    context.artifacts["privacy_metrics_json"] = privacy_path
    context.artifacts.update(lineage_paths)
    context.artifacts.update(figures)
    context.status = "success"
    manifest = build_manifest(context)
    context.artifacts["run_manifest"] = str(lineage.write_manifest(context.artifacts_dir, manifest))
    _time(context, "report", started, len(gold))
    return context


def build_manifest(context: PipelineContext) -> dict[str, Any]:
    """Everything needed to reproduce and audit this run."""
    settings = context.settings
    return {
        "run_id": context.run_id,
        "pipeline": settings.run["name"],
        "status": context.status,
        "started_at": context.started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "configuration": {
            "config_hash": file_sha256(Path(settings.paths.root) / "config" / "pipeline.yaml"),
            "seed": settings.seed,
            "as_of_date": settings.as_of_date,
            "target_total_records": settings.augmentation["target_total_records"],
            "salt_source": "environment" if not settings.using_dev_salt else "dev-fallback",
        },
        "inputs": {
            "raw_file": settings.raw_data_path.name,
            "raw_sha256": file_sha256(settings.raw_data_path),
            "raw_records": 4014,
        },
        "record_counts": context.stage_counts,
        "stage_timings_seconds": context.timings,
        "total_runtime_seconds": round(sum(context.timings.values()), 3),
        "versions": _versions(),
        "validation": {
            "interim": {
                "passed": context.reports["validate_interim"]["expectations_passed"],
                "failed": context.reports["validate_interim"]["expectations_failed"],
            },
            "gold": {
                "passed": context.reports["validate_gold"]["expectations_passed"],
                "failed": context.reports["validate_gold"]["expectations_failed"],
            },
        },
        "bias": {
            "breaches": context.reports["bias"]["breach_count"],
            "verdicts": context.reports["bias"]["verdicts"],
        },
        "cleaning": {
            "rows_dropped": context.reports["clean"]["rows_dropped"],
            "duplicates_found": context.reports["clean"]["duplicates_found"],
            "outliers_flagged": context.reports["clean"]["outliers_flagged"],
        },
        "artifacts": context.artifacts,
        "privacy": {
            **context.audit.summary(),
            "k_anonymity": context.reports.get("privacy_metrics", {}).get("released_table", {}),
            "granularity_recommendation": context.reports.get("privacy_metrics", {})
            .get("granularity_analysis", {})
            .get("recommendation"),
        },
    }


def run_pipeline(settings: Settings | None = None, *, stop_after: str | None = None) -> PipelineContext:
    """Execute every stage in order - the plain-Python equivalent of the DAG."""
    context = start_run(settings)
    stages = {
        "ingest": stage_ingest,
        "augment": stage_augment,
        "anonymise": stage_anonymise,
        "snapshot": stage_snapshot,
        "validate_interim": stage_validate_interim,
        "clean": stage_clean,
        "transform": stage_transform,
        "integrate": stage_integrate,
        "validate_gold": stage_validate_gold,
        "bias": stage_bias,
        "publish": stage_publish,
        "report": stage_report,
    }
    for name in STAGE_ORDER:
        context = stages[name](context)
        if stop_after and name == stop_after:
            break
    return context
