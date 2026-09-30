# MarginIQ

An AI-ready profit intelligence foundation for SaaS finance teams. MarginIQ brings monthly recurring revenue, customer attributes and cost-to-serve into one model, then explains margin movements and lets teams test operating assumptions.

> This is an early-stage MVP, not a production-certified enterprise platform. Use synthetic or approved non-sensitive data until your deployment passes security, privacy, legal and finance review. AI answers currently use deterministic intent routing; no external LLM is connected.

## What is included

- First-run workspace and administrator setup, signed sessions, scrypt password hashes, CSRF protection, role checks and a tenant-scoped audit log.
- Fictional SaaS sample data (140 accounts, 30 months) and transactional import of three validated CSV files.
- Executive overview, monthly P&L, MRR movement bridge, NRR/GRR, quarterly cohort retention, customer and segment profitability, allocated shared COGS, CAC/LTV/payback, forecast, scenario comparison, anomaly/leakage signals and a constrained data-grounded copilot.
- Responsive server-rendered interface and interactive ECharts visualizations.
- FastAPI JSON endpoints under `/api`.

## Quick start (Windows PowerShell)

Python 3.11+ is recommended. From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set the generated value as `SECRET_KEY` in `.env`. For a local run, keep `APP_ENV=development`; SQLite is created under `data/` automatically.

```powershell
python -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. The first visit opens workspace setup; choose the sample-data option to populate the dashboard. Run checks with:

```powershell
python -m pytest
```

For a production deployment, set `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`, and `SECURE_COOKIES=true` behind HTTPS. SQLite is intended for local evaluation only. PostgreSQL can be used with an appropriate SQLAlchemy driver, for example `postgresql+psycopg://...` plus `psycopg[binary]` in the deployment dependency set. The current implementation has no migrations; use Alembic before evolving production schemas.

## Local architecture

```text
Browser (Jinja + ECharts)
        | same-origin session + CSRF
FastAPI pages and JSON APIs
        | organization-scoped SQLAlchemy queries
SQLite (local) / PostgreSQL (deployment target)
        | pandas analytical model
MRR bridge, P&L, margin, unit economics, forecast, anomaly signals
```

- `app/models.py`: organization, member, customer, monthly revenue, cost and audit records.
- `app/services/metrics.py`: canonical metric calculations.
- `app/services/insights.py`, `forecast.py`, `anomalies.py`, `scenario.py`: analysis services.
- `app/services/csv_import.py`: validation before replacing tenant data in the request transaction.
- `app/routers/`: setup/auth, pages, workspace data, member management and JSON API.
- `app/templates/` and `app/static/`: rendered application UI.

## Data contract

Upload the sample templates from Data workspace. Every file is UTF-8 CSV; dates are `YYYY-MM` or `YYYY-MM-DD`; monetary values are non-negative USD.

`customers.csv`: `external_id,name,segment,region,industry,channel,signup_month`

`revenue.csv`: `external_id,month,plan,list_mrr,mrr`

`costs.csv`: `month,category,external_id,amount`

Allowed cost categories are `hosting`, `support`, `third_party`, `payment_fees`, `sales`, `marketing`, `rnd`, and `gna`. A blank cost `external_id` means shared/unattributed cost. Each customer/month pair in revenue must be unique. Import validates all three inputs before deleting existing organization records; the database transaction rolls back on a failed write.

## Metric definitions and caveats

| Metric | Current MVP definition |
|---|---|
| MRR / ARR | Latest observed monthly recurring revenue; ARR is latest MRR × 12, not recognized revenue. |
| Gross profit / margin | MRR less hosting, support, third-party and payment-fee costs. Shared COGS is allocated by revenue for customer/segment views. |
| MRR bridge | New, expansion, reactivation, contraction and churn based on customer-month MRR. First observed month is excluded from movement comparisons. |
| NRR / GRR | Fixed customers with MRR at both period endpoints; current MRR divided by baseline MRR. GRR caps customer-level expansion at baseline. |
| Cohort retention | First observed active quarter; cohort MRR relative to its observed starting MRR. Cohorts already active in the first dataset month are excluded. |
| CAC | Trailing six-month sales and marketing cost allocated by share of new MRR, divided by observed new logos. |
| LTV / payback | ARPA × gross margin ÷ observed monthly logo churn; CAC divided by monthly gross profit per active account. Directional estimates only. |
| Forecast | Damped Holt trend with grid-selected smoothing parameters; COGS and OpEx are forecast independently. Three-month holdout MAPE is shown when available. |
| Anomalies | Robust median-absolute-deviation outliers on month-over-month changes; account alerts identify negative gross profit and high discounts. Signals require human review. |
| Scenarios | Trailing six-month driver rates projected forward. Price, churn, new-business and cost assumptions are independent; no price elasticity is learned. |

