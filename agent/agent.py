"""
SAM Voice Agent — LiveKit Agents (Realtime) entrypoint.

Reads business_id, location_id, call_id from participant metadata (set by backend token)
and builds instructions + booking tools from:
- Business name + location (welcome)
- Global settings (businesses: language, country, date_format, time_format)
- Brand voice (brand_voice_profiles: tone, style, vocabulary, do_not_say, sample_responses)
- Services (services table)
- Staff + availability (user_availability, user_availability_overrides, user_services)
- Appointments CRUD (create, find, update, cancel)
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, function_tool, RunContext
from livekit.plugins import (
    openai,
    noise_cancellation,
)


load_dotenv(".env.local")

logger = logging.getLogger("voice-agent")

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"

DEFAULT_INSTRUCTIONS = """
You are a helpful AI customer service assistant.
Be friendly, professional, and concise in all responses.
If you cannot help with something, offer to transfer the caller to a human agent.

Booking a new appointment:
1. Ask which location they prefer (if the business has multiple).
2. Ask what service they need, then use get_services if you don't already have the list.
3. Ask if they have a preferred staff member; otherwise offer the next available using get_staff_for_service.
4. Use get_available_slots to find open times and offer a few options.
5. Collect the customer's name and phone number.
6. Repeat all details back clearly before calling book_appointment.
7. Confirm the booking ID once done.

Rescheduling or cancelling:
1. Ask for the customer's name to look up their appointment using find_appointments.
2. Confirm which appointment they mean.
3. For reschedule: check new availability with get_available_slots, then call update_appointment.
4. For cancel: confirm once more verbally, then call cancel_appointment.

