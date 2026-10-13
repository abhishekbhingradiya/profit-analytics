from dataclasses import replace
from datetime import date, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.tenancy as tenancy
from app.db import Base
from app.models import Vendor
from app.services.demo_data import load_demo
from app.services.notifications import generate_daily, unread_count
from app.services.secrets import decrypt_secret
from app.tenancy import engine_for, provision_tenant_dsn, tenant_session
from app.tenant_models import Customer, Notification, Product, Sale


def control_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_vendor(db, name, tmp_path):
    vendor = Vendor(name=name)
    db.add(vendor)
    db.flush()
    provision_tenant_dsn(vendor)
    return vendor


def test_each_vendor_gets_its_own_isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(tenancy, "settings", replace(tenancy.settings, tenant_data_dir=tmp_path))
    tenancy._engines.clear()
    db = control_session()
    vendor_a = make_vendor(db, "Vendor A", tmp_path)
    vendor_b = make_vendor(db, "Vendor B", tmp_path)
    assert decrypt_secret(vendor_a.db_dsn_encrypted) != decrypt_secret(vendor_b.db_dsn_encrypted)

    session_a = tenant_session(vendor_a)
    session_b = tenant_session(vendor_b)
    product = Product(product_code="SKU-1", name="Pump", unit_price=100)
    customer = Customer(name="Asha", email="a@example.com")
    session_a.add_all([product, customer])
    session_a.flush()
    session_a.add(Sale(product_id=product.id, customer_id=customer.id, quantity=1, unit_price=100,
                       total_amount=100, sale_date=date(2026, 10, 1)))
    session_a.commit()

    assert session_a.scalar(select(Product.product_code)) == "SKU-1"
    assert session_b.scalar(select(Product.id)) is None
    assert session_b.scalar(select(Sale.id)) is None
    session_a.close()
    session_b.close()
    assert engine_for(vendor_a) is not engine_for(vendor_b)


def test_demo_data_populates_tenant(tmp_path, monkeypatch):
    monkeypatch.setattr(tenancy, "settings", replace(tenancy.settings, tenant_data_dir=tmp_path))
    tenancy._engines.clear()
    db = control_session()
    vendor = make_vendor(db, "Demo Vendor", tmp_path)
    session = tenant_session(vendor)
    stats = load_demo(session, months=6)
    assert stats["products"] == 8
    assert stats["sales"] > 50
    assert session.scalar(select(Customer.id)) is not None
    session.close()


def test_daily_notifications_flag_deadlines_and_run_once(tmp_path, monkeypatch):
    monkeypatch.setattr(tenancy, "settings", replace(tenancy.settings, tenant_data_dir=tmp_path))
    tenancy._engines.clear()
    db = control_session()
    vendor = make_vendor(db, "Notify Vendor", tmp_path)
    session = tenant_session(vendor)
    today = date(2026, 10, 13)
    product = Product(product_code="SKU-9", name="Panel", unit_price=50)
    customer = Customer(name="Marco", email="m@example.com")
    session.add_all([product, customer])
    session.flush()
    session.add_all([
        Sale(product_id=product.id, customer_id=customer.id, quantity=1, unit_price=50, total_amount=50,
             sale_date=today - timedelta(days=30), due_date=today - timedelta(days=5), amount_paid=0),
        Sale(product_id=product.id, customer_id=customer.id, quantity=1, unit_price=50, total_amount=50,
             sale_date=today - timedelta(days=10), due_date=today + timedelta(days=2), amount_paid=0),
        Sale(product_id=product.id, customer_id=customer.id, quantity=1, unit_price=50, total_amount=50,
             sale_date=today - timedelta(days=3), due_date=None, amount_paid=50, paid_on=today),
    ])
    session.commit()

    created = generate_daily(session, db, vendor, today=today)
    assert created == 3
    kinds = set(session.scalars(select(Notification.kind)))
    assert kinds == {"deadline_crossed", "deadline_soon", "payment_completed"}
    assert unread_count(session) == 3
    # Second call the same day is a no-op.
    assert generate_daily(session, db, vendor, today=today) == 0
    session.close()
