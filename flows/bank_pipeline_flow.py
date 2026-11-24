"""Prefect 3 orchestration DAG for the UK bank customer data pipeline.

Run it once::

    python -m flows.bank_pipeline_flow

Serve it on a schedule::

    python -m flows.bank_pipeline_flow serve

The DAG is a thin orchestration layer: each task calls one stage function from
``src.pipeline``. Retries are attached where the failure mode is genuinely
transient (reading the extract from storage), not everywhere by reflex.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # allow `python flows/bank_pipeline_flow.py`
    sys.path.insert(0, str(REPO_ROOT))

from prefect import flow, get_run_logger, task  # noqa: E402

from src import pipeline as core  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.pipeline import PipelineContext  # noqa: E402


@task(name="01 ingest raw extract", tags=["ingestion", "pii"], retries=2, retry_delay_seconds=10)
def ingest(context: PipelineContext) -> PipelineContext:
    """Read the CSV, enforce the schema, drop direct identifiers."""
    get_run_logger().info("Reading raw extract: %s", context.settings.raw_data_path.name)
    return core.stage_ingest(context)


@task(name="02 augment to 5,000-record floor", tags=["augmentation"])
def augment(context: PipelineContext) -> PipelineContext:
    """Bootstrap synthetic records and inject the known defect classes."""
    return core.stage_augment(context)


@task(name="03 anonymise and hash identifiers", tags=["privacy"])
def anonymise(context: PipelineContext) -> PipelineContext:
    """Salted SHA-256, surrogate references, PII scan, leak measurement."""
    return core.stage_anonymise(context)


@task(name="04 snapshot interim dataset", tags=["lineage"])
def snapshot(context: PipelineContext) -> PipelineContext:
    """Write the interim dataset so Gate A validates what was actually produced."""
    return core.stage_snapshot(context)


@task(name="05 validate interim (gate A, advisory)", tags=["validation"])
def validate_interim(context: PipelineContext) -> PipelineContext:
    """Great Expectations, advisory gate: expected to catch the injected defects."""
    return core.stage_validate_interim(context)


@task(name="06 clean", tags=["quality"])
def clean(context: PipelineContext) -> PipelineContext:
    """Apply CQ-01 ... CQ-10 deterministically."""
    return core.stage_clean(context)


@task(name="07 transform features", tags=["transformation"])
def transform(context: PipelineContext) -> PipelineContext:
    """Derive tenure, bands, flags and the nullable churn target."""
    return core.stage_transform(context)


@task(name="08 integrate dimensions", tags=["integration"])
def integrate(context: PipelineContext) -> PipelineContext:
    """Join the region and product dimensions, build the gold products."""
    return core.stage_integrate(context)


@task(name="09 validate gold (gate B, blocking)", tags=["validation"])
def validate_gold(context: PipelineContext) -> PipelineContext:
    """Great Expectations, blocking gate: a critical failure stops the run."""
    return core.stage_validate_gold(context)


@task(name="10 bias detection suite", tags=["ethics", "fairness"])
def bias(context: PipelineContext) -> PipelineContext:
    """Fairlearn representation audit across gender, region and age band."""
    return core.stage_bias(context)


@task(name="11 publish analytical products", tags=["serving"])
def publish(context: PipelineContext) -> PipelineContext:
    """Write the analysis table and the campaign feed."""
    return core.stage_publish(context)


@task(name="12 lineage, charts and manifest", tags=["observability"])
def report(context: PipelineContext) -> PipelineContext:
    """Emit lineage, figures, the quality report and the run manifest."""
    return core.stage_report(context)


@flow(name="uk-bank-customer-etl", log_prints=True, description="BAN6800 Module 3 data pipeline")
def uk_bank_customer_pipeline(stop_after: str | None = None) -> dict:
    """End-to-end ETL: raw extract to governed, validated, model-ready data."""
    logger = get_run_logger()
    settings = load_settings()
    context = core.start_run(settings)
    logger.info("Run %s started | seed=%s | as_of=%s", context.run_id, settings.seed, settings.as_of_date)

    ordered = [
        ("ingest", ingest),
        ("augment", augment),
        ("anonymise", anonymise),
        ("snapshot", snapshot),
        ("validate_interim", validate_interim),
        ("clean", clean),
        ("transform", transform),
        ("integrate", integrate),
        ("validate_gold", validate_gold),
        ("bias", bias),
        ("publish", publish),
        ("report", report),
    ]
    for name, task_function in ordered:
        context = task_function(context)
        logger.info("stage %-16s complete | rows=%s", name, context.stage_counts.get(name, "-"))
        if stop_after and name == stop_after:
            logger.warning("Stopping early after %s as requested", name)
            break

    logger.info(
        "Run complete | gold=%s rows | gate B=%s/%s expectations",
        context.reports["validate_gold"]["rows_validated"] if "validate_gold" in context.reports else "-",
        context.reports.get("validate_gold", {}).get("expectations_passed", "-"),
        context.reports.get("validate_gold", {}).get("expectations_run", "-"),
    )
    return {
        "run_id": context.run_id,
        "gold_rows": context.stage_counts.get("publish", 0),
        "artifacts": context.artifacts,
        "manifest": str(context.artifacts_dir / "run_manifest.json"),
    }


def serve() -> None:
    """Deploy the DAG against an in-process schedule (daily 02:00 Europe/London)."""
    uk_bank_customer_pipeline.serve(
        name="uk-bank-customer-etl-daily",
        cron="0 2 * * *",
        tags=["ban6800", "module3"],
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve()
    else:
        uk_bank_customer_pipeline()
