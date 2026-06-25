# Appointment Booking Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST/PUT/DELETE /appointments` backend endpoints that mirror the voice agent's booking logic — validation, DB write, Google Calendar, Gmail, SMS — so the web UI goes through the same pipeline as the voice agent.

**Architecture:** Three new backend files (`schemas/appointments.py`, `services/booking_service.py`, `routers/appointments.py`) plus email helper additions to `email_service.py`. The frontend `useAppointments.ts` keeps its Supabase-direct READ but routes all writes (create, update, cancel) through the backend API. The voice agent is untouched — it keeps its own direct Supabase path.

**Tech Stack:** FastAPI, Pydantic, supabase-py (admin client), Google Calendar API, Gmail API (via existing email_service.py), Twilio SMS, React + TypeScript

---

## File Map

**Create:**
- `backend/app/schemas/appointments.py` — Pydantic request/response models
- `backend/app/services/booking_service.py` — validation, DB ops, GCal, email, SMS
- `backend/app/routers/appointments.py` — POST/PUT/DELETE endpoints

**Modify:**
- `backend/app/services/email_service.py` — add staff notification + reschedule + cancellation email helpers
- `backend/app/main.py` — register appointments router
- `ai-employees-app/src/lib/voiceAgentApi.ts` — add 3 appointment API functions
- `ai-employees-app/src/hooks/useAppointments.ts` — wire create/update/delete to backend

---

## Task 1: Pydantic Schemas

**Files:**
- Create: `backend/app/schemas/appointments.py`

- [ ] **Step 1: Create the schemas file**

```python
# backend/app/schemas/appointments.py
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class CreateAppointmentRequest(BaseModel):
    business_id: str
    location_id: Optional[str] = None
    assigned_user_id: str
    client_name: str
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    service: Optional[str] = None
    appointment_date: str   # YYYY-MM-DD
    appointment_time: str   # HH:MM 24h
    duration: Optional[str] = "60"
    notes: Optional[str] = None


class UpdateAppointmentRequest(BaseModel):
    business_id: str
    appointment_date: Optional[str] = None   # YYYY-MM-DD
    appointment_time: Optional[str] = None   # HH:MM 24h
    assigned_user_id: Optional[str] = None
    service: Optional[str] = None
    duration: Optional[str] = None
    notes: Optional[str] = None


class AppointmentResponse(BaseModel):
    id: str
    business_id: str
    location_id: Optional[str] = None
    assigned_user_id: str
    client_name: str
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    service: Optional[str] = None
    appointment_date: str
    appointment_time: str
    duration: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    confirmation_ref: Optional[str] = None
    created_at: Optional[str] = None


class CancelAppointmentResponse(BaseModel):
    id: str
    status: str   # "cancelled"
    message: str
```

