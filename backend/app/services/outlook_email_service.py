"""
Microsoft Outlook OAuth integration.

Connect-flow only for now — builds the auth URL, exchanges the authorization
code for tokens, and refreshes them. Actual mail sending via Microsoft Graph
is a separate follow-up; Gmail (email_service.py) remains the only wired-up
sender for appointment confirmations, reminders, and notifications.

Token storage: outlook_tokens table, same (business_id, location_id) shape as
gmail_tokens.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

MS_AUTH_BASE = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"
OUTLOOK_SEND_SCOPE = "Mail.Send"
# Delegated scope requested — matches the permissions actually granted on the
# Azure app (Mail.Send, offline_access, User.Read). No Mail.Read/Calendars.ReadWrite
# yet — those need admin consent added in Azure before requesting them here.
OUTLOOK_SCOPE = "offline_access Mail.Send User.Read"


# ── OAuth URL ─────────────────────────────────────────────────────────────────

def build_outlook_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": OUTLOOK_SCOPE,
        "state": state,
    })
    return f"{MS_AUTH_BASE}?{params}"


# ── Token exchange / refresh ──────────────────────────────────────────────────

async def exchange_code_for_tokens(
    code: str, client_id: str, client_secret: str, redirect_uri: str
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            MS_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": OUTLOOK_SCOPE,
            },
        )
        if not resp.is_success:
            logger.error("Outlook token exchange failed %s: %s", resp.status_code, resp.text[:300])
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(
    refresh_token: str, client_id: str, client_secret: str
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            MS_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "scope": OUTLOOK_SCOPE,
            },
        )
        if not resp.is_success:
            logger.error("Outlook token refresh failed %s: %s", resp.status_code, resp.text[:300])
        resp.raise_for_status()
        return resp.json()


# Note: unlike Google, Microsoft Graph has no token-revocation endpoint for
# delegated user consent. Disconnect can only delete our stored tokens — the
# user's actual consent grant persists until they remove it themselves at
# https://myaccount.microsoft.com/consents.


def token_expiry_from_response(token_data: dict) -> datetime:
    expires_in = int(token_data.get("expires_in", 3600))
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)


def _parse_scope_string(scope_string: Optional[str]) -> set[str]:
    if not scope_string:
        return set()
    return {scope.strip() for scope in scope_string.split() if scope.strip()}


def has_outlook_send_scope(scope_string: Optional[str]) -> bool:
    """Microsoft's token response already lists granted scopes — no separate introspection call needed."""
    return OUTLOOK_SEND_SCOPE in _parse_scope_string(scope_string)


async def fetch_microsoft_email(access_token: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GRAPH_ME_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        # Personal Microsoft accounts often have a null "mail" field — fall back to userPrincipalName.
        return data.get("mail") or data.get("userPrincipalName") or ""
