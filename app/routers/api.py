from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.security import get_current_user
from app.services.sales_analytics import (
    customer_rankings,
    load_sales,
    overview,
    payment_book,
    product_customers,
    product_leaderboard,
    sales_forecast,
    sales_series,
)
from app.services.serialize import clean
from app.tenancy import get_tenant_db
from app.tenant_models import Product

router = APIRouter(prefix="/api", tags=["analytics"], dependencies=[Depends(get_current_user)])


@router.get("/overview")
def get_overview(tenant_db: Session = Depends(get_tenant_db)):
    df = load_sales(tenant_db)
    products = tenant_db.scalar(select(func.count(Product.id))) or 0
    return clean(overview(df, products, date.today()))


@router.get("/products")
def get_products(q: str = Query("", max_length=120), tenant_db: Session = Depends(get_tenant_db)):
    df = load_sales(tenant_db)
    leaderboard = product_leaderboard(df, query=q)
    sold_ids = {row["product_id"] for row in leaderboard}
    needle = q.strip().casefold()
    unsold = [
        {"product_id": p.id, "product_code": p.product_code, "product_name": p.name, "category": p.category,
         "unit_price": p.unit_price, "revenue": 0, "units": 0, "orders": 0, "customers": 0,
         "received": 0, "outstanding": 0, "last_sold": None, "share": 0}
        for p in tenant_db.scalars(select(Product).order_by(Product.product_code))
        if p.id not in sold_ids
        and (not needle or needle in p.product_code.casefold() or needle in p.name.casefold() or needle in p.category.casefold())
    ]
    return clean(leaderboard + unsold)


@router.get("/products/{product_id}/customers")
def get_product_customers(product_id: int, tenant_db: Session = Depends(get_tenant_db)):
    if tenant_db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return clean(product_customers(load_sales(tenant_db), product_id))


@router.get("/customers")
def get_customers(tenant_db: Session = Depends(get_tenant_db)):
    return clean(customer_rankings(load_sales(tenant_db)))


@router.get("/series")
def get_series(
    granularity: str = Query("month", pattern="^(week|month|year|decade)$"),
    product_id: int | None = Query(None, ge=1),
    tenant_db: Session = Depends(get_tenant_db),
):
    return clean(sales_series(load_sales(tenant_db), granularity=granularity, product_id=product_id))


@router.get("/forecast")
def get_forecast(tenant_db: Session = Depends(get_tenant_db)):
    return clean(sales_forecast(load_sales(tenant_db)))


@router.get("/billing")
def get_billing(tenant_db: Session = Depends(get_tenant_db)):
    return clean(payment_book(load_sales(tenant_db), date.today()))
