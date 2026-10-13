"""Daily payment notifications: completed payments, approaching and crossed deadlines."""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Vendor
from app.services.formatting import money
from app.tenant_models import Notification, Sale

DUE_SOON_DAYS = 3


def _exists(db: Session, sale_id: int, kind: str, created_on: date) -> bool:
    return db.scalar(
        select(Notification.id).where(
            Notification.sale_id == sale_id, Notification.kind == kind, Notification.created_on == created_on
        ).limit(1)
    ) is not None


def generate_daily(tenant_db: Session, control_db: Session, vendor: Vendor, today: date | None = None) -> int:
    """Runs once per vendor per day on first visit; returns how many notices were created."""
    today = today or date.today()
    if vendor.last_notified_on == today:
        return 0
    created = 0
    sales = tenant_db.scalars(select(Sale)).all()
    for sale in sales:
        label = f"sale #{sale.id} ({money(sale.total_amount)})"
        if sale.is_paid and sale.paid_on == today and not _exists(tenant_db, sale.id, "payment_completed", today):
            tenant_db.add(Notification(created_on=today, kind="payment_completed", sale_id=sale.id,
                                       message=f"Payment completed for {label}."))
            created += 1
        elif not sale.is_paid and sale.due_date:
            if sale.due_date < today and not _exists(tenant_db, sale.id, "deadline_crossed", today):
                days = (today - sale.due_date).days
                tenant_db.add(Notification(created_on=today, kind="deadline_crossed", sale_id=sale.id,
                                           message=f"Deadline crossed: {money(sale.outstanding)} outstanding on {label}, {days} day(s) overdue."))
                created += 1
            elif today <= sale.due_date <= today + timedelta(days=DUE_SOON_DAYS) and not _exists(tenant_db, sale.id, "deadline_soon", today):
                tenant_db.add(Notification(created_on=today, kind="deadline_soon", sale_id=sale.id,
                                           message=f"Payment of {money(sale.outstanding)} for {label} is due on {sale.due_date.isoformat()}."))
                created += 1
    vendor.last_notified_on = today
    tenant_db.commit()
    control_db.commit()
    return created


def unread_count(tenant_db: Session) -> int:
    return tenant_db.scalar(select(func.count(Notification.id)).where(Notification.is_read.is_(False))) or 0
