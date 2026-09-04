"""
Supabase fetch helpers and slot computation for the voice agent.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("voice-agent")


def _local_now(business_timezone: str = "UTC") -> datetime:
    """
    Current wall-clock time in the business's local timezone, as a naive
    datetime — matches the naive HH:MM datetimes parsed elsewhere in this
    module (open/close hours, availability, requested booking times), so
    "now" comparisons aren't skewed by the business's UTC offset.
    Falls back to UTC on an unrecognised timezone string.
    """
    try:
        tz = ZoneInfo(business_timezone or "UTC")
    except ZoneInfoNotFoundError:
        logger.warning("Unknown business timezone %r, falling back to UTC", business_timezone)
        tz = ZoneInfo("UTC")
    return datetime.now(tz).replace(tzinfo=None)

# Skip semantic-memory summarization for trivial sessions (e.g. just a
# greeting) — nothing durable was likely said in fewer than 2 full turns.
MIN_MESSAGES_FOR_SEMANTIC_SUMMARY = 4


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


def _create_voice_conversation(
    supabase,
    *,
    conversations_table: str,
    business_id: str,
    user_id: str,
    location_id: str | None,
    room_name: str,
) -> str | None:
    """Create an episodic-memory conversation row for a new voice session (Remi or
    the HR onboarding assistant). Returns the new conversation id, or None if it
    couldn't be created — callers should treat that as "don't persist this session"
    rather than failing the call."""
    if not supabase or not business_id or not user_id:
        return None
    try:
        row = (
            supabase.table(conversations_table)
            .insert({
                "business_id": business_id,
                "location_id": location_id,
                "user_id": user_id,
                "channel": "voice",
                "room_name": room_name,
            })
            .execute()
        )
        data = getattr(row, "data", None) or []
        return data[0]["id"] if data else None
    except Exception as e:
        logger.warning("Failed to create %s conversation: %s", conversations_table, e)
        return None


def _finalize_voice_conversation(
    supabase,
    *,
    conversations_table: str,
    messages_table: str,
    conversation_id: str | None,
    business_id: str,
    messages: list[dict],
) -> None:
    """Bulk-insert captured turns and close out the conversation row at session end.
    Never raises — persistence failures must never affect the live call, they're only
    logged."""
    if not supabase or not conversation_id or not messages:
        return
    try:
        rows = [
            {
                "conversation_id": conversation_id,
                "business_id": business_id,
                "role": m["role"],
                "content": m["content"],
                "sequence_order": m["sequence_order"],
            }
            for m in messages
        ]
        supabase.table(messages_table).insert(rows).execute()
        now = datetime.now(timezone.utc).isoformat()
        supabase.table(conversations_table).update({
            "ended_at": now,
            "last_message_at": now,
            "message_count": len(messages),
        }).eq("id", conversation_id).execute()
        logger.info(
            "Persisted %d messages to %s for conversation %s",
            len(messages), messages_table, conversation_id,
        )
    except Exception as e:
        logger.warning(
            "Failed to finalize conversation %s in %s: %s",
            conversation_id, conversations_table, e,
        )


async def _summarize_conversation_to_facts(messages: list[dict], *, business_name: str) -> list[str]:
    """Extract durable, reusable facts from a voice session's transcript via
    a cheap model — never raises, returns [] on any failure (missing key,
    rate limit, malformed response) so a summarization problem never affects
    anything else. Skips trivial sessions before even calling out."""
    if len(messages) < MIN_MESSAGES_FOR_SEMANTIC_SUMMARY:
        return []
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        logger.warning("OPENAI_API_KEY not set — skipping semantic memory summarization")
        return []
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=openai_key)
        transcript_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You extract durable facts worth remembering from a conversation with {business_name}. "
                        "Only extract genuinely reusable preferences, decisions, or repeatedly-relevant "
                        "information (a stated preference, a policy detail, a contact, a recurring need). "
                        "Do not extract one-off questions, small talk, or anything unlikely to matter again. "
                        "Each fact must be a short, standalone sentence understandable without the transcript. "
                        "Return JSON: {\"facts\": [\"...\", ...]} — empty array if nothing durable."
                    ),
                },
                {"role": "user", "content": transcript_text},
            ],
        )
        result = json.loads(response.choices[0].message.content or "{}")
        facts = result.get("facts") or []
        return [str(f).strip() for f in facts if str(f).strip()]
    except Exception as e:
        logger.warning("Semantic memory summarization failed: %s", e)
        return []


def _fetch_recent_semantic_facts(
    supabase,
    *,
    facts_table: str,
    business_id: str,
    limit: int = 12,
) -> list[str]:
    """Most recently remembered facts for this business — a plain recency
    fetch, no embeddings/similarity search. Empty on any failure."""
    if not supabase or not business_id:
        return []
    try:
        rows = (
            supabase.table(facts_table)
            .select("fact_text")
            .eq("business_id", business_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        data = getattr(rows, "data", None) or []
        return [r["fact_text"] for r in data if r.get("fact_text")]
    except Exception as e:
        logger.warning("Failed to fetch semantic facts from %s: %s", facts_table, e)
        return []


def _format_semantic_context(facts: list[str]) -> str:
    """Render recalled facts as the block that fills a procedural-memory
    {context} slot. Empty string (self-omitting) when there's nothing to
    recall — matches prompt_builder.py's block-concatenation convention."""
    if not facts:
        return ""
    bullets = "\n".join(f"- {f}" for f in facts)
    return f"What you remember from past conversations with this business:\n{bullets}"


