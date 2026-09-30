from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User
from app.security import require_role, verify_csrf
from app.services.audit import record
from app.services.csv_import import ImportValidationError, replace_tenant_data, validate_uploads
from app.services.datasets import dataset_status
from app.services.demo_data import load_demo
from app.templating import flash

router = APIRouter()


def _read_limited(file: UploadFile, maximum: int) -> bytes:
    content = file.file.read(maximum + 1)
    if len(content) > maximum:
        raise HTTPException(status_code=413, detail="Each CSV must be smaller than the configured upload limit.")
    return content


@router.post("/data/demo", dependencies=[Depends(verify_csrf)])
def create_demo(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    try:
        load_demo(db, user.organization)
        record(db, user, "demo_data_loaded", "140 synthetic accounts, 30 months")
        db.commit()
    except Exception:
        db.rollback()
        raise
    flash(request, "success", "Synthetic SaaS dataset loaded. Your previous dataset was replaced.")
    from fastapi.responses import RedirectResponse

    return RedirectResponse("/dashboard", status_code=303)


@router.post("/data/import", dependencies=[Depends(verify_csrf)])
def import_data(
    request: Request,
    customers: UploadFile = File(...),
    revenue: UploadFile = File(...),
    costs: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    maximum = settings.max_upload_mb * 1024 * 1024
    try:
        frames = validate_uploads(
            _read_limited(customers, maximum),
            _read_limited(revenue, maximum),
            _read_limited(costs, maximum),
        )
        counts = replace_tenant_data(db, user.organization, frames)
        record(db, user, "csv_import", str(counts))
        db.commit()
    except ImportValidationError as exc:
        db.rollback()
        flash(request, "error", str(exc))
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/data", status_code=303)
    except Exception:
        db.rollback()
        raise
    flash(request, "success", f"Imported {counts['customers']} customers, {counts['revenue_rows']} revenue rows and {counts['cost_rows']} cost rows.")
    from fastapi.responses import RedirectResponse

    return RedirectResponse("/dashboard", status_code=303)
