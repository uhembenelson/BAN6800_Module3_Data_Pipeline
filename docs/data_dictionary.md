# Data Dictionary — v2 (Module 3)

Version 2 extends the Module 2 preliminary dictionary with the columns the
pipeline actually produces. Fields marked **derived** are generated in code and
their rule id can be traced in `docs/lineage.md`.

---

## 1. Source fields (P6 UK Bank Customer Profile Data)

| Field | Raw header | Type | Sensitivity | Pipeline treatment | Retained in gold |
|---|---|---|---|---|---|
| `customer_id` | `Customer ID` | String(9) | Indirect identifier — **encodes region** | Salted SHA-256 → `customer_key`, then dropped (AN-01) | No (replaced) |
| `name` | `Name` | String | **Direct identifier** | Deleted at ingestion (CQ-00) | No |
| `surname` | `Surname` | String | **Direct identifier** | Deleted at ingestion (CQ-00) | No |
| `gender` | `Gender` | Enum(Male, Female) | Protected characteristic | Domain-validated; fairness slicing only | Yes |
| `age` | `Age` | Integer | Protected characteristic | Range 16–100; median imputation (CQ-03/04) | Yes |
| `region` | `Region` | Enum(4 UK regions) | Geographic quasi-identifier | Domain-validated; joined to the region dimension | Yes |
| `job_classification` | `Job Classification` | Enum(White Collar, Blue Collar, Other) | Socio-economic proxy | `Unknown` level for nulls (CQ-08) | Yes |
| `date_joined` | `Date Joined` | Date (`dd.Mon.yy`) | Temporal quasi-identifier | Parsed; unparseable rows dropped (CQ-10) | Yes (as date) |
| `balance` | `Balance` | Decimal(2dp) | Financial data | Positivity check, median imputation, IQR flag (CQ-05/06/07) | Yes |

Source characteristics measured on the raw extract:

- 4,014 records × 9 fields, no missing values, no duplicate IDs.
- Regions: England 53.8%, Scotland 28.0%, Wales 13.0%, Northern Ireland 5.3%.
- Gender: Male 53.9%, Female 46.1%. Job: White Collar 48.7%, Blue Collar 26.1%, Other 25.2%.
- Age 15–64 (mean 38.6); five records below 18.
- All records joined during 2015 (05.Jan.15 – 30.Dec.15).

---

## 2. Derived fields (gold table)

| Column | Type | Rule | Definition | Governance note |
|---|---|---|---|---|
| `customer_key` | String(64) | AN-01 | `SHA-256(salt ‖ ":" ‖ customer_id)` | Salt in Key Vault; never committed |
| `crm_ref` | String(12) | AN-02 | Faker surrogate `CUS-########` | Contains no personal data |
| `age_band` | Enum | TR-03 | 16–24, 25–34, 35–44, 45–54, 55–64, 65+ | Fairness slicing only, never an offer input |
| `region_code` | String(9) | IN-01 | ONS code from `region_dimension.csv` | Never derived from the ID prefix |
| `tenure_days` | Integer | TR-01 | `snapshot_date − date_joined`, floored at 0 | — |
| `tenure_months` | Decimal(1dp) | TR-02 | `tenure_days / 30.44` | — |
| `balance_band` | Enum | TR-04 | Low <15k, Mid 15–45k, High 45–90k, Premium ≥90k | — |
| `is_minor` | Boolean | CQ-11 | `age < 18` | Drives marketing exclusion |
| `marketing_eligible` | Boolean | TR-06 | `not is_minor` (consent flag pending CRM) | Export gate |
| `high_value_flag` | Boolean | TR-05 | `balance ≥ 75th percentile` (56,652.82 on this run) | Selection decision audited for bias |
| `churn_label` | Boolean (nullable) | TR-08 | **Placeholder** — no closure data supplied | Awaiting signed-off definition (Module 2 I2) |
| `snapshot_date` | Date | TR-01 | `2015-12-31` from configuration | — |
| `age_imputed` | Boolean | CQ-04 | Age was missing or invalid and was imputed | Quality transparency |
| `balance_imputed` | Boolean | CQ-06 | Balance was missing or non-positive and was imputed | Quality transparency |
| `balance_outlier` | Boolean | CQ-07 | Balance above the IQR fence (116,687) | Flagged, not removed |
| `region_population_share` | Decimal(4dp) | IN-01 | Real ONS share for the region | Context for the fairness read |
| `min_group_size_ok` | Boolean | IN-02 | Measured cohort size ≥ 100 | RAID R1 control |
| `recommended_product_family` | String | IN-03 | Rules mapping (`balance_band` × `job_classification`) | Advisory only |
| `human_approval_required` | Boolean | IN-03 | Always `True` | UK GDPR Art. 22 control |

---

## 3. Quality flags carried into the gold table

The gold table is deliberately **not** silently clean. Three boolean columns keep
the repair history visible so Module 4 can choose how to treat repaired records:

| Flag | Records on the reference run | Meaning |
|---|---|---|
| `age_imputed` | 162 | Age was missing or impossible |
| `balance_imputed` | 108 | Balance was missing or non-positive |
| `balance_outlier` | 97 | Balance above the IQR fence, retained |
| `is_minor` | 5 | Under 18; excluded from campaign exports |

---

## 4. Data-quality expectations per field

| Field | Expectation | Level |
|---|---|---|
| `customer_key` | Not null, unique, 64 hex characters | Blocking |
| `age` | Not null, 16 ≤ age ≤ 100 | Blocking |
| `balance` | Not null, 0 ≤ balance ≤ 250,000 | Blocking |
| `gender` | In {Male, Female} | Blocking |
| `region` | In the four contracted regions | Blocking |
| `job_classification` | In {Blue Collar, White Collar, Other, Unknown} | Blocking |
| `date_joined` | Not null | Blocking |
| `churn_label` | May be null — **not asserted** | Intentional |

---

## 5. Planned source extensions (still outstanding)

| Field | Source | Status |
|---|---|---|
| `transaction_history` | Core banking | Blocked — access request D1 |
| `product_holdings` | Core banking | Blocked — access request D1 |
| `account_closure_date` | Core banking | Blocked — churn definition I2 |
| `consent_marketing` | CRM | Blocked — CRM extract |
| `call_note` | Contact centre | Blocked — redaction process required |
