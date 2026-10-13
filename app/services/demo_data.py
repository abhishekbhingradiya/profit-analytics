"""Deterministic fictional product/sales history so a new vendor can explore the app."""

import calendar
import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.tenant_models import Customer, Product, Sale

PRODUCTS = [
    ("SKU-1001", "Aluminium Frame Kit", "Hardware", 480.0),
    ("SKU-1002", "Hydraulic Pump v2", "Hardware", 1250.0),
    ("SKU-1003", "Control Panel Pro", "Electronics", 890.0),
    ("SKU-1004", "Sensor Array Pack", "Electronics", 320.0),
    ("SKU-1005", "Maintenance Plan", "Services", 150.0),
    ("SKU-1006", "Installation Service", "Services", 600.0),
    ("SKU-1007", "Filter Cartridge Set", "Consumables", 75.0),
    ("SKU-1008", "Premium Lubricant Case", "Consumables", 48.0),
]
FIRST_NAMES = ["Asha", "Marco", "Lena", "Ravi", "Sofia", "Daniel", "Mei", "Omar", "Julia", "Tomás", "Nina", "Kwame"]
COMPANIES = ["Vertex Mfg", "Bluejay Industrial", "Cedar Works", "Northstar Plants", "Atlas Fab", "Meridian Tools",
             "Orbit Machinery", "Redwood Assembly", "Summit Plants", "Brightline Ops"]


def _shift_month(month: date, offset: int) -> date:
    absolute = month.year * 12 + month.month - 1 + offset
    year, index = divmod(absolute, 12)
    day = min(month.day, calendar.monthrange(year, index + 1)[1])
    return date(year, index + 1, day)


def load_demo(db: Session, months: int = 18, today: date | None = None) -> dict:
    rng = random.Random(70406)
    today = today or date.today()
    start = _shift_month(today.replace(day=1), -(months - 1))

    products = [Product(product_code=c, name=n, category=cat, unit_price=p) for c, n, cat, p in PRODUCTS]
    db.add_all(products)
    customers = []
    for i in range(24):
        name = f"{rng.choice(FIRST_NAMES)} {chr(65 + i % 26)}."
        company = rng.choice(COMPANIES)
        customers.append(Customer(name=name, email=f"buyer{i + 1}@example.com", company=company))
    db.add_all(customers)
    db.flush()

    weights = [rng.uniform(0.4, 2.2) for _ in products]
    sales = 0
    for month_index in range(months):
        month_start = _shift_month(start, month_index)
        orders = rng.randint(14, 26)
        for _ in range(orders):
            product = rng.choices(products, weights=weights)[0]
            customer = rng.choice(customers)
            quantity = rng.randint(1, 6)
            unit_price = round(product.unit_price * rng.uniform(0.92, 1.05), 2)
            total = round(quantity * unit_price, 2)
            day = rng.randint(1, calendar.monthrange(month_start.year, month_start.month)[1])
            sale_date = month_start.replace(day=day)
            if sale_date > today:
                continue
            due_date = sale_date + timedelta(days=rng.choice([14, 30, 45]))
            roll = rng.random()
            if roll < 0.68:
                amount_paid, paid_on = total, min(due_date - timedelta(days=rng.randint(0, 10)), today)
            elif roll < 0.82:
                amount_paid, paid_on = round(total * rng.uniform(0.25, 0.75), 2), None
            else:
                amount_paid, paid_on = 0.0, None
            db.add(Sale(
                product_id=product.id, customer_id=customer.id, quantity=quantity, unit_price=unit_price,
                total_amount=total, sale_date=sale_date, due_date=due_date,
                amount_paid=amount_paid, paid_on=paid_on,
            ))
            sales += 1
    db.commit()
    return {"products": len(products), "customers": len(customers), "sales": sales}
