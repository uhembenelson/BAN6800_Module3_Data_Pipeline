"""Column-level data lineage and the run manifest.

Lineage is generated from code, not drawn by hand: every gold column is mapped
to the raw attributes and the rule that produced it. If the pipeline changes,
the lineage document changes with it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings

#: gold column -> (raw source columns, producing rule, stage)
LINEAGE: dict[str, dict[str, Any]] = {
    "customer_key": {
        "sources": ["Customer ID"],
        "rule": "AN-01 salted SHA-256",
        "stage": "anonymisation",
        "note": "raw identifier never reaches a downstream system",
    },
    "crm_ref": {
        "sources": ["(generated)"],
        "rule": "AN-02 Faker surrogate reference",
        "stage": "anonymisation",
        "note": "joinable business key containing no personal data",
    },
    "gender": {"sources": ["Gender"], "rule": "CQ-09 pass-through", "stage": "cleaning"},
    "age": {
        "sources": ["Age"],
        "rule": "CQ-03 range check, CQ-04 median imputation",
        "stage": "cleaning",
    },
    "age_band": {"sources": ["age"], "rule": "TR-03 banding", "stage": "transformation"},
    "region": {"sources": ["Region"], "rule": "CQ-09 pass-through", "stage": "cleaning"},
    "region_code": {
        "sources": ["region", "region_dimension.csv"],
        "rule": "IN-01 dimension join",
        "stage": "integration",
    },
    "job_classification": {
        "sources": ["Job Classification"],
        "rule": "CQ-08 Unknown level",
        "stage": "cleaning",
    },
    "date_joined": {"sources": ["Date Joined"], "rule": "CQ-10 date parse", "stage": "cleaning"},
    "tenure_days": {
        "sources": ["date_joined", "snapshot_date"],
        "rule": "TR-01 day difference",
        "stage": "transformation",
    },
    "tenure_months": {"sources": ["tenure_days"], "rule": "TR-02 /30.44", "stage": "transformation"},
    "balance": {
        "sources": ["Balance"],
        "rule": "CQ-05 positivity, CQ-06 median imputation, CQ-07 outlier flag",
        "stage": "cleaning",
    },
    "balance_band": {"sources": ["balance"], "rule": "TR-04 banding", "stage": "transformation"},
    "is_minor": {"sources": ["age"], "rule": "CQ-11 age < 18", "stage": "cleaning"},
    "marketing_eligible": {"sources": ["is_minor"], "rule": "TR-07", "stage": "transformation"},
    "high_value_flag": {
        "sources": ["balance"],
        "rule": "TR-05 >= 75th percentile",
        "stage": "transformation",
    },
    "churn_label": {
        "sources": ["core banking closure extract (not supplied)"],
        "rule": "TR-08 nullable placeholder",
        "stage": "transformation",
        "note": "signed-off churn definition required before Module 4",
    },
    "snapshot_date": {"sources": ["(config)"], "rule": "TR-01 as_of_date", "stage": "transformation"},
    "age_imputed": {"sources": ["age"], "rule": "CQ-04 flag", "stage": "cleaning"},
    "balance_imputed": {"sources": ["balance"], "rule": "CQ-06 flag", "stage": "cleaning"},
    "balance_outlier": {"sources": ["balance"], "rule": "CQ-07 flag", "stage": "cleaning"},
    "region_population_share": {
        "sources": ["region", "region_dimension.csv"],
        "rule": "IN-01 dimension join",
        "stage": "integration",
    },
    "min_group_size_ok": {
        "sources": ["region", "record_count"],
        "rule": "IN-02 n >= 100",
        "stage": "integration",
    },
    "recommended_product_family": {
        "sources": ["balance_band", "job_classification", "product_holding_dimension.csv"],
        "rule": "IN-03 rules engine",
        "stage": "integration",
    },
}

DOWNSTREAM_CONSUMERS: list[dict[str, str]] = [
    {
        "consumer": "gold_customer_profile",
        "type": "analysis table",
        "audience": "Module 4 model development",
        "sla": "rebuilt on every pipeline run",
    },
    {
        "consumer": "marketing_campaign_view",
        "type": "dashboard / campaign feed",
        "audience": "Marketing Manager - Retail",
        "sla": "eligible and high-value customers only",
    },
    {
        "consumer": "bias_report.json",
        "type": "governance feed",
        "audience": "Ethics Oversight Body, CRO",
        "sla": "produced on every run, retained with the run manifest",
    },
    {
        "consumer": "privacy_audit.log",
        "type": "audit trail",
        "audience": "DPO, FCA audit",
        "sla": "append-only, one line per data interaction",
    },
]


def build_lineage(settings: Settings) -> dict[str, Any]:
    """Assemble the lineage document for the current configuration."""
    stages = ["ingestion", "augmentation", "anonymisation", "cleaning", "transformation", "integration", "validation"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pipeline": settings.run["name"],
        "source_system": {
            "name": "P6 UK Bank Customer Profile Data",
            "format": "CSV",
            "frequency": "annual snapshot (2015); monthly in production",
            "records": 4014,
            "location": str(settings.raw_data_path.relative_to(settings.paths.root)),
        },
        "stages": stages,
        "column_lineage": LINEAGE,
        "downstream_consumers": DOWNSTREAM_CONSUMERS,
        "governance": {
            "pii_removed_at": "ingestion (name, surname) and anonymisation (customer_key)",
            "retention_days_raw": settings.governance["retention_days_raw"],
            "retention_days_gold": settings.governance["retention_days_gold"],
            "lawful_basis": settings.governance["lawful_basis"],
        },
    }


def write_lineage_doc(settings: Settings, artifacts: Path, docs: Path) -> dict[str, str]:
    """Emit the machine-readable lineage JSON and its human-readable twins."""
    lineage = build_lineage(settings)
    artifacts.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)

    json_path = artifacts / "lineage.json"
    json_path.write_text(json.dumps(lineage, indent=2), encoding="utf-8")

    lines = [
        "# Data Lineage - gold_customer_profile",
        "",
        "Generated by `src/lineage.py` on every pipeline run. Do not edit by hand.",
        "",
        "## Source",
        "",
        f"- **System:** {lineage['source_system']['name']}",
        f"- **Format:** {lineage['source_system']['format']} ({lineage['source_system']['records']:,} records)",
        f"- **Frequency:** {lineage['source_system']['frequency']}",
        "",
        "## Stages",
        "",
        " -> ".join(f"`{stage}`" for stage in lineage["stages"]),
        "",
        "## Column lineage",
        "",
        "| Gold column | Raw source | Rule | Stage | Note |",
        "|---|---|---|---|---|",
    ]
    for column, entry in lineage["column_lineage"].items():
        lines.append(
            f"| `{column}` | {', '.join(entry['sources'])} | {entry['rule']} | "
            f"{entry['stage']} | {entry.get('note', '')} |"
        )
    lines += [
        "",
        "## Downstream consumers",
        "",
        "| Consumer | Type | Audience | Contract |",
        "|---|---|---|---|",
    ]
    for consumer in lineage["downstream_consumers"]:
        lines.append(
            f"| `{consumer['consumer']}` | {consumer['type']} | {consumer['audience']} | {consumer['sla']} |"
        )

    md_path = docs / "lineage.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"lineage_json": str(json_path), "lineage_md": str(md_path)}


def write_manifest(artifacts: Path, manifest: dict[str, Any]) -> Path:
    """Persist the run manifest - the reproducibility record for this run."""
    artifacts.mkdir(parents=True, exist_ok=True)
    path = artifacts / "run_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return path
