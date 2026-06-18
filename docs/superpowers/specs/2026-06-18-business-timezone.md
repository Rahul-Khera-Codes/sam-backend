# Spec: Business Timezone — Store, Set, and Use

**Date:** 2026-06-18  
**Requested by:** Sam Maisuria (reported Jun 15: 9 AM appointment shows as 3 AM in Google Calendar)  
**Status:** Ready for review

---

## Problem

Appointments are stored as plain local time strings (e.g. `"09:00"`). When we create a Google Calendar event, we currently hardcode `timeZone: "UTC"`. This tells Google the appointment is at 9:00 AM UTC, but the business is in Edmonton (UTC-6), so Google Calendar displays it as 3:00 AM to the staff member.

This affects:
- Google Calendar events created on booking, reschedule, cancel
- `.ics` calendar attachments sent in booking confirmation emails (secondary, same root cause)

---

## How Timezones Work in This System

### Storage
Appointments are stored as local time strings with no timezone attached:
```
appointment_date = "2026-06-27"
appointment_time = "09:00"
```
This means "9 AM at the business location." No UTC conversion is done anywhere — times are always local. This is intentional and does NOT need to change.

### The only place timezone matters
When we write to **external systems** that need an absolute point in time:
1. Google Calendar events → `timeZone` field in the event body
2. `.ics` attachments in confirmation emails → `DTSTART` / `DTEND` fields

Everything else (portal calendar display, agent slot checking, DB storage) already works correctly because it treats times as local strings consistently.

---

## Desired Behaviour

1. Each business stores a timezone (e.g. `"America/Edmonton"`)
2. Business owner sets it once in Company Info → auto-detected from browser as a sensible default
3. Google Calendar events use the business timezone, not UTC
4. Agent reads timezone from the business record when creating events
5. `.ics` attachments also use the business timezone (bonus — same fix)

---

## Example

**Divinity DJs, Edmonton (UTC-6)**

| Step | Before fix | After fix |
|---|---|---|
| Sam books 9 AM | Stores "09:00" | Stores "09:00" (unchanged) |
| Calendar event written | `"09:00" timeZone: "UTC"` | `"09:00" timeZone: "America/Edmonton"` |
| Google stores internally | 09:00 UTC | 15:00 UTC |
| Staff opens calendar in Edmonton | Shows 3:00 AM ❌ | Shows 9:00 AM ✅ |
| Staff travels to Toronto | Shows 5:00 AM ❌ | Shows 11:00 AM ✅ (correct — appointment is in Edmonton) |

---

## Files to Change

### 1. Database — new migration

**File:** `ai-employees-app/supabase/migrations/YYYYMMDD_businesses_timezone.sql`

```sql
ALTER TABLE public.businesses
  ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'America/Toronto';
```

Default `'America/Toronto'` covers the most common Canadian timezone. Business owners in other timezones will update it via Company Info.

**No data migration needed** — existing appointments are unaffected (stored as local strings).

### 2. Backend schema — `BusinessUpdate` Pydantic model

**File:** `backend/app/schemas/business.py` (or wherever BusinessUpdate is defined)

Add `timezone: str | None = None` to the update schema so the Company Info save endpoint accepts and persists it.

### 3. Frontend — Company Info timezone selector

**File:** `ai-employees-app/src/pages/dashboard/BusinessSettings.tsx` (Company Info tab)

**Changes:**
- Add a `timezone` field to the Company Info form
- Default value: pre-filled from `Intl.DateTimeFormat().resolvedOptions().timeZone` if the business has no timezone set yet (browser suggestion only — owner can change)
- Display: a searchable dropdown of IANA timezone names (e.g. `"America/Edmonton"`, `"America/Toronto"`, `"America/Vancouver"`, etc.)
- Saves with the rest of Company Info on submit

**Timezone dropdown options (minimum set for Canada + common US):**
```
America/St_Johns       — Newfoundland (UTC-3:30)
America/Halifax        — Atlantic (UTC-4)
America/Toronto        — Eastern (UTC-5)
America/Winnipeg       — Central (UTC-6)
America/Edmonton       — Mountain (UTC-7)
America/Vancouver      — Pacific (UTC-8)
America/New_York       — US Eastern
America/Chicago        — US Central
America/Denver         — US Mountain
America/Los_Angeles    — US Pacific
UTC                    — UTC (fallback)
```

Label format: `"Mountain Time — America/Edmonton"` for readability.

### 4. Backend — Google Calendar event creation

**File:** `backend/app/services/google_calendar_service.py`

**Function:** `_appointment_to_event(appointment)`

Currently:
```python
"start": {"dateTime": start_dt, "timeZone": "UTC"},
"end":   {"dateTime": end_dt,   "timeZone": "UTC"},
```

After fix — accept timezone as a parameter:
```python
def _appointment_to_event(appointment: dict, timezone: str = "UTC") -> dict:
    ...
    "start": {"dateTime": start_dt, "timeZone": timezone},
    "end":   {"dateTime": end_dt,   "timeZone": timezone},
```

**Function:** `create_calendar_event(token_row, appointment, client_id, client_secret, supabase)`

The caller already has `supabase` and `appointment["business_id"]`. Fetch timezone:
```python
biz = supabase.table("businesses").select("timezone").eq("id", appointment["business_id"]).limit(1).execute()
tz = (biz.data[0].get("timezone") or "UTC") if biz.data else "UTC"
event = _appointment_to_event(appointment, timezone=tz)
```

Same for `update_calendar_event` and any other function that builds event bodies.

### 5. Agent — Google Calendar event creation

**File:** `agent/gcal_helpers.py`

The agent already fetches business data at session start (`self._supabase`, `self._business_id`). When it calls the calendar helpers, it needs to pass the business timezone.

In `_gcal_create_event` (or however the agent creates events):
- Fetch `businesses.timezone` for `self._business_id` at session start (alongside services, staff, etc.)
- Store as `self._timezone`
- Pass to calendar event creation

**Or simpler:** pass timezone directly from the agent's `Assistant.__init__` where business data is already loaded.

### 6. `.ics` email attachments (bonus — same root cause)

**File:** `agent/ics_helpers.py` (if exists) or `agent/gmail_helpers.py`

The `.ics` `DTSTART` / `DTEND` lines currently likely use UTC or no timezone. Same fix applies — use the business timezone. This ensures the calendar invite in confirmation emails also shows the correct time when the customer adds it to their calendar.

---

## What Does NOT Change

- How appointments are stored in the DB — still plain local time strings
- Agent's same-day booking validation — already uses UTC for date comparison, not affected
- Portal calendar display — already correct (renders stored local time strings as-is)
- Any existing appointments — no backfill needed; new events created after the fix will be correct

---

## Testing

1. Set Divinity DJs timezone to `"America/Edmonton"` in Company Info
2. Book an appointment for 9:00 AM via the portal or agent
3. Open Google Calendar for the connected staff member
4. Verify event shows **9:00 AM** (not 3:00 AM)
5. Reschedule → verify update reflects correctly
6. Cancel → verify event deleted
7. Check `.ics` attachment in confirmation email → verify DTSTART shows 9:00 AM Edmonton time

---

## Summary of Changes

| File | Change |
|---|---|
| `supabase/migrations/...sql` | Add `timezone` column to `businesses` |
| `backend/app/schemas/business.py` | Add `timezone` to update schema |
| `BusinessSettings.tsx` | Timezone dropdown in Company Info |
| `google_calendar_service.py` | Use business timezone in event body |
| `agent/gcal_helpers.py` | Pass business timezone to calendar events |
| `agent/ics_helpers.py` | Use business timezone in `.ics` attachments |
