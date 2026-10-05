"""Derives customers and monthly recurring revenue from Stripe subscriptions.

Approximations (documented in the UI): start/end months are counted in full,
usage-based prices are skipped, and non-monthly intervals are normalized.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.integrations.stripe_client import StripeClient
from app.models import Connection, CostEntry, Customer, Organization, RevenueEntry, SyncRun

INTERVAL_PER_MONTH = {"month": 1.0, "year": 1 / 12, "week": 4.345, "day": 30.44}
SKIPPED_STATUSES = {"incomplete", "incomplete_expired", "trialing"}


def _month(ts: int) -> date:
    moment = datetime.fromtimestamp(ts, tz=timezone.utc)
    return date(moment.year, moment.month, 1)


def _next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def month_span(start: date, end: date | None, today: date) -> list[date]:
    last = min(end or today, today)
    months = []
    cursor = start
    while cursor <= last and len(months) <= 600:
        months.append(cursor)
        cursor = _next_month(cursor)
    return months


def monthly_list_amount(subscription: dict) -> tuple[float, str]:
    """Pre-discount monthly amount and a plan label; usage-based items are skipped."""
    total = 0.0
    labels = []
    for item in (subscription.get("items") or {}).get("data") or []:
        price = item.get("price") or {}
        recurring = price.get("recurring") or {}
        unit = price.get("unit_amount")
        factor = INTERVAL_PER_MONTH.get(recurring.get("interval"))
        if unit is None or factor is None:
            continue
        interval_count = max(1, int(recurring.get("interval_count") or 1))
        quantity = int(item.get("quantity") or 1)
        total += (unit / 100) * quantity * factor / interval_count
        labels.append(price.get("nickname") or price.get("lookup_key") or price.get("id") or "Plan")
    return round(total, 4), (labels[0] if labels else "Plan")


def apply_discount(subscription: dict, list_monthly: float) -> float:
    coupon = ((subscription.get("discount") or {}).get("coupon")) or {}
    net = list_monthly
    if coupon.get("percent_off"):
        net = list_monthly * (1 - float(coupon["percent_off"]) / 100)
    elif coupon.get("amount_off"):
        net = list_monthly - float(coupon["amount_off"]) / 100
    return round(max(0.0, min(net, list_monthly)), 4)


def map_customer(org_id: int, raw: dict) -> Customer:
    metadata = raw.get("metadata") or {}
    return Customer(
        org_id=org_id,
        external_id=raw["id"],
        name=(raw.get("name") or raw.get("email") or raw["id"])[:200],
        segment=(metadata.get("segment") or "Unknown")[:60],
        region=(metadata.get("region") or "Unknown")[:60],
        industry=(metadata.get("industry") or "Unknown")[:60],
        channel=(metadata.get("channel") or "Unknown")[:60],
        signup_month=_month(raw["created"]) if raw.get("created") else None,
    )


def build_revenue_rows(subscriptions: list[dict], today: date) -> dict[tuple[str, date], dict]:
    """Aggregate per customer-month; the plan label follows the largest MRR contributor."""
    rows: dict[tuple[str, date], dict] = {}
    for subscription in subscriptions:
        if subscription.get("status") in SKIPPED_STATUSES:
            continue
        customer = subscription.get("customer")
        start_ts = subscription.get("start_date") or subscription.get("created")
        if not customer or not start_ts:
            continue
        customer_id = customer["id"] if isinstance(customer, dict) else customer
        list_monthly, plan = monthly_list_amount(subscription)
        if list_monthly <= 0:
            continue
        net_monthly = apply_discount(subscription, list_monthly)
        end_ts = subscription.get("ended_at") or subscription.get("canceled_at")
        for month in month_span(_month(start_ts), _month(end_ts) if end_ts else None, today):
            key = (customer_id, month)
            row = rows.setdefault(key, {"list_mrr": 0.0, "mrr": 0.0, "plan": plan, "plan_mrr": 0.0})
            row["list_mrr"] += list_monthly
            row["mrr"] += net_monthly
            if net_monthly > row["plan_mrr"]:
                row.update(plan=plan, plan_mrr=net_monthly)
    return rows


def sync_stripe(db: Session, org: Organization, client: StripeClient, today: date | None = None) -> dict:
    """Replace customers and revenue from Stripe; shared cost pools are preserved."""
    today = (today or date.today()).replace(day=1)
    raw_customers = client.list_all("/customers")
    subscriptions = client.list_all("/subscriptions", {"status": "all"})
    revenue_rows = build_revenue_rows(subscriptions, today)
    if not revenue_rows:
        raise ValueError("Stripe returned no billable subscriptions; nothing was imported.")
    active_customer_ids = {customer_id for customer_id, _ in revenue_rows}

    db.execute(delete(RevenueEntry).where(RevenueEntry.org_id == org.id))
    db.execute(delete(CostEntry).where(CostEntry.org_id == org.id, CostEntry.customer_id.is_not(None)))
    db.execute(delete(Customer).where(Customer.org_id == org.id))

    by_external = {raw["id"]: raw for raw in raw_customers}
    customers = [
        map_customer(org.id, by_external.get(external_id, {"id": external_id}))
        for external_id in sorted(active_customer_ids)
    ]
    db.add_all(customers)
    db.flush()
    id_map = {customer.external_id: customer.id for customer in customers}

    db.add_all(
        RevenueEntry(
            org_id=org.id,
            customer_id=id_map[external_id],
            month=month,
            plan=str(row["plan"])[:60],
            list_mrr=round(row["list_mrr"], 2),
            mrr=round(row["mrr"], 2),
        )
        for (external_id, month), row in revenue_rows.items()
    )
    months = sorted({month for _, month in revenue_rows})
    latest_mrr = sum(row["mrr"] for (_, month), row in revenue_rows.items() if month == months[-1])
    return {
        "customers": len(customers),
        "revenue_rows": len(revenue_rows),
        "first_month": months[0].strftime("%Y-%m"),
        "last_month": months[-1].strftime("%Y-%m"),
        "latest_mrr": round(latest_mrr, 2),
        "subscriptions_seen": len(subscriptions),
    }


def record_sync(db: Session, connection: Connection, status: str, stats: dict | None = None, error: str = "") -> SyncRun:
    run = SyncRun(
        org_id=connection.org_id,
        connection_id=connection.id,
        provider=connection.provider,
        status=status,
        stats=json.dumps(stats) if stats else "",
        error=error[:2000],
        finished_at=datetime.now(timezone.utc),
    )
    db.add(run)
    return run
