# Data Governance Framework

BAN6800 Module 3 · UK Bank Customer Data Pipeline
Owner: Data Protection Officer · Approver: Chief Risk & Compliance Officer

This framework operationalises the Module 1 data stewardship principles and the
Module 2 privacy plan. Every control below is either **implemented in code** or
**explicitly flagged as a manual process** — no control exists only on paper.

---

## 1. Data classification

| Class | Definition | Examples in this pipeline | Handling |
|---|---|---|---|
| **D1 — Direct identifier** | Identifies a natural person on its own | `Name`, `Surname` | Dropped at ingestion; never persisted |
| **D2 — Pseudonymous identifier** | Identifies a record, not a person, without the key | `customer_key`, `crm_ref` | Salted hash / surrogate; access controlled |
| **D3 — Quasi-identifier** | Combining them can re-identify | `region`, `age_band`, `gender`, `job_classification` | k-anonymity measured; granularity governed |
| **D4 — Sensitive attribute** | Special-category or protected characteristic | `gender`, `age` | Fairness monitoring only; never a decision input |
| **D5 — Financial data** | Account values | `balance`, `balance_band` | Encrypted at rest; role-restricted |
| **D6 — Derived / aggregate** | Non-identifying outputs | `bias_report.json`, `run_manifest.json` | Shareable internally |

`Name` and `Surname` are removed by `src/ingestion.py` before any transformation,
so no downstream artefact — including the audit log — can contain them.

---

## 2. Access control (RBAC)

Defined in `config/pipeline.yaml` under `governance.roles`:

| Role | Permitted actions | Dataset scope | Enforcement |
|---|---|---|---|
| `data_engineer` | read_raw, transform, write_processed | `data/raw`, `data/interim`, `data/processed` | Container service account; write scope limited to `data/` |
| `lead_data_scientist` | read_processed | `data/processed` | Read-only mount; no access to `data/raw` |
| `marketing_manager` | read_marketing_view | `data/processed/marketing_campaign_view.csv` | Export gate; direct identifiers absent by construction |
| `dpo` | read_audit_log, read_governance | `artifacts/`, `docs/` | Read-only |
| `auditor` | read_audit_log | `artifacts/privacy_audit.log` | Append-only source, read-only target |

**Implemented:** the raw extract is readable only where the pipeline runs; the
published products contain no direct identifiers, so the marketing role cannot
receive personal data even if the export is misconfigured.
**Manual:** identity-provider group mapping (Azure AD) for the roles above must be
maintained by IT — this is a deployment-time control outside the repository.

---

## 3. Lawful basis and purpose limitation

| Element | Decision |
|---|---|
| Lawful basis | UK GDPR Art. 6(1)(f) legitimate interests — retention of existing customers under FCA Consumer Duty |
| Purpose | Customer segmentation and retention analytics only |
| Prohibited purposes | Credit underwriting, price setting, automated offers (Module 2 out-of-scope list) |
| Special category data | None processed |
| Automated decision-making | None — every recommendation carries `human_approval_required = True` (UK GDPR Art. 22) |
| Children | 5 minor records identified and excluded from marketing eligibility (`is_minor`) |

The lawful basis string is stamped onto **every** audit log line, so the basis for
each processing event is provable rather than claimed.

---

## 4. Retention and deletion

| Data | Retention | Mechanism | Config key |
|---|---|---|---|
| Raw extract | 24 months (Module 1 rule) | Manual purge of `data/raw/` | `retention_days_raw: 730` |
| Interim snapshot | 30 days | Overwritten on every run | — |
| Gold analytical table | 36 months | Rebuildable from raw + config | `retention_days_gold: 1095` |
| Privacy audit log | 6 years (FCA record-keeping) | Append-only | — |
| Run manifest | 6 years | One file per run | — |

Deletion is a documented manual step because this pipeline runs against a local
copy. In production it becomes an Azure Blob lifecycle policy — the retention
values are already in configuration so the policy can be generated from them.

