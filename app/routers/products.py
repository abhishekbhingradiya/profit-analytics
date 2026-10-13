"""Vendor entry forms: products, sales and payment updates."""

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import require_role, verify_csrf
from app.services.audit import record
from app.tenancy import get_tenant_db
from app.templating import flash
from app.tenant_models import Customer, Notification, Product, Sale

router = APIRouter()


def _back(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _parse_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be YYYY-MM-DD") from exc


@router.post("/products", dependencies=[Depends(verify_csrf)])
def add_product(
    request: Request,
    product_code: str = Form(...),
    name: str = Form(...),
    category: str = Form(""),
    unit_price: float = Form(...),
    db: Session = Depends(get_db),
    tenant_db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role("analyst")),
):
    product_code, name = product_code.strip(), name.strip()
    if not product_code or not name or unit_price < 0 or unit_price > 1e9:
        flash(request, "error", "Provide a product ID, a name and a non-negative price.")
        return _back("/products")
    if tenant_db.scalar(select(Product.id).where(func.lower(Product.product_code) == product_code.lower())):
        flash(request, "error", f"Product ID “{product_code}” already exists. Product IDs must be unique.")
        return _back("/products")
    tenant_db.add(Product(product_code=product_code[:64], name=name[:200],
                          category=(category.strip() or "General")[:80], unit_price=round(unit_price, 2)))
    tenant_db.commit()
    record(db, user, "product_added", f"code={product_code}")
    db.commit()
    flash(request, "success", f"Product “{name}” ({product_code}) added. The list below is updated.")
    return _back("/products")


@router.post("/sales", dependencies=[Depends(verify_csrf)])
def record_sale(
    request: Request,
    product_id: int = Form(...),
    customer_name: str = Form(...),
    customer_email: str = Form(""),
    customer_company: str = Form(""),
    quantity: int = Form(1),
    unit_price: str = Form(""),
    sale_date: str = Form(""),
    due_date: str = Form(""),
    amount_paid: float = Form(0.0),
    db: Session = Depends(get_db),
    tenant_db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role("analyst")),
):
    product = tenant_db.get(Product, product_id)
    customer_name = customer_name.strip()
    if product is None or not customer_name or not 1 <= quantity <= 1_000_000:
        flash(request, "error", "Pick a product, enter the customer name and a valid quantity.")
        return _back("/products")
    try:
        price = round(float(unit_price), 2) if unit_price.strip() else product.unit_price
    except ValueError:
        flash(request, "error", "Unit price must be a number.")
        return _back("/products")
    if price < 0 or amount_paid < 0:
        flash(request, "error", "Amounts cannot be negative.")
        return _back("/products")
    when = _parse_date(sale_date.strip() or None, "Sale date") or date.today()
    due = _parse_date(due_date.strip() or None, "Due date")
    email = customer_email.strip().lower()[:254]
    customer = tenant_db.scalar(
        select(Customer).where(func.lower(Customer.name) == customer_name.lower(), Customer.email == email)
    )
    if customer is None:
        customer = Customer(name=customer_name[:200], email=email, company=customer_company.strip()[:200])
        tenant_db.add(customer)
        tenant_db.flush()
    total = round(price * quantity, 2)
    paid = min(round(amount_paid, 2), total)
    tenant_db.add(Sale(
        product_id=product.id, customer_id=customer.id, quantity=quantity, unit_price=price,
        total_amount=total, sale_date=when, due_date=due,
        amount_paid=paid, paid_on=when if paid >= total else None,
    ))
    tenant_db.commit()
    record(db, user, "sale_recorded", f"product={product.product_code}; customer={customer.name}; total={total}")
    db.commit()
    flash(request, "success", f"Sale recorded: {quantity} × {product.name} to {customer.name}.")
    return _back("/products")


@router.post("/sales/{sale_id}/payment", dependencies=[Depends(verify_csrf)])
def record_payment(
    sale_id: int,
    request: Request,
    amount: float = Form(...),
    paid_on: str = Form(""),
    db: Session = Depends(get_db),
    tenant_db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role("analyst")),
):
    sale = tenant_db.get(Sale, sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    if amount <= 0:
        flash(request, "error", "Payment amount must be positive.")
        return _back("/billing")
    when = _parse_date(paid_on.strip() or None, "Payment date") or date.today()
    sale.amount_paid = min(round(sale.amount_paid + amount, 2), sale.total_amount)
    if sale.is_paid:
        sale.paid_on = when
    tenant_db.commit()
    record(db, user, "payment_recorded", f"sale={sale_id}; amount={amount}")
    db.commit()
    status = "fully paid" if sale.is_paid else f"{sale.outstanding:,.2f} still outstanding"
    flash(request, "success", f"Payment saved for sale #{sale_id}; {status}.")
    return _back("/billing")


@router.post("/notifications/read", dependencies=[Depends(verify_csrf)])
def mark_notifications_read(
    request: Request,
    tenant_db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role("viewer")),
):
    tenant_db.execute(update(Notification).where(Notification.is_read.is_(False)).values(is_read=True))
    tenant_db.commit()
    flash(request, "success", "All notifications marked as read.")
    return _back("/notifications")
