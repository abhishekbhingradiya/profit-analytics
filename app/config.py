import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    env: str
    database_url: str
    tenant_database_url_template: str | None
    tenant_data_dir: Path
    secret_key: str
    secure_cookies: bool

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def load_settings() -> Settings:
    env = os.getenv("APP_ENV", "development")
    secret = os.getenv("SECRET_KEY", "")
    if not secret:
        if env == "production":
            raise RuntimeError("SECRET_KEY must be set in production")
        secret = secrets.token_urlsafe(48)
        log.warning("SECRET_KEY not set; using a random key (sessions reset on restart)")
    default_control = f"sqlite:///{(BASE_DIR / 'data' / 'control.db').as_posix()}"
    database_url = os.getenv("DATABASE_URL") or default_control
    template = os.getenv("TENANT_DATABASE_URL_TEMPLATE") or None
    if template and "{tenant}" not in template:
        raise RuntimeError("TENANT_DATABASE_URL_TEMPLATE must contain a {tenant} placeholder")
    if env == "production":
        if database_url.startswith("sqlite"):
            raise RuntimeError("Use a hosted control database (DATABASE_URL) in production, not SQLite")
        if not template:
            raise RuntimeError("TENANT_DATABASE_URL_TEMPLATE is required in production")
    return Settings(
        env=env,
        database_url=database_url,
        tenant_database_url_template=template,
        tenant_data_dir=BASE_DIR / "data" / "tenants",
        secret_key=secret,
        secure_cookies=os.getenv("SECURE_COOKIES", "false").lower() == "true",
    )


settings = load_settings()
