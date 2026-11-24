# Sprint Backlog

Each sprint lasts two weeks. Ticket identifiers can be replaced with GitHub issue numbers after publication.

| Sprint | Ticket | Work item | Deliverable |
|---|---|---|---|
| 0 | S0-01 | Agree and sign off the operational churn definition | Churn label specification |
| 0 | S0-02 | Submit core-banking and CRM data-access requests | Approved data-access request |
| 0 | S0-03 | Complete LIA and submit DPIA | Governance gate pack |
| 0 | S0-04 | Initialize repository, environment, and documentation | Repository and `requirements.txt` |
| 1 | S1-01 | Build ingestion and schema-validation checks | `src/data_loader.py` and tests |
| 1 | S1-02 | Implement identifier hashing and direct-identifier removal | Privacy-safe ingestion control |
| 1 | S1-03 | Confirm the preliminary data dictionary | Approved data dictionary |
| 2 | S2-01 | Complete exploratory data-quality and representation analysis | EDA report |
| 2 | S2-02 | Build and review four customer personas | Segmentation model and persona cards |
| 2 | S2-03 | Validate clusters with silhouette scores and business review | Segmentation validation report |
| 3 | S3-01 | Create the governed churn training dataset | Labelled feature matrix |
| 3 | S3-02 | Train weighted XGBoost baseline | Churn model and evaluation report |
| 3 | S3-03 | Measure AUC and recall in the highest-risk decile | Model performance gate |
| 4 | S4-01 | Produce local and global SHAP explanations | Explainability report |
| 4 | S4-02 | Test demographic parity, equal opportunity, and calibration | Fairness audit |
| 4 | S4-03 | Complete the model card and ethics review | Approved model card |
| 5 | S5-01 | Implement rules-based next-action recommendations | Prescriptive rules module |
| 5 | S5-02 | Add human approval and consent gates | Approval and PECR controls |
| 5 | S5-03 | Define the scoring API and batch-export contract | API specification |
| 6 | S6-01 | Configure PSI, uptime, latency, and batch monitoring | Monitoring dashboard specification |
| 6 | S6-02 | Complete stakeholder UAT and adviser training | Signed UAT record |
| 6 | S6-03 | Complete release and governance review | Release decision and final gate pack |
