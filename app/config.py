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
    secret_key: str
    secure_cookies: bool
    max_upload_mb: int
    allow_live_stripe: bool

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
    default_db = f"sqlite:///{(BASE_DIR / 'data' / 'profit_analytics.db').as_posix()}"
    return Settings(
        env=env,
        database_url=os.getenv("DATABASE_URL") or default_db,
        secret_key=secret,
        allow_live_stripe=os.getenv("ALLOW_LIVE_STRIPE", "false").lower() == "true",
        secure_cookies=os.getenv("SECURE_COOKIES", "false").lower() == "true",
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "25")),
    )


settings = load_settings()
