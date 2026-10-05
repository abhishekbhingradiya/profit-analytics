from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.integrations.qbo_client import QBOClient, QBOError
from app.integrations.qbo_sync import refresh_account_mappings, report_account_rows, report_months, sync_quickbooks
from app.models import AccountMapping, CostEntry, Customer, Organization, RevenueEntry

TODAY = date(2026, 10, 1)


def pnl_report():
    return {
        "Columns": {
            "Column": [
                {"ColTitle": "", "ColType": "Account"},
                {"ColTitle": "Aug 2026", "ColType": "Money", "MetaData": [{"Name": "StartDate", "Value": "2026-08-01"}]},
                {"ColTitle": "Sep 2026", "ColType": "Money", "MetaData": [{"Name": "StartDate", "Value": "2026-09-01"}]},
                {"ColTitle": "Total", "ColType": "Money"},
            ]
        },
        "Rows": {
            "Row": [
                {
                    "type": "Section",
                    "Header": {"ColData": [{"value": "Expenses"}]},
                    "Rows": {
                        "Row": [
                            {"type": "Data", "ColData": [{"value": "AWS Hosting", "id": "52"}, {"value": "1,200.00"}, {"value": "1300.50"}, {"value": "2500.50"}]},
                            {"type": "Data", "ColData": [{"value": "Advertising", "id": "7"}, {"value": "400"}, {"value": ""}, {"value": "400"}]},
                            {"type": "Data", "ColData": [{"value": "Travel", "id": "9"}, {"value": "90"}, {"value": "60"}, {"value": "150"}]},
                        ]
                    },
                }
            ]
        },
    }


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responder):
        self.responder = responder

    def get(self, url, params=None, headers=None, timeout=None):
        return self.responder(url, params or {})


def paging_responder(url, params):
    if "/query" in url:
        position = int(params["query"].split("STARTPOSITION ")[1].split(" ")[0])
        if "CompanyInfo" in params["query"] or position > 400:
            return FakeResponse({"QueryResponse": {"Account": []}})
        page = [{"Id": str(position + i), "Name": f"Acct {position + i}", "AccountType": "Expense"} for i in range(200)]
        return FakeResponse({"QueryResponse": {"Account": page}})
    return FakeResponse(pnl_report())


def test_client_requires_credentials_and_surfaces_fault_messages():
    with pytest.raises(QBOError):
        QBOClient(" ", "token")
    session = FakeSession(lambda url, params: FakeResponse({"Fault": {"Error": [{"Message": "Bad request"}]}}, 400))
    with pytest.raises(QBOError, match="Bad request"):
        QBOClient("123", "token", session=session).query("SELECT * FROM CompanyInfo")
    expired = FakeSession(lambda url, params: FakeResponse({}, 401))
    with pytest.raises(QBOError, match="fresh access token"):
        QBOClient("123", "token", session=expired).query("SELECT * FROM CompanyInfo")


def test_client_paginates_queries_by_start_position():
    client = QBOClient("123", "token", session=FakeSession(paging_responder))
    accounts = client.query_all("SELECT Id FROM Account", "Account", page_size=200, max_pages=5)
    assert len(accounts) == 400
    assert accounts[200]["Id"] == "201"


def test_report_parser_extracts_months_and_leaf_accounts():
    months = report_months(pnl_report())
    assert months == [date(2026, 8, 1), date(2026, 9, 1)]
    rows = report_account_rows(pnl_report())
    assert [row["account_id"] for row in rows] == ["52", "7", "9"]
    assert rows[0]["amounts"][:2] == [1200.0, 1300.5]
    assert rows[1]["amounts"][1] == 0.0


def _seeded_org(db):
    org = Organization(name="Pilot")
    db.add(org)
    db.flush()
    customer = Customer(org_id=org.id, external_id="C1", name="Acme", segment="SMB", region="NA", industry="X", channel="Direct")
    db.add(customer)
    db.flush()
    db.add(RevenueEntry(org_id=org.id, customer_id=customer.id, month=date(2026, 9, 1), plan="Growth", list_mrr=100, mrr=100))
    db.add(CostEntry(org_id=org.id, month=date(2026, 9, 1), category="hosting", customer_id=None, amount=999))
    db.add(CostEntry(org_id=org.id, month=date(2026, 7, 1), category="gna", customer_id=None, amount=50))
    db.add(CostEntry(org_id=org.id, month=date(2026, 9, 1), category="support", customer_id=customer.id, amount=40))
    db.flush()
    return org, customer


def test_sync_replaces_window_costs_and_respects_mappings():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    client = QBOClient("123", "token", session=FakeSession(lambda url, params: FakeResponse(pnl_report())))
    with Session(engine) as db:
        org, customer = _seeded_org(db)
        added = refresh_account_mappings(
            db, org, [{"Id": "52", "Name": "AWS Hosting", "AccountType": "Expense"}, {"Id": "7", "Name": "Advertising", "AccountType": "Expense"}]
        )
        assert added == 2
        assert refresh_account_mappings(db, org, [{"Id": "52", "Name": "AWS Hosting"}]) == 0
        for mapping in db.scalars(select(AccountMapping)):
            mapping.category = {"52": "hosting", "7": "marketing"}.get(mapping.account_id)
        db.flush()

        stats = sync_quickbooks(db, org, client, months=3, today=TODAY)
        db.commit()

        assert stats["cost_rows"] == 3
        assert stats["imported_amount"] == pytest.approx(2900.5)
        assert stats["excluded_amount"] == pytest.approx(150.0)
        assert stats["unmapped_accounts"] == ["Travel"]
        shared = db.scalars(select(CostEntry).where(CostEntry.org_id == org.id, CostEntry.customer_id.is_(None))).all()
        by_key = {(entry.month, entry.category): entry.amount for entry in shared}
        assert by_key[(date(2026, 9, 1), "hosting")] == pytest.approx(1300.5)
        assert by_key[(date(2026, 8, 1), "marketing")] == pytest.approx(400.0)
        # Outside the report window and direct costs survive; revenue untouched.
        assert by_key[(date(2026, 7, 1), "gna")] == 50
        direct = db.scalars(select(CostEntry).where(CostEntry.customer_id.is_not(None))).all()
        assert len(direct) == 1
        assert db.scalar(select(RevenueEntry.mrr)) == 100


def test_sync_fails_clearly_without_mapped_accounts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    client = QBOClient("123", "token", session=FakeSession(lambda url, params: FakeResponse(pnl_report())))
    with Session(engine) as db:
        org = Organization(name="Pilot")
        db.add(org)
        db.flush()
        with pytest.raises(ValueError, match="map GL accounts"):
            sync_quickbooks(db, org, client, months=3, today=TODAY)
    engine.dispose()
