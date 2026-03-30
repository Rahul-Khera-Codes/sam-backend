"""
Google Calendar helpers for the voice agent (async HTTP).
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from constants import GOOGLE_TOKEN_URL, GOOGLE_CALENDAR_BASE

logger = logging.getLogger("voice-agent")


async def _gcal_refresh_token(refresh_token: str) -> dict | None:
    """Refresh a Google access token. Returns token dict or None."""
    try:
        import httpx
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            return None
        async with httpx.AsyncClient() as http:
            r = await http.post(GOOGLE_TOKEN_URL, data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            })
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning("Google token refresh failed: %s", e)
    return None


async def _gcal_get_valid_token(supabase, staff_id: str) -> str | None:
    """
    Fetch the Google Calendar token for a staff member and refresh if expired.
    Returns a valid access token or None if not connected / refresh failed.
    """
    try:
        r = supabase.table("google_calendar_tokens").select("*").eq("staff_id", staff_id).limit(1).execute()
        data = getattr(r, "data", None) or []
        if not data:
            return None
        row = data[0]

        expiry_raw = row.get("token_expiry")
        if expiry_raw:
            try:
                expiry = datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00"))
            except ValueError:
                expiry = datetime.now(timezone.utc)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= expiry:
                refreshed = await _gcal_refresh_token(row["refresh_token"])
                if not refreshed:
                    return None
                new_expiry = datetime.now(timezone.utc) + timedelta(seconds=refreshed.get("expires_in", 3600) - 60)
                supabase.table("google_calendar_tokens").update({
                    "access_token": refreshed["access_token"],
                    "token_expiry": new_expiry.isoformat(),
                }).eq("id", row["id"]).execute()
                return refreshed["access_token"]

        return row["access_token"]
    except Exception as e:
        logger.warning("Failed to get Google token for staff %s: %s", staff_id, e)
        return None


def _gcal_build_event(appointment: dict) -> dict:
    """Build a Google Calendar event body from an appointment dict."""
    date = appointment.get("appointment_date", "")
    time_str = appointment.get("appointment_time", "00:00")
    duration_raw = appointment.get("duration", "60")
    try:
        duration_minutes = int(str(duration_raw).split()[0])
    except (ValueError, IndexError):
        duration_minutes = 60

    hour, minute = map(int, time_str.split(":"))
    end_total = hour * 60 + minute + duration_minutes
    end_hour, end_minute = divmod(end_total, 60)

    description_parts = []
    if appointment.get("service"):
        description_parts.append(f"Service: {appointment['service']}")
    if appointment.get("notes"):
        description_parts.append(f"Notes: {appointment['notes']}")

    return {
        "summary": f"{appointment.get('client_name', 'Client')} — {appointment.get('service', 'Appointment')}",
        "description": "\n".join(description_parts),
        "start": {"dateTime": f"{date}T{time_str}:00", "timeZone": "UTC"},
        "end": {"dateTime": f"{date}T{end_hour:02d}:{end_minute:02d}:00", "timeZone": "UTC"},
    }


async def _gcal_create_event(supabase, staff_id: str, appointment: dict) -> str | None:
    """Create a Google Calendar event. Returns google_event_id or None."""
    access_token = await _gcal_get_valid_token(supabase, staff_id)
    if not access_token:
        return None
    try:
        import httpx
        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{GOOGLE_CALENDAR_BASE}/calendars/primary/events",
                headers={"Authorization": f"Bearer {access_token}"},
                json=_gcal_build_event(appointment),
            )
            if r.status_code == 200:
                return r.json().get("id")
    except Exception as e:
        logger.warning("Failed to create Google Calendar event: %s", e)
    return None


async def _gcal_update_event(supabase, staff_id: str, google_event_id: str, appointment: dict) -> bool:
    """Update an existing Google Calendar event."""
    access_token = await _gcal_get_valid_token(supabase, staff_id)
    if not access_token:
        return False
    try:
        import httpx
        async with httpx.AsyncClient() as http:
            r = await http.patch(
                f"{GOOGLE_CALENDAR_BASE}/calendars/primary/events/{google_event_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                json=_gcal_build_event(appointment),
            )
            return r.status_code == 200
    except Exception as e:
        logger.warning("Failed to update Google Calendar event %s: %s", google_event_id, e)
    return False


async def _gcal_delete_event(supabase, staff_id: str, google_event_id: str) -> bool:
    """Delete a Google Calendar event."""
    access_token = await _gcal_get_valid_token(supabase, staff_id)
    if not access_token:
        return False
    try:
        import httpx
        async with httpx.AsyncClient() as http:
            r = await http.delete(
                f"{GOOGLE_CALENDAR_BASE}/calendars/primary/events/{google_event_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            return r.status_code in (204, 410)
    except Exception as e:
        logger.warning("Failed to delete Google Calendar event %s: %s", google_event_id, e)
    return False


def _gcal_get_superadmin_id(supabase, business_id: str) -> str | None:
    """Return the user_id of the first super_admin for a business, or None."""
    try:
        r = (
            supabase.table("user_roles")
            .select("user_id")
            .eq("business_id", business_id)
            .eq("role", "super_admin")
            .limit(1)
            .execute()
        )
        data = getattr(r, "data", None) or []
        return data[0]["user_id"] if data else None
    except Exception as e:
        logger.warning("Failed to fetch superadmin for business %s: %s", business_id, e)
        return None
