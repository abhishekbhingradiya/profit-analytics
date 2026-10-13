from datetime import date

import pandas as pd
import pytest

from app.services.sales_analytics import (
    FORECAST_MIN_HISTORY_DAYS,
    customer_rankings,
    overview,
    payment_book,
    product_customers,
    product_leaderboard,
    sales_forecast,
    sales_series,
)

TODAY = date(2026, 10, 13)


def frame(rows):
    df = pd.DataFrame(rows)
    df["sale_date"] = pd.to_datetime(df["sale_date"])
    df["outstanding"] = (df["total_amount"] - df["amount_paid"]).clip(lower=0).round(2)
    return df


def sample():
    base = {"customer_email": "", "company": "", "paid_on": None, "category": "Hardware"}
    return frame([
        {**base, "sale_id": 1, "product_id": 1, "customer_id": 1, "quantity": 2, "total_amount": 200.0, "amount_paid": 200.0,
         "sale_date": date(2026, 8, 3), "due_date": date(2026, 8, 20), "product_code": "P1", "product_name": "Pump", "customer_name": "Asha"},
        {**base, "sale_id": 2, "product_id": 1, "customer_id": 2, "quantity": 1, "total_amount": 100.0, "amount_paid": 40.0,
         "sale_date": date(2026, 9, 10), "due_date": date(2026, 9, 25), "product_code": "P1", "product_name": "Pump", "customer_name": "Marco"},
        {**base, "sale_id": 3, "product_id": 2, "customer_id": 1, "quantity": 5, "total_amount": 50.0, "amount_paid": 0.0,
         "sale_date": date(2026, 10, 5), "due_date": date(2026, 12, 1), "product_code": "P2", "product_name": "Filter", "customer_name": "Asha"},
    ])


def test_overview_totals_and_overdue():
    result = overview(sample(), product_count=2, today=TODAY)
    assert result["total_revenue"] == 350.0
    assert result["received"] == 240.0
    assert result["outstanding"] == 110.0
    assert result["overdue"] == 60.0  # sale 2 past its due date
    assert result["customers"] == 2


def test_product_leaderboard_orders_by_revenue_and_searches():
    board = product_leaderboard(sample())
    assert [row["product_code"] for row in board] == ["P1", "P2"]
    assert board[0]["revenue"] == 300.0
    assert board[0]["customers"] == 2
    filtered = product_leaderboard(sample(), query="filt")
    assert [row["product_code"] for row in filtered] == ["P2"]


def test_product_customers_lists_buyers_best_first():
    buyers = product_customers(sample(), product_id=1)
    assert [b["customer_name"] for b in buyers] == ["Asha", "Marco"]
    assert buyers[1]["outstanding"] == 60.0


def test_customer_rankings_expose_highest_and_lowest():
    ranking = customer_rankings(sample())
    assert ranking["highest"]["customer_name"] == "Asha"
    assert ranking["lowest"]["customer_name"] == "Marco"
    assert ranking["highest"]["revenue"] == 250.0


def test_series_buckets_week_month_year_decade():
    df = sample()
    weeks = sales_series(df, "week")
    months = sales_series(df, "month")
    years = sales_series(df, "year")
    decades = sales_series(df, "decade")
    assert len(weeks) == 3
    assert [m["bucket"] for m in months] == ["Aug 2026", "Sep 2026", "Oct 2026"]
    assert years == [{"bucket": "2026", "revenue": 350.0, "received": 240.0, "orders": 3}]
    assert decades[0]["bucket"] == "2020s"
    with pytest.raises(ValueError):
        sales_series(df, "hour")


def test_payment_book_orders_overdue_first():
    book = payment_book(sample(), TODAY)
    assert book["overdue"] == 60.0
    assert book["rows"][0]["status"] == "overdue"
    assert book["rows"][0]["days_overdue"] == 18
    statuses = {row["sale_id"]: row["status"] for row in book["rows"]}
    assert statuses == {1: "paid", 2: "overdue", 3: "unpaid"}


def test_forecast_locked_until_one_month_of_history():
    short = sample()
    short = short[short["sale_date"] >= "2026-09-20"]
    result = sales_forecast(short, today=TODAY)
    assert result["available"] is False
    assert "one month" in result["reason"]


def test_forecast_available_with_enough_history():
    rows = []
    for month in range(1, 10):
        rows.append({
            "sale_id": month, "product_id": 1, "customer_id": 1, "quantity": 1,
            "total_amount": 100.0 + month * 10, "amount_paid": 0.0, "sale_date": date(2026, month, 15),
            "due_date": None, "paid_on": None, "product_code": "P1", "product_name": "Pump",
            "customer_name": "Asha", "customer_email": "", "company": "", "category": "X",
        })
    result = sales_forecast(frame(rows), horizon_months=3, today=TODAY)
    assert result["available"] is True
    assert len(result["forecast"]) == 3
    assert result["forecast"][0]["lower"] <= result["forecast"][0]["revenue"] <= result["forecast"][0]["upper"]
    span = (date(2026, 9, 15) - date(2026, 1, 15)).days
    assert span >= FORECAST_MIN_HISTORY_DAYS
