"""
Google Calendar service — OAuth token management + Calendar API calls.

Flow:
  1. Frontend calls GET /integrations/google/auth-url  → backend returns OAuth URL
  2. User approves → Google redirects to GOOGLE_REDIRECT_URI with ?code=...
  3. Frontend sends code to POST /integrations/google/callback → backend exchanges for tokens, saves to DB
  4. On book/update/cancel appointment → this service creates/updates/deletes Google Calendar events

Token refresh is automatic: every call checks expiry and refreshes if needed before hitting the API.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/userinfo.email openid"


# ── OAuth URL ─────────────────────────────────────────────────────────────────

def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """
    Returns the Google OAuth consent URL. The frontend redirects the user here.
    `state` should encode the user_id + business_id so the callback knows who to save tokens for.
    """
    params = (
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={SCOPES}"
        f"&access_type=offline"
        f"&prompt=consent"        # Always show consent so we get refresh_token every time
        f"&state={state}"
    )
    return GOOGLE_AUTH_BASE + params


# ── Token exchange ────────────────────────────────────────────────────────────

async def exchange_code_for_tokens(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict:
    """
    Exchange OAuth authorization code for access_token + refresh_token.
    Returns raw token dict from Google.
    Raises httpx.HTTPStatusError on failure.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """Refresh the access token using the stored refresh token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def revoke_token(token: str) -> None:
    """Revoke an access or refresh token (used on disconnect)."""
    async with httpx.AsyncClient() as client:
        await client.post(GOOGLE_REVOKE_URL, params={"token": token})


# ── Token helpers ─────────────────────────────────────────────────────────────

def token_expiry_from_response(token_data: dict) -> datetime:
    """Convert expires_in seconds to an absolute UTC datetime."""
    expires_in = token_data.get("expires_in", 3600)
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)  # 60s buffer


def is_token_expired(expiry: datetime) -> bool:
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= expiry


# ── Google Calendar API ───────────────────────────────────────────────────────

def _appointment_to_event(appointment: dict) -> dict:
    """
    Convert an appointments table row to a Google Calendar event body.
    appointment must have: client_name, service, appointment_date (YYYY-MM-DD),
    appointment_time (HH:MM), duration (minutes as string or int), notes, location_name (optional)
    """
    date = appointment.get("appointment_date", "")
    time_str = appointment.get("appointment_time", "00:00")
    duration_raw = appointment.get("duration", "60")
    try:
        duration_minutes = int(str(duration_raw).split()[0])
    except (ValueError, IndexError):
        duration_minutes = 60

    # Build ISO datetime strings
    start_dt = f"{date}T{time_str}:00"
    hour, minute = map(int, time_str.split(":"))
    end_minute = minute + duration_minutes
    end_hour = hour + end_minute // 60
    end_minute = end_minute % 60
    end_dt = f"{date}T{end_hour:02d}:{end_minute:02d}:00"

    description_parts = []
    if appointment.get("service"):
        description_parts.append(f"Service: {appointment['service']}")
    if appointment.get("notes"):
        description_parts.append(f"Notes: {appointment['notes']}")

    event = {
        "summary": f"{appointment.get('client_name', 'Client')} — {appointment.get('service', 'Appointment')}",
        "description": "\n".join(description_parts),
        "start": {"dateTime": start_dt, "timeZone": "UTC"},
        "end": {"dateTime": end_dt, "timeZone": "UTC"},
    }

    if appointment.get("location_name"):
        event["location"] = appointment["location_name"]

    return event


async def _get_valid_access_token(
    token_row: dict,
    client_id: str,
    client_secret: str,
    supabase,
) -> Optional[str]:
    """
    Returns a valid access token, refreshing if expired.
    Updates the DB row if refreshed.
    Returns None if refresh fails.
    """
    expiry_raw = token_row.get("token_expiry")
    if isinstance(expiry_raw, str):
        try:
            expiry = datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))
        except ValueError:
            expiry = datetime.now(timezone.utc)
    else:
        expiry = expiry_raw or datetime.now(timezone.utc)

    if is_token_expired(expiry):
        try:
            refreshed = await refresh_access_token(
                token_row["refresh_token"], client_id, client_secret
            )
            new_expiry = token_expiry_from_response(refreshed)
            supabase.table("google_calendar_tokens").update({
                "access_token": refreshed["access_token"],
                "token_expiry": new_expiry.isoformat(),
            }).eq("id", token_row["id"]).execute()
            return refreshed["access_token"]
        except Exception as e:
            logger.warning("Failed to refresh Google token for staff %s: %s", token_row.get("staff_id"), e)
            return None

    return token_row["access_token"]


async def create_calendar_event(
    token_row: dict,
    appointment: dict,
    client_id: str,
    client_secret: str,
    supabase,
) -> Optional[str]:
    """
    Create a Google Calendar event for the appointment.
    Returns the google_event_id or None on failure.
    """
    access_token = await _get_valid_access_token(token_row, client_id, client_secret, supabase)
    if not access_token:
        return None

    event_body = _appointment_to_event(appointment)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GOOGLE_CALENDAR_BASE}/calendars/primary/events",
                headers={"Authorization": f"Bearer {access_token}"},
                json=event_body,
            )
            resp.raise_for_status()
            return resp.json().get("id")
    except Exception as e:
        logger.warning("Failed to create Google Calendar event: %s", e)
        return None


async def update_calendar_event(
    token_row: dict,
    google_event_id: str,
    appointment: dict,
    client_id: str,
    client_secret: str,
    supabase,
) -> bool:
    """Update an existing Google Calendar event. Returns True on success."""
    access_token = await _get_valid_access_token(token_row, client_id, client_secret, supabase)
    if not access_token:
        return False

    event_body = _appointment_to_event(appointment)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{GOOGLE_CALENDAR_BASE}/calendars/primary/events/{google_event_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                json=event_body,
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.warning("Failed to update Google Calendar event %s: %s", google_event_id, e)
        return False


async def delete_calendar_event(
    token_row: dict,
    google_event_id: str,
    client_id: str,
    client_secret: str,
    supabase,
) -> bool:
    """Delete a Google Calendar event. Returns True on success."""
    access_token = await _get_valid_access_token(token_row, client_id, client_secret, supabase)
    if not access_token:
        return False

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{GOOGLE_CALENDAR_BASE}/calendars/primary/events/{google_event_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            # 204 = deleted, 410 = already gone — both are fine
            if resp.status_code not in (204, 410):
                resp.raise_for_status()
            return True
    except Exception as e:
        logger.warning("Failed to delete Google Calendar event %s: %s", google_event_id, e)
        return False


# ── Supabase token lookup ─────────────────────────────────────────────────────

def get_token_row(supabase, staff_id: str) -> Optional[dict]:
    """Fetch the google_calendar_tokens row for a staff member. Returns None if not connected."""
    try:
        r = (
            supabase.table("google_calendar_tokens")
            .select("*")
            .eq("staff_id", staff_id)
            .limit(1)
            .execute()
        )
        data = getattr(r, "data", None) or []
        return data[0] if data else None
    except Exception as e:
        logger.warning("Failed to fetch Google token row for staff %s: %s", staff_id, e)
        return None