General rules:
- Never invent availability — always use the tools to check.
- Confirm details clearly before any write action (book, update, cancel).
- If a tool returns an error, apologise and offer to transfer to a human.
"""


# ── Google Calendar helpers (agent-side, async HTTP) ─────────────────────────

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


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _get_supabase():
    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if url and key:
            return create_client(url, key)
    except Exception as e:
        logger.warning("Supabase not available: %s", e)
    return None


def _fetch_business(supabase, business_id: str) -> dict | None:
    if not supabase or not business_id:
        return None
    try:
        r = supabase.table("businesses").select("*").eq("id", business_id).limit(1).execute()
        data = getattr(r, "data", None) or []
        return data[0] if data and isinstance(data[0], dict) else None
    except Exception as e:
        logger.warning("Failed to fetch business: %s", e)
        return None


def _fetch_location(supabase, location_id: str) -> dict | None:
    if not supabase or not location_id:
        return None
    try:
        r = supabase.table("locations").select("*").eq("id", location_id).limit(1).execute()
        data = getattr(r, "data", None) or []
        return data[0] if data and isinstance(data[0], dict) else None
    except Exception as e:
        logger.warning("Failed to fetch location: %s", e)
        return None


def _fetch_locations(supabase, business_id: str) -> list[dict]:
    if not supabase or not business_id:
        return []
    try:
        r = (
            supabase.table("locations")
            .select("id, name, address, phone")
            .eq("business_id", business_id)
            .execute()
        )
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch locations: %s", e)
        return []


def _fetch_services(supabase, business_id: str) -> list[dict]:
    """Fetch active services for the business."""
    if not supabase or not business_id:
        return []
    try:
        r = (
            supabase.table("services")
            .select("id, name, description, duration_minutes, price")
            .eq("business_id", business_id)
            .eq("is_active", True)
            .execute()
        )
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch services: %s", e)
        return []


def _fetch_staff_with_ids(supabase, business_id: str) -> list[dict]:
    """
    Fetch all staff for the business.
    Returns list of {user_id, name, location_ids}.
    """
    if not supabase or not business_id:
        return []
    try:
        ur = supabase.table("user_roles").select("user_id").eq("business_id", business_id).execute()
        user_ids = [r["user_id"] for r in (getattr(ur, "data", None) or []) if r.get("user_id")]
        if not user_ids:
            return []

        ul = (
            supabase.table("user_locations")
            .select("user_id, location_id")
            .in_("user_id", user_ids)
            .execute()
        )
        pf = (
            supabase.table("profiles")
            .select("id, first_name, last_name")
            .in_("id", user_ids)
            .execute()
        )

        name_map: dict[str, str] = {}
        for row in getattr(pf, "data", None) or []:
            uid = row.get("id")
            if uid:
                first = (row.get("first_name") or "").strip()
                last = (row.get("last_name") or "").strip()
                name_map[uid] = f"{first} {last}".strip() or "Staff"

        loc_map: dict[str, list[str]] = {}
        for row in getattr(ul, "data", None) or []:
            uid = row.get("user_id")
            lid = row.get("location_id")
            if uid and lid:
                loc_map.setdefault(uid, []).append(lid)

        return [
            {
                "user_id": uid,
                "name": name_map.get(uid, "Staff"),
                "location_ids": loc_map.get(uid, []),
            }
            for uid in user_ids
        ]
    except Exception as e:
        logger.warning("Failed to fetch staff: %s", e)
        return []


def _fetch_user_service_ids(supabase, user_ids: list[str]) -> dict[str, list[str]]:
    """Returns {user_id: [service_id, ...]}."""
    if not supabase or not user_ids:
        return {}
    try:
        r = (
            supabase.table("user_services")
            .select("user_id, service_id")
            .in_("user_id", user_ids)
            .execute()
        )
        result: dict[str, list[str]] = {}
        for row in getattr(r, "data", None) or []:
            uid = row.get("user_id")
            sid = row.get("service_id")
            if uid and sid:
                result.setdefault(uid, []).append(sid)
        return result
    except Exception as e:
        logger.warning("Failed to fetch user services: %s", e)
        return {}


def _fetch_user_availability(supabase, user_id: str) -> list[dict]:
    """Fetch weekly recurring availability for a staff member."""
    if not supabase or not user_id:
        return []
    try:
        r = (
            supabase.table("user_availability")
            .select("day_of_week, start_time, end_time, is_available")
            .eq("user_id", user_id)
            .execute()
        )
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch user availability: %s", e)
        return []


def _fetch_user_overrides(supabase, user_id: str, target_date: str) -> list[dict]:
    """Fetch date-specific availability overrides (time off) for a staff member."""
    if not supabase or not user_id:
        return []
    try:
        r = (
            supabase.table("user_availability_overrides")
            .select("is_unavailable, start_time, end_time")
            .eq("user_id", user_id)
            .eq("override_date", target_date)
            .execute()
        )
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch user overrides: %s", e)
        return []


def _fetch_appointments_on_date(supabase, user_id: str, target_date: str) -> list[dict]:
    """Fetch existing booked appointments for a staff member on a date."""
    if not supabase or not user_id:
        return []
    try:
        r = (
            supabase.table("appointments")
            .select("appointment_time, duration")
            .eq("assigned_user_id", user_id)
            .eq("appointment_date", target_date)
            .execute()
        )
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch appointments on date: %s", e)
        return []


def _compute_available_slots(
    availability: list[dict],
    overrides: list[dict],
    booked: list[dict],
    target_date: str,
    slot_minutes: int = 60,
) -> list[str]:
    """
    Compute free time slots for a given date.
    Returns list of "HH:MM" strings (24h).
    """
    try:
        d = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        return []

    # day_of_week enum matches Python weekday: Mon=0 … Sun=6
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_name = day_names[d.weekday()]

    # Find working window for this day
    work_start = work_end = None
    for row in availability:
        if row.get("day_of_week") == day_name and row.get("is_available"):
            st, et = row.get("start_time"), row.get("end_time")
            if st and et:
                work_start = datetime.strptime(st[:5], "%H:%M")
                work_end = datetime.strptime(et[:5], "%H:%M")
            break

    if not work_start or not work_end:
        return []

    # Full-day unavailability override
    for ov in overrides:
        if ov.get("is_unavailable") and not ov.get("start_time"):
            return []

    # Build busy intervals
    busy: list[tuple[datetime, datetime]] = []

    for appt in booked:
        at = appt.get("appointment_time")
        dur_raw = str(appt.get("duration") or slot_minutes)
        if at:
            try:
                dur_digits = "".join(c for c in dur_raw.split()[0] if c.isdigit())
                dur_min = int(dur_digits) if dur_digits else slot_minutes
            except (ValueError, AttributeError):
                dur_min = slot_minutes
            try:
                s = datetime.strptime(at[:5], "%H:%M")
                busy.append((s, s + timedelta(minutes=dur_min)))
            except ValueError:
                pass

    for ov in overrides:
        if ov.get("is_unavailable") and ov.get("start_time") and ov.get("end_time"):
            try:
                s = datetime.strptime(ov["start_time"][:5], "%H:%M")
                e = datetime.strptime(ov["end_time"][:5], "%H:%M")
                busy.append((s, e))
            except ValueError:
                pass

    # Generate slots
    slots: list[str] = []
    current = work_start
    while current + timedelta(minutes=slot_minutes) <= work_end:
        slot_end = current + timedelta(minutes=slot_minutes)
        if not any(current < b_end and slot_end > b_start for b_start, b_end in busy):
            slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=slot_minutes)

    return slots


def _fmt_time_12h(t: str) -> str:
    """Convert HH:MM (24h) to 12h AM/PM string."""
    try:
        h, m = map(int, t.split(":"))
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {suffix}"
    except Exception:
        return t


# ── Instruction builders ──────────────────────────────────────────────────────

def _format_global_settings(business: dict) -> str:
    parts = []
    lang = business.get("language")
    country = business.get("country")
    date_fmt = business.get("date_format")
    time_fmt = business.get("time_format")
    if lang or country:
        locale = " and ".join(p for p in [lang, country] if p)
        if locale:
            parts.append(f"Use the business language and region: {locale}. Speak in that language unless the caller uses another.")
    if date_fmt:
        parts.append(f"When stating dates use this format: {date_fmt}.")
    if time_fmt:
        parts.append(f"When stating times use {time_fmt} format.")
    if not parts:
        return ""
    return "Global settings: " + " ".join(parts) + "\n\n"


def _format_brand_voice(profile: dict) -> str:
    parts = []
    tone = profile.get("tone")
    style = profile.get("style")
    if tone:
        parts.append(f"Tone: {tone}.")
    if style:
        parts.append(f"Style: {style}.")

    vocabulary = profile.get("vocabulary")
    if vocabulary is not None:
        if isinstance(vocabulary, str):
            try:
                vocabulary = json.loads(vocabulary)
            except json.JSONDecodeError:
                vocabulary = None
        if isinstance(vocabulary, list) and vocabulary:
            preferred, avoid = [], []
            for item in vocabulary:
                if isinstance(item, dict):
                    if item.get("preferred"):
                        preferred.append(str(item["preferred"]))
                    if item.get("avoid"):
                        avoid.append(str(item["avoid"]))
            if preferred:
                parts.append(f"Prefer saying: {', '.join(preferred)}.")
            if avoid:
                parts.append(f"Avoid saying: {', '.join(avoid)}.")

    do_not_say = profile.get("do_not_say")
    if do_not_say and isinstance(do_not_say, list):
        phrases = [str(p) for p in do_not_say if p]
        if phrases:
            parts.append(f"Never say these words or phrases: {', '.join(phrases)}.")

    sample_responses = profile.get("sample_responses")
    if sample_responses is not None:
        if isinstance(sample_responses, str):
            try:
                sample_responses = json.loads(sample_responses)
            except json.JSONDecodeError:
                sample_responses = None
        if isinstance(sample_responses, list) and sample_responses:
            examples = []
            for item in sample_responses[:3]:
                if isinstance(item, dict) and item.get("scenario") and item.get("response"):
                    examples.append(f"Example ({item['scenario']}): \"{item['response']}\"")
            if examples:
                parts.append("Follow the style of these example responses: " + "; ".join(examples) + ".")

    if not parts:
        return ""
    return "Brand voice: " + " ".join(parts) + "\n\n"


def _format_locations_and_employees(
    locations: list[dict],
    employees_by_location: dict[str, list[str]],
) -> str:
    if not locations:
        return ""
    lines = []
    for loc in locations:
        loc_id = loc.get("id")
        name = loc.get("name") or "Unknown"
        address = loc.get("address") or ""
        phone = loc.get("phone") or ""
        parts = [f"Location: {name}"]
        if address:
            parts.append(f"address: {address}")
        if phone:
            parts.append(f"phone: {phone}")
        staff = (employees_by_location.get(loc_id) if loc_id else []) or []
        if staff:
            parts.append(f"staff: {', '.join(staff)}")
        lines.append("; ".join(parts))
    return "Locations and staff: " + " | ".join(lines) + "\n\n"


def _fetch_business_hours(supabase, business_id: str) -> list[dict]:
    """Fetch weekly business hours from business_hours table."""
    if not supabase or not business_id:
        return []
    try:
        r = (
            supabase.table("business_hours")
            .select("day_of_week, open_time, close_time, is_open")
            .eq("business_id", business_id)
            .execute()
        )
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch business hours: %s", e)
        return []


def _fetch_knowledge_base(supabase, business_id: str) -> list[dict]:
    """Fetch text entries from knowledge_base table (excludes unprocessed files)."""
    if not supabase or not business_id:
        return []
    try:
        r = (
            supabase.table("knowledge_base")
            .select("title, text_content")
            .eq("business_id", business_id)
            .eq("content_type", "text")
            .execute()
        )
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch knowledge base: %s", e)
        return []


def _format_business_details(business: dict) -> str:
    """Format full business info block for the prompt."""
    parts = []
    if business.get("type"):
        parts.append(f"Business type: {business['type']}.")
    if business.get("phone"):
        parts.append(f"Phone: {business['phone']}.")
    if business.get("email"):
        parts.append(f"Email: {business['email']}.")
    if business.get("address"):
        parts.append(f"Address: {business['address']}.")
    if business.get("website"):
        parts.append(f"Website: {business['website']}.")
    if business.get("service_area"):
        parts.append(f"Service area: {business['service_area']}.")
    if business.get("payment_methods"):
        parts.append(f"Payment methods accepted: {business['payment_methods']}.")
    if business.get("extra_fees"):
        parts.append(f"Extra fees: {business['extra_fees']}.")
    if business.get("return_policy"):
        parts.append(f"Return/refund policy: {business['return_policy']}.")
    if business.get("warranty_info"):
        parts.append(f"Warranty: {business['warranty_info']}.")
    if business.get("terms_conditions"):
        parts.append(f"Terms & conditions: {business['terms_conditions']}.")
    if business.get("privacy_policy"):
        parts.append(f"Privacy policy: {business['privacy_policy']}.")
    if not parts:
        return ""
    return "Business details: " + " ".join(parts) + "\n\n"


def _format_business_hours(hours: list[dict]) -> str:
    """Format business hours into a readable prompt block."""
    if not hours:
        return ""
    day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_label = {
        "monday": "Mon", "tuesday": "Tue", "wednesday": "Wed",
        "thursday": "Thu", "friday": "Fri", "saturday": "Sat", "sunday": "Sun",
    }
    hours_map = {row["day_of_week"]: row for row in hours if row.get("day_of_week")}

    def fmt_time(t: str | None) -> str:
        if not t:
            return ""
        try:
            h, m = map(int, t[:5].split(":"))
            suffix = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            return f"{h12}:{m:02d} {suffix}"
        except Exception:
            return t[:5]

    parts = []
    for day in day_order:
        row = hours_map.get(day)
        if not row:
            continue
        label = day_label.get(day, day.capitalize())
        if row.get("is_open"):
            open_t = fmt_time(row.get("open_time"))
            close_t = fmt_time(row.get("close_time"))
            parts.append(f"{label} {open_t}–{close_t}")
        else:
            parts.append(f"{label} Closed")

    if not parts:
        return ""
    return "Business hours: " + ", ".join(parts) + ".\n\n"


def _format_services_for_prompt(services: list[dict]) -> str:
    """Format services list for the system prompt (upfront knowledge)."""
    if not services:
        return ""
    lines = []
    for svc in services:
        name = svc.get("name", "")
        dur = svc.get("duration_minutes")
        price = svc.get("price")
        desc = svc.get("description") or ""
        parts = [f"- {name}"]
        details = []
        if dur:
            details.append(f"{dur} min")
        if price and price > 0:
            details.append(f"${price:.2f}")
        elif price == -1:
            details.append("price varies")
        if desc:
            details.append(desc)
        if details:
            parts.append(f"({', '.join(details)})")
        lines.append(" ".join(parts))
    return "Services offered:\n" + "\n".join(lines) + "\n\n"


def _format_knowledge_base(entries: list[dict]) -> str:
    """Format knowledge base text entries for the prompt."""
    if not entries:
        return ""
    blocks = []
    for entry in entries:
        text = (entry.get("text_content") or "").strip()
        if text:
            blocks.append(text)
    if not blocks:
        return ""
    return "Additional business information:\n" + "\n\n".join(blocks) + "\n\n"


def _fetch_brand_voice(supabase, business_id: str) -> dict | None:
    if not supabase or not business_id:
        return None
    try:
        r = (
            supabase.table("brand_voice_profiles")
            .select("*")
            .eq("business_id", business_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        data = getattr(r, "data", None) or []
        return data[0] if data and isinstance(data[0], dict) else None
    except Exception as e:
        logger.warning("Failed to fetch brand voice: %s", e)
        return None


def build_instructions(business_id: str | None, location_id: str | None) -> str:
    """
    Build the full agent system prompt from all business data in Supabase:
    welcome · global settings · business details · hours · services ·
    brand voice · locations + staff · knowledge base · default instructions
    """
    company_name = "your company"
    location_phrase = ""

    supabase = _get_supabase()

    # ── Core business row ─────────────────────────────────────────────────────
    business = _fetch_business(supabase, business_id) if business_id else None
    if business and business.get("name"):
        company_name = business["name"]

    global_block   = _format_global_settings(business)   if business    else ""
    details_block  = _format_business_details(business)  if business    else ""

    # ── Hours ─────────────────────────────────────────────────────────────────
    biz_hours    = _fetch_business_hours(supabase, business_id) if business_id else []
    hours_block  = _format_business_hours(biz_hours)

    # ── Services (upfront knowledge so agent doesn't need to call the tool) ───
    services       = _fetch_services(supabase, business_id) if business_id else []
    services_block = _format_services_for_prompt(services)

    # ── Brand voice ───────────────────────────────────────────────────────────
    brand       = _fetch_brand_voice(supabase, business_id) if business_id else None
    brand_block = _format_brand_voice(brand) if brand else ""

    # ── Locations + staff ─────────────────────────────────────────────────────
    locations_block = ""
    if business_id:
        locations = _fetch_locations(supabase, business_id)
        employees_by_location: dict[str, list[str]] = {}
        staff_list = _fetch_staff_with_ids(supabase, business_id)
        for s in staff_list:
            for lid in s.get("location_ids", []):
                employees_by_location.setdefault(lid, []).append(s["name"])
        locations_block = _format_locations_and_employees(locations, employees_by_location)

    # ── Knowledge base (free-text entries only; files not yet processed) ──────
    kb_entries = _fetch_knowledge_base(supabase, business_id) if business_id else []
    kb_block   = _format_knowledge_base(kb_entries)

    # ── Spoken location context for greeting ──────────────────────────────────
    if supabase and location_id:
        loc = _fetch_location(supabase, location_id)
        if loc:
            parts = [loc.get("name"), loc.get("city"), loc.get("state"), loc.get("country")]
            spoken = ", ".join(p for p in parts if p)
            if spoken:
                location_phrase = f" in {spoken}"

    # ── Assemble ──────────────────────────────────────────────────────────────
    welcome = (
        f"You are the AI phone receptionist for {company_name}{location_phrase}. "
        "Always start the call with a short, friendly welcome that includes the business name"
    )
    if location_phrase:
        welcome += " and the location"
    welcome += (
        ". Example: \"Thank you for calling "
        f"{company_name}{location_phrase}, how can I help you today?\" "
        "Then continue the conversation following these rules:\n\n"
    )

    return (
        welcome
        + global_block
        + details_block
        + hours_block
        + services_block
        + brand_block
        + locations_block
        + kb_block
        + DEFAULT_INSTRUCTIONS.strip()
    )


# ── Agent with booking tools ──────────────────────────────────────────────────

class Assistant(Agent):
    def __init__(
        self,
        instructions: str = DEFAULT_INSTRUCTIONS,
        supabase=None,
        business_id: str | None = None,
        call_id: str | None = None,
        locations: list[dict] | None = None,
        services: list[dict] | None = None,
        staff: list[dict] | None = None,
    ) -> None:
        super().__init__(instructions=instructions)
        self._supabase = supabase
        self._business_id = business_id
        self._call_id = call_id
        self._locations = locations or []
        self._services = services or []
        self._staff = staff or []

        # Lookup maps (case-insensitive name → record)
        self._location_by_name: dict[str, dict] = {
            loc["name"].lower(): loc for loc in self._locations if loc.get("name")
        }
        self._service_by_name: dict[str, dict] = {
            svc["name"].lower(): svc for svc in self._services if svc.get("name")
        }
        self._staff_by_name: dict[str, dict] = {
            s["name"].lower(): s for s in self._staff if s.get("name")
        }

        # user_id → name and name → user_id for booking
        self._staff_id_to_name: dict[str, str] = {
            s["user_id"]: s["name"] for s in self._staff if s.get("user_id")
        }
        self._location_id_to_name: dict[str, str] = {
            loc["id"]: loc["name"] for loc in self._locations if loc.get("id")
        }

        # Preload user_services mapping
        self._user_service_ids: dict[str, list[str]] = {}
        if supabase and self._staff:
            user_ids = [s["user_id"] for s in self._staff if s.get("user_id")]
            if user_ids:
                self._user_service_ids = _fetch_user_service_ids(supabase, user_ids)

    def _resolve_location(self, name: str) -> dict | None:
        """Resolve location by exact or partial name match."""
        loc = self._location_by_name.get(name.lower())
        if loc:
            return loc
        for k, v in self._location_by_name.items():
            if name.lower() in k or k in name.lower():
                return v
        return None

    def _resolve_service(self, name: str) -> dict | None:
        """Resolve service by exact or partial name match."""
        svc = self._service_by_name.get(name.lower())
        if svc:
            return svc
        for k, v in self._service_by_name.items():
            if name.lower() in k or k in name.lower():
                return v
        return None

    def _resolve_staff(self, name: str) -> dict | None:
        """Resolve staff by exact or partial name match."""
        s = self._staff_by_name.get(name.lower())
        if s:
            return s
        for k, v in self._staff_by_name.items():
            if name.lower() in k or k in name.lower():
                return v
        return None

    # ── Tools ──────────────────────────────────────────────────────────────────

    @function_tool()
    async def get_services(self, context: RunContext) -> str:
        """List all services offered by the business, including duration and price."""
        if not self._services:
            return "No services are currently configured. Please ask a staff member for details."
        lines = []
        for svc in self._services:
            name = svc.get("name", "Unknown")
            dur = svc.get("duration_minutes")
            price = svc.get("price")
            desc = svc.get("description") or ""
            parts = [name]
            if dur:
                parts.append(f"{dur} min")
            if price and price > 0:
                parts.append(f"${price:.2f}")
            elif price == -1:
                parts.append("price varies")
            if desc:
                parts.append(desc)
            lines.append(" — ".join(parts))
        return "Available services:\n" + "\n".join(lines)

    @function_tool()
    async def get_staff_for_service(
        self,
        context: RunContext,
        location_name: str,
        service_name: str,
    ) -> str:
        """
        Get staff members at a specific location who can perform a given service.
        Call this before offering staff choices to the customer.
        """
        loc = self._resolve_location(location_name)
        if not loc:
            available = ", ".join(l["name"] for l in self._locations)
            return f"Location '{location_name}' not found. Available locations: {available or 'none'}."

        svc = self._resolve_service(service_name)

        # Staff at this location
        loc_id = loc["id"]
        staff_at_loc = [s for s in self._staff if loc_id in s.get("location_ids", [])]
        if not staff_at_loc:
            return f"No staff found at {loc['name']}."

        # Filter by service capability if we found the service
        if svc:
            svc_id = svc["id"]
            capable = [
                s for s in staff_at_loc
                if svc_id in self._user_service_ids.get(s["user_id"], [])
            ]
            if capable:
                names = ", ".join(s["name"] for s in capable)
                return f"Staff at {loc['name']} who offer {svc['name']}: {names}."

        # Fallback: return all staff at location
        names = ", ".join(s["name"] for s in staff_at_loc)
        return f"Staff available at {loc['name']}: {names}."

    @function_tool()
    async def get_available_slots(
        self,
        context: RunContext,
        staff_name: str,
        date: str,
        service_name: str = "",
    ) -> str:
        """
        Get available appointment slots for a staff member on a specific date.
        date must be in YYYY-MM-DD format (e.g. 2026-03-20).
        service_name is optional — if provided the slot size matches the service duration.
        """
        if not self._supabase:
            return "Availability check is unavailable right now."

        staff = self._resolve_staff(staff_name)
        if not staff:
            return f"Staff member '{staff_name}' not found."

        slot_minutes = 60
        if service_name:
            svc = self._resolve_service(service_name)
            if svc and svc.get("duration_minutes"):
                slot_minutes = svc["duration_minutes"]

        user_id = staff["user_id"]
        availability = _fetch_user_availability(self._supabase, user_id)
        overrides = _fetch_user_overrides(self._supabase, user_id, date)
        booked = _fetch_appointments_on_date(self._supabase, user_id, date)

        slots = _compute_available_slots(availability, overrides, booked, date, slot_minutes)

        if not slots:
            return f"{staff['name']} has no available slots on {date}."

        formatted = ", ".join(_fmt_time_12h(s) for s in slots[:8])
        more = f" (and {len(slots) - 8} more)" if len(slots) > 8 else ""
        return f"{staff['name']} is available on {date} at: {formatted}{more}."

    @function_tool()
    async def book_appointment(
        self,
        context: RunContext,
        client_name: str,
        client_phone: str,
        service_name: str,
        staff_name: str,
        location_name: str,
        date: str,
        time: str,
        notes: str = "",
    ) -> str:
        """
        Book an appointment after confirming all details with the customer.
        date: YYYY-MM-DD  |  time: HH:MM (24h, e.g. 14:30)
        Always repeat details back to the customer and get verbal confirmation before calling this.
        """
        if not self._supabase or not self._business_id:
            return "Booking is unavailable right now. Please call back or book in person."

        staff = self._resolve_staff(staff_name)
        if not staff:
            return f"Could not find staff member '{staff_name}'. Please verify the name."

        loc = self._resolve_location(location_name)
        svc = self._resolve_service(service_name)

        duration_str = str(svc["duration_minutes"]) if svc and svc.get("duration_minutes") else "60"
        service_label = svc["name"] if svc else service_name
        location_label = loc["name"] if loc else location_name

        # Store phone in notes since appointments table has no client_phone column yet
        combined_notes = f"Phone: {client_phone}"
        if notes:
            combined_notes += f" | {notes}"
        if self._call_id:
            combined_notes += f" | call_id: {self._call_id}"

        try:
            row = {
                "business_id": self._business_id,
                "location_id": loc["id"] if loc else None,
                "assigned_user_id": staff["user_id"],
                "client_name": client_name,
                "service": service_label,
                "appointment_date": date,
                "appointment_time": time,
                "duration": duration_str,
                "notes": combined_notes,
                "created_by": "voice-agent",
            }
            r = self._supabase.table("appointments").insert(row).execute()
            data = getattr(r, "data", None) or []
            if data:
                appt_id = data[0].get("id", "")
                short_id = appt_id[:8].upper()

                # ── Google Calendar: create event on staff's calendar ──────
                gcal_event_id = await _gcal_create_event(
                    self._supabase,
                    staff["user_id"],
                    {**row, "client_name": client_name},
                )
                if gcal_event_id and appt_id:
                    try:
                        self._supabase.table("appointments").update(
                            {"google_event_id": gcal_event_id}
                        ).eq("id", appt_id).execute()
                    except Exception:
                        pass  # Non-fatal — booking already saved

                return (
                    f"Appointment confirmed! "
                    f"{client_name} is booked for {service_label} "
                    f"with {staff['name']} at {location_label} "
                    f"on {date} at {_fmt_time_12h(time)}. "
                    f"Confirmation reference: {short_id}."
                )
            return "The appointment was saved, but I could not retrieve the confirmation ID. Please note down the details."
        except Exception as e:
            logger.error("Failed to book appointment: %s", e)
            return "Sorry, there was an error saving the appointment. Please try again or contact us directly."

    @function_tool()
    async def find_appointments(
        self,
        context: RunContext,
        client_name: str,
    ) -> str:
        """
        Look up upcoming appointments for a customer by their name.
        Use this before rescheduling or cancelling to find the appointment ID.
        """
        if not self._supabase or not self._business_id:
            return "Appointment lookup is unavailable right now."
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            r = (
                self._supabase.table("appointments")
                .select("id, client_name, service, appointment_date, appointment_time, location_id, assigned_user_id")
                .eq("business_id", self._business_id)
                .gte("appointment_date", today)
                .ilike("client_name", f"%{client_name}%")
                .order("appointment_date")
                .limit(5)
                .execute()
            )
            data = getattr(r, "data", None) or []
            if not data:
                return f"No upcoming appointments found for '{client_name}'."

            lines = []
            for appt in data:
                adate = appt.get("appointment_date", "")
                atime = appt.get("appointment_time", "")
                svc = appt.get("service") or "appointment"
                cname = appt.get("client_name", "")
                sname = self._staff_id_to_name.get(appt.get("assigned_user_id", ""), "")
                lname = self._location_id_to_name.get(appt.get("location_id", ""), "")
                short_id = appt.get("id", "")[:8].upper()

                parts = [f"{cname}: {svc} on {adate} at {_fmt_time_12h(atime)}"]
                if sname:
                    parts.append(f"with {sname}")
                if lname:
                    parts.append(f"at {lname}")
                parts.append(f"(ref: {short_id})")
                lines.append(" ".join(parts))

            return "Upcoming appointments:\n" + "\n".join(lines)
        except Exception as e:
            logger.error("Failed to find appointments: %s", e)
            return "Could not look up appointments at this time."

    @function_tool()
    async def update_appointment(
        self,
        context: RunContext,
        appointment_ref: str,
        new_date: str = "",
        new_time: str = "",
        notes: str = "",
    ) -> str:
        """
        Reschedule an existing appointment.
        appointment_ref: the 8-character reference from find_appointments.
        new_date: YYYY-MM-DD  |  new_time: HH:MM (24h)
        """
        if not self._supabase or not self._business_id:
            return "Appointment updates are unavailable right now."
        try:
            updates: dict = {}
            if new_date:
                updates["appointment_date"] = new_date
            if new_time:
                updates["appointment_time"] = new_time
            if notes:
                updates["notes"] = notes
            if not updates:
                return "No changes were specified."

            # Find full UUID by prefix
            r_all = (
                self._supabase.table("appointments")
                .select("id")
                .eq("business_id", self._business_id)
                .gte("appointment_date", datetime.now().strftime("%Y-%m-%d"))
                .execute()
            )
            full_id = next(
                (row["id"] for row in (getattr(r_all, "data", None) or [])
                 if row.get("id", "").upper().startswith(appointment_ref.upper())),
                None,
            )
            if not full_id:
                return f"Could not find appointment with reference '{appointment_ref}'. Please use find_appointments first."

            self._supabase.table("appointments").update(updates).eq("id", full_id).execute()

            # ── Google Calendar: update event if staff has connected calendar ──
            appt_row_r = (
                self._supabase.table("appointments")
                .select("google_event_id, assigned_user_id, appointment_date, appointment_time, duration, service, client_name, notes")
                .eq("id", full_id)
                .limit(1)
                .execute()
            )
            appt_rows = getattr(appt_row_r, "data", None) or []
            if appt_rows:
                appt_row = appt_rows[0]
                google_event_id = appt_row.get("google_event_id")
                assigned_uid = appt_row.get("assigned_user_id")
                if google_event_id and assigned_uid:
                    await _gcal_update_event(self._supabase, assigned_uid, google_event_id, appt_row)

            change_parts = []
            if new_date:
                change_parts.append(f"date to {new_date}")
            if new_time:
                change_parts.append(f"time to {_fmt_time_12h(new_time)}")
            return f"Appointment updated: changed {' and '.join(change_parts)}. All set!"
        except Exception as e:
            logger.error("Failed to update appointment: %s", e)
            return "Sorry, could not update the appointment. Please contact us directly."

    @function_tool()
    async def cancel_appointment(
        self,
        context: RunContext,
        appointment_ref: str,
    ) -> str:
        """
        Cancel an existing appointment by its reference ID.
        Always confirm verbally with the customer before calling this.
        """
        if not self._supabase or not self._business_id:
            return "Cancellation is unavailable right now."
        try:
            r_all = (
                self._supabase.table("appointments")
                .select("id, client_name, service, appointment_date, appointment_time, assigned_user_id, google_event_id")
                .eq("business_id", self._business_id)
                .gte("appointment_date", datetime.now().strftime("%Y-%m-%d"))
                .execute()
            )
            match = next(
                (row for row in (getattr(r_all, "data", None) or [])
                 if row.get("id", "").upper().startswith(appointment_ref.upper())),
                None,
            )
            if not match:
                return f"Could not find appointment with reference '{appointment_ref}'. Please use find_appointments first."

            # ── Google Calendar: delete event before removing from DB ─────
            google_event_id = match.get("google_event_id")
            assigned_uid = match.get("assigned_user_id")
            if google_event_id and assigned_uid:
                await _gcal_delete_event(self._supabase, assigned_uid, google_event_id)

            self._supabase.table("appointments").delete().eq("id", match["id"]).execute()

            cname = match.get("client_name", "")
            svc = match.get("service") or "appointment"
            adate = match.get("appointment_date", "")
            atime = _fmt_time_12h(match.get("appointment_time", ""))
            return f"Cancelled: {cname}'s {svc} on {adate} at {atime} has been removed. Is there anything else I can help with?"
        except Exception as e:
            logger.error("Failed to cancel appointment: %s", e)
            return "Sorry, could not cancel the appointment. Please contact us directly."


# ── Post-call finalization ───────────────────────────────────────────────────

async def _generate_summary(
    supabase,
    call_id: str,
    business_id: str,
    transcript_log: list[dict],
) -> None:
    """Generate a GPT-4o summary of the call and save to call_summaries."""
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        logger.warning("OPENAI_API_KEY not set — skipping summary generation")
        return

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=openai_key)

    transcript_text = "\n".join(
        f"{u['speaker'].upper()}: {u['text']}"
        for u in transcript_log
    )

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "Summarize this voice call transcript. "
                    "Return JSON with these keys: "
                    "summary_text (string), "
                    "key_topics (array of strings), "
                    "sentiment (one of: positive, neutral, negative)."
                ),
            },
            {"role": "user", "content": transcript_text},
        ],
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    sentiment = result.get("sentiment", "neutral")

    supabase.table("call_summaries").insert({
        "call_id": call_id,
        "business_id": business_id,
        "summary_text": result.get("summary_text"),
        "key_topics": result.get("key_topics", []),
        "insights": {"sentiment_from_summary": sentiment},
    }).execute()

    supabase.table("calls").update({
        "sentiment": sentiment,
    }).eq("id", call_id).execute()

    logger.info("Summary saved for call %s (sentiment=%s)", call_id, sentiment)


async def _finalize_call(
    supabase,
    call_id: str | None,
    business_id: str | None,
    duration_s: int,
    transcript_log: list[dict],
) -> None:
    """Save transcripts, mark call completed, generate summary."""
    if not supabase or not call_id:
        logger.warning("Cannot finalize call — supabase or call_id missing")
        return

    # 1. Bulk-save all transcript utterances
    if transcript_log:
        try:
            supabase.table("transcripts").insert(transcript_log).execute()
            logger.info(
                "Saved %d transcript utterances for call %s",
                len(transcript_log), call_id,
            )
        except Exception as e:
            logger.error("Failed to save transcripts: %s", e)

    # 2. Mark call completed
    try:
        supabase.table("calls").update({
            "status": "completed",
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": duration_s,
        }).eq("id", call_id).execute()
    except Exception as e:
        logger.error("Failed to update call status: %s", e)

    # 3. Generate and save summary
    if transcript_log and business_id:
        try:
            await _generate_summary(supabase, call_id, business_id, transcript_log)
        except Exception as e:
            logger.error("Failed to generate summary: %s", e)

    logger.info(
        "Call %s finalized — duration=%ds utterances=%d",
        call_id, duration_s, len(transcript_log),
    )


# ── LiveKit entry point ───────────────────────────────────────────────────────

server = AgentServer()


@server.rtc_session()
async def voice_agent(ctx: agents.JobContext):
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    logger.info("Participant connected: %s", participant.identity)

    instructions = DEFAULT_INSTRUCTIONS
    business_id: str | None = None
    location_id: str | None = None
    call_id: str | None = None
    supabase = None
    locations: list[dict] = []
    services: list[dict] = []
    staff: list[dict] = []

    raw_meta = participant.metadata
    if isinstance(raw_meta, str) and raw_meta:
        try:
            meta = json.loads(raw_meta)
            business_id = meta.get("business_id")
            location_id = meta.get("location_id")
            call_id = meta.get("call_id")
        except json.JSONDecodeError:
            logger.warning("Invalid participant metadata: %s", raw_meta)

    if business_id or location_id:
        supabase = _get_supabase()
        instructions = build_instructions(business_id, location_id)
        if supabase and business_id:
            locations = _fetch_locations(supabase, business_id)
            services = _fetch_services(supabase, business_id)
            staff = _fetch_staff_with_ids(supabase, business_id)
            logger.info(
                "Loaded context — locations: %d, services: %d, staff: %d (call_id=%s)",
                len(locations), len(services), len(staff), call_id,
            )

    call_start_time = datetime.now(timezone.utc)
    transcript_log: list[dict] = []
    seq_counter = 0

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(),
        preemptive_generation=True,
    )
    assistant = Assistant(
        instructions=instructions,
        supabase=supabase,
        business_id=business_id,
        call_id=call_id,
        locations=locations,
        services=services,
        staff=staff,
    )

    # ── Transcript capture ────────────────────────────────────────────────────
    # Fired by AgentSession each time a full conversation turn is committed
    # (both user speech and agent response).
    @session.on("conversation_item_added")
    def _on_item_added(ev) -> None:
        nonlocal seq_counter
        try:
            item = getattr(ev, "item", ev)
            role = getattr(item, "role", None)
            if role not in ("user", "assistant"):
                return

            # Extract text — try text_content property first, then iterate content blocks
            text: str = ""
            if hasattr(item, "text_content"):
                text = item.text_content or ""
            elif hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "text") and block.text:
                        text += block.text
            text = text.strip()
            if not text:
                return

            seq_counter += 1
            ts = (datetime.now(timezone.utc) - call_start_time).total_seconds()
            entry = {
                "call_id": call_id,
                "business_id": business_id,
                "speaker": "customer" if role == "user" else "agent",
                "text": text,
                "timestamp_seconds": round(ts, 2),
                "sequence_order": seq_counter,
            }
            transcript_log.append(entry)
            logger.debug("Transcript [%s]: %s", entry["speaker"], text[:80])
        except Exception as e:
            logger.warning("Error in transcript handler: %s", e)

    await session.start(
        room=ctx.room,
        agent=assistant,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                    if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC(),
            ),
        ),
    )
    await session.generate_reply()

    # ── Wait for caller to disconnect ─────────────────────────────────────────
    caller_left = asyncio.Event()

    @ctx.room.on("participant_disconnected")
    def _on_participant_disconnected(p: rtc.RemoteParticipant) -> None:
        logger.info("Participant disconnected: %s — triggering finalization", p.identity)
        caller_left.set()

    await caller_left.wait()

    # ── Post-call finalization ────────────────────────────────────────────────
    duration_s = int((datetime.now(timezone.utc) - call_start_time).total_seconds())
    logger.info(
        "Finalizing call %s — duration=%ds utterances=%d",
        call_id, duration_s, len(transcript_log),
    )
    await _finalize_call(supabase, call_id, business_id, duration_s, transcript_log)


if __name__ == "__main__":
    agents.cli.run_app(server)
