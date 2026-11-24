# Module 3 Submission Checklist

BAN6800 · Designing a Data Pipeline for Business Analytics Solutions

## Presentation

- [x] PowerPoint, 12 slides (within the 10–12 requirement)
- [x] Title slide with name, course, and project title
- [x] Visuals dominant over text; one main idea per slide
- [x] Speaker notes on every slide explaining each pipeline stage
- [x] GitHub repository link on the title and reproducibility slides
- [x] NXU-style citations and a reference slide
- [x] AI Disclosure Form completed and submitted alongside

## Technical requirements

| Requirement | Deliverable | Location | Status |
|---|---|---|---|
| Orchestration DAG | Prefect 3 flow, 12 tasks | `flows/bank_pipeline_flow.py` | Done — run verified |
| Data validation suite | Great Expectations 1.25, 11 expectations, two gates | `src/validation_gx.py` | Done — 11/11 at Gate B |
| Validation screenshots | Data Docs validation result pages | `artifacts/screenshots/gx_validation_*.png` | Done |
| Unit tests | 73 tests across 8 modules | `tests/` | Done — all passing |
| Containerisation | Dockerfile + compose | `Dockerfile`, `docker-compose.yml` | Done |
| Bias detection | Fairlearn representation audit | `src/bias_suite.py` | Done — 6 audits, 0 breaches |
| Anonymisation | Salted SHA-256 + Faker surrogates | `src/anonymisation.py` | Done — leak closed |
| Data governance | RBAC, retention, DPIA | `docs/data_governance.md` | Done |
| Privacy audit log | JSON-lines, 47 events/run | `src/audit.py` → `artifacts/privacy_audit.log` | Done |
| Data lineage | Column-level, generated | `artifacts/lineage.json`, `docs/lineage.md` | Done |
| Reproducibility | Manifest with hashes, seed, versions | `artifacts/run_manifest.json` | Done |

## Continuity with Modules 1 and 2

- [x] Same dataset as Module 1 (`P6 UK Bank Customer Profile Data`)
- [x] Same business problem and KPIs (churn −15%, cross-sell +22%, campaign set-up 14 days → 2 hours)
- [x] Module 2 architecture honoured: Azure UK South, Python, K-Means/XGBoost path preserved for Module 4
- [x] Module 2 RAID log updated: R1 (NI sample) tracked with a 100-record rule; R2 (ID exposes region) closed and measured
- [x] Module 2 data dictionary extended to v2 with 16 derived fields
- [x] Module 1 ethical charter operationalised: disparate impact band 0.80–1.25 enforced in code
- [x] Human-in-the-loop preserved: every recommendation carries `human_approval_required = True`

## Outstanding (documented, not hidden)

- [ ] Churn label definition signed off — blocks the Module 4 supervised target
- [ ] Core-banking extract access (dependency D1)
- [ ] CRM consent flag join
- [ ] Salt rotation procedure with downstream re-key
- [ ] External release requires generalisation to (region, age_band) — k=7

## Pre-submission verification

```bash
pytest                                   # 73 passed
python -m flows.local_runner             # gate B 11/11
cat artifacts/run_manifest.json          # hashes, seed, versions
open gx/uncommitted/data_docs/local_site/index.html
```
