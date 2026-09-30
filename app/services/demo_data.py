"""Deterministic, fictional SaaS dataset for first-run exploration."""

from datetime import date
import calendar
import math
import random

import numpy as np
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import CostEntry, Customer, Organization, RevenueEntry

SEGMENTS = ["SMB", "Mid-Market", "Enterprise"]
REGIONS = ["North America", "Europe", "APAC"]
INDUSTRIES = ["Software", "Financial Services", "Manufacturing", "Healthcare", "Retail"]
PLANS = {"Starter": 249, "Growth": 799, "Scale": 2499, "Enterprise": 6999}


def _shift_month(month: date, offset: int) -> date:
    absolute = month.year * 12 + month.month - 1 + offset
    year, month_index = divmod(absolute, 12)
    day = min(month.day, calendar.monthrange(year, month_index + 1)[1])
    return date(year, month_index + 1, day)


def load_demo(db: Session, org: Organization, customer_count: int = 140, months: int = 30) -> None:
    """Replace this organization's data with realistic, synthetic MRR and cost history."""
    db.execute(delete(CostEntry).where(CostEntry.org_id == org.id))
    db.execute(delete(RevenueEntry).where(RevenueEntry.org_id == org.id))
    db.execute(delete(Customer).where(Customer.org_id == org.id))
    py_rng = random.Random(48291)
    rng = np.random.default_rng(48291)
    today = date.today().replace(day=1)
    if customer_count < 8 or months < 12:
        raise ValueError("Demo dataset requires at least 8 customers and 12 months")
    month_dates = [_shift_month(today, i - months + 1) for i in range(months)]

    customers = []
    revenue_rows = []
    customer_info = []
    for i in range(customer_count):
        start = py_rng.randint(0, min(months - 1, int(months * 0.78)))
        segment = py_rng.choices(SEGMENTS, weights=[0.55, 0.32, 0.13])[0]
        plan = py_rng.choices(list(PLANS), weights=[0.38, 0.34, 0.20, 0.08])[0]
        price = PLANS[plan] * py_rng.uniform(0.8, 1.2)
        name = f"{py_rng.choice(['Northstar', 'Summit', 'Atlas', 'Bright', 'Cedar', 'Vertex', 'Bluejay', 'Meridian', 'Orbit', 'Redwood'])} {py_rng.choice(['Labs', 'Systems', 'Group', 'Works', 'Partners', 'Digital'])} {i + 1:03d}"
        customer = Customer(
            org_id=org.id,
            external_id=f"CUST-{i + 1:04d}",
            name=name,
            segment=segment,
            region=py_rng.choice(REGIONS),
            industry=py_rng.choice(INDUSTRIES),
            channel=py_rng.choices(["Direct", "Partner", "Inbound"], weights=[0.48, 0.27, 0.25], k=1)[0],
            signup_month=month_dates[start],
        )
        customers.append(customer)
        customer_info.append((start, segment, plan, price))
    db.add_all(customers)
    db.flush()

    active = np.zeros(customer_count, dtype=bool)
    mrr = np.zeros(customer_count, dtype=float)
    for month_index, month in enumerate(month_dates):
        new_ids = []
        for i, customer in enumerate(customers):
            start, segment, plan, base_price = customer_info[i]
            if month_index < start:
                continue
            if month_index == start:
                active[i], mrr[i] = True, base_price
                new_ids.append(i)
                continue
            if not active[i]:
                continue
            churn_rate = {"SMB": 0.023, "Mid-Market": 0.012, "Enterprise": 0.006}[segment]
            if rng.random() < churn_rate:
                active[i], mrr[i] = False, 0.0
                continue
            monthly_growth = 0.004 + (0.004 if segment == "Enterprise" else 0.0)
            mrr[i] *= max(0.97, 1 + rng.normal(monthly_growth, 0.025))
            if rng.random() < 0.025:
                mrr[i] *= 1.15

        for i, customer in enumerate(customers):
            if not active[i]:
                continue
            list_price = mrr[i] * py_rng.uniform(1.02, 1.13)
            revenue_rows.append(
                RevenueEntry(
                    org_id=org.id,
                    customer_id=customer.id,
                    month=month,
                    plan=customer_info[i][2],
                    list_mrr=round(list_price, 2),
                    mrr=round(float(mrr[i]), 2),
                )
            )

        active_mrr = float(mrr.sum())
        if active_mrr <= 0:
            continue
        trend = 1 + 0.006 * month_index
        # Costs include shared pools and a small directly attributable sample.
        monthly_costs = {
            "hosting": (0.12 + 0.025 * math.sin(month_index / 4)) * active_mrr,
            "support": 0.055 * active_mrr,
            "third_party": 0.035 * active_mrr,
            "payment_fees": 0.024 * active_mrr,
            "sales": 0.22 * active_mrr * trend,
            "marketing": 0.17 * active_mrr * trend,
            "rnd": 0.19 * active_mrr,
            "gna": 0.13 * active_mrr,
        }
        for category, amount in monthly_costs.items():
            db.add(CostEntry(org_id=org.id, month=month, category=category, customer_id=None, amount=round(amount, 2)))

    db.add_all(revenue_rows)
    db.flush()
