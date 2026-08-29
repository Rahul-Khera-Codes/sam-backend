"""
Booking pipeline for web UI appointments.
Mirrors the voice agent's book_appointment / update_appointment / cancel_appointment logic.
All side effects (GCal, email, SMS) are fire-and-forget — never raise to the caller.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from twilio.rest import Client as TwilioClient

from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.appointments import (
    CreateAppointmentRequest,
    UpdateAppointmentRequest,
    AppointmentResponse,
    CancelAppointmentResponse,
)
from app.services import google_calendar_service
from app.services.email_service import (
    send_appointment_confirmation,
    send_staff_notification,
    send_reschedule_confirmation,
    send_staff_reschedule_notification,
    send_cancellation_confirmation,
    send_staff_cancellation_notification,
)

logger = logging.getLogger(__name__)

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _fmt_time_12h(t: str) -> str:
    try:
        h, m = map(int, t[:5].split(":"))
        suffix = "AM" if h < 12 else "PM"
        h = h % 12 or 12
        return f"{h}:{m:02d} {suffix}"
    except Exception:
        return t


def _fetch_business_hours(business_id: str, location_id: Optional[str]) -> list[dict]:
    try:
        q = (
            supabase_admin.table("business_hours")
            .select("day_of_week, is_open, open_time, close_time")
            .eq("business_id", business_id)
        )
        if location_id:
            q = q.eq("location_id", location_id)
        else:
            q = q.is_("location_id", "null")
        return q.execute().data or []
    except Exception as e:
        logger.warning("Failed to fetch business hours: %s", e)
        return []


def _fetch_active_custom_schedule(
    business_id: str,
    location_id: Optional[str],
    now: Optional[datetime] = None,
) -> Optional[dict]:
    try:
        if now is None:
            now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        dow = DAY_NAMES[now.weekday()]
        q = (
            supabase_admin.table("custom_schedules")
            .select("*")
            .eq("business_id", business_id)
            .eq("is_enabled", True)
        )
        if location_id:
            q = q.eq("location_id", location_id)
        r = q.execute()
        schedules = r.data or []
        candidates = []
        for s in schedules:
            stype = s.get("schedule_type")
            if stype == "one_time":
                start = s.get("start_date") or ""
                end = s.get("end_date") or ""
                if start <= today_str <= end:
                    candidates.append(s)
            elif stype == "recurring":
                if dow in (s.get("days_of_week") or []):
                    candidates.append(s)
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.get("priority") or 0)
    except Exception as e:
        logger.warning("Failed to fetch custom schedule: %s", e)
        return None


def _validate_booking(
    business_id: str, location_id: Optional[str], date: str, time: str, duration_minutes: int = 60
) -> None:
    """Raises HTTPException(400) if date/time is invalid, or if [time, time+duration) falls
    outside business hours."""
    try:
        appt_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format '{date}'. Use YYYY-MM-DD.")

    today = datetime.now(timezone.utc).date()
    if appt_date < today:
        raise HTTPException(status_code=400, detail="Cannot book appointments in the past.")

    try:
        appt_start_dt = datetime.strptime(time[:5], "%H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid time format '{time}'. Use HH:MM.")
    appt_time = appt_start_dt.time()
    appt_end_time = (appt_start_dt + timedelta(minutes=duration_minutes)).time()

    day_name = DAY_NAMES[appt_date.weekday()]
    appt_dt = datetime(appt_date.year, appt_date.month, appt_date.day, tzinfo=timezone.utc)

    custom = _fetch_active_custom_schedule(business_id, location_id, now=appt_dt)
    if custom is not None:
        if custom.get("is_agent_disabled"):
            raise HTTPException(
                status_code=400,
                detail=f"Business is closed on {date} due to a special schedule.",
            )
        open_t = (custom.get("open_time") or "")[:5]
        close_t = (custom.get("close_time") or "")[:5]
        if open_t and close_t:
            open_time = datetime.strptime(open_t, "%H:%M").time()
            close_time = datetime.strptime(close_t, "%H:%M").time()
            if appt_time < open_time or appt_end_time > close_time:
                raise HTTPException(
                    status_code=400,
                    detail=f"{_fmt_time_12h(time)} is outside special schedule hours ({_fmt_time_12h(open_t)}–{_fmt_time_12h(close_t)}), or the {duration_minutes}-minute appointment would run past closing.",
                )
        return  # custom schedule valid, skip regular hours

    hours = _fetch_business_hours(business_id, location_id)
    day_hours = next((h for h in hours if h.get("day_of_week") == day_name), None)
    if day_hours and not day_hours.get("is_open"):
        raise HTTPException(
            status_code=400,
            detail=f"Business is closed on {day_name.capitalize()}s.",
        )
    if day_hours:
        open_t = (day_hours.get("open_time") or "")[:5]
        close_t = (day_hours.get("close_time") or "")[:5]
        if open_t and close_t:
            open_time = datetime.strptime(open_t, "%H:%M").time()
            close_time = datetime.strptime(close_t, "%H:%M").time()
            if appt_time < open_time or appt_end_time > close_time:
                raise HTTPException(
                    status_code=400,
                    detail=f"{_fmt_time_12h(time)} is outside business hours ({_fmt_time_12h(open_t)}–{_fmt_time_12h(close_t)}), or the {duration_minutes}-minute appointment would run past closing.",
                )


def _check_double_booking(
    user_id: str, date: str, time: str, exclude_id: Optional[str] = None
) -> bool:
    try:
        r = (
            supabase_admin.table("appointments")
            .select("id, appointment_time")
            .eq("assigned_user_id", user_id)
            .eq("appointment_date", date)
            .neq("status", "cancelled")
            .execute()
        )
        for row in r.data or []:
            if exclude_id and row.get("id") == exclude_id:
                continue
            if (row.get("appointment_time") or "")[:5] == time[:5]:
                return True
        return False
    except Exception as e:
        logger.warning("Double-booking check failed, treating as taken: %s", e)
        return True


def _fetch_user_availability(user_id: str) -> list[dict]:
    try:
        r = (
            supabase_admin.table("user_availability")
            .select("day_of_week, start_time, end_time, is_available")
            .eq("user_id", user_id)
            .execute()
        )
        return r.data or []
    except Exception as e:
        logger.warning("Failed to fetch user availability: %s", e)
        return []


def _fetch_user_overrides(user_id: str, date: str) -> list[dict]:
    try:
        r = (
            supabase_admin.table("user_availability_overrides")
            .select("is_unavailable, start_time, end_time")
            .eq("user_id", user_id)
            .eq("override_date", date)
            .execute()
        )
        return r.data or []
    except Exception as e:
        logger.warning("Failed to fetch user overrides: %s", e)
        return []


def _fetch_staff_appointments_on_date(user_id: str, date: str) -> list[dict]:
    try:
        r = (
            supabase_admin.table("appointments")
            .select("id, appointment_time, duration")
            .eq("assigned_user_id", user_id)
            .eq("appointment_date", date)
            .neq("status", "cancelled")
            .execute()
        )
        return r.data or []
    except Exception as e:
        logger.warning("Failed to fetch appointments on date: %s", e)
        return []


def _validate_staff_availability(
    user_id: str,
    staff_name: str,
    date: str,
    time: str,
    duration_minutes: int = 60,
    exclude_appointment_id: Optional[str] = None,
) -> None:
    """Raises HTTPException(400) if the staff member isn't available for
    [time, time+duration_minutes) on the given date, per their user_availability,
    date overrides, and existing booked appointments.

    If the staff member has zero user_availability rows configured at all (never
    set up individual hours), this is a no-op — booking then relies on
    business-hours validation only (see _validate_booking)."""
    availability = _fetch_user_availability(user_id)
    if not availability:
        return

    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        appt_start = datetime.strptime(time[:5], "%H:%M")
    except ValueError:
        return  # malformed input — _validate_booking already caught this

    day_name = DAY_NAMES[d.weekday()]
    appt_end = appt_start + timedelta(minutes=duration_minutes)

    day_row = next(
        (a for a in availability if a.get("day_of_week") == day_name and a.get("is_available")),
        None,
    )
    if not day_row or not day_row.get("start_time") or not day_row.get("end_time"):
        raise HTTPException(
            status_code=400,
            detail=f"{staff_name} is not scheduled to work on {day_name.capitalize()}s.",
        )

    work_start = datetime.strptime(day_row["start_time"][:5], "%H:%M")
    work_end = datetime.strptime(day_row["end_time"][:5], "%H:%M")
    if appt_start < work_start or appt_end > work_end:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{staff_name} is only available from {_fmt_time_12h(day_row['start_time'][:5])} "
                f"to {_fmt_time_12h(day_row['end_time'][:5])} on {day_name.capitalize()}s, which "
                f"doesn't fit a {duration_minutes}-minute appointment starting at "
                f"{_fmt_time_12h(time[:5])}."
            ),
        )

    overrides = _fetch_user_overrides(user_id, date)
    for ov in overrides:
        if ov.get("is_unavailable") and not ov.get("start_time"):
            raise HTTPException(
                status_code=400, detail=f"{staff_name} is unavailable on {date}.",
            )

    busy: list[tuple[datetime, datetime]] = []
    for ov in overrides:
        if ov.get("is_unavailable") and ov.get("start_time") and ov.get("end_time"):
            try:
                busy.append((
                    datetime.strptime(ov["start_time"][:5], "%H:%M"),
                    datetime.strptime(ov["end_time"][:5], "%H:%M"),
                ))
            except ValueError:
                pass

    booked = _fetch_staff_appointments_on_date(user_id, date)
    for appt in booked:
        if exclude_appointment_id and appt.get("id") == exclude_appointment_id:
            continue
        at = appt.get("appointment_time")
        if not at:
            continue
        dur_raw = str(appt.get("duration") or duration_minutes)
        dur_digits = "".join(c for c in dur_raw.split()[0] if c.isdigit())
        dur_min = int(dur_digits) if dur_digits else duration_minutes
        b_start = None
        for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
            try:
                b_start = datetime.strptime(at.strip(), fmt)
                break
            except ValueError:
                pass
        if b_start:
            busy.append((b_start, b_start + timedelta(minutes=dur_min)))

    for b_start, b_end in busy:
        if appt_start < b_end and b_start < appt_end:
            raise HTTPException(
                status_code=400,
                detail=f"{staff_name} is not available at {_fmt_time_12h(time[:5])} on {date}.",
            )


def _validate_onsite_address(values: dict) -> None:
    if not values.get("appointment_is_onsite", False):
        return
    required = {
        "appointment_address_street": "street address",
        "appointment_address_city": "city",
        "appointment_address_state": "state/province",
        "appointment_address_postal_code": "postal code",
        "appointment_address_country": "country",
    }
    missing = [label for key, label in required.items() if not (values.get(key) or "").strip()]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"On-site appointments require address details: {', '.join(missing)}.",
        )


def _get_superadmin_id(business_id: str) -> Optional[str]:
    try:
        r = (
            supabase_admin.table("user_roles")
            .select("user_id")
            .eq("business_id", business_id)
            .eq("role", "super_admin")
            .limit(1)
            .execute()
        )
        return r.data[0]["user_id"] if r.data else None
    except Exception:
        return None


def _get_staff_email(user_id: str) -> Optional[str]:
    try:
        result = supabase_admin.auth.admin.get_user_by_id(user_id)
        return result.user.email if result and result.user else None
    except Exception:
        return None


def _get_staff_name(user_id: str) -> str:
    try:
        r = (
            supabase_admin.table("profiles")
            .select("first_name, last_name")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if not r.data:
            return ""
        row = r.data[0]
        return f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
    except Exception:
        return ""


def _get_business(business_id: str) -> dict:
    try:
        r = (
            supabase_admin.table("businesses")
            .select("name, phone, email, timezone")
            .eq("id", business_id)
            .limit(1)
            .execute()
        )
        return r.data[0] if r.data else {}
    except Exception:
        return {}


def _get_location_name(location_id: Optional[str]) -> str:
    if not location_id:
        return ""
    try:
        r = (
            supabase_admin.table("locations")
            .select("name")
            .eq("id", location_id)
            .limit(1)
            .execute()
        )
        return r.data[0]["name"] if r.data else ""
    except Exception:
        return ""


def _get_gcal_token_row(user_id: str) -> Optional[dict]:
    return google_calendar_service.get_token_row(supabase_admin, user_id)


async def create_appointment(
    req: CreateAppointmentRequest,
    created_by: str,
) -> AppointmentResponse:
    duration_minutes = req.duration or 60
    _validate_booking(
        req.business_id, req.location_id, req.appointment_date, req.appointment_time,
        duration_minutes=duration_minutes,
    )
    staff_name = _get_staff_name(req.assigned_user_id) or "This staff member"
    _validate_staff_availability(
        req.assigned_user_id, staff_name, req.appointment_date, req.appointment_time,
        duration_minutes=duration_minutes,
    )

    if _check_double_booking(req.assigned_user_id, req.appointment_date, req.appointment_time):
        raise HTTPException(
            status_code=409,
            detail="That time slot is already booked. Please choose a different time.",
        )

    row = {
        "business_id": req.business_id,
        "location_id": req.location_id,
        "assigned_user_id": req.assigned_user_id,
        "client_name": req.client_name,
        "client_phone": req.client_phone or "",
        "client_email": req.client_email or "",
        "service": req.service or "",
        "appointment_date": req.appointment_date,
        "appointment_time": req.appointment_time,
        "duration": str(req.duration or 60),
        "notes": req.notes or "",
        "created_by": created_by,
        "appointment_is_onsite": req.appointment_is_onsite,
        "appointment_address_street": req.appointment_address_street,
        "appointment_address_city": req.appointment_address_city,
        "appointment_address_state": req.appointment_address_state,
        "appointment_address_postal_code": req.appointment_address_postal_code,
        "appointment_address_country": req.appointment_address_country,
    }
    _validate_onsite_address(row)

    r = supabase_admin.table("appointments").insert(row).execute()
    if not r.data:
        raise HTTPException(status_code=500, detail="Failed to save appointment.")

    appt = r.data[0]
    appt_id: str = appt["id"]
    short_id = appt_id[:8].upper()

    biz = _get_business(req.business_id)
    biz_name = biz.get("name") or "Your Business"
    biz_phone = biz.get("phone") or ""
    biz_tz = biz.get("timezone") or "America/Toronto"
    location_name = _get_location_name(req.location_id)
    duration_min = req.duration or 60

    gcal_updates: dict = {}
    staff_token = _get_gcal_token_row(req.assigned_user_id)
    if staff_token:
        try:
            staff_event_id = await google_calendar_service.create_calendar_event(
                token_row=staff_token,
                appointment={**row, "client_name": req.client_name, "location_name": location_name},
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                supabase=supabase_admin,
                timezone=biz_tz,
            )
            if staff_event_id:
                gcal_updates["google_event_id"] = staff_event_id
                logger.info("GCal staff event created: %s", staff_event_id)
            else:
                logger.warning("GCal staff event returned None for user %s", req.assigned_user_id)
        except Exception as e:
            logger.warning("GCal staff event failed: %s", e)

    admin_id = _get_superadmin_id(req.business_id)
    if admin_id and admin_id != req.assigned_user_id:
        admin_token = _get_gcal_token_row(admin_id)
        if admin_token:
            try:
                admin_event_id = await google_calendar_service.create_calendar_event(
                    token_row=admin_token,
                    appointment={**row, "client_name": req.client_name, "location_name": location_name},
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    supabase=supabase_admin,
                    timezone=biz_tz,
                )
                if admin_event_id:
                    gcal_updates["google_event_id_admin"] = admin_event_id
                    logger.info("GCal admin event created: %s", admin_event_id)
                else:
                    logger.warning("GCal admin event returned None for user %s", admin_id)
            except Exception as e:
                logger.warning("GCal admin event failed: %s", e)

    if gcal_updates:
        try:
            supabase_admin.table("appointments").update(gcal_updates).eq("id", appt_id).execute()
        except Exception:
            pass

    if req.client_email:
        try:
            await send_appointment_confirmation(
                supabase=supabase_admin,
                business_id=req.business_id,
                location_id=req.location_id,
                client_name=req.client_name,
                client_email=req.client_email,
                service=req.service or "Appointment",
                staff_name="",
                location=location_name,
                date=req.appointment_date,
                time=req.appointment_time,
                duration_minutes=duration_min,
                confirmation_ref=short_id,
                business_name=biz_name,
                business_phone=biz_phone,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
            )
        except Exception:
            pass

    staff_email_addr = _get_staff_email(req.assigned_user_id)
    if staff_email_addr:
        try:
            await send_staff_notification(
                supabase=supabase_admin,
                business_id=req.business_id,
                location_id=req.location_id,
                business_name=biz_name,
                staff_email=staff_email_addr,
                staff_name=_get_staff_name(req.assigned_user_id),
                client_name=req.client_name,
                client_phone=req.client_phone or "",
                client_email=req.client_email or "",
                service=req.service or "Appointment",
                location=location_name,
                date=req.appointment_date,
                time=req.appointment_time,
                duration_minutes=duration_min,
                confirmation_ref=short_id,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
            )
        except Exception:
            pass

    if req.client_phone and settings.twilio_account_sid and settings.twilio_auth_token:
        try:
            from_number = None
            if req.location_id:
                loc_r = (
                    supabase_admin.table("business_phone_numbers")
                    .select("phone_number")
                    .eq("business_id", req.business_id)
                    .eq("location_id", req.location_id)
                    .eq("is_active", True)
                    .limit(1)
                    .execute()
                )
                if loc_r.data:
                    from_number = loc_r.data[0]["phone_number"]
            if not from_number:
                biz_r = (
                    supabase_admin.table("business_phone_numbers")
                    .select("phone_number")
                    .eq("business_id", req.business_id)
                    .eq("is_active", True)
                    .limit(1)
                    .execute()
                )
                if biz_r.data:
                    from_number = biz_r.data[0]["phone_number"]
            if from_number:
                twilio = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
                body = (
                    f"Hi {req.client_name}, your {req.service or 'appointment'} is confirmed for "
                    f"{req.appointment_date} at {_fmt_time_12h(req.appointment_time)}. "
                    f"Ref: {short_id}. — {biz_name}"
                )
                twilio.messages.create(to=req.client_phone, from_=from_number, body=body)
        except Exception as e:
            logger.warning("SMS confirmation failed: %s", e)

    return AppointmentResponse(**appt, confirmation_ref=short_id)


async def update_appointment(
    appointment_id: str,
    req: UpdateAppointmentRequest,
) -> AppointmentResponse:
    r = (
        supabase_admin.table("appointments")
        .select("*")
        .eq("id", appointment_id)
        .eq("business_id", req.business_id)
        .neq("status", "cancelled")
        .limit(1)
        .execute()
    )
    if not r.data:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    appt = r.data[0]

    updates: dict = {}
    fields_set = req.model_fields_set
    if req.client_name is not None:
        updates["client_name"] = req.client_name
    if req.client_phone is not None:
        updates["client_phone"] = req.client_phone
    if req.client_email is not None:
        updates["client_email"] = req.client_email
    if req.appointment_date is not None:
        updates["appointment_date"] = req.appointment_date
    if req.appointment_time is not None:
        updates["appointment_time"] = req.appointment_time
    if req.assigned_user_id is not None:
        updates["assigned_user_id"] = req.assigned_user_id
    if req.service is not None:
        updates["service"] = req.service
    if req.duration is not None:
        updates["duration"] = str(req.duration)
    if req.notes is not None:
        updates["notes"] = req.notes
    if req.appointment_is_onsite is not None:
        updates["appointment_is_onsite"] = req.appointment_is_onsite
    if "appointment_address_street" in fields_set:
        updates["appointment_address_street"] = req.appointment_address_street
    if "appointment_address_city" in fields_set:
        updates["appointment_address_city"] = req.appointment_address_city
    if "appointment_address_state" in fields_set:
        updates["appointment_address_state"] = req.appointment_address_state
    if "appointment_address_postal_code" in fields_set:
        updates["appointment_address_postal_code"] = req.appointment_address_postal_code
    if "appointment_address_country" in fields_set:
        updates["appointment_address_country"] = req.appointment_address_country

    if not updates:
        raise HTTPException(status_code=400, detail="No changes provided.")

    new_date = updates.get("appointment_date") or appt["appointment_date"]
    new_time = updates.get("appointment_time") or appt["appointment_time"]
    assigned_uid = updates.get("assigned_user_id") or appt["assigned_user_id"]

    date_changed = "appointment_date" in updates and updates["appointment_date"] != appt["appointment_date"]
    time_changed = (
        "appointment_time" in updates
        and updates["appointment_time"][:5] != (appt["appointment_time"] or "")[:5]
    )
    assignee_changed = "assigned_user_id" in updates and updates["assigned_user_id"] != appt["assigned_user_id"]
    date_or_time_changed = date_changed or time_changed

    new_duration_minutes = updates.get("duration")
    if new_duration_minutes is not None:
        new_duration_minutes = int(new_duration_minutes)
    else:
        new_duration_minutes = int(str(appt.get("duration") or "60").split()[0])

    if date_or_time_changed or assignee_changed:
        _validate_booking(
            req.business_id, appt.get("location_id"), new_date, new_time,
            duration_minutes=new_duration_minutes,
        )
        staff_name = _get_staff_name(assigned_uid) or "This staff member"
        _validate_staff_availability(
            assigned_uid, staff_name, new_date, new_time,
            duration_minutes=new_duration_minutes, exclude_appointment_id=appointment_id,
        )
        if _check_double_booking(assigned_uid, new_date, new_time, exclude_id=appointment_id):
            raise HTTPException(
                status_code=409,
                detail="That time slot is already booked. Please choose a different time.",
            )

    _validate_onsite_address({**appt, **updates})

    supabase_admin.table("appointments").update(updates).eq("id", appointment_id).execute()

    updated_appt = {**appt, **updates}
    short_id = appointment_id[:8].upper()
    biz = _get_business(req.business_id)
    biz_name = biz.get("name") or "Your Business"
    biz_phone = biz.get("phone") or ""
    biz_tz = biz.get("timezone") or "America/Toronto"
    location_id = appt.get("location_id")
    location_name = _get_location_name(location_id)
    duration_min = int(str(updated_appt.get("duration") or "60").split()[0])

    if appt.get("google_event_id"):
        staff_token = _get_gcal_token_row(assigned_uid)
        if staff_token:
            try:
                await google_calendar_service.update_calendar_event(
                    token_row=staff_token,
                    google_event_id=appt["google_event_id"],
                    appointment={**updated_appt, "location_name": location_name},
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    supabase=supabase_admin,
                    timezone=biz_tz,
                )
            except Exception:
                pass

    admin_id = _get_superadmin_id(req.business_id)
    if appt.get("google_event_id_admin") and admin_id:
        admin_token = _get_gcal_token_row(admin_id)
        if admin_token:
            try:
                await google_calendar_service.update_calendar_event(
                    token_row=admin_token,
                    google_event_id=appt["google_event_id_admin"],
                    appointment={**updated_appt, "location_name": location_name},
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    supabase=supabase_admin,
                    timezone=biz_tz,
                )
            except Exception:
                pass

    client_email = appt.get("client_email") or ""
    if client_email and date_or_time_changed:
        try:
            await send_reschedule_confirmation(
                supabase=supabase_admin,
                business_id=req.business_id,
                location_id=location_id,
                business_name=biz_name,
                business_phone=biz_phone,
                client_name=appt.get("client_name", ""),
                client_email=client_email,
                service=updated_appt.get("service") or "Appointment",
                staff_name="",
                location=location_name,
                new_date=new_date,
                new_time=new_time,
                duration_minutes=duration_min,
                confirmation_ref=short_id,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
            )
        except Exception:
            pass

    staff_email_addr = _get_staff_email(assigned_uid)
    if staff_email_addr and date_or_time_changed:
        try:
            await send_staff_reschedule_notification(
                supabase=supabase_admin,
                business_id=req.business_id,
                location_id=location_id,
                business_name=biz_name,
                staff_email=staff_email_addr,
                staff_name=_get_staff_name(assigned_uid),
                client_name=appt.get("client_name", ""),
                client_phone=appt.get("client_phone") or "",
                service=updated_appt.get("service") or "Appointment",
                location=location_name,
                new_date=new_date,
                new_time=new_time,
                duration_minutes=duration_min,
                confirmation_ref=short_id,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
            )
        except Exception:
            pass

    r2 = (
        supabase_admin.table("appointments")
        .select("*")
        .eq("id", appointment_id)
        .single()
        .execute()
    )
    return AppointmentResponse(**(r2.data or updated_appt), confirmation_ref=short_id)


async def cancel_appointment(
    appointment_id: str,
    business_id: str,
) -> CancelAppointmentResponse:
    r = (
        supabase_admin.table("appointments")
        .select("*")
        .eq("id", appointment_id)
        .eq("business_id", business_id)
        .neq("status", "cancelled")
        .limit(1)
        .execute()
    )
    if not r.data:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    appt = r.data[0]

    supabase_admin.table("appointments").update({"status": "cancelled"}).eq("id", appointment_id).execute()

    assigned_uid = appt.get("assigned_user_id")
    short_id = appointment_id[:8].upper()
    biz = _get_business(business_id)
    biz_name = biz.get("name") or "Your Business"
    biz_phone = biz.get("phone") or ""
    location_id = appt.get("location_id")

    if appt.get("google_event_id") and assigned_uid:
        staff_token = _get_gcal_token_row(assigned_uid)
        if staff_token:
            try:
                await google_calendar_service.delete_calendar_event(
                    token_row=staff_token,
                    google_event_id=appt["google_event_id"],
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    supabase=supabase_admin,
                )
            except Exception:
                pass

    admin_id = _get_superadmin_id(business_id)
    if appt.get("google_event_id_admin") and admin_id:
        admin_token = _get_gcal_token_row(admin_id)
        if admin_token:
            try:
                await google_calendar_service.delete_calendar_event(
                    token_row=admin_token,
                    google_event_id=appt["google_event_id_admin"],
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    supabase=supabase_admin,
                )
            except Exception:
                pass

    client_email = appt.get("client_email") or ""
    if client_email:
        try:
            await send_cancellation_confirmation(
                supabase=supabase_admin,
                business_id=business_id,
                location_id=location_id,
                business_name=biz_name,
                business_phone=biz_phone,
                client_name=appt.get("client_name", ""),
                client_email=client_email,
                service=appt.get("service") or "Appointment",
                date=appt.get("appointment_date", ""),
                time=appt.get("appointment_time", ""),
                confirmation_ref=short_id,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
            )
        except Exception:
            pass

    if assigned_uid:
        staff_email_addr = _get_staff_email(assigned_uid)
        if staff_email_addr:
            try:
                await send_staff_cancellation_notification(
                    supabase=supabase_admin,
                    business_id=business_id,
                    location_id=location_id,
                    business_name=biz_name,
                    staff_email=staff_email_addr,
                    staff_name=_get_staff_name(assigned_uid),
                    client_name=appt.get("client_name", ""),
                    client_phone=appt.get("client_phone") or "",
                    service=appt.get("service") or "Appointment",
                    date=appt.get("appointment_date", ""),
                    time=appt.get("appointment_time", ""),
                    confirmation_ref=short_id,
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                )
            except Exception:
                pass

    return CancelAppointmentResponse(
        id=appointment_id,
        status="cancelled",
        message=f"Appointment {short_id} cancelled successfully.",
    )
