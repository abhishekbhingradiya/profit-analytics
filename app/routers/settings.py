from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import MIN_PASSWORD_LENGTH, hash_password, require_role, verify_csrf
from app.services.audit import record
from app.templating import flash

router = APIRouter()


@router.post("/settings/users", dependencies=[Depends(verify_csrf)])
def create_user(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    actor: User = Depends(require_role("admin")),
):
    email, full_name = email.strip().lower(), full_name.strip()
    if role not in {"admin", "analyst", "viewer"} or len(password) < MIN_PASSWORD_LENGTH or "@" not in email:
        flash(request, "error", "Check the role, email address and password length.")
        return RedirectResponse("/settings", status_code=303)
    if db.scalar(select(User.id).where(User.email == email)):
        flash(request, "error", "That email already has an account.")
        return RedirectResponse("/settings", status_code=303)
    user = User(
        org_id=actor.org_id,
        full_name=full_name[:200],
        email=email[:254],
        role=role,
        password_hash=hash_password(password),
    )
    db.add(user)
    record(db, actor, "user_created", f"email={email}; role={role}")
    db.commit()
    flash(request, "success", f"Added {email} to the workspace.")
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/users/{user_id}/status", dependencies=[Depends(verify_csrf)])
def set_user_status(
    user_id: int,
    request: Request,
    active: bool = Form(...),
    db: Session = Depends(get_db),
    actor: User = Depends(require_role("admin")),
):
    target = db.scalar(select(User).where(User.id == user_id, User.org_id == actor.org_id))
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == actor.id and not active:
        flash(request, "error", "You cannot deactivate your own account.")
        return RedirectResponse("/settings", status_code=303)
    target.is_active = active
    record(db, actor, "user_status_changed", f"user_id={target.id}; active={active}")
    db.commit()
    flash(request, "success", f"Updated {target.email}.")
    return RedirectResponse("/settings", status_code=303)
