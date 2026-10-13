from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, Vendor
from app.security import (
    DUMMY_HASH,
    LoginThrottle,
    MIN_PASSWORD_LENGTH,
    hash_password,
    start_session,
    verify_csrf,
    verify_password,
)
from app.services.audit import record
from app.services.demo_data import load_demo
from app.tenancy import provision_tenant_dsn, tenant_session
from app.templating import render

router = APIRouter()
login_throttle = LoginThrottle()


@router.get("/")
def root(request: Request, db: Session = Depends(get_db)):
    if db.scalar(select(User.id).limit(1)) is None:
        return RedirectResponse("/setup", status_code=303)
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)


@router.get("/setup")
def setup_page(request: Request, db: Session = Depends(get_db)):
    if db.scalar(select(User.id).limit(1)) is not None:
        return RedirectResponse("/login", status_code=303)
    return render(request, "setup.html", title="Create your vendor account", error=None)


@router.post("/setup", dependencies=[Depends(verify_csrf)])
def setup(
    request: Request,
    vendor_name: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    load_sample_data: bool = Form(False),
    db: Session = Depends(get_db),
):
    if db.scalar(select(User.id).limit(1)) is not None:
        return RedirectResponse("/login", status_code=303)
    vendor_name, full_name, email = vendor_name.strip(), full_name.strip(), email.strip().lower()
    if not vendor_name or not full_name or "@" not in email:
        return render(request, "setup.html", title="Create your vendor account",
                      error="Enter a valid business name, your name and a work email.", status_code=422)
    if len(password) < MIN_PASSWORD_LENGTH:
        return render(request, "setup.html", title="Create your vendor account",
                      error=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", status_code=422)
    vendor = Vendor(name=vendor_name[:200])
    db.add(vendor)
    db.flush()
    provision_tenant_dsn(vendor)
    user = User(vendor_id=vendor.id, email=email[:254], full_name=full_name[:200],
                password_hash=hash_password(password), role="admin")
    db.add(user)
    db.flush()
    tenant_db = tenant_session(vendor)
    try:
        if load_sample_data:
            load_demo(tenant_db)
    finally:
        tenant_db.close()
    record(db, user, "vendor_created", f"sample_data={bool(load_sample_data)}")
    db.commit()
    start_session(request, user)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html", title="Sign in", error=None)


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()[:254]
    ip = request.client.host if request.client else "unknown"
    key = f"{ip}:{email}"
    if login_throttle.is_blocked(key):
        return render(request, "login.html", title="Sign in",
                      error="Too many attempts. Please wait 15 minutes before trying again.", status_code=429)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    encoded = user.password_hash if user else DUMMY_HASH
    valid = verify_password(password, encoded)
    if user is None or not valid or not user.is_active:
        login_throttle.record_failure(key)
        return render(request, "login.html", title="Sign in", error="Email or password is incorrect.", status_code=401)
    login_throttle.reset(key)
    start_session(request, user)
    record(db, user, "login")
    db.commit()
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
