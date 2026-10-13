# VendorLens

Multi-tenant sales analytics for vendors: products, the customers who buy them, billing with payment deadlines, and forecasts — with **one isolated database per vendor**.

> Early-stage MVP. Use synthetic or approved non-sensitive data until your deployment passes security, privacy and backup review.

## What it does

- **Products**: add products with your own manually chosen product IDs; search across the whole catalog; the highest-selling product always leads the dashboard.
- **Customers under products**: expand any product to see every customer who bought it, best buyer first; a full customer ranking shows the highest and lowest buyers.
- **Entry forms**: record products, sales and payments from the UI; lists and rankings update on submit.
- **Billing**: per-sale payment status — received (how much), outstanding (how much and due when), partial, and overdue with days crossed.
- **Daily notifications**: generated once per day per vendor — payment completed, deadline approaching (3 days), deadline crossed.
- **Analytics**: revenue billed vs cash received bucketed by week, month, year or decade, filterable per product.
- **Forecasting**: monthly revenue prediction (damped Holt trend, 95% interval) that deliberately stays **locked until one month of sales history** exists.

## Architecture: database per vendor

```text
Control plane DB (vendors, users, audit, encrypted tenant DSNs)
        │
        ├── vendor 1 → own database (products, customers, sales, notifications)
        ├── vendor 2 → own database
        └── ...
```

- `DATABASE_URL` points at the hosted control-plane database.
- `TENANT_DATABASE_URL_TEMPLATE` (e.g. `postgresql+psycopg://user:pass@host/sales_{tenant}`) defines where each vendor's database lives; it is formatted per vendor and stored **encrypted** in the control plane.
- Production refuses to start with SQLite or without the tenant template; development falls back to one SQLite file per vendor under `data/tenants/`.
- Sessions are signed cookies; passwords use salted scrypt; all state-changing routes are CSRF-protected; roles: viewer / analyst (record sales & payments) / admin (manage team).

## Quick start (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env   # set SECRET_KEY
python -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>, create a vendor account, and keep the sample-data option checked to explore. Run tests with `python -m pytest`.

For hosted deployment set `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL` (managed Postgres), `TENANT_DATABASE_URL_TEMPLATE`, `ALLOWED_HOSTS` and `SECURE_COOKIES=true` behind HTTPS. Provision database credentials with least privilege: the app only needs schema-create on first tenant touch. There are no migrations yet — adopt Alembic before changing production schemas.

## Code map

- [app/models.py](app/models.py) — control plane: vendors, users, audit.
- [app/tenant_models.py](app/tenant_models.py) — per-vendor schema: products, customers, sales, notifications.
- [app/tenancy.py](app/tenancy.py) — DSN provisioning, engine cache, per-request tenant session.
- [app/services/sales_analytics.py](app/services/sales_analytics.py) — leaderboards, rankings, time buckets, payment book, gated forecast.
- [app/services/notifications.py](app/services/notifications.py) — daily payment notices.
- [app/routers/](app/routers) — auth/signup, pages, entry forms, JSON API.

## Known limits (deliberate for the MVP)

- Daily notifications are generated on first visit of the day; add a scheduler/worker for true background delivery (and email/SMS channels).
- The forecast is a trend baseline without seasonality or promotions.
- No OAuth/SSO, no migrations, no automated backups — required before production.
