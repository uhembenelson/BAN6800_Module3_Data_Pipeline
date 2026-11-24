# Pipeline Architecture

BAN6800 Module 3 · UK Bank Customer Data Pipeline

## 1. Design principles

1. **Rules live in configuration, not in code.** `config/pipeline.yaml` is the
   single source of truth for thresholds, bands, retention periods and role
   permissions. Change the record floor once and the DAG, the validation suite
   and the documentation all follow.
2. **The core is orchestrator-agnostic.** Every stage is a plain function
   `ctx -> ctx` in `src/pipeline.py`. Prefect wraps them in `@task`; pytest calls
   them directly. No business logic sits inside a decorator.
3. **Every gate is evidenced.** A stage is not "done" because it logged success;
   it is done because it produced a JSON artefact and a unit test.
4. **Fail loud, fail early, fail upstream.** Schema violations stop at ingestion.
   A critical expectation failure stops at Gate B. Nothing half-valid reaches
   `data/processed/`.

## 2. Stage contract

| # | Stage | Function | Input | Output | Owner | Failure mode |
|---|---|---|---|---|---|---|
| 01 | Ingest | `pipeline.stage_ingest` | `data/raw/*.csv` | de-identified frame | Data Engineer | `SchemaError`, non-retryable |
| 02 | Augment | `stage_augment` | ingested frame | 5,000+ frame with defects | Data Engineer | raises if floor not met |
| 03 | Anonymise | `stage_anonymise` | augmented frame | hashed frame | Data Engineer | `ValueError` on residual PII |
| 04 | Snapshot | `stage_snapshot` | hashed frame | `data/interim/*.csv` | Data Engineer | disk write error |
| 05 | Validate A | `stage_validate_interim` | interim CSV | `validation_interim.json` | Data Engineer | advisory — logs, never blocks |
| 06 | Clean | `stage_clean` | interim frame | cleaned frame | Data Engineer | deterministic, idempotent |
| 07 | Transform | `stage_transform` | cleaned frame | featured frame | Data Engineer | raises on unknown band |
| 08 | Integrate | `stage_integrate` | featured frame | gold + campaign view | Data Engineer | `ValueError` on missing gold columns |
| 09 | Validate B | `stage_validate_gold` | gold frame | `validation_gold.json` | Data Engineer | **blocking** — raises |
| 10 | Bias audit | `stage_bias` | gold frame | `bias_report.json` | ML Lead | advisory |
| 11 | Publish | `stage_publish` | gold + view | CSV + Parquet | Data Engineer | disk write error |
| 12 | Report | `stage_report` | everything | lineage, charts, manifest | Data Engineer | advisory |

## 3. Rule catalogue

### Ingestion (CQ-00)
Raw headers are mapped to snake_case; `Name` and `Surname` are dropped before any
other processing. The regional prefix of `Customer ID` is captured in
`id_region_prefix` **only** so the leak can be measured, then dropped at
anonymisation.

### Cleaning (CQ-01 … CQ-10)

| Rule | Action | Records on the reference run |
|---|---|---|
| CQ-01 | Exact duplicate rows removed | 21 |
| CQ-02 | Duplicate `customer_key` collapsed | 0 |
| CQ-03 | Age present but outside 16–100 rejected to null | 7 |
| CQ-04 | Missing age imputed with cohort median | 162 |
| CQ-05 | Non-positive balance rejected to null | 5 |
| CQ-06 | Missing balance imputed with cohort median | 108 |
| CQ-07 | Balance above the IQR fence (116,687) flagged, retained | 97 |
| CQ-08 | Missing job classification → `Unknown` | 77 |
| CQ-09 | Rows with missing gender or region dropped | 0 |
| CQ-10 | Unparseable `date_joined` dropped | 5 |

"Present but impossible" (CQ-03, CQ-05) is counted separately from "missing"
(CQ-04, CQ-06). Lumping them together hides how much data was actually corrupt
versus absent: 17 values were rejected, 270 were imputed.

