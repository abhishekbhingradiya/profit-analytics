"""Validate all CSV inputs before replacing tenant data in one transaction."""

from __future__ import annotations

from datetime import date
import io
import re

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import CostEntry, Customer, Organization, RevenueEntry

EXPECTED = {
    "customers": {"external_id", "name", "segment", "region", "industry", "channel", "signup_month"},
    "revenue": {"external_id", "month", "plan", "list_mrr", "mrr"},
    "costs": {"month", "category", "external_id", "amount"},
}
DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
ALLOWED_CATEGORIES = {"hosting", "support", "third_party", "payment_fees", "sales", "marketing", "rnd", "gna"}


class ImportValidationError(ValueError):
    pass


def _parse_csv(content: bytes, name: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except Exception as exc:
        raise ImportValidationError(f"Could not read {name}: {exc}") from exc
    if len(df) > 1_000_000:
        raise ImportValidationError(f"{name} has more than 1,000,000 rows")
    missing = EXPECTED[name] - set(df.columns)
    if missing:
        raise ImportValidationError(f"{name}.csv missing columns: {', '.join(sorted(missing))}")
    if df.empty:
        raise ImportValidationError(f"{name}.csv must contain at least one row")
    return df


def _date(value: str, field: str, row: int) -> date:
    if not DATE_RE.fullmatch(value.strip()):
        raise ImportValidationError(f"{field}, row {row}: use YYYY-MM or YYYY-MM-DD")
    try:
        parts = value.strip().split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) == 3 else 1)
    except ValueError as exc:
        raise ImportValidationError(f"{field}, row {row}: invalid date") from exc


def _number(value: str, field: str, row: int) -> float:
    try:
        result = float(value.strip().replace(",", ""))
    except ValueError as exc:
        raise ImportValidationError(f"{field}, row {row}: must be numeric") from exc
    if not pd.notna(result) or result < 0 or result > 1e12:
        raise ImportValidationError(f"{field}, row {row}: must be between 0 and 1,000,000,000,000")
    return result


def validate_uploads(customers_bytes: bytes, revenue_bytes: bytes, costs_bytes: bytes) -> dict:
    frames = {
        "customers": _parse_csv(customers_bytes, "customers"),
        "revenue": _parse_csv(revenue_bytes, "revenue"),
        "costs": _parse_csv(costs_bytes, "costs"),
    }
    c, r, k = frames["customers"], frames["revenue"], frames["costs"]

    if c["external_id"].str.strip().eq("").any() or c["name"].str.strip().eq("").any():
        raise ImportValidationError("customers.csv requires non-empty external_id and name")
    if c["external_id"].duplicated().any():
        raise ImportValidationError("customers.csv contains duplicate external_id values")
    customer_ids = set(c["external_id"].str.strip())
    for column in ("segment", "region", "industry", "channel"):
        c[column] = c[column].str.strip().replace("", "Unknown")
    c["external_id"] = c["external_id"].str.strip()
    c["name"] = c["name"].str.strip()
    c["signup_month"] = [_date(v, "signup_month", i) if v.strip() else None for i, v in enumerate(c.signup_month, 2)]

    if not r["external_id"].str.strip().isin(customer_ids).all():
        row = int((~r["external_id"].str.strip().isin(customer_ids)).to_numpy().argmax()) + 2
        raise ImportValidationError(f"revenue.csv row {row}: external_id not found in customers.csv")
    if r["plan"].str.strip().eq("").any():
        raise ImportValidationError("revenue.csv requires a plan for each row")
    r["external_id"] = r["external_id"].str.strip()
    r["plan"] = r["plan"].str.strip()
    r["month"] = [_date(v, "month", i) for i, v in enumerate(r.month, 2)]
    for col in ("mrr", "list_mrr"):
        r[col] = [_number(v, col, i) for i, v in enumerate(r[col], 2)]
    if (r["list_mrr"] < r["mrr"]).any():
        raise ImportValidationError("list_mrr cannot be less than mrr")
    if r.duplicated(["external_id", "month"]).any():
        raise ImportValidationError("revenue.csv has duplicate external_id/month pairs")

    k["month"] = [_date(v, "month", i) for i, v in enumerate(k.month, 2)]
    k["category"] = k["category"].str.strip().str.lower()
    if not k["category"].isin(ALLOWED_CATEGORIES).all():
        invalid = sorted(set(k.loc[~k["category"].isin(ALLOWED_CATEGORIES), "category"]))
        raise ImportValidationError("Unknown cost category: " + ", ".join(invalid))
    k["external_id"] = k["external_id"].str.strip()
    unknown = (k["external_id"] != "") & ~k["external_id"].isin(customer_ids)
    if unknown.any():
        row = int(unknown.to_numpy().argmax()) + 2
        raise ImportValidationError(f"costs.csv row {row}: external_id not found in customers.csv")
    k["amount"] = [_number(v, "amount", i) for i, v in enumerate(k.amount, 2)]
    return frames


def replace_tenant_data(db: Session, org: Organization, frames: dict) -> dict:
    """Call inside a request transaction; all parsing and validation must happen first."""
    db.execute(delete(CostEntry).where(CostEntry.org_id == org.id))
    db.execute(delete(RevenueEntry).where(RevenueEntry.org_id == org.id))
    db.execute(delete(Customer).where(Customer.org_id == org.id))
    customers_df = frames["customers"]
    customers = [
        Customer(
            org_id=org.id,
            external_id=row.external_id,
            name=row.name,
            segment=row.segment,
            region=row.region,
            industry=row.industry,
            channel=row.channel,
            signup_month=row.signup_month,
        )
        for row in customers_df.itertuples(index=False)
    ]
    db.add_all(customers)
    db.flush()
    id_map = {c.external_id: c.id for c in customers}
    rev = frames["revenue"]
    db.add_all(
        [
            RevenueEntry(
                org_id=org.id,
                customer_id=id_map[row.external_id],
                month=row.month,
                plan=row.plan,
                list_mrr=row.list_mrr,
                mrr=row.mrr,
            )
            for row in rev.itertuples(index=False)
        ]
    )
    costs = frames["costs"]
    db.add_all(
        [
            CostEntry(
                org_id=org.id,
                month=row.month,
                category=row.category,
                customer_id=id_map.get(row.external_id) if row.external_id else None,
                amount=row.amount,
            )
            for row in costs.itertuples(index=False)
        ]
    )
    return {"customers": len(customers), "revenue_rows": len(rev), "cost_rows": len(costs)}