These are explicit MVP policies, not universal accounting conventions. Finance should approve the chart of accounts, revenue recognition basis, capitalization treatment, cost allocation rules, currency conversion and cohort definitions before decisions rely on the results.

## Roles

- **Viewer:** read dashboards and analysis.
- **Analyst:** viewer access plus run scenarios.
- **Admin:** analyst access plus import/replace data and manage members.

All active organization members can currently see the entire workspace dataset. Row-level access, SSO/SAML, SCIM, managed secrets, centralized rate limits, retention policies and admin recovery are not implemented.

## API overview

Authenticated read endpoints include `/api/kpis`, `/api/pnl`, `/api/mrr-bridge`, `/api/profitability`, `/api/customers`, `/api/retention`, `/api/unit-economics`, `/api/forecast`, `/api/anomalies` and `/api/insights`. `POST /api/scenarios` and `POST /api/copilot` require the session CSRF token in `X-CSRF-Token`. Interactive API docs are available at `/docs` in development only.

## Full product development scope

### Phase 0: customer and finance discovery

Interview CFOs, controllers, FP&A leaders and SaaS operators. Select an ICP, define a canonical financial metric dictionary with a finance partner, map source-system fields, identify decision workflows and recruit design partners. Exit with validated workflows, security boundaries, data contracts, acceptance criteria and a clickable prototype.

### Phase 1: trustworthy SaaS analytics MVP

This repository is the starting point: CSV ingestion, core SaaS P&L and unit economics, deterministic explanations, baseline forecast, what-if scenarios, basic anomaly detection, multi-user workspace and an executive dashboard. Pilot with synthetic/approved data and reconcile results against a finance-owned spreadsheet before expanding integrations.

### Phase 2: governed data integrations

Add a durable ingestion job system, idempotent imports and lineage; begin with one accounting/billing connector and CRM, then add warehouse-native/Snowflake, BigQuery or Databricks connectivity. Build mapping and reconciliation workflows, currencies, fiscal calendars, historical snapshots, data quality tests, freshness status and reversible backfills. Adopt Alembic migrations and an analytics warehouse when workload warrants it.

### Phase 3: enterprise trust and collaboration

Implement SSO/SAML and SCIM, row-level and entity-level access policies, tenant-isolation tests, secrets management, encryption/key rotation, audit exports, backup/restore drills, retention/deletion controls, observability, reliability targets and incident response. Complete threat modeling, penetration testing, privacy review and SOC 2 readiness before enterprise commitments.

### Phase 4: intelligence layer

Connect a contracted enterprise LLM only after the metric semantic layer and permission policy exist. Use tool-based, read-only metric queries with allowlisted operations, schema-aware validation, query/time limits, citations to source records and explicit uncertainty. Keep financial arithmetic in audited deterministic code; evaluate answer correctness against a finance-authored benchmark. Add scenario optimization only with causal/elasticity evidence and approval workflows.

### Phase 5: vertical products and action loops

Develop industry-specific cost models for SaaS, manufacturing, retail and logistics; add pricing realization, renewal risk, customer cost-to-serve, cloud FinOps and carbon-adjusted margin where validated. Track recommendation adoption and realized outcomes; provide controlled integrations into CRM/CPQ/ERP with human approval and rollback.

## Near-term engineering backlog

1. Add Alembic migration baseline and an automated tenant-isolation test suite.
2. Add true sales pipeline and CRM attribution for new-logo CAC, plus contractual ARR and churn reasons.
3. Define fiscal calendar, timezone, currency and revenue-recognition policies; support corrections and late-arriving records.
4. Add background ingestion, job status, import preview/reconciliation and downloadable error reports.
5. Add saved filters, customer drill-through, PDF/CSV exports and alert delivery with user-defined thresholds.
6. Replace in-memory login throttling with a shared store before multi-worker production; configure backups and restore tests.
7. Add frontend/browser accessibility and visual regression tests at desktop and mobile widths.
8. Add a permissioned LLM adapter only after deterministic metrics, evaluation tests and enterprise data handling are agreed.
