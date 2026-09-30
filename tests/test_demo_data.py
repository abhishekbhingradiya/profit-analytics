from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import CostEntry, Customer, Organization, RevenueEntry
from app.services.demo_data import load_demo


def test_demo_generator_creates_complete_saas_history():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        org = Organization(name="Test SaaS")
        db.add(org)
        db.flush()
        load_demo(db, org, customer_count=12, months=12)
        assert db.scalar(select(Customer.id).where(Customer.org_id == org.id).limit(1)) is not None
        revenue_count = db.scalar(select(RevenueEntry.id).where(RevenueEntry.org_id == org.id).limit(1))
        cost_count = db.scalar(select(CostEntry.id).where(CostEntry.org_id == org.id).limit(1))
        assert revenue_count is not None
        assert cost_count is not None
        assert db.scalar(select(Customer.region).where(Customer.org_id == org.id).limit(1)) is not None
    engine.dispose()
