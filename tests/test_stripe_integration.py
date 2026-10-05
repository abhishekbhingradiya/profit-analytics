from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.integrations.stripe_client import StripeClient, StripeError, is_test_key
from app.integrations.stripe_sync import apply_discount, build_revenue_rows, month_span, monthly_list_amount, sync_stripe
from app.models import CostEntry, Customer, Organization, RevenueEntry
from app.services.secrets import SecretUnavailable, decrypt_secret, encrypt_secret

TODAY = date(2026, 10, 1)


def subscription(sub_id, customer, unit_amount, interval="month", start=1735689600, status="active", **extra):
    base = {
        "id": sub_id,
        "customer": customer,
        "status": status,
        "start_date": start,  # 2025-01-01 UTC
        "items": {"data": [{"quantity": 1, "price": {"id": f"price_{sub_id}", "nickname": "Growth", "unit_amount": unit_amount, "recurring": {"interval": interval, "interval_count": 1}}}]},
    }
    base.update(extra)
    return base


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeSession:
    """Serves /v1 paths from canned pages and records pagination cursors."""

    def __init__(self, pages_by_path):
        self.pages = pages_by_path
        self.calls = []

    def get(self, url, params=None, auth=None, timeout=None):
        path = url.split("/v1")[1]
        self.calls.append((path, dict(params or {})))
        pages = self.pages.get(path, [{"data": [], "has_more": False}])
        index = 0
        if params and params.get("starting_after"):
            for i, page in enumerate(pages):
                if page["data"] and page["data"][-1]["id"] == params["starting_after"]:
                    index = i + 1
                    break
        return FakeResponse(pages[min(index, len(pages) - 1)])


def test_secret_round_trip_and_tamper_detection():
    token = encrypt_secret("sk_test_abc123")
    assert token != "sk_test_abc123"
    assert decrypt_secret(token) == "sk_test_abc123"
    with pytest.raises(SecretUnavailable):
        decrypt_secret(token[:-4] + "0000")


def test_client_requires_secret_key_and_detects_test_mode():
    with pytest.raises(StripeError):
        StripeClient("pk_test_notsecret")
    assert is_test_key("sk_test_x")
    assert is_test_key("rk_test_x")
    assert not is_test_key("sk_live_x")


def test_client_paginates_with_cursor():
    pages = {
        "/customers": [
            {"data": [{"id": "cus_1"}, {"id": "cus_2"}], "has_more": True},
            {"data": [{"id": "cus_3"}], "has_more": False},
        ]
    }
    client = StripeClient("sk_test_key", session=FakeSession(pages))
    items = client.list_all("/customers")
    assert [item["id"] for item in items] == ["cus_1", "cus_2", "cus_3"]


def test_monthly_normalization_and_discounts():
    yearly = subscription("s1", "cus_1", 120000, interval="year")
    amount, plan = monthly_list_amount(yearly)
    assert amount == pytest.approx(100.0)
    assert plan == "Growth"
    discounted = dict(yearly, discount={"coupon": {"percent_off": 25}})
    assert apply_discount(discounted, 100.0) == pytest.approx(75.0)
    amount_off = dict(yearly, discount={"coupon": {"amount_off": 2000}})
    assert apply_discount(amount_off, 100.0) == pytest.approx(80.0)


def test_month_span_counts_start_and_end_months():
    months = month_span(date(2025, 11, 1), date(2026, 2, 10), TODAY)
    assert months[0] == date(2025, 11, 1)
    assert months[-1] == date(2026, 2, 1)
    open_ended = month_span(date(2026, 8, 1), None, TODAY)
    assert open_ended[-1] == TODAY


def test_build_rows_aggregates_customer_months_and_skips_trials():
    subs = [
        subscription("s1", "cus_1", 10000),
        subscription("s2", "cus_1", 5000),
        subscription("s3", "cus_2", 7000, status="trialing"),
    ]
    rows = build_revenue_rows(subs, TODAY)
    assert ("cus_2", TODAY) not in rows
    row = rows[("cus_1", TODAY)]
    assert row["mrr"] == pytest.approx(150.0)
    assert row["plan"] == "Growth"


def test_sync_replaces_revenue_and_keeps_shared_costs():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    pages = {
        "/customers": [{"data": [{"id": "cus_1", "name": "Acme", "created": 1735689600, "metadata": {"segment": "Mid-Market"}}], "has_more": False}],
        "/subscriptions": [{"data": [subscription("s1", "cus_1", 10000)], "has_more": False}],
        "/account": [{"id": "acct_1"}],
    }
    client = StripeClient("sk_test_key", session=FakeSession(pages))
    with Session(engine) as db:
        org = Organization(name="Pilot")
        db.add(org)
        db.flush()
        old = Customer(org_id=org.id, external_id="OLD", name="Old", segment="SMB", region="NA", industry="X", channel="Direct")
        db.add(old)
        db.flush()
        db.add(CostEntry(org_id=org.id, month=date(2026, 9, 1), category="hosting", customer_id=None, amount=500))
        db.add(CostEntry(org_id=org.id, month=date(2026, 9, 1), category="support", customer_id=old.id, amount=90))
        db.flush()

        stats = sync_stripe(db, org, client, today=TODAY)
        db.commit()

        assert stats["customers"] == 1
        assert stats["latest_mrr"] == pytest.approx(100.0)
        customers = db.scalars(select(Customer).where(Customer.org_id == org.id)).all()
        assert [customer.external_id for customer in customers] == ["cus_1"]
        assert customers[0].segment == "Mid-Market"
        revenue = db.scalars(select(RevenueEntry).where(RevenueEntry.org_id == org.id)).all()
        assert len(revenue) == stats["revenue_rows"] and all(entry.mrr == 100.0 for entry in revenue)
        remaining_costs = db.scalars(select(CostEntry).where(CostEntry.org_id == org.id)).all()
        assert len(remaining_costs) == 1 and remaining_costs[0].customer_id is None
    engine.dispose()


def test_sync_refuses_empty_subscription_data():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    client = StripeClient("sk_test_key", session=FakeSession({}))
    with Session(engine) as db:
        org = Organization(name="Pilot")
        db.add(org)
        db.flush()
        with pytest.raises(ValueError, match="no billable subscriptions"):
            sync_stripe(db, org, client, today=TODAY)
    engine.dispose()