Interpolation is deliberately **cohort median, not mean**: the balance
distribution is right-skewed and a mean would inflate low-balance customers into
the high-value segment.

### Transformation (TR-01 … TR-08)

| Rule | Feature | Derivation |
|---|---|---|
| TR-01 | `tenure_days` | `snapshot_date − date_joined`, floored at 0 |
| TR-02 | `tenure_months` | `tenure_days / 30.44` |
| TR-03 | `age_band` | 16–24, 25–34, 35–44, 45–54, 55–64, 65+ |
| TR-04 | `balance_band` | Low <15k, Mid 15–45k, High 45–90k, Premium ≥90k |
| TR-05 | `high_value_flag` | balance ≥ 75th percentile of the cohort |
| TR-06 | `marketing_eligible` | not a minor, and passes the consent gate |
| TR-07 | `region_code` | from the governed region dimension, never the ID prefix |
| TR-08 | `churn_label` | nullable boolean placeholder (see §7) |

### Integration (IN-01 … IN-03)

* `IN-01` joins `reference/region_dimension.csv` on `region` (many-to-one).
* `IN-02` sets `min_group_size_ok` from the **measured** cohort size per region
  (n ≥ 100), not from a hard-coded figure.
* `IN-03` joins `reference/product_holding_dimension.csv` on
  (`balance_band`, `job_classification`) to produce
  `recommended_product_family`. Unmatched combinations fall back to
  *"Manual review — no approved rule"* rather than defaulting to a product.

## 4. Idempotency and retries

Every stage is a pure function of its inputs plus configuration. Re-running the
DAG produces byte-identical gold data for the same seed and salt. Retries are
attached **only** to ingestion, where the failure mode (an object-store read) is
genuinely transient:

```python
@task(name="01 ingest raw extract", retries=2, retry_delay_seconds=10)
```

Retrying a validation failure would be a bug, not resilience.

## 5. Orchestration

`flows/bank_pipeline_flow.py` defines the Prefect 3 flow `uk-bank-customer-etl`
with 12 tasks, each carrying tags for filtering (`ingestion`, `privacy`,
`validation`, `ethics`, `serving`, `observability`). Scheduled deployment:

```bash
python -m flows.bank_pipeline_flow serve     # daily 02:00, in-process
```

`flows/local_runner.py` runs the same stages without Prefect, which is what the
Docker image uses by default so the container has no server dependency.

## 6. Scaling path

| Today | At 10× | At 100× |
|---|---|---|
| Pandas in-process | chunked reads + `pyarrow` | Spark on Azure Databricks (UK South) |
| Local filesystem | Azure Blob Storage + DVC | Delta Lake with time travel |
| Prefect in-process | Prefect server on AKS | Prefect Cloud + K8s work pools |
| Postgres-free | — | Gold registered in Unity Catalog / Synapse |

The stage boundaries are already the right seam: `ingest`, `clean`, `transform`
and `integrate` each take and return a frame, so swapping Pandas for Spark means
rewriting four functions, not redesigning the pipeline.

## 7. The churn label gap

The committed extract contains no account-closure, transaction or product data,
so no supervised target exists. `TR-08` therefore emits `churn_label` as a
nullable `boolean` and the Great Expectations suite deliberately does not assert
non-null on it. The label specification — observation window, definition of an
exit, cooling-off period — remains Module 2 issue **I2**, to be signed off by the
sponsor and CRO before Module 4 begins. Downstream code can already join on the
column; it simply has no positive examples yet.

## 8. Failure handling and observability

* Every stage writes a structured audit line, including failures
  (`stageN.action.failed`) with the exception type.
* `artifacts/run_manifest.json` is written only on a successful completion, so
  its presence is the "run is good" signal used by the container healthcheck.
* Great Expectations Data Docs are rebuilt on every run from the file context at
  `gx/`, giving a browsable history of every validation result.
