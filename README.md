# UK Bank Customer Data Pipeline — BAN6800 Module 3

A reproducible, validated and governed ETL pipeline that turns the raw P6 UK bank
customer extract into a dataset a model can actually learn from.

This repository continues the capstone project from Module 1 (vision) and Module 2
(delivery plan). It adds the engineering layer those documents only promised: a
working DAG, a validation suite with two gates, an anonymisation and audit trail,
a bias detection suite, and a container that runs the whole thing.

> **The headline:** 4,014 raw records in, **5,155 validated rows out**, 9 columns
> in, 25 governed columns out, **11/11 Great Expectations checks passing** at the
> blocking gate, **0 fairness breaches**, and **73 unit tests green**.

---

## 1. The business problem this serves

The Module 1 vision targets high churn and weak cross-sell in a UK retail bank
that still segments customers on static demographic buckets. The Module 2 plan
identified the root cause: customer data sits in disconnected systems with no
pipeline, no agreed churn definition and no governance, so there is no behavioural
signal to segment on.

Before any model can be built, the data has to be trustworthy, reproducible and
lawful. That is this module's job.

| Module | Progress |
|---|---|
| 1 | Vision, ethical charter, stakeholder map |
| 2 | Root cause, architecture, sprint plan, RAID log, GitHub repo |
| **3** | **This repository — the data pipeline** |
| 4 | Predictive model, XAI, fairness in deployment |

---

## 2. Architecture

```text
 P6 UK Bank Customer Profile (CSV, 4,014 rows)
                │
        ┌───────▼────────┐
   01   │  INGEST        │  schema contract, drop name + surname     (CQ-00)
        └───────┬────────┘
        ┌───────▼────────┐
   02   │  AUGMENT       │  bootstrap to the 5,000-record floor,
        │                │  inject known defect classes              (AG-01)
        └───────┬────────┘
        ┌───────▼────────┐
   03   │  ANONYMISE     │  salted SHA-256, Faker surrogate key,
        │                │  PII scan, identifier-leak measurement    (AN-01)
        └───────┬────────┘
        ┌───────▼────────┐
   04   │  SNAPSHOT      │  persist interim → what Gate A sees
        └───────┬────────┘
        ┌───────▼────────┐
   05   │  VALIDATE (A)  │  Great Expectations — advisory
        └───────┬────────┘
        ┌───────▼────────┐
   06   │  CLEAN         │  CQ-01 … CQ-10, deterministic
        └───────┬────────┘
        ┌───────▼────────┐
   07   │  TRANSFORM     │  tenure, bands, flags, nullable target     (TR-01…TR-08)
        └───────┬────────┘
        ┌───────▼────────┐
   08   │  INTEGRATE     │  region + product dimensions               (IN-01…IN-03)
        └───────┬────────┘
        ┌───────▼────────┐
   09   │  VALIDATE (B)  │  Great Expectations — blocking
        └───────┬────────┘
        ┌───────▼────────┐
   10   │  BIAS AUDIT    │  Fairlearn representation analysis
        └───────┬────────┘
        ┌───────▼────────┐
   11   │  PUBLISH       │  gold table + campaign feed
        └───────┬────────┘
        ┌───────▼────────┐
   12   │  REPORT        │  lineage, charts, quality report, manifest
        └───────┬────────┘
                ▼
   data/processed/gold_customer_profile.parquet   (5,155 × 25)
   data/processed/marketing_campaign_view.csv     (1,286)
   artifacts/run_manifest.json                    (reproducibility record)
```

Full detail: [docs/pipeline_architecture.md](docs/pipeline_architecture.md).

---

## 3. Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export PIPELINE_HASH_SALT="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"

make test      # 73 tests
make run       # the plain-Python runner
make dag       # the Prefect DAG, same stages
```

Or in Docker:

```bash
docker build -t ban6800-module3-pipeline .
docker run --rm -e PIPELINE_HASH_SALT="$PIPELINE_HASH_SALT" \
  -v "$PWD/artifacts:/app/artifacts" ban6800-module3-pipeline