---

## 5. Privacy audit logging

`src/audit.py` writes one JSON object per line to `artifacts/privacy_audit.log`
via the Python `logging` module. Each line records:

```json
{
  "timestamp": "2026-11-22T14:48:01+00:00",
  "run_id": "run-20261122T144801Z-65c876",
  "actor": "etl-service@bank-uk",
  "action": "stage3.anonymise.complete",
  "dataset": "data/interim/anonymised",
  "records_affected": 5181,
  "columns_touched": ["customer_key", "crm_ref", "gender", "age"],
  "legal_basis": "UK GDPR Art. 6(1)(f) legitimate interests - FCA Consumer Duty",
  "severity": "INFO",
  "detail": {"pii_scan_total_hits": 0, "salt_source": "environment"}
}
```

Properties that matter:

* **No customer values are ever logged** — counts, column names and rule ids only.
  An audit log that leaks PII is itself a breach.
* **Failures are logged** as `stageN.action.failed` with the exception type.
* **Start and complete pairs** allow duration and record-count reconciliation.

A reference run produces 47 events across 12 stages.

---

## 6. Consent and opt-out

PECR requires a valid marketing consent before any campaign list leaves the
system. The gold table carries `marketing_eligible`, which currently reflects the
minor-exclusion rule. The consent flag itself lives in the CRM and is joined at
scoring time (Module 2 dependency D1); the export gate refuses any row without a
valid consent flag. **Status: wired, blocked on CRM extract.**

---

## 7. DPIA summary

| Risk | Likelihood | Impact | Control | Residual |
|---|---|---|---|---|
| Re-identification from quasi-identifiers | Medium | High | k-anonymity measured (k=1 full, k=7 at region+age); internal-only release under RBAC | Medium → **Low** for internal use |
| Identifier encodes region (RAID R2) | Certain | Medium | Salted SHA-256; Cramér's V 1.000 → 0.000 | **Closed** |
| Profiling a minor | Low | High | `is_minor` flag; excluded from `marketing_eligible` | **Closed** |
| Salt compromise | Low | Critical | Salt in environment/Key Vault, never committed; rotation requires re-key | Open — process control |
| Audit log itself sensitive | Low | Medium | No values logged; access limited to DPO/auditor roles | **Closed** |
| Over-retention of raw extract | Medium | Medium | Retention value in config; manual purge scheduled | Open — process control |

---

## 8. Incident response

1. **Detect** — failed PII scan, validation gate failure, or DPO review.
2. **Contain** — halt the DAG (`stop_after` parameter), revoke the salt, quarantine
   `data/processed/`.
3. **Assess** — use the audit log to determine which datasets were touched and how
   many records; UK GDPR breach notification window is 72 hours.
4. **Notify** — DPO → CRO → ICO if the threshold in Art. 33 is met.
5. **Remediate** — add the failing case as a unit test before the pipeline is
   re-enabled. Every incident becomes a regression test.

---

## 9. Audit cadence

| Activity | Frequency | Owner |
|---|---|---|
| Review `privacy_audit.log` anomalies | Monthly | DPO |
| Re-run bias suite and compare to thresholds | Monthly | ML Lead |
| Confirm retention deletions executed | Quarterly | Data Engineer |
| Re-validate lawful basis and DPIA | Annually or on scope change | DPO + CRO |
| Review granularity analysis if external release is proposed | Per release | DPO |

---

## 10. Known gaps

1. **Salt rotation** has no automated re-key procedure — downstream `customer_key`
   values would change, so rotation must be coordinated. Documented, not solved.
2. **Consent flags** are not yet joined (CRM dependency D1).
3. **Retention enforcement** is manual for the local deployment.
4. **k=1 at full granularity** means the gold table must not be released
   externally without generalisation to at least (region, age_band), per
   `artifacts/privacy_metrics.json`.
