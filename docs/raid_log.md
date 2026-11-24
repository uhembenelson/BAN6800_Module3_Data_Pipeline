# Technical RAID Log

| ID | Type | Item | Mitigation or action | Owner |
|---|---|---|---|---|
| R1 | Risk | Northern Ireland has too few records for stable fairness estimates | Use confidence intervals and a minimum group-size rule | ML Lead |
| R2 | Risk | Customer ID prefixes may expose geography | Salted hashing and automated proxy tests | Data Engineer |
| R3 | Risk | Interest-rate changes may cause model drift | Monthly PSI review and governed retraining trigger | MLOps Lead |
| R4 | Risk | Advisers may over-rely on model scores | Human-in-the-loop training and advisory-only scores | Business Analyst |
| A1 | Assumption | Core banking can supply 24 months of transactions and closures | Confirm availability in Sprint 0 | Tech Lead |
| A2 | Assumption | Job classification is a usable income proxy | Validate in EDA and Gate 1 review | Lead Data Scientist |
| I1 | Issue | P6 data lacks salary | Request salary bands and validate any proxy | Lead Data Scientist |
| I2 | Issue | P6 data lacks a churn label | Sign off a standard label in Sprint 1 | Sponsor and CRO |
| D1 | Dependency | Core-banking extracts are required for prediction | Submit access request in Sprint 0 | Tech Lead |
| D2 | Dependency | DPIA approval is required before personal data enters Azure | Start DPIA in Sprint 0 | DPO |
