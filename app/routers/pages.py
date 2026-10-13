from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import get_current_user, require_role
from app.services.notifications import generate_daily, unread_count
from app.tenancy import get_tenant_db
from app.templating import render
from app.tenant_models import Customer, Notification, Product, Sale

router = APIRouter()

PAGE_META = {
    "dashboard": ("Overview", "Your best products, your buyers and the money still on the table."),
    "products": ("Products", "Add products, record sales and see who buys each one."),
    "customers": ("Customers", "Who buys the most, who buys the least, and what they owe."),
    "billing": ("Billing & payments", "Received, outstanding and overdue — per sale and per deadline."),
    "analytics": ("Analytics", "Sales over time, from weekly detail to a decade view, with forecasts."),
    "notifications": ("Notifications", "Daily payment updates: completed, due soon and crossed deadlines."),
    "settings": ("Account settings", "Team access for your vendor account."),
}


def _context(tenant_db: Session, user: User) -> dict:
    stats = {
        "products": tenant_db.scalar(select(func.count(Product.id))) or 0,
        "customers": tenant_db.scalar(select(func.count(Customer.id))) or 0,
        "sales": tenant_db.scalar(select(func.count(Sale.id))) or 0,
        "last_sale": tenant_db.scalar(select(func.max(Sale.sale_date))),
    }
    recent = tenant_db.scalars(
        select(Notification).order_by(Notification.created_on.desc(), Notification.id.desc()).limit(4)
    ).all()
    return {"user": user, "vendor": user.vendor, "stats": stats, "unread": unread_count(tenant_db), "recent_notes": recent}


@router.get("/dashboard")
@router.get("/products")
@router.get("/customers")
@router.get("/billing")
@router.get("/analytics")
def page(
    request: Request,
    db: Session = Depends(get_db),
    tenant_db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    key = request.url.path.strip("/")
    if key == "dashboard":
        generate_daily(tenant_db, db, user.vendor)
    title, description = PAGE_META[key]
    return render(request, f"pages/{key}.html", title=title, description=description,
                  active=key, **_context(tenant_db, user))


@router.get("/notifications")
def notifications_page(
    request: Request,
    db: Session = Depends(get_db),
    tenant_db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    generate_daily(tenant_db, db, user.vendor)
    title, description = PAGE_META["notifications"]
    items = tenant_db.scalars(
        select(Notification).order_by(Notification.created_on.desc(), Notification.id.desc()).limit(200)
    ).all()
    return render(request, "pages/notifications.html", title=title, description=description,
                  active="notifications", notifications=items, **_context(tenant_db, user))


@router.get("/settings")
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    tenant_db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role("admin")),
):
    title, description = PAGE_META["settings"]
    users = db.scalars(select(User).where(User.vendor_id == user.vendor_id).order_by(User.created_at)).all()
    return render(request, "pages/settings.html", title=title, description=description,
                  active="settings", users=users, **_context(tenant_db, user))


@router.get("/favicon.ico")
def favicon():
    return Response(status_code=204)
