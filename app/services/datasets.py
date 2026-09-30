from dataclasses import dataclass

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CostEntry, Customer, RevenueEntry


@dataclass
class Dataset:
    customers: pd.DataFrame  # customer_id, external_id, name, segment, region, industry, channel, signup_month
    revenue: pd.DataFrame  # customer_id, month, plan, list_mrr, mrr
    costs: pd.DataFrame  # month, category, customer_id (nullable), amount

    @property
    def is_empty(self) -> bool:
        return self.revenue.empty


def _to_month(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.to_period("M").dt.to_timestamp().astype("datetime64[ns]")


def build_dataset(customers: pd.DataFrame, revenue: pd.DataFrame, costs: pd.DataFrame) -> Dataset:
    customers = customers.copy()
    revenue = revenue.copy()
    costs = costs.copy()
    customers["customer_id"] = customers["customer_id"].astype("int64")
    customers["signup_month"] = pd.to_datetime(customers["signup_month"])
    revenue["customer_id"] = revenue["customer_id"].astype("int64")
    revenue["month"] = _to_month(revenue["month"])
    revenue[["list_mrr", "mrr"]] = revenue[["list_mrr", "mrr"]].astype(float)
    costs["month"] = _to_month(costs["month"])
    costs["customer_id"] = costs["customer_id"].astype("Int64")
    costs["amount"] = costs["amount"].astype(float)
    return Dataset(customers=customers, revenue=revenue, costs=costs)


def load_dataset(db: Session, org_id: int) -> Dataset:
    conn = db.connection()
    customers = pd.read_sql(
        select(
            Customer.id.label("customer_id"),
            Customer.external_id,
            Customer.name,
            Customer.segment,
            Customer.region,
            Customer.industry,
            Customer.channel,
            Customer.signup_month,
        ).where(Customer.org_id == org_id),
        conn,
    )
    revenue = pd.read_sql(
        select(
            RevenueEntry.customer_id, RevenueEntry.month, RevenueEntry.plan, RevenueEntry.list_mrr, RevenueEntry.mrr
        ).where(RevenueEntry.org_id == org_id),
        conn,
    )
    costs = pd.read_sql(
        select(CostEntry.month, CostEntry.category, CostEntry.customer_id, CostEntry.amount).where(
            CostEntry.org_id == org_id
        ),
        conn,
    )
    return build_dataset(customers, revenue, costs)


def has_data(db: Session, org_id: int) -> bool:
    return db.scalar(select(RevenueEntry.id).where(RevenueEntry.org_id == org_id).limit(1)) is not None


def dataset_status(db: Session, org_id: int) -> dict:
    customers = db.scalar(select(func.count(Customer.id)).where(Customer.org_id == org_id)) or 0
    revenue_rows, first, last = db.execute(
        select(func.count(RevenueEntry.id), func.min(RevenueEntry.month), func.max(RevenueEntry.month)).where(
            RevenueEntry.org_id == org_id
        )
    ).one()
    cost_rows = db.scalar(select(func.count(CostEntry.id)).where(CostEntry.org_id == org_id)) or 0
    return {
        "customers": customers,
        "revenue_rows": revenue_rows or 0,
        "cost_rows": cost_rows,
        "first_month": first.strftime("%Y-%m") if first else None,
        "last_month": last.strftime("%Y-%m") if last else None,
    }
