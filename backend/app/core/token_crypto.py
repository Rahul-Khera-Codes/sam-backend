"""Shared encryption for OAuth integration tokens stored at rest (Google
Calendar, Gmail, Outlook access/refresh tokens) — these are confidential
credentials granting calendar/email read-write access, not just opaque IDs.

Reuses the same Fernet key already configured for marketing-platform token
encryption (MARKETING_TOKEN_ENCRYPTION_KEY) rather than requiring a new secret
to be provisioned before this fix can take effect in production.

Unlike marketing_social_service.py's _decrypt_token (safe to assume every
stored value there was always encrypted), decrypt_oauth_token() falls back to
returning the value unchanged when it isn't a valid Fernet token, because
google_calendar_tokens/gmail_tokens/outlook_tokens have existing production
rows stored as plaintext prior to this fix. Every write from here on encrypts;
each previously-plaintext row is transparently upgraded to encrypted the next
time it's refreshed/rewritten (access tokens refresh hourly), with no manual
backfill required.
"""

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Optional[Fernet]:
    raw_key = settings.marketing_token_encryption_key
    if not raw_key:
        return None
    try:
        return Fernet(raw_key.encode())
    except Exception:
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode()).digest())
        return Fernet(derived)


def encrypt_oauth_token(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    fernet = _fernet()
    if fernet is None:
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt_oauth_token(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    fernet = _fernet()
    if fernet is None:
        return value
    try:
        return fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        # Legacy plaintext row from before this fix — use as-is. It will be
        # re-written encrypted the next time it's refreshed.
        return value
