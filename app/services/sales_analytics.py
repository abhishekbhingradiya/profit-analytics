"""Core analytics for products, customers, payments and sales forecasting."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.tenant_models import Customer, Product, Sale

GRANULARITIES = ("week", "month", "year", "decade")
FORECAST_MIN_HISTORY_DAYS = 30


def load_sales(db: Session) -> pd.DataFrame:
    rows = db.execute(
        select(
            Sale.id.label("sale_id"),
            Sale.product_id,
            Sale.customer_id,
            Sale.quantity,
            Sale.total_amount,
            Sale.amount_paid,
            Sale.sale_date,
            Sale.due_date,
            Sale.paid_on,
            Product.product_code,
            Product.name.label("product_name"),
            Product.category,
            Customer.name.label("customer_name"),
            Customer.email.label("customer_email"),
            Customer.company,
        )
        .join(Product, Product.id == Sale.product_id)
        .join(Customer, Customer.id == Sale.customer_id)
    ).all()
    df = pd.DataFrame(rows, columns=[
        "sale_id", "product_id", "customer_id", "quantity", "total_amount", "amount_paid",
        "sale_date", "due_date", "paid_on", "product_code", "product_name", "category",
        "customer_name", "customer_email", "company",
    ])
    if not df.empty:
        df["sale_date"] = pd.to_datetime(df["sale_date"])
        df["outstanding"] = (df["total_amount"] - df["amount_paid"]).clip(lower=0).round(2)
    return df


def overview(df: pd.DataFrame, product_count: int, today: date) -> dict:
    if df.empty:
        return {
            "total_revenue": 0, "received": 0, "outstanding": 0, "overdue": 0,
            "sales": 0, "products": product_count, "customers": 0, "avg_order_value": None,
            "last_sale": None,
        }
    overdue = df[(df["outstanding"] > 0) & df["due_date"].notna() & (pd.to_datetime(df["due_date"]) < pd.Timestamp(today))]
    return {
        "total_revenue": float(df["total_amount"].sum()),
        "received": float(df["amount_paid"].sum()),
        "outstanding": float(df["outstanding"].sum()),
        "overdue": float(overdue["outstanding"].sum()),
        "sales": int(len(df)),
        "products": product_count,
        "customers": int(df["customer_id"].nunique()),
        "avg_order_value": float(df["total_amount"].mean()),
        "last_sale": df["sale_date"].max().date().isoformat(),
    }


def product_leaderboard(df: pd.DataFrame, query: str = "") -> list[dict]:
    """Highest-revenue products first; `query` filters by code, name or category."""
    if df.empty:
        return []
    g = (
        df.groupby(["product_id", "product_code", "product_name", "category"], as_index=False)
        .agg(
            revenue=("total_amount", "sum"),
            units=("quantity", "sum"),
            orders=("sale_id", "count"),
            customers=("customer_id", "nunique"),
            received=("amount_paid", "sum"),
            outstanding=("outstanding", "sum"),
            last_sold=("sale_date", "max"),
        )
        .sort_values(["revenue", "units"], ascending=False)
    )
    if query:
        needle = query.strip().casefold()
        mask = (
            g["product_code"].str.casefold().str.contains(needle, regex=False)
            | g["product_name"].str.casefold().str.contains(needle, regex=False)
            | g["category"].str.casefold().str.contains(needle, regex=False)
        )
        g = g[mask]
    g["last_sold"] = g["last_sold"].dt.strftime("%Y-%m-%d")
    g["share"] = (g["revenue"] / df["total_amount"].sum()).round(4)
    return g.round(2).to_dict(orient="records")


def product_customers(df: pd.DataFrame, product_id: int) -> list[dict]:
    """Every customer who bought the product, best buyer first."""
    sub = df[df["product_id"] == product_id]
    if sub.empty:
        return []
    g = (
        sub.groupby(["customer_id", "customer_name", "customer_email", "company"], as_index=False)
        .agg(
            revenue=("total_amount", "sum"),
            units=("quantity", "sum"),
            orders=("sale_id", "count"),
            received=("amount_paid", "sum"),
            outstanding=("outstanding", "sum"),
            last_purchase=("sale_date", "max"),
        )
        .sort_values("revenue", ascending=False)
    )
    g["last_purchase"] = g["last_purchase"].dt.strftime("%Y-%m-%d")
    return g.round(2).to_dict(orient="records")


def customer_rankings(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"customers": [], "highest": None, "lowest": None}
    g = (
        df.groupby(["customer_id", "customer_name", "customer_email", "company"], as_index=False)
        .agg(
            revenue=("total_amount", "sum"),
            orders=("sale_id", "count"),
            units=("quantity", "sum"),
            received=("amount_paid", "sum"),
            outstanding=("outstanding", "sum"),
            products=("product_id", "nunique"),
            last_purchase=("sale_date", "max"),
        )
        .sort_values("revenue", ascending=False)
    )
    g["last_purchase"] = g["last_purchase"].dt.strftime("%Y-%m-%d")
    records = g.round(2).to_dict(orient="records")
    return {"customers": records, "highest": records[0], "lowest": records[-1]}


def _bucket_labels(dates: pd.Series, granularity: str) -> pd.Series:
    if granularity == "week":
        starts = dates.dt.to_period("W-SUN").dt.start_time
        return starts.dt.strftime("Wk of %d %b %Y")
    if granularity == "month":
        return dates.dt.strftime("%b %Y")
    if granularity == "year":
        return dates.dt.strftime("%Y")
    if granularity == "decade":
        return ((dates.dt.year // 10) * 10).astype(str) + "s"
    raise ValueError(f"Unsupported granularity: {granularity}")


def sales_series(df: pd.DataFrame, granularity: str = "month", product_id: int | None = None) -> list[dict]:
    """Revenue and cash received per period, from weekly up to per-decade buckets."""
    if granularity not in GRANULARITIES:
        raise ValueError(f"Unsupported granularity: {granularity}")
    if product_id is not None:
        df = df[df["product_id"] == product_id]
    if df.empty:
        return []
    work = df.copy()
    work["bucket"] = _bucket_labels(work["sale_date"], granularity)
    work["order_key"] = work["sale_date"]
    g = (
        work.groupby("bucket", as_index=False)
        .agg(revenue=("total_amount", "sum"), received=("amount_paid", "sum"), orders=("sale_id", "count"), first=("order_key", "min"))
        .sort_values("first")
        .drop(columns="first")
    )
    return g.round(2).to_dict(orient="records")


def payment_book(df: pd.DataFrame, today: date) -> dict:
    """Received vs outstanding, plus per-sale status with deadline aging."""
    if df.empty:
        return {"received": 0, "outstanding": 0, "overdue": 0, "rows": []}
    work = df.copy()
    due = pd.to_datetime(work["due_date"])
    is_paid = work["outstanding"] <= 0.005
    is_overdue = ~is_paid & due.notna() & (due < pd.Timestamp(today))
    work["status"] = np.select(
        [is_paid, is_overdue, work["amount_paid"] > 0],
        ["paid", "overdue", "partial"],
        default="unpaid",
    )
    work["days_overdue"] = np.where(is_overdue, (pd.Timestamp(today) - due).dt.days, 0)
    rows = work.sort_values(["status", "days_overdue"], ascending=[True, False])[
        ["sale_id", "product_code", "product_name", "customer_name", "total_amount",
         "amount_paid", "outstanding", "sale_date", "due_date", "paid_on", "status", "days_overdue"]
    ].copy()
    rows["sale_date"] = rows["sale_date"].dt.strftime("%Y-%m-%d")
    rows["due_date"] = pd.to_datetime(rows["due_date"]).dt.strftime("%Y-%m-%d")
    rows["paid_on"] = pd.to_datetime(rows["paid_on"]).dt.strftime("%Y-%m-%d")
    rows = rows.replace({np.nan: None, "NaT": None})
    status_order = {"overdue": 0, "partial": 1, "unpaid": 2, "paid": 3}
    records = sorted(rows.to_dict(orient="records"), key=lambda r: (status_order[r["status"]], -(r["days_overdue"] or 0)))
    return {
        "received": float(work["amount_paid"].sum()),
        "outstanding": float(work["outstanding"].sum()),
        "overdue": float(work.loc[is_overdue, "outstanding"].sum()),
        "rows": records,
    }


def _holt_forecast(values: np.ndarray, horizon: int, phi: float = 0.98):
    if len(values) < 3:
        flat = np.full(horizon, values[-1] if len(values) else 0.0)
        return flat, flat, flat
    best = None
    for alpha in np.linspace(0.1, 0.9, 9):
        for beta in np.linspace(0.05, 0.5, 10):
            level, trend = values[0], values[1] - values[0]
            fitted = np.empty_like(values)
            fitted[0] = values[0]
            for t in range(1, len(values)):
                forecast = level + phi * trend
                fitted[t] = forecast
                new_level = alpha * values[t] + (1 - alpha) * forecast
                trend = beta * (new_level - level) + (1 - beta) * phi * trend
                level = new_level
            sse = float(((values[1:] - fitted[1:]) ** 2).sum())
            if best is None or sse < best[0]:
                best = (sse, level, trend, fitted)
    _, level, trend, fitted = best
    steps = np.arange(1, horizon + 1)
    point = level + np.cumsum(phi**steps) * trend
    resid = values[1:] - fitted[1:]
    sigma = float(resid.std(ddof=1)) if len(resid) > 1 else 0.0
    width = 1.96 * sigma * np.sqrt(steps)
    return np.clip(point, 0, None), np.clip(point - width, 0, None), np.clip(point + width, 0, None)


def sales_forecast(df: pd.DataFrame, horizon_months: int = 3, today: date | None = None) -> dict:
    """Monthly revenue forecast, deliberately unavailable before 30 days of history."""
    today = today or date.today()
    if df.empty:
        return {"available": False, "reason": "No sales recorded yet."}
    span_days = (df["sale_date"].max() - df["sale_date"].min()).days
    if span_days < FORECAST_MIN_HISTORY_DAYS:
        remaining = FORECAST_MIN_HISTORY_DAYS - span_days
        return {
            "available": False,
            "reason": f"Forecasting unlocks after one month of sales history to keep predictions honest. About {remaining} more days of data needed.",
        }
    monthly = (
        df.set_index("sale_date")
        .resample("MS")["total_amount"]
        .sum()
    )
    values = monthly.to_numpy(dtype=float)
    point, lower, upper = _holt_forecast(values, horizon_months)
    future = pd.date_range(monthly.index[-1] + pd.DateOffset(months=1), periods=horizon_months, freq="MS")
    return {
        "available": True,
        "method": "Damped Holt trend on monthly revenue, 95% interval",
        "history": [{"bucket": ts.strftime("%b %Y"), "revenue": round(float(v), 2)} for ts, v in monthly.items()],
        "forecast": [
            {"bucket": ts.strftime("%b %Y"), "revenue": round(float(p), 2), "lower": round(float(lo), 2), "upper": round(float(hi), 2)}
            for ts, p, lo, hi in zip(future, point, lower, upper)
        ],
        "next_month": round(float(point[0]), 2),
    }
