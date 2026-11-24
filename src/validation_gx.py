"""Stage 7 - data validation with Great Expectations.

The suite is declared in code (not clicked together in a notebook) so it is
reviewable, diffable and reproducible. Two gates use the same expectations:

* **Gate A - interim dataset** (post-ingestion, post-cleaning-to-be): advisory.
  It is expected to fail on the defects the augmentation injected, which is how
  we prove the gate actually fires.
* **Gate B - gold dataset**: blocking. Any critical expectation failing raises
  and the pipeline stops before publishing.

Expectations tagged ``meta.gate = "critical"`` are blocking; the rest are
advisory signals recorded in the report.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import Settings

try:  # pragma: no cover - import guard exercised by the Docker build
    import great_expectations as gx
    from great_expectations import expectations as gxe

    GX_AVAILABLE = True
    GX_VERSION = getattr(gx, "__version__", "unknown")
except Exception:  # pragma: no cover
    gx = None
    gxe = None
    GX_AVAILABLE = False
    GX_VERSION = "not installed"


CRITICAL = {"gate": "critical", "owner": "data-engineering"}
ADVISORY = {"gate": "advisory", "owner": "data-engineering"}


def build_expectations(gate: str) -> list[dict[str, Any]]:
    """Declarative expectation list shared by both gates.

    ``gate`` is ``interim`` or ``gold``; the gold gate adds the blocking
    completeness rules that the cleaning stage is responsible for satisfying.
    """
    meta = CRITICAL if gate == "gold" else ADVISORY
    return [
        {
            "type": "ExpectTableRowCountToBeBetween",
            "kwargs": {"min_value": 5000, "max_value": 50000},
            "meta": meta,
            "why": "Module 3 contractual record floor",
        },
        {
            "type": "ExpectColumnValuesToNotBeNull",
            "kwargs": {"column": "customer_key"},
            "meta": meta,
            "why": "Every record must carry a pseudonymous key",
        },
        {
            "type": "ExpectColumnValuesToBeUnique",
            "kwargs": {"column": "customer_key"},
            "meta": meta,
            "why": "One row per customer - prevents fan-out in Module 4 features",
        },
        {
            "type": "ExpectColumnValuesToNotBeNull",
            "kwargs": {"column": "age"},
            "meta": meta,
            "why": "Age is required for fairness slicing",
        },
        {
            "type": "ExpectColumnValuesToBeBetween",
            "kwargs": {"column": "age", "min_value": 16, "max_value": 100},
            "meta": meta,
            "why": "Contractual plausibility band for a retail banking customer",
        },
        {
            "type": "ExpectColumnValuesToNotBeNull",
            "kwargs": {"column": "balance"},
            "meta": meta,
            "why": "Balance drives every downstream feature",
        },
        {
            "type": "ExpectColumnValuesToBeBetween",
            "kwargs": {"column": "balance", "min_value": 0, "max_value": 250000},
            "meta": meta,
            "why": "No negative balances; ceiling guards against keying errors",
        },
        {
            "type": "ExpectColumnValuesToBeInSet",
            "kwargs": {"column": "gender", "value_set": ["Male", "Female"]},
            "meta": meta,
            "why": "Contracted demographic domain",
        },
        {
            "type": "ExpectColumnValuesToBeInSet",
            "kwargs": {
                "column": "region",
                "value_set": ["England", "Scotland", "Wales", "Northern Ireland"],
            },
            "meta": meta,
            "why": "Four UK regions in scope per the Module 1 vision",
        },
        {
            "type": "ExpectColumnValuesToBeInSet",
            "kwargs": {
                "column": "job_classification",
                "value_set": ["Blue Collar", "White Collar", "Other", "Unknown"],
            },
            "meta": meta,
            "why": "Unknown is an explicit level, never a silent null",
        },
        {
            "type": "ExpectColumnValuesToNotBeNull",
            "kwargs": {"column": "date_joined"},
            "meta": meta,
            "why": "Tenure cannot be derived without a joining date",
        },
    ]


def _instantiate(spec: dict[str, Any]) -> Any:
    """Build a GX expectation object from the declarative spec."""
    factory = getattr(gxe, spec["type"], None)
    if factory is None:
        raise AttributeError(f"Great Expectations has no expectation {spec['type']!r}")
    meta = {**spec.get("meta", {}), "why": spec.get("why", "")}
    return factory(meta=meta, **spec["kwargs"])


def _new_context(settings: Settings | None = None) -> Any:
    """Prefer a file-backed context so Great Expectations Data Docs are built.

    Data Docs give the reviewer a browsable record of every validation result,
    which is stronger evidence than a screenshot of a terminal.
    """
    if settings is not None:
        try:
            return gx.get_context(mode="file", project_root_dir=str(settings.paths.root))
        except Exception:  # pragma: no cover - fall back rather than fail the run
            pass
    return gx.get_context(mode="ephemeral")


def _suite(expectation_specs: list[dict[str, Any]], name: str, settings: Settings | None = None) -> tuple[Any, Any]:
    context = _new_context(settings)
    suite = gx.ExpectationSuite(name=name)
    try:
        suite = context.suites.add_or_update(suite)
    except Exception:  # pragma: no cover - older contexts only expose add/save
        suite = context.suites.add(suite)
    for spec in expectation_specs:
        suite.add_expectation(_instantiate(spec))
    return context, suite


def run_suite(settings: Settings, frame: pd.DataFrame, gate: str) -> dict[str, Any]:
    """Validate a dataframe against the gate suite and return a JSON-safe report."""
    if not GX_AVAILABLE:  # pragma: no cover
        raise ImportError(
            "Great Expectations is required for the validation stage. "
            "Install it with: pip install 'great_expectations>=1.0'"
        )

    specs = build_expectations(gate)
    suite_name = f"{settings.validation['suite_name']}_{gate}"
    context, suite = _suite(specs, suite_name, settings)

    data_source = context.data_sources.add_or_update_pandas(name=f"pandas_{gate}") \
        if hasattr(context.data_sources, "add_or_update_pandas") \
        else context.data_sources.add_pandas(name=f"pandas_{gate}")
    try:
        asset = data_source.add_dataframe_asset(name=f"bank_customers_{gate}")
    except Exception:
        asset = data_source.get_asset(f"bank_customers_{gate}")
    try:
        batch_definition = asset.add_batch_definition_whole_dataframe(name=f"batch_{gate}")
    except Exception:
        batch_definition = asset.get_batch_definition(f"batch_{gate}")

    batch = batch_definition.get_batch(batch_parameters={"dataframe": frame})

    # A ValidationDefinition both runs the suite and persists the result, which is
    # what makes the result visible in the Great Expectations Data Docs site.
    validation_definition = None
    try:
        validation_definition = context.validation_definitions.add_or_update(
            gx.ValidationDefinition(
                name=f"{suite_name}_validation", data=batch_definition, suite=suite
            )
        )
        validation = validation_definition.run(batch_parameters={"dataframe": frame})
    except Exception:
        validation_definition = None
        validation = batch.validate(suite)

    results: list[dict[str, Any]] = []
    for item in validation.results:
        config_item = item.expectation_config
        # Gate severity travels on the expectation's own meta block, so the report
        # cannot be corrupted by Great Expectations re-ordering its suite.
        meta = getattr(config_item, "meta", None) or {}
        results.append(
            {
                "expectation": config_item.type,
                "column": (config_item.kwargs or {}).get("column"),
                "success": bool(item.success),
                "observed": item.result.get("observed_value")
                if isinstance(item.result, dict)
                else None,
                "unexpected_count": (item.result or {}).get("unexpected_count"),
                "why": meta.get("why", ""),
                "gate": meta.get("gate", "advisory"),
            }
        )

    data_docs: dict[str, Any] = {"built": False}
    try:
        context.build_data_docs()
        site = Path(settings.paths.root) / "gx" / "uncommitted" / "data_docs" / "local_site" / "index.html"
        data_docs = {
            "built": site.exists(),
            "index": str(site),
            "validation_definition": getattr(validation_definition, "name", None),
            "persisted_result": validation_definition is not None,
        }
    except Exception as error:  # pragma: no cover - docs are evidence, not a gate
        data_docs = {"built": False, "error": f"{type(error).__name__}: {error}"}

    critical_failures = [
        result for result in results if result["gate"] == "critical" and not result["success"]
    ]
    payload: dict[str, Any] = {
        "engine": "great_expectations",
        "engine_version": GX_VERSION,
        "suite_name": suite_name,
        "gate": gate,
        "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows_validated": int(len(frame)),
        "columns_validated": int(frame.shape[1]),
        "expectations_run": len(results),
        "expectations_passed": sum(1 for result in results if result["success"]),
        "expectations_failed": sum(1 for result in results if not result["success"]),
        "success": bool(validation.success),
        "critical_failures": critical_failures,
        "data_docs": data_docs,
        "results": results,
    }
    return payload


def persist(report: dict[str, Any], path: Path) -> Path:
    """Write the validation report as JSON for the run manifest and the deck."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def assert_gate(report: dict[str, Any], *, fail_on_error: bool = True) -> None:
    """Block the pipeline when a critical expectation fails on the gold gate."""
    if not fail_on_error:
        return
    if report.get("critical_failures"):
        names = ", ".join(
            f"{failure['expectation']}({failure['column']})"
            for failure in report["critical_failures"]
        )
        raise ValueError(f"Data validation gate failed: {names}")
