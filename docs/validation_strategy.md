# Validation Strategy

BAN6800 Module 3 · UK Bank Customer Data Pipeline
Engine: Great Expectations 1.25.0 · Suite: `bank_customer_profile_suite`

---

## 1. Why two gates

A validation suite that only ever sees clean data proves nothing. It will pass,
the pipeline will look healthy, and nobody will know whether the checks work.

This pipeline therefore validates the **same 11 expectations twice**:

| Gate | Dataset | Mode | Reference result |
|---|---|---|---|
| **A** | `data/interim/bank_customer_interim.csv` — post-ingestion, post-augmentation, **pre-cleaning** | advisory | **5 passed / 6 failed** |
| **B** | `data/processed/gold_customer_profile` — post-cleaning | **blocking** | **11 passed / 0 failed** |

Gate A failing is the evidence that the suite has teeth. Gate B passing is what
authorises publication. A critical failure at Gate B raises
`ValueError: Data validation gate failed: ...` and the DAG stops before anything
reaches `data/processed/`.

---

## 2. The suite

| # | Expectation | Column | Gate | Why it exists |
|---|---|---|---|---|
| 1 | `ExpectTableRowCountToBeBetween(5000, 50000)` | — | critical | Module 3 record floor |
| 2 | `ExpectColumnValuesToNotBeNull` | `customer_key` | critical | Every record must be pseudonymised |
| 3 | `ExpectColumnValuesToBeUnique` | `customer_key` | critical | Prevents fan-out in Module 4 features |
| 4 | `ExpectColumnValuesToNotBeNull` | `age` | critical | Required for fairness slicing |
| 5 | `ExpectColumnValuesToBeBetween(16, 100)` | `age` | critical | Plausibility band |
| 6 | `ExpectColumnValuesToNotBeNull` | `balance` | critical | Drives every downstream feature |
| 7 | `ExpectColumnValuesToBeBetween(0, 250000)` | `balance` | critical | No negatives; ceiling catches keying errors |
| 8 | `ExpectColumnValuesToBeInSet` | `gender` | critical | Contracted domain |
| 9 | `ExpectColumnValuesToBeInSet` | `region` | critical | Four UK regions in scope |
| 10 | `ExpectColumnValuesToBeInSet` | `job_classification` | critical | `Unknown` is an explicit level |
| 11 | `ExpectColumnValuesToNotBeNull` | `date_joined` | critical | Tenure cannot be invented |

Gate severity travels on each expectation's `meta.gate` field, so the pipeline
decides blocking behaviour from the expectation object itself. Great Expectations
re-orders suites internally; positional indexing would silently mislabel
severity, which is exactly the kind of quiet failure this module is about.

### Deliberately not asserted

`churn_label` is **not** asserted non-null. It is a nullable placeholder awaiting
the signed-off churn definition (Module 2 issue I2). Asserting it would either
fail every run or force a fabricated label — both worse than an honest null.

---

## 3. Gate A results (interim)

| Expectation | Unexpected values |
|---|---|
| `customer_key` unique | 42 data points across duplicated records |
| `age` not null | 155 |
| `age` between 16 and 100 | 7 (values −5 and 200) |
| `balance` not null | 103 |
| `balance` between 0 and 250,000 | 5 (value −1250) |
| `date_joined` not null | 5 |

These are exactly the defect classes the augmentation injects — nothing more,
nothing less. The gate is calibrated to what the cleaning stage can actually fix.

---

## 4. Proving the suite catches defects

`tests/test_validation.py` feeds the suite deliberately broken frames and asserts
a `critical_failure`. Nine tests:

| Defect injected | Assertion |
|---|---|
| Clean 5,200-row frame | suite **passes** (no false positives) |
| Negative balance | fails on `expect_column_values_to_be_between` |
| Duplicate `customer_key` | fails on `..._to_be_unique` |
| Missing age | fails on `..._to_not_be_null` |
| Age = 200 | fails |
| Region = "Cork" | fails on `..._to_be_in_set` |
| 100 rows only | fails on `..._table_row_count_to_be_between` |
| Gate raises | `assert_gate` raises `ValueError` |
| Interim gate | every result tagged `advisory` |

If a future change weakens the suite, these tests fail first.

---

## 5. Data-quality evidence beyond the suite

`artifacts/quality_report.json` profiles the interim and gold datasets with the
same profiler and diffs them:

| Check | Interim | Gold | Status |
|---|---|---|---|
| Record count | 5,181 | 5,155 | PASS (≥5,000) |
| Duplicate business keys | 21 | 0 | PASS |
| Missing cells (shared columns) | 341 | 0 | PASS |
| Duplicate full rows | 0 | 0 | PASS |
| Columns | 9 | 25 | PASS |

Two subtleties the first run exposed and the profiler now handles:

* `churn_label` is null **by design** and is excluded from the null count.
* `crm_ref` is regenerated per row, so a perfectly duplicated customer record is
  no longer a duplicated *row*. Duplicate detection therefore runs on the
  pseudonymous business key.

---

## 6. Reproducing the evidence

```bash
export PIPELINE_HASH_SALT="...your salt..."
python -m flows.local_runner

# The suite result
cat artifacts/validation_gold.json | python -m json.tool | head -30

# Browsable Great Expectations Data Docs
open gx/uncommitted/data_docs/local_site/index.html

# The defect-detection proof
pytest tests/test_validation.py -v
```

The DAG rebuilds Data Docs on every run from the file-backed context at `gx/`, so
the HTML site always reflects the most recent validation.