def _store_semantic_facts(
    supabase,
    *,
    facts_table: str,
    business_id: str,
    location_id: str | None,
    source_conversation_id: str | None,
    created_by_user_id: str | None,
    facts: list[str],
) -> None:
    """Persist newly extracted facts, skipping any that duplicate an existing
    fact for this business verbatim (case/whitespace-insensitive) — a simple
    safeguard against the model re-stating the same fact across sessions.
    Never raises."""
    if not supabase or not business_id or not facts:
        return
    try:
        existing_rows = (
            supabase.table(facts_table)
            .select("fact_text")
            .eq("business_id", business_id)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        existing = {
            (r.get("fact_text") or "").strip().lower()
            for r in (getattr(existing_rows, "data", None) or [])
        }
        new_rows = [
            {
                "business_id": business_id,
                "location_id": location_id,
                "source_conversation_id": source_conversation_id,
                "created_by_user_id": created_by_user_id,
                "fact_text": fact,
            }
            for fact in facts
            if fact.strip().lower() not in existing
        ]
        if new_rows:
            supabase.table(facts_table).insert(new_rows).execute()
            logger.info(
                "Stored %d new semantic fact(s) in %s for business %s",
                len(new_rows), facts_table, business_id,
            )
    except Exception as e:
        logger.warning("Failed to store semantic facts in %s: %s", facts_table, e)


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
            .select("id, name, description, duration_minutes, price, is_onsite")
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


def _resolve_work_hours(
    availability: list[dict],
    day_name: str,
) -> tuple[datetime, datetime] | None:
    """
    Return (work_start, work_end) datetimes for the given weekday name from a
    staff member's weekly `user_availability` rows.
    Returns None if they're not marked available that day (or have no matching row).
    """
    for row in availability:
        if row.get("day_of_week") == day_name and row.get("is_available"):
            st, et = row.get("start_time"), row.get("end_time")
            if st and et:
                return (
                    datetime.strptime(st[:5], "%H:%M"),
                    datetime.strptime(et[:5], "%H:%M"),
                )
            break
    return None


def _compute_busy_intervals(
    overrides: list[dict],
    booked: list[dict],
    default_duration_minutes: int = 60,
) -> list[tuple[datetime, datetime]] | None:
    """
    Build busy time intervals for a day from date-specific overrides and booked
    appointments. Returns None if a full-day "unavailable" override applies
    (an override with is_unavailable=True and no start/end time set).
    """
    for ov in overrides:
        if ov.get("is_unavailable") and not ov.get("start_time"):
            return None

    busy: list[tuple[datetime, datetime]] = []

    for appt in booked:
        at = appt.get("appointment_time")
        dur_raw = str(appt.get("duration") or default_duration_minutes)
        if at:
            try:
                dur_digits = "".join(c for c in dur_raw.split()[0] if c.isdigit())
                dur_min = int(dur_digits) if dur_digits else default_duration_minutes
            except (ValueError, AttributeError):
                dur_min = default_duration_minutes
            # Parse both 24h ("16:00") and 12h ("9:00 AM") formats
            appt_dt = None
            for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
                try:
                    appt_dt = datetime.strptime(at.strip(), fmt)
                    break
                except ValueError:
                    pass
            if appt_dt:
                busy.append((appt_dt, appt_dt + timedelta(minutes=dur_min)))

    for ov in overrides:
        if ov.get("is_unavailable") and ov.get("start_time") and ov.get("end_time"):
            try:
                s = datetime.strptime(ov["start_time"][:5], "%H:%M")
                e = datetime.strptime(ov["end_time"][:5], "%H:%M")
                busy.append((s, e))
            except ValueError:
                pass

    return busy


def _compute_available_slots(
    availability: list[dict],
    overrides: list[dict],
    booked: list[dict],
    target_date: str,
    slot_minutes: int = 60,
    business_timezone: str = "UTC",
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

    work_hours = _resolve_work_hours(availability, day_name)
    if work_hours is None:
        return []
    work_start, work_end = work_hours

    busy = _compute_busy_intervals(overrides, booked, slot_minutes)
    if busy is None:
        return []

    # For today (in the business's local timezone), exclude slots that
    # start at or before the current local time.
    now_cutoff: datetime | None = None
    _now = _local_now(business_timezone)
    if target_date == _now.strftime("%Y-%m-%d"):
        now_cutoff = datetime(1900, 1, 1, _now.hour, _now.minute)

    slots: list[str] = []
    current = work_start
    while current + timedelta(minutes=slot_minutes) <= work_end:
        slot_end = current + timedelta(minutes=slot_minutes)
        if now_cutoff is not None and current <= now_cutoff:
            current += timedelta(minutes=slot_minutes)
            continue
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


def _format_slots_for_speech(name: str, date: str, slots: list[str], cap: int = 8) -> str:
    """
    Format a day's available slots for a spoken response, capped at `cap` shown times.
    AIE-43: when there are more slots than `cap`, the caller must never be left thinking
    the last *shown* time is the last *available* one — always state the true last slot
    of the day explicitly, since the model has no other way to know the list was truncated.
    """
    if not slots:
        return f"{name} has no available slots on {date}."

    formatted = ", ".join(_fmt_time_12h(s) for s in slots[:cap])
    if len(slots) > cap:
        last = _fmt_time_12h(slots[-1])
        more = f" (and {len(slots) - cap} more, up to {last} — the actual last available time that day)"
    else:
        more = ""
    return f"{name} is available on {date} at: {formatted}{more}."


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


def _validate_booking_datetime(
    supabase,
    business_id: str,
    location_id: str | None,
    date: str,
    time: str | None = None,
    duration_minutes: int = 60,
    business_timezone: str = "UTC",
) -> str | None:
    """
    Returns None if the date/time is valid for booking.
    Returns an agent-readable error string if not.
    Checks: date not in past, valid formats, business open on that day,
    time + duration within open/close hours, custom schedule overrides.
    "Now"/"today" are evaluated in the business's local timezone, since
    open/close hours and the requested time are local wall-clock values.
    """
    try:
        appt_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return f"Invalid date format '{date}'. Please use YYYY-MM-DD."

    _now = _local_now(business_timezone)
    today = _now.date()
    if appt_date < today:
        return (
            f"Cannot book appointments in the past. "
            f"Today is {today.strftime('%Y-%m-%d')}."
        )

    appt_time = None
    appt_end_time = None
    if time is not None:
        try:
            appt_start_dt = datetime.strptime(time[:5], "%H:%M")
        except ValueError:
            return f"Invalid time format '{time}'. Please use HH:MM (24-hour)."
        appt_time = appt_start_dt.time()
        appt_end_time = (appt_start_dt + timedelta(minutes=duration_minutes)).time()

        # Reject same-day bookings at or before the current local time
        if appt_date == today:
            current_time = _now.time()
            if appt_time <= current_time:
                return (
                    f"Cannot book at {_fmt_time_12h(time[:5])} — "
                    f"that time has already passed today. "
                    f"Please choose a time after {_fmt_time_12h(current_time.strftime('%H:%M'))}."
                )

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_name = day_names[appt_date.weekday()]

    # Custom schedule takes priority over regular hours
    appt_dt = datetime(appt_date.year, appt_date.month, appt_date.day, tzinfo=timezone.utc)
    custom = _fetch_active_custom_schedule(supabase, business_id, location_id, now=appt_dt)
    if custom is not None:
        if custom.get("is_agent_disabled"):
            return (
                f"The business is closed on {date} due to a special schedule. "
                f"Please choose a different date."
            )
        open_t = (custom.get("open_time") or "")[:5]
        close_t = (custom.get("close_time") or "")[:5]
        if open_t and close_t:
            try:
                open_time = datetime.strptime(open_t, "%H:%M").time()
                close_time = datetime.strptime(close_t, "%H:%M").time()
                if appt_time is not None and (appt_time < open_time or appt_end_time > close_time):
                    return (
                        f"The time {_fmt_time_12h(time[:5])} is outside the special "
                        f"schedule hours ({_fmt_time_12h(open_t)}–{_fmt_time_12h(close_t)}) "
                        f"for {date}, or the {duration_minutes}-minute appointment would run "
                        f"past closing."
                    )
            except ValueError:
                pass
        return None  # Custom schedule valid, skip regular hours

    # Regular business hours (_fetch_business_hours_for_location handles None supabase safely)
    hours = _fetch_business_hours_for_location(supabase, business_id, location_id)
    day_hours = next((h for h in hours if h.get("day_of_week") == day_name), None)
    if day_hours is not None and not day_hours.get("is_open"):
        return (
            f"The business is closed on {day_name.capitalize()}s. "
            f"Please choose a day when the business is open."
        )
    if day_hours:
        open_t = (day_hours.get("open_time") or "")[:5]
        close_t = (day_hours.get("close_time") or "")[:5]
        if open_t and close_t:
            try:
                open_time = datetime.strptime(open_t, "%H:%M").time()
                close_time = datetime.strptime(close_t, "%H:%M").time()
                if appt_time is not None and (appt_time < open_time or appt_end_time > close_time):
                    return (
                        f"The time {_fmt_time_12h(time[:5])} is outside business hours "
                        f"({_fmt_time_12h(open_t)}–{_fmt_time_12h(close_t)}) "
                        f"on {day_name.capitalize()}s, or the {duration_minutes}-minute "
                        f"appointment would run past closing."
                    )
            except ValueError:
                pass

    return None


def _validate_booking_date(
    supabase,
    business_id: str,
    location_id: str | None,
    date: str,
    business_timezone: str = "UTC",
) -> str | None:
    """
    Returns None if the date is valid for booking (not past, business open that day).
    Returns an agent-readable error string if not.
    Does NOT check whether a specific time is within hours — pass time=None to _validate_booking_datetime.
    Use this when computing available slots for a full day.
    """
    return _validate_booking_datetime(
        supabase, business_id, location_id, date, time=None, business_timezone=business_timezone,
    )


def _validate_staff_availability(
    supabase,
    user_id: str,
    staff_name: str,
    date: str,
    time: str,
    duration_minutes: int = 60,
    exclude_appointment_id: str | None = None,
) -> str | None:
    """
    Returns None if the staff member is available for [time, time+duration_minutes)
    on the given date, per their user_availability, date overrides, and existing
    booked appointments.
    Returns an agent-readable error string if not.

    If the staff member has zero user_availability rows configured at all (they've
    never set up individual hours), skips this check entirely and returns None —
    booking then relies on business-hours validation only, since availability
    setup is optional and shouldn't silently block staff who haven't configured it.
    """
    availability = _fetch_user_availability(supabase, user_id)
    if not availability:
        return None

    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        appt_start = datetime.strptime(time[:5], "%H:%M")
    except ValueError:
        return None  # malformed input — _validate_booking_datetime already caught this

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_name = day_names[d.weekday()]

    work_hours = _resolve_work_hours(availability, day_name)
    if work_hours is None:
        return (
            f"{staff_name} is not scheduled to work on {day_name.capitalize()}s. "
            f"Please choose a different day or staff member."
        )
    work_start, work_end = work_hours
    appt_end = appt_start + timedelta(minutes=duration_minutes)

    if appt_start < work_start or appt_end > work_end:
        return (
            f"{staff_name} is only available from {_fmt_time_12h(work_start.strftime('%H:%M'))} "
            f"to {_fmt_time_12h(work_end.strftime('%H:%M'))} on {day_name.capitalize()}s, which "
            f"doesn't fit a {duration_minutes}-minute appointment starting at "
            f"{_fmt_time_12h(time[:5])}. Please choose an earlier time."
        )

    overrides = _fetch_user_overrides(supabase, user_id, date)
    booked = _fetch_appointments_on_date(supabase, user_id, date)
    if exclude_appointment_id:
        booked = [b for b in booked if b.get("id") != exclude_appointment_id]
    busy = _compute_busy_intervals(overrides, booked, duration_minutes)
    if busy is None:
        return f"{staff_name} is unavailable on {date}. Please choose a different day."

    for b_start, b_end in busy:
        if appt_start < b_end and b_start < appt_end:
            return (
                f"{staff_name} is not available at {_fmt_time_12h(time[:5])} on {date}. "
                f"Please choose a different time slot."
            )

    return None


def _find_next_slots(
    supabase,
    business_id: str,
    location_id: str | None,
    user_entries: list[dict],
    slot_minutes: int,
    from_date: str,
    max_days: int = 30,
    after_time: str | None = None,
    min_time: str | None = None,
    business_timezone: str = "UTC",
) -> list[dict]:
    """
    Scan forward from from_date (YYYY-MM-DD) for the next day that has available slots.
    user_entries: list of {"user_id": str, "name": str}
    after_time: optional HH:MM (24-hour) — when given, slots on from_date earlier than this
    time are excluded, so a caller can ask for something later than what was already offered.
    Only applies to from_date itself; later days in the scan are unaffected, since a later
    day's morning slots haven't been offered yet and shouldn't be hidden.
    min_time: optional HH:MM (24-hour) — when given, slots earlier than this time are excluded
    on EVERY day scanned, not just from_date. Use for a standing time-of-day preference (e.g.
    "afternoons only, any day this week") that should hold across the whole scan, unlike
    after_time which only resumes the search on the single day already offered.
    Returns list of {"date": str, "time": str, "staff_name": str, "staff_user_id": str}.
    Returns at most 3 slots per staff member for the first available day.
    Returns [] if no availability found within max_days.
    """
    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date()
    except ValueError:
        return []

    today = _local_now(business_timezone).date()
    if start < today:
        start = today

    # Pre-fetch weekly availability for all users — this doesn't change per day
    availability_cache: dict[str, list[dict]] = {}
    for entry in user_entries:
        uid = entry["user_id"]
        try:
            availability_cache[uid] = _fetch_user_availability(supabase, uid)
        except Exception as e:
            logger.warning("_find_next_slots: failed to fetch availability for %s: %s", uid, e)
            availability_cache[uid] = []

    for i in range(max_days):
        check_date = start + timedelta(days=i)
        date_str = check_date.strftime("%Y-%m-%d")

        if _validate_booking_date(supabase, business_id, location_id, date_str, business_timezone):
            continue  # closed day — skip

        day_slots: list[dict] = []
        for entry in user_entries:
            user_id = entry["user_id"]
            name = entry["name"]
            try:
                availability = availability_cache.get(user_id, [])
                overrides = _fetch_user_overrides(supabase, user_id, date_str)
                booked = _fetch_appointments_on_date(supabase, user_id, date_str)
                slots = _compute_available_slots(
                    availability, overrides, booked, date_str, slot_minutes, business_timezone,
                )
                if after_time and i == 0:
                    slots = [s for s in slots if s >= after_time]
                if min_time:
                    slots = [s for s in slots if s >= min_time]
                last_slot = slots[-1] if len(slots) > 3 else None
                for slot in slots[:3]:  # cap at 3 per staff member shown, but remember the true last one
                    day_slots.append({
                        "date": date_str,
                        "time": slot,
                        "staff_name": name,
                        "staff_user_id": user_id,
                        "last_time": last_slot,
                    })
            except Exception as e:
                logger.warning("_find_next_slots: error for user %s on %s: %s", user_id, date_str, e)
                continue

        if day_slots:
            return day_slots  # return first day that has any slots

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
                .select("id, name, description, duration_minutes, price, is_onsite")
                .eq("business_id", business_id)
                .eq("is_active", True)
                .in_("id", service_ids)
                .execute()
            )
            return getattr(sr, "data", None) or []
        except Exception as e:
            logger.warning("Failed to fetch location services: %s", e)
            return []

    # No location_id — return empty per no-silent-fallback design
    logger.warning("_fetch_services_for_location called with no location_id for business %s", business_id)
    return []


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


def _fetch_documents_for_location(
    supabase,
    business_id: str,
    location_id: str | None,
) -> list[dict]:
    """Fetch uploaded documents that Remi may attach to email for a location."""
    if not supabase or not business_id:
        return []
    try:
        base_select = (
            "id, name, description, file_path, file_name, storage_bucket, "
            "document_scope, remi_document_purpose"
        )
        business_query = (
            supabase.table("business_documents")
            .select(base_select)
            .eq("business_id", business_id)
            .eq("document_scope", "business")
        )
        if location_id:
            business_query = business_query.eq("location_id", location_id)
        else:
            business_query = business_query.is_("location_id", "null")
        business_docs = getattr(business_query.execute(), "data", None) or []

        remi_query = (
            supabase.table("business_documents")
            .select(base_select)
            .eq("business_id", business_id)
            .eq("document_scope", "executive_remi")
            .eq("remi_document_purpose", "email_attachment")
            .eq("status", "published")
        )
        if location_id:
            remi_query = remi_query.eq("location_id", location_id)
        else:
            remi_query = remi_query.is_("location_id", "null")
        remi_docs = getattr(remi_query.execute(), "data", None) or []
        return [*business_docs, *remi_docs]
    except Exception as e:
        logger.warning("Failed to fetch documents: %s", e)
        return []


def _is_within_available_hours(available_start: str | None, available_end: str | None) -> bool:
    """
    Return True if the current UTC time falls within [available_start, available_end].
    If either value is missing or malformed, returns True (always available).
    Handles overnight windows where end < start (e.g. 22:00 – 06:00).
    """
    if not available_start or not available_end:
        return True
    try:
        now_utc = datetime.now(timezone.utc)
        now_minutes = now_utc.hour * 60 + now_utc.minute

        start_h, start_m = map(int, available_start.split(":"))
        end_h, end_m     = map(int, available_end.split(":"))
        start_minutes = start_h * 60 + start_m
        end_minutes   = end_h * 60 + end_m

        if start_minutes <= end_minutes:
            return start_minutes <= now_minutes <= end_minutes
        else:
            return now_minutes >= start_minutes or now_minutes <= end_minutes
    except (ValueError, AttributeError):
        return True


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
            .select("id, name, phone, department_tag, forwarding_rule, available_start, available_end")
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


def _fetch_agent_state(
    supabase,
    business_id: str,
    location_id: str | None,
) -> dict | None:
    """
    Returns the agent_state row for this business/location, or None if not found.
    A missing row means the agent is active by default — callers must treat None as is_active=True.
    """
    try:
        q = (
            supabase.table("agent_state")
            .select("is_active, toggled_at, toggled_by")
            .eq("business_id", business_id)
        )
        if location_id:
            q = q.eq("location_id", location_id)
        else:
            q = q.is_("location_id", "null")
        r = q.limit(1).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.warning("Failed to fetch agent_state: %s", e)
        return None
