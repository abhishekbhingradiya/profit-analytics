"""Database-per-vendor routing.

Each vendor's DSN comes from TENANT_DATABASE_URL_TEMPLATE (hosted databases, e.g.
postgresql+psycopg://user:pass@host/sales_{tenant}). Development falls back to
one SQLite file per vendor; production refuses to start without the template.
"""

import logging
import threading
from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import User, Vendor
from app.security import get_current_user
from app.services.secrets import decrypt_secret, encrypt_secret
from app.tenant_models import TenantBase

log = logging.getLogger(__name__)

_engines: dict[int, Engine] = {}
_lock = threading.Lock()


def provision_tenant_dsn(vendor: Vendor) -> None:
    """Assign and encrypt the vendor's database DSN; call once at signup."""
    if settings.tenant_database_url_template:
        dsn = settings.tenant_database_url_template.format(tenant=f"vendor_{vendor.id}")
    else:
        settings.tenant_data_dir.mkdir(parents=True, exist_ok=True)
        dsn = f"sqlite:///{(settings.tenant_data_dir / f'vendor_{vendor.id}.db').as_posix()}"
        log.warning("No TENANT_DATABASE_URL_TEMPLATE set; vendor %s uses a local dev database", vendor.id)
    vendor.db_dsn_encrypted = encrypt_secret(dsn)


def engine_for(vendor: Vendor) -> Engine:
    with _lock:
        engine = _engines.get(vendor.id)
        if engine is not None:
            return engine
        dsn = decrypt_secret(vendor.db_dsn_encrypted)
        url = make_url(dsn)
        kwargs: dict = {"pool_pre_ping": True}
        if url.get_backend_name() == "sqlite":
            kwargs = {"connect_args": {"check_same_thread": False}}
        engine = create_engine(dsn, **kwargs)
        TenantBase.metadata.create_all(engine)
        _engines[vendor.id] = engine
        return engine


def tenant_session(vendor: Vendor) -> Session:
    return sessionmaker(bind=engine_for(vendor), expire_on_commit=False)()


def get_tenant_db(user: User = Depends(get_current_user)) -> Iterator[Session]:
    session = tenant_session(user.vendor)
    try:
        yield session
    finally:
        session.close()


def dispose_engines() -> None:
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
