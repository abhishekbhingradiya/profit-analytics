import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.integrations.stripe_client import StripeClient, StripeError, is_test_key
from app.integrations.stripe_sync import record_sync, sync_stripe
from app.models import Connection, SyncRun, User
from app.security import require_role, verify_csrf
from app.services.audit import record
from app.services.datasets import dataset_status
from app.services.secrets import SecretUnavailable, decrypt_secret, encrypt_secret
from app.templating import flash, render

router = APIRouter()


def _get_connection(db: Session, org_id: int) -> Connection | None:
    return db.scalar(select(Connection).where(Connection.org_id == org_id, Connection.provider == "stripe"))


def _redirect() -> RedirectResponse:
    return RedirectResponse("/integrations", status_code=303)


@router.get("/integrations")
def integrations_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    connection = _get_connection(db, user.org_id)
    runs = db.scalars(
        select(SyncRun).where(SyncRun.org_id == user.org_id).order_by(SyncRun.started_at.desc()).limit(10)
    ).all()
    parsed_runs = [
        {"run": run, "stats": json.loads(run.stats) if run.stats else None}
        for run in runs
    ]
    return render(
        request,
        "pages/integrations.html",
        title="Integrations",
        description="Connect billing data so revenue reflects your live subscription base.",
        user=user,
        org=user.organization,
        data_status=dataset_status(db, user.org_id),
        active="integrations",
        connection=connection,
        runs=parsed_runs,
        allow_live=settings.allow_live_stripe,
    )


@router.post("/integrations/stripe/connect", dependencies=[Depends(verify_csrf)])
def connect_stripe(
    request: Request,
    api_key: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    api_key = api_key.strip()
    if not is_test_key(api_key) and not settings.allow_live_stripe:
        flash(request, "error", "Only Stripe test-mode keys (sk_test_/rk_test_) are accepted until ALLOW_LIVE_STRIPE is enabled.")
        return _redirect()
    try:
        account = StripeClient(api_key).account()
    except StripeError as exc:
        flash(request, "error", f"Stripe rejected the connection: {exc}")
        return _redirect()
    label = ((account.get("settings") or {}).get("dashboard") or {}).get("display_name") or account.get("id", "Stripe")
    connection = _get_connection(db, user.org_id)
    if connection is None:
        connection = Connection(org_id=user.org_id, provider="stripe")
        db.add(connection)
    connection.account_label = str(label)[:200]
    connection.encrypted_secret = encrypt_secret(api_key)
    record(db, user, "integration_connected", f"provider=stripe; account={label}")
    db.commit()
    flash(request, "success", f"Connected Stripe account “{label}”. Run a sync to import subscriptions.")
    return _redirect()


@router.post("/integrations/stripe/sync", dependencies=[Depends(verify_csrf)])
def sync_stripe_now(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    connection = _get_connection(db, user.org_id)
    if connection is None:
        flash(request, "error", "Connect a Stripe account first.")
        return _redirect()
    try:
        client = StripeClient(decrypt_secret(connection.encrypted_secret))
        stats = sync_stripe(db, user.organization, client)
        connection.last_synced_at = datetime.now(timezone.utc)
        record_sync(db, connection, "success", stats)
        record(db, user, "integration_synced", f"provider=stripe; {stats}")
        db.commit()
    except (StripeError, SecretUnavailable, ValueError) as exc:
        db.rollback()
        record_sync(db, connection, "failed", error=str(exc))
        db.commit()
        flash(request, "error", f"Sync failed: {exc}")
        return _redirect()
    except Exception:
        db.rollback()
        raise
    flash(
        request,
        "success",
        f"Imported {stats['customers']} customers and {stats['revenue_rows']} revenue rows "
        f"({stats['first_month']} to {stats['last_month']}). Direct customer costs were cleared; shared cost pools were kept.",
    )
    return _redirect()


@router.post("/integrations/stripe/disconnect", dependencies=[Depends(verify_csrf)])
def disconnect_stripe(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    connection = _get_connection(db, user.org_id)
    if connection is not None:
        db.execute(delete(SyncRun).where(SyncRun.connection_id == connection.id))
        db.delete(connection)
        record(db, user, "integration_disconnected", "provider=stripe")
        db.commit()
        flash(request, "success", "Stripe disconnected. Imported data remains until you replace it.")
    return _redirect()
