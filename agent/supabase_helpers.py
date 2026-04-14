"""
Supabase fetch helpers and slot computation for the voice agent.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("voice-agent")


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


def _is_feature_enabled(supabase, business_id: str, feature_key: str, default: bool = True) -> bool:
    """Check whether a feature flag is enabled for a business. Returns default if not found."""
    if not supabase or not business_id:
        return default
    try:
        r = (
            supabase.table("agent_settings")
            .select("is_enabled")
            .eq("business_id", business_id)
            .eq("feature_key", feature_key)
            .limit(1)
            .execute()
        )
        data = getattr(r, "data", None) or []
        if data:
            return bool(data[0].get("is_enabled", default))
    except Exception as e:
        logger.warning("Could not check feature flag %s: %s", feature_key, e)
    return default


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
            .select("id, appointment_time, duration")
            .eq("assigned_user_id", user_id)
            .eq("appointment_date", target_date)
            .neq("status", "cancelled")
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

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_name = day_names[d.weekday()]

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

    for ov in overrides:
        if ov.get("is_unavailable") and not ov.get("start_time"):
            return []

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


# ── Location-scoped fetch functions (no fallback) ────────────────────────────


def _fetch_business_hours_for_location(
    supabase,
    business_id: str,
    location_id: str | None,
) -> list[dict]:
    """Fetch business hours for a specific location. Returns empty if none configured."""
    if not supabase or not business_id:
        return []
    try:
        query = (
            supabase.table("business_hours")
            .select("day_of_week, open_time, close_time, is_open")
            .eq("business_id", business_id)
        )
        if location_id:
            query = query.eq("location_id", location_id)
        else:
            query = query.is_("location_id", "null")
        r = query.execute()
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch business hours: %s", e)
        return []


def _is_feature_enabled_for_location(
    supabase,
    business_id: str,
    location_id: str | None,
    feature_key: str,
    default: bool = True,
) -> bool:
    """Check feature flag for a specific location. No fallback to business level."""
    if not supabase or not business_id:
        return default
    try:
        query = (
            supabase.table("agent_settings")
            .select("is_enabled")
            .eq("business_id", business_id)
            .eq("feature_key", feature_key)
        )
        if location_id:
            query = query.eq("location_id", location_id)
        else:
            query = query.is_("location_id", "null")
        r = query.limit(1).execute()
        data = getattr(r, "data", None) or []
        if data:
            return bool(data[0].get("is_enabled", default))
    except Exception as e:
        logger.warning("Could not check feature flag %s: %s", feature_key, e)
    return default


def _get_feature_config_value(
    supabase,
    business_id: str,
    location_id: str | None,
    feature_key: str,
) -> dict:
    """Return the config_value JSONB for a feature flag. Empty dict if not found."""
    if not supabase or not business_id:
        return {}
    try:
        query = (
            supabase.table("agent_settings")
            .select("config_value")
            .eq("business_id", business_id)
            .eq("feature_key", feature_key)
        )
        if location_id:
            query = query.eq("location_id", location_id)
        else:
            query = query.is_("location_id", "null")
        r = query.limit(1).execute()
        data = getattr(r, "data", None) or []
        if data:
            cv = data[0].get("config_value")
            return cv if isinstance(cv, dict) else {}
    except Exception as e:
        logger.warning("Could not get config_value for %s: %s", feature_key, e)
    return {}


def _fetch_services_for_location(
    supabase,
    business_id: str,
    location_id: str | None,
) -> list[dict]:
    """Fetch services mapped to a location via location_services. Returns empty if none mapped."""
    if not supabase or not business_id:
        return []

    if location_id:
        try:
            r = (
                supabase.table("location_services")
                .select("service_id")
                .eq("location_id", location_id)
                .eq("is_active", True)
                .execute()
            )
            service_ids = [row["service_id"] for row in (getattr(r, "data", None) or [])]
            if not service_ids:
                return []
            sr = (
                supabase.table("services")
                .select("id, name, description, duration_minutes, price")
                .eq("business_id", business_id)
                .eq("is_active", True)
                .in_("id", service_ids)
                .execute()
            )
            return getattr(sr, "data", None) or []
        except Exception as e:
            logger.warning("Failed to fetch location services: %s", e)
            return []

    # No location_id — return all business services (legacy web call without location)
    return _fetch_services(supabase, business_id)


def _fetch_knowledge_base_for_location(
    supabase,
    business_id: str,
    location_id: str | None,
) -> list[dict]:
    """Fetch KB entries for a specific location only."""
    if not supabase or not business_id:
        return []
    try:
        query = (
            supabase.table("knowledge_base")
            .select("title, text_content")
            .eq("business_id", business_id)
            .eq("content_type", "text")
        )
        if location_id:
            query = query.eq("location_id", location_id)
        else:
            query = query.is_("location_id", "null")
        r = query.execute()
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch knowledge base: %s", e)
        return []


def _fetch_forwarding_contacts(
    supabase,
    business_id: str,
    location_id: str | None,
) -> list[dict]:
    """
    Fetch enabled forwarding contacts for this (business, location).
    The agent uses these + their natural-language rules to decide whether
    to direct a caller to a specific person.
    """
    if not supabase or not business_id:
        return []
    try:
        query = (
            supabase.table("forwarding_contacts")
            .select("id, name, phone, department_tag, forwarding_rule")
            .eq("business_id", business_id)
            .eq("is_active", True)
        )
        if location_id:
            query = query.eq("location_id", location_id)
        r = query.execute()
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch forwarding contacts: %s", e)
        return []


def _fetch_active_custom_schedule(
    supabase,
    business_id: str,
    location_id: str | None,
    now: datetime | None = None,
) -> dict | None:
    """
    Return the single custom_schedule that applies to the given moment, or None.
    Rules:
      - is_enabled = true
      - type one_time: start_date <= today <= end_date
      - type recurring: today's day-of-week in days_of_week
    If multiple match, highest priority wins; ties broken by created_at desc.
    """
    if not supabase or not business_id or not location_id:
        return None

    now = now or datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    dow = now.strftime("%A").lower()  # 'monday' etc.

    try:
        r = (
            supabase.table("custom_schedules")
            .select("*")
            .eq("business_id", business_id)
            .eq("location_id", location_id)
            .eq("is_enabled", True)
            .order("priority", desc=True)
            .order("created_at", desc=True)
            .execute()
        )
        rows = getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch custom schedules: %s", e)
        return None

    for row in rows:
        stype = row.get("schedule_type")
        if stype == "one_time":
            sd = row.get("start_date")
            ed = row.get("end_date")
            if sd and ed and sd <= today_str <= ed:
                return row
        elif stype == "recurring":
            days = row.get("days_of_week") or []
            if dow in [d.lower() for d in days]:
                return row

    return None
