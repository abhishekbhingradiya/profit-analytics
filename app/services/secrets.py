"""Symmetric encryption for connector credentials, keyed from SECRET_KEY.

Rotating SECRET_KEY invalidates stored connector secrets; users must reconnect.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretUnavailable(Exception):
    pass


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode()
    except (InvalidToken, ValueError) as exc:
        raise SecretUnavailable("Stored credential cannot be decrypted; reconnect the integration.") from exc
