# Data Anonymisation Plan

BAN6800 Module 3 · UK Bank Customer Data Pipeline
Owner: Data Protection Officer · Implemented in: `src/anonymisation.py`, `src/leakage.py`, `src/privacy_metrics.py`

---

## 1. PII inventory and treatment

| Field | Type | Present in raw | Treatment | Where | Residual risk |
|---|---|---|---|---|---|
| `Customer ID` | Indirect identifier | Yes | Salted SHA-256 → `customer_key`; raw value dropped | `anonymise()` | None — irreversible without the salt |
| `Name` | Direct identifier | Yes | **Deleted** before any transformation | `ingest()` | None |
| `Surname` | Direct identifier | Yes | **Deleted** before any transformation | `ingest()` | None |
| `Gender` | Protected characteristic | Yes | Retained for fairness monitoring only | — | Low — quasi-identifier |
| `Age` | Protected characteristic | Yes | Retained; banded for release | `transform()` | Low — quasi-identifier |
| `Region` | Geographic quasi-identifier | Yes | Retained; governed by the region dimension | — | Low — small NI sample |
| `Job Classification` | Socio-economic proxy | Yes | Retained; `Unknown` level for missing | `clean()` | Low |
| `Date Joined` | Temporal quasi-identifier | Yes | Retained; converted to tenure | `clean()` | Low |
| `Balance` | Financial data | Yes | Retained; banded for reporting | `transform()` | Low |

The supplied extract contains **no email, phone, address or postcode fields**. A
regex PII scanner still runs over every free-text column to prove that claim
rather than assert it.

---

## 2. Pseudonymisation method

```
customer_key = SHA-256( salt || ":" || customer_id )
```

* **Algorithm:** SHA-256 (`hashlib`), keyed by a salt held in `PIPELINE_HASH_SALT`.
* **Salt handling:** environment variable in development, Azure Key Vault in
  production. A documented development fallback keeps CI green; when it is used,
  the anonymisation report records `salt_source: dev-fallback (NOT PRODUCTION)`.
* **Determinism:** the same ID and salt always produce the same key, so joins
  across runs remain stable.
* **Rotation:** rotating the salt changes every key. Rotation is therefore a
  coordinated re-key of downstream systems, documented in
  `docs/data_governance.md` §10.
* **Surrogate business key:** `crm_ref` (e.g. `CUS-48213907`) is generated with
  Faker under a fixed seed. It is stable per run and contains no personal data,
  giving operational teams a human-quotable reference.

### Why the raw ID had to go — measured, not assumed

The first digit of `Customer ID` maps exactly to region:

| Prefix | Region | Records |
|---|---|---|
| 1 | England | 2,159 |
| 2 | Scotland | 1,124 |
| 3 | Wales | 520 |
| 4 | Northern Ireland | 211 |

Cramér's V between the leading character and region:

| State | Cramér's V | Verdict |
|---|---|---|
| Raw `Customer ID` prefix | **1.000** | CRITICAL — identifier fully determines region |
| Hashed `customer_key` prefix | **0.000** | CLEAN — no measurable association |

This was Module 2 RAID risk **R2** (and Module 1 risk ETH-01). It is now closed by
measurement, and `tests/test_anonymisation.py::test_anonymise_breaks_the_region_leak`
fails the build if the leak ever returns.

---

## 3. PII scanning

Two complementary controls run on every pipeline execution:

1. **Free-text regex scan** (`email`, `phone_uk`, `postcode`) over every object /
   string column, excluding the governed identifier columns. Reference run:
   **0 hits** across `gender`, `region`, `job_classification`, `date_joined_raw`.
2. **Structural identifier validation** on the columns the regex scan excludes:
   `customer_key` must be exactly 64 lowercase hex characters and unique;
   `crm_ref` must match `^CUS-\d{8}$`.

### A false positive worth recording

The first execution of the scanner returned **21 hits** — all inside
`customer_key`. A 64-character hex digest occasionally contains an eleven-digit
run that satisfies the UK mobile pattern. The fix was not to weaken the regex but
to scope the control: hashes are validated structurally, free text is scanned for
patterns. This is why the scan reports `columns_scanned` and `columns_excluded`
explicitly.

---

## 4. k-anonymity of the released table

Quasi-identifiers assessed: `region`, `age_band`, `gender`, `job_classification`.
Disclosure threshold: **k ≥ 5**.

| Release granularity | k | Equivalence classes | Records in classes < 5 | Share |
|---|---|---|---|---|
| region + age_band + gender + job_classification | **1** | 141 | 86 | 1.67% |
| region + age_band + gender | **3** | 40 | 9 | 0.14% |
| **region + age_band** | **7** | 20 | 0 | 0.00% |
| region only | **276** | 4 | 0 | 0.00% |

**Finding:** the gold table is **not** k-anonymous at full granularity. One
customer combination is unique.

**Decision:** the gold table is an *internal analytical product* under RBAC, not
an external release. Access control, not suppression, is the control for internal
use. If any extract were ever to leave the organisation, it must be released at
`region + age_band` (k=7) or coarser. That recommendation is generated
automatically into `artifacts/privacy_metrics.json` so it travels with the data.

**Why not suppress now:** suppressing the 86 at-risk records would remove 1.67%
of the population non-randomly (unusual age/job combinations), which would bias
the fairness audit — a privacy control that creates a fairness defect is not an
improvement.

---

## 5. Re-identification risk assessment

| Attack | Feasibility | Rationale |
|---|---|---|
| Name lookup in the released table | Impossible | Names deleted at ingestion |
| Direct ID reversal | Infeasible without the salt | SHA-256 preimage resistance; salt not in the repository |
| Region inference from the ID | Defeated | Cramér's V 0.000 (measured) |
| Home address inference | Not possible | No address field; `region` only |
| Mosaic attack via unique combination | **Possible** at full granularity | k=1; mitigated by RBAC and the granularity recommendation |
| Membership inference against Module 4 model | Out of scope here | Addressed in Module 4 fairness and privacy work |

---

## 6. Verification

| Control | Evidence | Test |
|---|---|---|
| Direct identifiers removed | `data/processed/*.csv` contain no `name`/`surname` | `test_ingestion.py` |
| Hashing irreversible | 64-hex digest, salted, salt-dependent | `test_anonymisation.py` |
| Region leak closed | Cramér's V 1.000 → 0.000 | `test_anonymise_breaks_the_region_leak` |
| No residual PII | Scanner returns 0 hits | `test_pii_scanner_accepts_a_clean_frame` |
| Scanner actually detects PII | Injected email / postcode is caught | `test_pii_scanner_catches_*` |
| Identifier shape enforced | Regex + uniqueness | `validate_identifiers()` |
| Audit trail complete | 47 JSON lines per run | `artifacts/privacy_audit.log` |

---

## 7. Residual risk statement

After the controls above, the remaining privacy risk is **inference from
quasi-identifier combinations within the organisation**, mitigated by role-based
access, internal-only release and a documented generalisation rule for any
external share. The salt remains the single point of failure for key reversal and
is managed outside the repository.