```

A full run takes **~2.6 seconds** on the reference machine and is deterministic:
the same input, configuration file, seed and salt produce the same customer keys
and the same 5,155 rows.

---

## 4. What comes out

| Artefact | Path | Consumer |
|---|---|---|
| Gold analysis table | `data/processed/gold_customer_profile.parquet` | Module 4 model development |
| Campaign feed | `data/processed/marketing_campaign_view.csv` | Marketing Manager — Retail |
| Validation results | `artifacts/validation_{interim,gold}.json` | DPO / auditors |
| Great Expectations Data Docs | `gx/uncommitted/data_docs/local_site/index.html` | Reviewers |
| Bias report | `artifacts/bias_report.json`, `bias_summary.csv` | Ethics Oversight Body |
| Privacy metrics | `artifacts/privacy_metrics.json` | DPO |
| Privacy audit trail | `artifacts/privacy_audit.log` | DPO / FCA audit |
| Column lineage | `artifacts/lineage.json`, `docs/lineage.md` | Module 4, new joiners |
| Run manifest | `artifacts/run_manifest.json` | Reproducibility evidence |

### The gold schema

`customer_key`, `crm_ref`, `gender`, `age`, `age_band`, `region`, `region_code`,
`job_classification`, `date_joined`, `tenure_days`, `tenure_months`, `balance`,
`balance_band`, `is_minor`, `marketing_eligible`, `high_value_flag`,
`churn_label` (null by design), `snapshot_date`, `age_imputed`,
`balance_imputed`, `balance_outlier`, `region_population_share`,
`min_group_size_ok`, `recommended_product_family`, `human_approval_required`.

---

## 5. Validation: two gates, not one

A suite that only ever sees clean data proves nothing. So the same 11
expectations run twice:

| Gate | Dataset | Mode | Result on this run |
|---|---|---|---|
| A | interim, post-augmentation | advisory | **5 passed / 6 failed** — the gate caught the injected defects |
| B | gold, post-cleaning | blocking | **11 passed / 0 failed** |

Gate A failing is the point: it demonstrates the checks fire. Gate B passing is
what authorises publication. The defect classes under test (duplicate keys,
missing age, impossible age, missing balance, negative balance, unparseable
date) are each covered by a unit test that feeds a deliberately broken frame to
the suite and asserts a failure — see `tests/test_validation.py`.

---

## 6. Privacy and governance

- **Direct identifiers removed at ingestion** (`Name`, `Surname`).
- **`Customer ID` → salted SHA-256 `customer_key`.** The raw ID encodes region
  in its first digit (1=England … 4=Northern Ireland); this was Module 2 RAID
  risk **R2** and it is now measured: Cramér's V between the identifier prefix
  and region is **1.000** before hashing and **0.000** after (no measurable association).
- **PII scanner** over every free-text column, with governed identifier columns
  excluded and validated structurally instead.
- **k-anonymity measured, not assumed:** k=1 at full granularity
  (region + age band + gender + job class), k=7 at (region + age band), which is
  the recommended external-release granularity.
- **Privacy audit log:** one JSON line per read, transformation and write, with
  lawful basis and record counts — never customer values.

See [docs/anonymization_plan.md](docs/anonymization_plan.md) and
[docs/data_governance.md](docs/data_governance.md).

---

## 7. Bias detection

Fairlearn audits two governed decisions against three protected attributes.

| Attribute | Decision | Disparate impact | Breaches |
|---|---|---|---|
| gender | high-value selection | 0.936 | 0 |
| region | high-value selection | 0.895 | 0 |
| age_band | high-value selection | 0.906 | 0 |
| gender | marketing eligibility | 0.999 | 0 |
| region | marketing eligibility | 0.986 | 0 |
| age_band | marketing eligibility | 0.983 | 0 |

All inside the 0.80–1.25 band set by the Module 1 charter. Northern Ireland
(n=276) clears the 100-record minimum-group rule, so the RAID R1 caveat is
tracked rather than guessed at. Equal-opportunity and calibration metrics need a
labelled target and are therefore deferred to Module 4 with the churn label.

---

## 8. Repository layout

```text
.
├── config/pipeline.yaml        # single source of truth for every rule
├── data/raw/                   # the supplied extract (read-only)
├── data/interim/               # snapshot validated by Gate A
├── data/processed/             # published products
├── reference/                  # governed dimensions (region, product)
├── src/                        # pipeline modules (no orchestrator imports)
├── flows/                      # Prefect DAG + plain-Python runner
├── tests/                      # 73 unit and integration tests
├── docs/                       # architecture, governance, lineage, dictionary
├── gx/                         # Great Expectations project + Data Docs
├── scripts/                    # helper scripts (screenshot capture)
├── artifacts/                  # run outputs (not versioned)
├── Dockerfile
└── docker-compose.yml
```

Design rule: **`src/` never imports Prefect.** The orchestration layer is a thin
shell around testable functions, which is why the whole pipeline can run inside
pytest without an orchestrator.

---

## 9. Known limitations (stated, not hidden)

1. **Synthetic augmentation.** The committed extract has 4,014 records; the
   Module 3 brief requires at least 5,000. 1,146 records were added by bootstrap
   resampling of the real empirical distributions with bounded noise, seed 42.
   Module 1 and Module 2 argued against synthetic customer records; the Module 3
   brief permits supplementation. The tension is recorded here, in the run
   manifest and in the governance document rather than resolved silently.
2. **No churn label.** P6 contains no closure or transaction data. `churn_label`
   ships as a nullable placeholder with a signed-off specification still
   outstanding (Module 2 issue I2).
3. **Single snapshot.** All records joined in 2015, so tenure is bounded by one
   year and there is no behavioural history.
4. **k=1 at full granularity.** The gold table is an internal analytical product
   under access control, not an external release; the granularity analysis shows
   what would be required if it ever became one.
5. **Rules-based recommendations.** `recommended_product_family` is Module 2's
   prescriptive engine in its deterministic form; every row is flagged
   `human_approval_required = True`.

---

## 10. Reproducibility

`artifacts/run_manifest.json` records, for every run: the SHA-256 of the input
file, the SHA-256 of `config/pipeline.yaml`, the seed, the snapshot date, the
salt source (environment vs dev fallback), package versions, per-stage timings,
row counts at every stage, and the full privacy audit summary.

Change the salt and every `customer_key` changes — rotation therefore requires a
coordinated re-key of downstream systems. This is documented in
[docs/data_governance.md](docs/data_governance.md).

---

## 11. References

Fairlearn contributors. (2024). *Fairlearn: A toolkit for assessing and improving
fairness in AI*. https://fairlearn.org

Great Expectations. (2025). *Great Expectations documentation*.
https://docs.greatexpectations.io

Information Commissioner's Office. (2024). *Guide to the UK General Data
Protection Regulation*. https://ico.org.uk

Prefect Technologies. (2025). *Prefect 3 documentation*. https://docs.prefect.io

Rezig, E. K., Cao, L., Stonebraker, M., Simonini, G., Godabrelidze, D., Alamoudi,
S., ... & Bruckner, D. (2022). Such a silly question: Data validation in
practice. *SIGMOD Record*, 51(4), 20–31.

Sambasivan, N., Kapania, S., Highfill, H., Akrong, D., Paritosh, P., & Aroyo, L.
(2021). "Everyone wants to do the model work, not the data work": Data cascades
in high-stakes AI. *CHI 2021*, 1–15.
