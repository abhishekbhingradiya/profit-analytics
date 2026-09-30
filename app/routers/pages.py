from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import get_current_user, require_role
from app.services.datasets import dataset_status, has_data
from app.templating import render

router = APIRouter()

PAGE_META = {
    "dashboard": ("Overview", "A clear view of recurring revenue, retention and operating performance."),
    "insights": ("Why it changed", "A period-over-period explanation of gross-profit movement."),
    "revenue": ("Revenue & MRR", "Recurring revenue movements, growth and customer retention."),
    "profitability": ("Profitability", "See where recurring revenue becomes gross profit."),
    "unit_economics": ("Unit economics", "Customer acquisition cost, lifetime value and payback."),
    "forecast": ("Forecast", "A statistical baseline for revenue, gross profit and operating income."),
    "scenarios": ("Scenarios", "Change operating assumptions and compare modeled outcomes."),
    "anomalies": ("Alerts & leakage", "Find unusual movements, costly accounts and discount leakage."),
    "copilot": ("AI copilot", "Ask questions about the tenant's modeled profitability data."),
    "data": ("Data workspace", "Manage sample data and import monthly SaaS records."),
    "settings": ("Workspace settings", "Users and workspace security controls."),
}


@router.get("/dashboard")
@router.get("/insights")
@router.get("/revenue")
@router.get("/profitability")
@router.get("/unit-economics")
@router.get("/forecast")
@router.get("/scenarios")
@router.get("/anomalies")
@router.get("/copilot")
@router.get("/data")
def page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    key = request.url.path.strip("/").replace("-", "_")
    if key == "dashboard" and not has_data(db, user.org_id):
        return RedirectResponse("/data", status_code=303)
    title, description = PAGE_META[key]
    return render(
        request,
        f"pages/{key}.html",
        title=title,
        description=description,
        user=user,
        org=user.organization,
        data_status=dataset_status(db, user.org_id),
        active=key,
    )


@router.get("/settings")
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    title, description = PAGE_META["settings"]
    return render(
        request,
        "pages/settings.html",
        title=title,
        description=description,
        user=user,
        org=user.organization,
        users=db.scalars(select(User).where(User.org_id == user.org_id).order_by(User.created_at)).all(),
        data_status=dataset_status(db, user.org_id),
        active="settings",
    )
