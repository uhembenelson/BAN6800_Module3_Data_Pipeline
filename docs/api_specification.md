# Preliminary Scoring API Specification

The scoring interface is planned for Sprint 5 and remains subject to data-governance approval.

## Request

- Pseudonymous customer identifier
- Approved engineered features
- Consent status

## Response

- Churn propensity score from 0 to 1
- Low, medium, or high risk band
- Three leading SHAP drivers
- Recommended next action
- Human-approval-required flag

## Non-functional targets

- API latency below 200 ms under the agreed test load
- 99.9% service availability target
- Batch scoring of 50,000 records within 30 minutes
- No automated customer offer without human approval
