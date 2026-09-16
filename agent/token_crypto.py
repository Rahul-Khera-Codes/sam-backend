"""Shared encryption for OAuth integration tokens stored at rest (Google
Calendar, Gmail, Outlook access/refresh tokens) — mirrors
backend/app/core/token_crypto.py. Duplicated here because the agent is a
separate deployment/container with its own dependency tree, not a shared
import with the backend service.

Uses the same MARKETING_TOKEN_ENCRYPTION_KEY secret as the backend (copied
into agent/.env.local) so tokens encrypted by the backend can be decrypted
here, and vice versa when the agent refreshes a token itself.

decrypt_oauth_token() falls back to returning the value unchanged when it
isn't a valid Fernet token, because google_calendar_tokens/gmail_tokens/
outlook_tokens have existing rows stored as plaintext prior to this fix. Each
previously-plaintext row is transparently upgraded to encrypted the next time
it's refreshed/rewritten (access tokens refresh hourly), with no manual
backfill required.
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet | None:
    raw_key = os.getenv("MARKETING_TOKEN_ENCRYPTION_KEY", "")
    if not raw_key:
        return None
    try:
        return Fernet(raw_key.encode())
    except Exception:
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode()).digest())
        return Fernet(derived)


def encrypt_oauth_token(value: str | None) -> str | None:
    if not value:
        return value
    fernet = _fernet()
    if fernet is None:
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt_oauth_token(value: str | None) -> str | None:
    if not value:
        return value
    fernet = _fernet()
    if fernet is None:
        return value
    try:
        return fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return value
