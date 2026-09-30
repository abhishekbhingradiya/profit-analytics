import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Customer, Organization
from app.services.csv_import import ImportValidationError, replace_tenant_data, validate_uploads

CUSTOMERS = b"external_id,name,segment,region,industry,channel,signup_month\nA,Acme,Mid-Market,NA,Software,Direct,2025-01\n"
REVENUE = b"external_id,month,plan,list_mrr,mrr\nA,2025-01,Scale,100,90\n"
COSTS = b"month,category,external_id,amount\n2025-01,hosting,,10\n"


def test_valid_csvs_parse_to_normalized_frames():
    frames = validate_uploads(CUSTOMERS, REVENUE, COSTS)
    assert frames["customers"].iloc[0].external_id == "A"
    assert frames["revenue"].iloc[0].mrr == 90
    assert frames["costs"].iloc[0].external_id == ""


def test_import_rejects_unknown_revenue_customer():
    revenue = REVENUE.replace(b"A,2025-01", b"MISSING,2025-01")
    with pytest.raises(ImportValidationError, match="not found"):
        validate_uploads(CUSTOMERS, revenue, COSTS)


def test_import_rejects_unknown_cost_category():
    costs = COSTS.replace(b"hosting", b"miscellaneous")
    with pytest.raises(ImportValidationError, match="Unknown cost category"):
        validate_uploads(CUSTOMERS, REVENUE, costs)


def test_import_rejects_list_price_below_mrr():
    revenue = REVENUE.replace(b",100,90", b",80,90")
    with pytest.raises(ImportValidationError, match="list_mrr"):
        validate_uploads(CUSTOMERS, revenue, COSTS)


def test_import_rejects_duplicate_customer_month():
    revenue = REVENUE + b"A,2025-01,Scale,100,90\n"
    with pytest.raises(ImportValidationError, match="duplicate"):
        validate_uploads(CUSTOMERS, revenue, COSTS)


def test_validated_import_replaces_only_organization_data():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        org = Organization(name="Import Test")
        other = Organization(name="Other Tenant")
        db.add_all([org, other])
        db.flush()
        db.add_all(
            [
                Customer(org_id=org.id, external_id="OLD", name="Old", segment="SMB", region="NA", industry="Software", channel="Direct"),
                Customer(org_id=other.id, external_id="KEEP", name="Keep", segment="SMB", region="NA", industry="Software", channel="Direct"),
            ]
        )
        db.commit()
        frames = validate_uploads(CUSTOMERS, REVENUE, COSTS)
        counts = replace_tenant_data(db, org, frames)
        db.commit()
        assert counts == {"customers": 1, "revenue_rows": 1, "cost_rows": 1}
        org_ids = set(db.scalars(select(Customer.external_id).where(Customer.org_id == org.id)))
        other_ids = set(db.scalars(select(Customer.external_id).where(Customer.org_id == other.id)))
        assert org_ids == {"A"}
        assert other_ids == {"KEEP"}
    engine.dispose()
