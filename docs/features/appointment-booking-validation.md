# Appointment Booking Hours Validation

## What it does
When an appointment is created or edited via the UI (or the voice agent), the backend rejects
dates/times outside the business's working hours. A business has two layers of hours:
- **Regular weekly hours** (`business_hours`) — one row per day of week, `is_open` + `open_time`/
  `close_time`.
- **Custom schedule overrides** (`custom_schedules`) — either a `one_time` date-range override
  (e.g. a holiday closure/special hours) or a `recurring` override tied to specific days of the
  week (e.g. "closed every Sunday" beyond the regular hours config). When one is active for the
  requested date, it wins over the regular weekly hours entirely (not merged).

As of 2026-08-27 this validation is also surfaced to the user in two ways instead of failing
silently or generically:
1. The Create/Edit Appointment dialogs (`ai-employees-app`) show a live hint — "Business hours
   for Mon, Aug 31: 5:00 PM – 11:30 PM" (or the special-schedule/closed equivalent) — that
   recalculates as the picked date changes, so the user knows the valid window *before* trying to
   book.
2. If a booking is still rejected (e.g. the picked time is outside that window), the toast now
   shows the backend's actual reason instead of a generic "Failed to create appointment".

## Key files
**Backend (sam-backend)**
- `backend/app/services/booking_service.py`:
  - `_fetch_business_hours(business_id, location_id)` — regular weekly hours for the day.
  - `_fetch_active_custom_schedule(business_id, location_id, now)` — resolves the single active
    override for a given moment: `one_time` matches by `start_date <= today <= end_date`;
    `recurring` matches by day-of-week membership in `days_of_week` (array column). Ties across
    multiple matching schedules broken by highest `priority`.
  - `_validate_booking(business_id, location_id, date, time)` — the single entry point called by
    both `create_appointment` and `update_appointment`; raises `HTTPException(400, detail=...)`
    with a specific human-readable reason (invalid format, past date, closed day, outside
    hours/special-schedule hours) — never a generic message.
- `backend/app/routers/appointments.py` — `create_appointment`/`update_appointment` propagate
  whatever `booking_service` raises; no error-message rewriting happens at the router layer.

**Frontend (ai-employees-app)**
- `src/hooks/useBusiness.ts` — `useBusinessHours(businessId, locationId)`, direct Supabase read of
  `business_hours`.
- `src/hooks/useCustomSchedules.ts` — `useCustomSchedules()`, direct Supabase read of
  `custom_schedules` for the current business + selected location, pre-sorted
  `priority desc, created_at desc` (same tie-break the backend applies).
- `src/pages/dashboard/Calendar.tsx`:
  - `getBusinessHoursMessage(date)` — frontend mirror of `_validate_booking`'s hours resolution
    (custom schedule first, regular hours fallback), used to render the live hint. Deliberately
    kept as logic duplicated in this file (matching the existing per-file helper convention here,
    e.g. `formatApptTime`/`parseTimeToMinutes`) rather than extracted to a shared lib, since only
    this file needs it.
  - Hint rendered as a `col-span-2` line directly under the Date/Time fields in both the Create
    Appointment dialog (after the Time field, before Assigned To) and the Edit Appointment dialog
    (same position).
  - `handleCreateAppointment`, `handleDeleteAppointment`, `handleStatusUpdate` — all three now
    show `error.message` (the backend's actual `detail`) instead of a hardcoded generic string,
    falling back to the generic string only if no message is present. (The employee-code-gated
    status-change path, via `EmployeeCodeDialog`, already showed the real error inline — no change
    needed there.)

## Bugs fixed 2026-08-27
- **Recurring custom schedules were silently never enforced.** `_fetch_active_custom_schedule`'s
  `recurring` branch checked `s.get("day_of_week") == dow`, but the actual DB column is
  `days_of_week` (plural, array) — `select("*")` never returns a `day_of_week` key, so this was
  always `None == dow`, i.e. always `False`. Confirmed via live data: two active businesses had
  `is_enabled=true` recurring schedules (e.g. "Outside Regular Hours") that were configured but
  had zero actual effect on booking validation. Fixed to `dow in (s.get("days_of_week") or [])`,
  matching the voice agent's already-correct implementation of the same logic in
  `agent/supabase_helpers.py::_fetch_active_custom_schedule` (which was never wrong — this bug was
  specific to the web-booking path in `booking_service.py`). **Behavior change:** appointments
  that were previously bookable outside those businesses' configured recurring restricted hours
  are now correctly rejected.
- **Generic error toasts swallowed the real reason.** `Calendar.tsx`'s create/delete/status-update
  handlers all discarded the thrown `Error`'s `.message` (which already carried the backend's
  `detail` string end-to-end) in favor of a hardcoded string like `"Failed to create appointment"`.
  Found via a real user report: a 9:00 AM booking attempt against a business open 5:00 PM–11:30 PM
  Mondays showed only "Failed to create appointment" instead of the specific reason.

## Decisions / tradeoffs
- **Frontend hint mirrors backend logic rather than calling an API.** No new backend endpoint was
  added to compute "effective hours for a date" — the frontend already has `business_hours` and
  `custom_schedules` available via existing hooks, so replicating the (now-fixed) resolution logic
  client-side avoids an extra round-trip. Risk: if the two implementations ever drift again, the
  hint could mislead. Mitigated by keeping the specific-reason toast fix in place as a backstop —
  even if the hint is ever wrong, the user still sees why a rejected booking failed.
- **Custom schedule fully replaces regular hours for the date, never merges.** Matches the
  pre-existing backend behavior (`return` immediately after custom-schedule validation in
  `_validate_booking`) — not a new decision, just carried through to the frontend hint for
  consistency.