- [ ] **Step 2: Verify syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import ast; ast.parse(open('backend/app/schemas/appointments.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/appointments.py
git commit -m "feat: add appointment Pydantic schemas"
```

---

## Task 2: Email Helper Functions

**Files:**
- Modify: `backend/app/services/email_service.py`

The file already has `send_appointment_confirmation()` for the customer. We need 4 more functions for staff notification, reschedule (customer + staff), and cancellation (customer + staff). They all follow the same pattern: build subject/body → call `send_email()`.

The `send_email()` and `get_valid_access_token()` functions already exist in this file. The `_fmt_time_12h()` helper also already exists. All new functions go at the bottom of the file.

- [ ] **Step 1: Add `send_staff_notification`**

Append to `backend/app/services/email_service.py`:

```python
async def send_staff_notification(
    supabase,
    business_id: str,
    location_id: Optional[str],
    business_name: str,
    staff_email: str,
    staff_name: str,
    client_name: str,
    client_phone: str,
    client_email: str,
    service: str,
    location: str,
    date: str,
    time: str,
    duration_minutes: int,
    confirmation_ref: str,
    client_id: str = "",
    client_secret: str = "",
) -> bool:
    access_token = await get_valid_access_token(
        supabase, business_id, client_id, client_secret, location_id=location_id
    )
    if not access_token:
        return False
    token_row = get_token_row(supabase, business_id, location_id=location_id)
    sender = token_row["google_email"] if token_row else "noreply@example.com"
    time_display = _fmt_time_12h(time)
    subject = f"New Appointment: {client_name} — {service} on {date}"
    html_body = f"""
    <p>Hi {staff_name},</p>
    <p>A new appointment has been booked for you.</p>
    <ul>
      <li><strong>Client:</strong> {client_name}</li>
      <li><strong>Phone:</strong> {client_phone or '—'}</li>
      <li><strong>Email:</strong> {client_email or '—'}</li>
      <li><strong>Service:</strong> {service}</li>
      <li><strong>Date:</strong> {date} at {time_display}</li>
      <li><strong>Duration:</strong> {duration_minutes} minutes</li>
      <li><strong>Location:</strong> {location}</li>
      <li><strong>Ref:</strong> {confirmation_ref}</li>
    </ul>
    <p>— {business_name}</p>
    """
    plain_body = (
        f"New appointment: {client_name} | {service} | {date} {time_display} | "
        f"Phone: {client_phone} | Ref: {confirmation_ref}"
    )
    try:
        return await send_email(
            access_token=access_token,
            sender=f"{business_name} <{sender}>",
            to=staff_email,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
        )
    except Exception:
        return False
```

- [ ] **Step 2: Add `send_reschedule_confirmation`**

```python
async def send_reschedule_confirmation(
    supabase,
    business_id: str,
    location_id: Optional[str],
    business_name: str,
    business_phone: str,
    client_name: str,
    client_email: str,
    service: str,
    staff_name: str,
    location: str,
    new_date: str,
    new_time: str,
    duration_minutes: int,
    confirmation_ref: str,
    client_id: str = "",
    client_secret: str = "",
) -> bool:
    access_token = await get_valid_access_token(
        supabase, business_id, client_id, client_secret, location_id=location_id
    )
    if not access_token:
        return False
    token_row = get_token_row(supabase, business_id, location_id=location_id)
    sender = token_row["google_email"] if token_row else "noreply@example.com"
    time_display = _fmt_time_12h(new_time)
    subject = f"Appointment Rescheduled — {service} on {new_date}"
    html_body = f"""
    <p>Hi {client_name},</p>
    <p>Your appointment has been rescheduled.</p>
    <ul>
      <li><strong>Service:</strong> {service}</li>
      <li><strong>Staff:</strong> {staff_name}</li>
      <li><strong>New Date:</strong> {new_date} at {time_display}</li>
      <li><strong>Duration:</strong> {duration_minutes} minutes</li>
      <li><strong>Location:</strong> {location}</li>
      <li><strong>Ref:</strong> {confirmation_ref}</li>
    </ul>
    <p>Questions? Call us at {business_phone}.</p>
    <p>— {business_name}</p>
    """
    plain_body = (
        f"Rescheduled: {service} on {new_date} at {time_display} | "
        f"Ref: {confirmation_ref} | {business_phone}"
    )
    try:
        return await send_email(
            access_token=access_token,
            sender=f"{business_name} <{sender}>",
            to=client_email,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
        )
    except Exception:
        return False
```

- [ ] **Step 3: Add `send_staff_reschedule_notification`**

```python
async def send_staff_reschedule_notification(
    supabase,
    business_id: str,
    location_id: Optional[str],
    business_name: str,
    staff_email: str,
    staff_name: str,
    client_name: str,
    client_phone: str,
    service: str,
    location: str,
    new_date: str,
    new_time: str,
    duration_minutes: int,
    confirmation_ref: str,
    client_id: str = "",
    client_secret: str = "",
) -> bool:
    access_token = await get_valid_access_token(
        supabase, business_id, client_id, client_secret, location_id=location_id
    )
    if not access_token:
        return False
    token_row = get_token_row(supabase, business_id, location_id=location_id)
    sender = token_row["google_email"] if token_row else "noreply@example.com"
    time_display = _fmt_time_12h(new_time)
    subject = f"Appointment Rescheduled: {client_name} — {new_date}"
    html_body = f"""
    <p>Hi {staff_name},</p>
    <p>An appointment has been rescheduled.</p>
    <ul>
      <li><strong>Client:</strong> {client_name} ({client_phone or '—'})</li>
      <li><strong>Service:</strong> {service}</li>
      <li><strong>New Date:</strong> {new_date} at {time_display}</li>
      <li><strong>Duration:</strong> {duration_minutes} minutes</li>
      <li><strong>Location:</strong> {location}</li>
      <li><strong>Ref:</strong> {confirmation_ref}</li>
    </ul>
    <p>— {business_name}</p>
    """
    plain_body = (
        f"Rescheduled: {client_name} | {service} | {new_date} {time_display} | Ref: {confirmation_ref}"
    )
    try:
        return await send_email(
            access_token=access_token,
            sender=f"{business_name} <{sender}>",
            to=staff_email,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
        )
    except Exception:
        return False
```

- [ ] **Step 4: Add `send_cancellation_confirmation` and `send_staff_cancellation_notification`**

```python
async def send_cancellation_confirmation(
    supabase,
    business_id: str,
    location_id: Optional[str],
    business_name: str,
    business_phone: str,
    client_name: str,
    client_email: str,
    service: str,
    date: str,
    time: str,
    confirmation_ref: str,
    client_id: str = "",
    client_secret: str = "",
) -> bool:
    access_token = await get_valid_access_token(
        supabase, business_id, client_id, client_secret, location_id=location_id
    )
    if not access_token:
        return False
    token_row = get_token_row(supabase, business_id, location_id=location_id)
    sender = token_row["google_email"] if token_row else "noreply@example.com"
    subject = f"Appointment Cancelled — {service} on {date}"
    html_body = f"""
    <p>Hi {client_name},</p>
    <p>Your appointment has been cancelled.</p>
    <ul>
      <li><strong>Service:</strong> {service}</li>
      <li><strong>Was scheduled:</strong> {date} at {_fmt_time_12h(time)}</li>
      <li><strong>Ref:</strong> {confirmation_ref}</li>
    </ul>
    <p>To rebook, call us at {business_phone}.</p>
    <p>— {business_name}</p>
    """
    plain_body = f"Cancelled: {service} on {date}. Ref: {confirmation_ref}. Call {business_phone} to rebook."
    try:
        return await send_email(
            access_token=access_token,
            sender=f"{business_name} <{sender}>",
            to=client_email,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
        )
    except Exception:
        return False


async def send_staff_cancellation_notification(
    supabase,
    business_id: str,
    location_id: Optional[str],
    business_name: str,
    staff_email: str,
    staff_name: str,
    client_name: str,
    client_phone: str,
    service: str,
    date: str,
    time: str,
    confirmation_ref: str,
    client_id: str = "",
    client_secret: str = "",
) -> bool:
    access_token = await get_valid_access_token(
        supabase, business_id, client_id, client_secret, location_id=location_id
    )
    if not access_token:
        return False
    token_row = get_token_row(supabase, business_id, location_id=location_id)
    sender = token_row["google_email"] if token_row else "noreply@example.com"
    subject = f"Appointment Cancelled: {client_name} — {date}"
    html_body = f"""
    <p>Hi {staff_name},</p>
    <p>The following appointment has been cancelled.</p>
    <ul>
      <li><strong>Client:</strong> {client_name} ({client_phone or '—'})</li>
      <li><strong>Service:</strong> {service}</li>
      <li><strong>Was scheduled:</strong> {date} at {_fmt_time_12h(time)}</li>
      <li><strong>Ref:</strong> {confirmation_ref}</li>
    </ul>
    <p>— {business_name}</p>
    """
    plain_body = f"Cancelled: {client_name} | {service} | {date}. Ref: {confirmation_ref}"
    try:
        return await send_email(
            access_token=access_token,
            sender=f"{business_name} <{sender}>",
            to=staff_email,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
        )
    except Exception:
        return False
```

- [ ] **Step 5: Check that `get_valid_access_token` in email_service.py accepts `location_id` kwarg**

```bash
grep -n "def get_valid_access_token" backend/app/services/email_service.py
```

If the signature does NOT have `location_id`, add it as an optional kwarg:
```python
async def get_valid_access_token(
    supabase, business_id: str, client_id: str, client_secret: str,
    location_id: Optional[str] = None,
) -> Optional[str]:
```
And update the `get_token_row` call inside it to pass `location_id=location_id`.

Similarly check `get_token_row`:
```bash
grep -n "def get_token_row" backend/app/services/email_service.py
```
If it doesn't accept `location_id`, add it as an optional kwarg and pass it to the Supabase query filter.

- [ ] **Step 6: Verify syntax**

```bash
python -c "import ast; ast.parse(open('backend/app/services/email_service.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/email_service.py
git commit -m "feat: add staff notification, reschedule and cancellation email helpers"
```

---

## Task 3: Booking Service

**Files:**
- Create: `backend/app/services/booking_service.py`

This service mirrors what `book_appointment`, `update_appointment`, and `cancel_appointment` do in `agent/agent.py`. It uses `supabase_admin` directly (no Supabase client is passed in). All side effects (GCal, email, SMS) are fire-and-forget — failures are logged but never propagate to the caller.

- [ ] **Step 1: Create the service file with validation helpers**

```python
# backend/app/services/booking_service.py
"""
Booking pipeline for web UI appointments.
Mirrors the voice agent's book_appointment / update_appointment / cancel_appointment logic.
All side effects (GCal, email, SMS) are fire-and-forget — never raise to the caller.
"""
import logging
from datetime import datetime, timezone
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


def _validate_booking(business_id: str, location_id: Optional[str], date: str, time: str) -> None:
    """Raises HTTPException(400) if date/time is invalid or outside business hours."""
    try:
        appt_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format '{date}'. Use YYYY-MM-DD.")

    today = datetime.now(timezone.utc).date()
    if appt_date < today:
        raise HTTPException(status_code=400, detail=f"Cannot book appointments in the past.")

    try:
        appt_time = datetime.strptime(time[:5], "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid time format '{time}'. Use HH:MM.")

    day_name = DAY_NAMES[appt_date.weekday()]

    # Custom schedule takes priority
    appt_dt = datetime(appt_date.year, appt_date.month, appt_date.day, tzinfo=timezone.utc)
    custom = _fetch_active_custom_schedule(business_id, location_id, now=appt_dt)
    if custom is not None:
        if custom.get("is_agent_disabled"):
            raise HTTPException(status_code=400, detail=f"Business is closed on {date} due to a special schedule.")
        open_t = (custom.get("open_time") or "")[:5]
        close_t = (custom.get("close_time") or "")[:5]
        if open_t and close_t:
            open_time = datetime.strptime(open_t, "%H:%M").time()
            close_time = datetime.strptime(close_t, "%H:%M").time()
            if appt_time < open_time or appt_time >= close_time:
                raise HTTPException(
                    status_code=400,
                    detail=f"{_fmt_time_12h(time)} is outside special schedule hours ({_fmt_time_12h(open_t)}–{_fmt_time_12h(close_t)})."
                )
        return  # custom schedule valid, skip regular hours

    # Regular business hours
    hours = _fetch_business_hours(business_id, location_id)
    day_hours = next((h for h in hours if h.get("day_of_week") == day_name), None)
    if day_hours and not day_hours.get("is_open"):
        raise HTTPException(status_code=400, detail=f"Business is closed on {day_name.capitalize()}s.")
    if day_hours:
        open_t = (day_hours.get("open_time") or "")[:5]
        close_t = (day_hours.get("close_time") or "")[:5]
        if open_t and close_t:
            open_time = datetime.strptime(open_t, "%H:%M").time()
            close_time = datetime.strptime(close_t, "%H:%M").time()
            if appt_time < open_time or appt_time >= close_time:
                raise HTTPException(
                    status_code=400,
                    detail=f"{_fmt_time_12h(time)} is outside business hours ({_fmt_time_12h(open_t)}–{_fmt_time_12h(close_t)})."
                )


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
                if s.get("day_of_week") == dow:
                    candidates.append(s)

        if not candidates:
            return None
        return max(candidates, key=lambda s: s.get("priority") or 0)
    except Exception as e:
        logger.warning("Failed to fetch custom schedule: %s", e)
        return None


def _check_double_booking(user_id: str, date: str, time: str, exclude_id: Optional[str] = None) -> bool:
    """Returns True if the slot is already taken."""
    try:
        r = (
            supabase_admin.table("appointments")
            .select("id, appointment_time")
            .eq("assigned_user_id", user_id)
            .eq("appointment_date", date)
            .neq("status", "cancelled")
            .execute()
        )
        for row in (r.data or []):
            if exclude_id and row.get("id") == exclude_id:
                continue
            if (row.get("appointment_time") or "")[:5] == time[:5]:
                return True
        return False
    except Exception as e:
        logger.warning("Double-booking check failed: %s", e)
        return False


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


def _get_business(business_id: str) -> dict:
    try:
        r = (
            supabase_admin.table("businesses")
            .select("name, phone, email")
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
```

- [ ] **Step 2: Add `create_appointment` function**

Append to `backend/app/services/booking_service.py`:

```python
async def create_appointment(
    req: CreateAppointmentRequest,
    created_by: str,
) -> AppointmentResponse:
    # Guard 1: date/time + business hours
    _validate_booking(req.business_id, req.location_id, req.appointment_date, req.appointment_time)

    # Guard 2: double-booking
    if _check_double_booking(req.assigned_user_id, req.appointment_date, req.appointment_time):
        raise HTTPException(
            status_code=409,
            detail=f"That time slot is already booked. Please choose a different time.",
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
        "duration": req.duration or "60",
        "notes": req.notes or "",
        "created_by": created_by,
    }

    r = supabase_admin.table("appointments").insert(row).select().single().execute()
    if not r.data:
        raise HTTPException(status_code=500, detail="Failed to save appointment.")

    appt = r.data
    appt_id: str = appt["id"]
    short_id = appt_id[:8].upper()

    biz = _get_business(req.business_id)
    biz_name = biz.get("name") or "Your Business"
    biz_phone = biz.get("phone") or ""
    location_name = _get_location_name(req.location_id)
    duration_min = int((req.duration or "60").split()[0])

    # ── Google Calendar: staff calendar ────────────────────────────────────
    gcal_updates: dict = {}
    staff_token = _get_gcal_token_row(req.assigned_user_id)
    if staff_token:
        staff_event_id = await google_calendar_service.create_calendar_event(
            token_row=staff_token,
            appointment={**row, "client_name": req.client_name, "location_name": location_name},
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            supabase=supabase_admin,
        )
        if staff_event_id:
            gcal_updates["google_event_id"] = staff_event_id

    # ── Google Calendar: superadmin calendar ───────────────────────────────
    admin_id = _get_superadmin_id(req.business_id)
    if admin_id and admin_id != req.assigned_user_id:
        admin_token = _get_gcal_token_row(admin_id)
        if admin_token:
            admin_event_id = await google_calendar_service.create_calendar_event(
                token_row=admin_token,
                appointment={**row, "client_name": req.client_name, "location_name": location_name},
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                supabase=supabase_admin,
            )
            if admin_event_id:
                gcal_updates["google_event_id_admin"] = admin_event_id

    if gcal_updates:
        try:
            supabase_admin.table("appointments").update(gcal_updates).eq("id", appt_id).execute()
        except Exception:
            pass

    # ── Email: confirmation to customer ───────────────────────────────────
    if req.client_email:
        try:
            await send_appointment_confirmation(
                supabase=supabase_admin,
                business_id=req.business_id,
                client_name=req.client_name,
                client_email=req.client_email,
                service=req.service or "Appointment",
                staff_name=_get_staff_email(req.assigned_user_id) or "",
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

    # ── Email: notification to staff ──────────────────────────────────────
    staff_email_addr = _get_staff_email(req.assigned_user_id)
    if staff_email_addr:
        try:
            await send_staff_notification(
                supabase=supabase_admin,
                business_id=req.business_id,
                location_id=req.location_id,
                business_name=biz_name,
                staff_email=staff_email_addr,
                staff_name=staff_email_addr,
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

    # ── SMS: confirmation to customer ─────────────────────────────────────
    if req.client_phone and settings.twilio_account_sid and settings.twilio_auth_token:
        try:
            from_number_r = (
                supabase_admin.table("business_phone_numbers")
                .select("phone_number")
                .eq("business_id", req.business_id)
                .eq("location_id", req.location_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            from_number = from_number_r.data[0]["phone_number"] if from_number_r.data else None
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

    return AppointmentResponse(
        **appt,
        confirmation_ref=short_id,
    )
```

- [ ] **Step 3: Add `update_appointment` function**

Append to `backend/app/services/booking_service.py`:

```python
async def update_appointment(
    appointment_id: str,
    req: UpdateAppointmentRequest,
) -> AppointmentResponse:
    # Fetch existing row
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
    if req.appointment_date is not None:
        updates["appointment_date"] = req.appointment_date
    if req.appointment_time is not None:
        updates["appointment_time"] = req.appointment_time
    if req.assigned_user_id is not None:
        updates["assigned_user_id"] = req.assigned_user_id
    if req.service is not None:
        updates["service"] = req.service
    if req.duration is not None:
        updates["duration"] = req.duration
    if req.notes is not None:
        updates["notes"] = req.notes

    if not updates:
        raise HTTPException(status_code=400, detail="No changes provided.")

    new_date = updates.get("appointment_date") or appt["appointment_date"]
    new_time = updates.get("appointment_time") or appt["appointment_time"]
    assigned_uid = updates.get("assigned_user_id") or appt["assigned_user_id"]

    # Validate new date/time if changed
    if "appointment_date" in updates or "appointment_time" in updates:
        _validate_booking(req.business_id, appt.get("location_id"), new_date, new_time)
        if _check_double_booking(assigned_uid, new_date, new_time, exclude_id=appointment_id):
            raise HTTPException(
                status_code=409,
                detail=f"That time slot is already booked. Please choose a different time.",
            )

    supabase_admin.table("appointments").update(updates).eq("id", appointment_id).execute()

    updated_appt = {**appt, **updates}
    short_id = appointment_id[:8].upper()
    biz = _get_business(req.business_id)
    biz_name = biz.get("name") or "Your Business"
    biz_phone = biz.get("phone") or ""
    location_name = _get_location_name(appt.get("location_id"))
    duration_min = int((updated_appt.get("duration") or "60").split()[0])

    # ── Google Calendar: update staff event ───────────────────────────────
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
                )
            except Exception:
                pass

    # ── Google Calendar: update admin event ───────────────────────────────
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
                )
            except Exception:
                pass

    # ── Email: reschedule confirmation to customer ─────────────────────────
    client_email = appt.get("client_email") or ""
    if client_email and ("appointment_date" in updates or "appointment_time" in updates):
        try:
            await send_reschedule_confirmation(
                supabase=supabase_admin,
                business_id=req.business_id,
                location_id=appt.get("location_id"),
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

    # ── Email: reschedule notification to staff ────────────────────────────
    staff_email_addr = _get_staff_email(assigned_uid)
    if staff_email_addr and ("appointment_date" in updates or "appointment_time" in updates):
        try:
            await send_staff_reschedule_notification(
                supabase=supabase_admin,
                business_id=req.business_id,
                location_id=appt.get("location_id"),
                business_name=biz_name,
                staff_email=staff_email_addr,
                staff_name=staff_email_addr,
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
```

- [ ] **Step 4: Add `cancel_appointment` function**

Append to `backend/app/services/booking_service.py`:

```python
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

    # Soft delete
    supabase_admin.table("appointments").update({"status": "cancelled"}).eq("id", appointment_id).execute()

    assigned_uid = appt.get("assigned_user_id")
    short_id = appointment_id[:8].upper()
    biz = _get_business(business_id)
    biz_name = biz.get("name") or "Your Business"
    biz_phone = biz.get("phone") or ""
    location_id = appt.get("location_id")

    # ── Google Calendar: delete staff event ───────────────────────────────
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

    # ── Google Calendar: delete admin event ───────────────────────────────
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

    # ── Email: cancellation confirmation to customer ───────────────────────
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

    # ── Email: cancellation notification to staff ──────────────────────────
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
                    staff_name=staff_email_addr,
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
```

- [ ] **Step 5: Verify syntax**

```bash
python -c "import ast; ast.parse(open('backend/app/services/booking_service.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/booking_service.py
git commit -m "feat: add booking_service with validation, GCal, email and SMS pipeline"
```

---

## Task 4: Appointments Router + Register in main.py

**Files:**
- Create: `backend/app/routers/appointments.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create the router**

```python
# backend/app/routers/appointments.py
import logging
from fastapi import APIRouter, Depends
from app.core.auth import get_user_id, require_business_access
from app.schemas.appointments import (
    CreateAppointmentRequest,
    UpdateAppointmentRequest,
    AppointmentResponse,
    CancelAppointmentResponse,
)
from app.services import booking_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentResponse)
async def create_appointment(
    body: CreateAppointmentRequest,
    user_id: str = Depends(get_user_id),
    _: str = Depends(require_business_access()),
):
    return await booking_service.create_appointment(body, created_by=user_id)


@router.put("/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(
    appointment_id: str,
    body: UpdateAppointmentRequest,
    _: str = Depends(get_user_id),
    __: str = Depends(require_business_access()),
):
    return await booking_service.update_appointment(appointment_id, body)


@router.delete("/{appointment_id}", response_model=CancelAppointmentResponse)
async def cancel_appointment(
    appointment_id: str,
    business_id: str,
    _: str = Depends(get_user_id),
    __: str = Depends(require_business_access()),
):
    return await booking_service.cancel_appointment(appointment_id, business_id)
```

- [ ] **Step 2: Register the router in main.py**

In `backend/app/main.py`, add to the imports block:
```python
from app.routers import appointments as appointments_router
```

Then add after the last `app.include_router(...)` line:
```python
app.include_router(appointments_router.router)
```

- [ ] **Step 3: Verify syntax**

```bash
python -c "import ast; ast.parse(open('backend/app/routers/appointments.py').read()); print('router OK')"
python -c "import ast; ast.parse(open('backend/app/main.py').read()); print('main OK')"
```
Expected: both print `OK`.

- [ ] **Step 4: Start the backend and confirm the routes exist**

```bash
docker compose up -d sam-backend
sleep 3
curl -s http://localhost:8003/openapi.json | python -c "import json,sys; routes=[r for r in json.load(sys.stdin)['paths'] if '/appointments' in r]; print(routes)"
```
Expected output includes `/appointments`, `/appointments/{appointment_id}`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/appointments.py backend/app/main.py
git commit -m "feat: add /appointments POST/PUT/DELETE endpoints"
```

---

## Task 5: Frontend Wiring

**Files:**
- Modify: `ai-employees-app/src/lib/voiceAgentApi.ts`
- Modify: `ai-employees-app/src/hooks/useAppointments.ts`

Work from: `/home/lap-68/Documents/gt-rahul/ai-employees-app`

- [ ] **Step 1: Add 3 API functions to `voiceAgentApi.ts`**

Find the end of the existing appointment-related functions (or add before the closing export). Add:

```typescript
// ── Appointments (backend pipeline) ──────────────────────────────────────────

export interface CreateAppointmentPayload {
  business_id: string;
  location_id?: string | null;
  assigned_user_id: string;
  client_name: string;
  client_phone?: string;
  client_email?: string;
  service?: string;
  appointment_date: string;
  appointment_time: string;
  duration?: string;
  notes?: string;
}

export interface UpdateAppointmentPayload {
  business_id: string;
  appointment_date?: string;
  appointment_time?: string;
  assigned_user_id?: string;
  service?: string;
  duration?: string;
  notes?: string;
}

export interface AppointmentApiResponse {
  id: string;
  business_id: string;
  location_id?: string | null;
  assigned_user_id: string;
  client_name: string;
  client_phone?: string | null;
  client_email?: string | null;
  service?: string | null;
  appointment_date: string;
  appointment_time: string;
  duration?: string | null;
  notes?: string | null;
  status?: string | null;
  confirmation_ref?: string | null;
  created_at?: string | null;
}

export async function createAppointmentApi(
  token: string,
  data: CreateAppointmentPayload,
): Promise<AppointmentApiResponse> {
  const res = await fetch(`${API_BASE_URL}/appointments`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail || "Failed to create appointment");
  }
  return res.json();
}

export async function updateAppointmentApi(
  token: string,
  appointmentId: string,
  data: UpdateAppointmentPayload,
): Promise<AppointmentApiResponse> {
  const res = await fetch(`${API_BASE_URL}/appointments/${appointmentId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail || "Failed to update appointment");
  }
  return res.json();
}

export async function cancelAppointmentApi(
  token: string,
  appointmentId: string,
  businessId: string,
): Promise<{ id: string; status: string; message: string }> {
  const res = await fetch(
    `${API_BASE_URL}/appointments/${appointmentId}?business_id=${businessId}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail || "Failed to cancel appointment");
  }
  return res.json();
}
```

- [ ] **Step 2: Update `useAppointments.ts` — add imports and update createAppointment**

At the top of `useAppointments.ts`, add to existing imports:
```typescript
import { useAuth } from "@/contexts/AuthContext";
import {
  createAppointmentApi,
  updateAppointmentApi,
  cancelAppointmentApi,
} from "@/lib/voiceAgentApi";
```

Note: `useAuth` is likely already imported. Just add the three API functions.

Replace `createAppointment` (lines 105–125):
```typescript
const createAppointment = async (appointment: AppointmentInsert) => {
  if (!businessId || !user) {
    return { error: new Error("No business ID or user") };
  }
  const token = session?.access_token;
  if (!token) return { error: new Error("Not authenticated") };
  try {
    const data = await createAppointmentApi(token, {
      ...appointment,
      business_id: businessId,
    });
    setAppointments((prev) => [...prev, data as unknown as Appointment]);
    return { data, error: null };
  } catch (e: any) {
    return { data: null, error: e };
  }
};
```

- [ ] **Step 3: Update `updateAppointment`**

Replace `updateAppointment` (lines 127–142):
```typescript
const updateAppointment = async (id: string, updates: AppointmentUpdate) => {
  const token = session?.access_token;
  if (!token || !businessId) return { data: null, error: new Error("Not authenticated") };
  try {
    const data = await updateAppointmentApi(token, id, {
      ...updates,
      business_id: businessId,
    });
    setAppointments((prev) =>
      prev.map((apt) => (apt.id === id ? (data as unknown as Appointment) : apt))
    );
    return { data, error: null };
  } catch (e: any) {
    return { data: null, error: e };
  }
};
```

- [ ] **Step 4: Update `deleteAppointment` (now a soft-cancel)**

Replace `deleteAppointment` (lines 144–155):
```typescript
const deleteAppointment = async (id: string) => {
  const token = session?.access_token;
  if (!token || !businessId) return { error: new Error("Not authenticated") };
  try {
    await cancelAppointmentApi(token, id, businessId);
    setAppointments((prev) => prev.filter((apt) => apt.id !== id));
    return { error: null };
  } catch (e: any) {
    return { error: e };
  }
};
```

- [ ] **Step 5: Ensure `session` is destructured from `useAuth`**

At the top of `useAppointments`, check that `session` is destructured:
```typescript
const { user, session } = useAuth();
```
If only `user` is currently destructured, add `session`.

- [ ] **Step 6: TypeScript check**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx tsc --noEmit 2>&1 | grep -i "appointment"
```
Expected: no output (no TS errors related to appointments).

- [ ] **Step 7: Commit frontend**

```bash
git add src/lib/voiceAgentApi.ts src/hooks/useAppointments.ts
git commit -m "feat: wire appointment create/update/cancel through backend pipeline"
```

---

## Verification

After all tasks complete, do a quick end-to-end check:

1. Open the Calendar page in the browser
2. Create a new appointment → check that a Google Calendar event appears + confirmation email arrives
3. Edit the appointment time → check that GCal event updates + reschedule email arrives
4. Delete the appointment → check that GCal event is deleted + cancellation email arrives + appointment disappears from calendar (soft-deleted, not hard-deleted)
5. Try booking outside business hours → should get a 400 error shown in UI
6. Try double-booking same staff + same slot → should get a 409 error
