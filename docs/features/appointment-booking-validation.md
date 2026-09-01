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
- **Per-employee hours** (`user_availability` + `user_availability_overrides`) — as of 2026-08-29
  (AIE-45), a booking must also fit within the *specific assigned staff member's* configured hours
  for that day (and not overlap their date-specific time off or another booking), not just the
  business's hours. This check is skipped (falls back to business-hours-only) if that staff member
  has never configured individual hours at all.
- Both business-hours and employee-hours checks are **duration-aware**: they validate
  `[appointment_time, appointment_time + duration)` against the closing/end-of-shift boundary, not
  just the start time (see AIE-45 below for the bug this fixes).

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
  - `_validate_booking(business_id, location_id, date, time, duration_minutes=60)` — the single
    entry point called by both `create_appointment` and `update_appointment`; raises
    `HTTPException(400, detail=...)` with a specific human-readable reason (invalid format, past
    date, closed day, `[time, time+duration)` outside hours/special-schedule hours) — never a
    generic message.
  - `_validate_staff_availability(user_id, staff_name, date, time, duration_minutes=60,
    exclude_appointment_id=None)` — the assigned staff member's own hours/overrides/overlap check
    (AIE-45); called alongside `_validate_booking` from both `create_appointment` and
    `update_appointment` (the latter gated on the date, time, or assignee actually changing).
    `exclude_appointment_id` prevents a reschedule from spuriously conflicting with its own prior
    slot. No-ops if the staff member has zero `user_availability` rows configured.
- `agent/supabase_helpers.py` (voice agent, mirrors the above):
  - `_validate_booking_datetime(..., duration_minutes=60)` and the new
    `_validate_staff_availability(...)` — same logic and same signature shape as the backend
    versions, called from `book_appointment` and `update_appointment` in `agent/agent.py`.
  - `_resolve_work_hours(availability, day_name)` / `_compute_busy_intervals(overrides, booked,
    default_duration_minutes)` — extracted out of `_compute_available_slots` so the booking-time
    check and the advisory slot-listing tools (`get_available_slots`,
    `find_next_available_slot`) share one implementation instead of duplicating the overlap math.
- `backend/app/routers/appointments.py` — `create_appointment`/`update_appointment` propagate
  whatever `booking_service` raises; no error-message rewriting happens at the router layer.

**Frontend (ai-employees-app)**
- `src/hooks/useBusiness.ts` — `useBusinessHours(businessId, locationId)`, direct Supabase read of
  `business_hours`.
- `src/hooks/useCustomSchedules.ts` — `useCustomSchedules()`, direct Supabase read of
  `custom_schedules` for the current business + selected location, pre-sorted
  `priority desc, created_at desc` (same tie-break the backend applies).
- `src/hooks/useTeamMemberAvailability.ts` — direct Supabase read of `user_availability` +
  `user_availability_overrides` for an arbitrary `targetUserId` (an admin/manager viewing a staff
  member's schedule, as opposed to `useUserAvailability.ts` which is "my own" schedule). Wired into
  `Calendar.tsx` as of AIE-45 to source the staff-hours hint below.
- `src/pages/dashboard/Calendar.tsx`:
  - `getBusinessHoursMessage(date, staffAvailability?)` — frontend mirror of `_validate_booking`'s
    hours resolution (custom schedule first, regular hours fallback), used to render the live hint.
    Deliberately kept as logic duplicated in this file (matching the existing per-file helper
    convention here, e.g. `formatApptTime`/`parseTimeToMinutes`) rather than extracted to a shared
    lib, since only this file needs it. As of AIE-45, when the dialog's assigned staff member has
    `user_availability` configured, their hours for that day are appended to the hint (e.g.
    "· Staff hours: 9:00 AM – 4:00 PM") via `useTeamMemberAvailability`, since the actual booking is
    now validated against those hours too, not just business hours. This is advisory text only —
    the real enforcement is the backend's `_validate_staff_availability`.
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

## Bug fixed 2026-08-29 (AIE-43) — agent refused to offer later slots until pressured
`find_next_available_slot` (`agent/agent.py`) → `_find_next_slots` (`agent/supabase_helpers.py`)
scans forward day-by-day and returns at most 3 slots per staff member — always the 3 *earliest*
slots of the first day that has any opening (`slots[:3]` after `_compute_available_slots`, which
returns slots in ascending time order). Neither the tool nor the underlying helper had any
parameter for "give me something later," so when a caller asked for a later time than what was
first offered, the LLM's only options were to re-run the identical query (same 3 earliest slots
again) or fall back to `get_available_slots` for a concrete date — which the system prompt only
sanctioned once the caller named a specific date, not on a bare "do you have anything later."
Caller had to keep pushing until they stated a date/time explicitly before the agent would check
`get_available_slots` (which returns the full day, up to 8 slots) and finally surface a later
opening.

**Fix:**
- `_find_next_slots` gained an optional `after_time` (HH:MM 24-hour) param — when set, slots on
  the *first* scanned date (`from_date`) earlier than `after_time` are filtered out before the
  top-3 cap is applied; later days in the scan are unaffected so a fresh day still starts from its
  own morning. Per-staff cap stays at 3 (unchanged, still covered by
  `test_find_next_slots_returns_max_3_per_staff`).
- `find_next_available_slot` (`agent/agent.py`) exposes this as an `after_time` tool parameter,
  threaded straight through to `_find_next_slots`.
- `agent/prompt_builder.py` (`DEFAULT_INSTRUCTIONS`, booking step 6a) now instructs the agent: if
  the caller asks for something later than what was just offered, re-call
  `find_next_available_slot` with the same `staff_name`/`service_name`/`from_date` and `after_time`
  set to the last offered time, rather than assuming nothing later exists — only fall to the next
  day once that also comes back empty.

## Bug fixed 2026-08-29 (AIE-45) — bookings past an employee's actual hours
Reported: the CSE voice agent offered and booked a consultation at 4:45pm for a staff member whose
shift ends at 4:00pm.

Root cause, two layers deep:
1. `_validate_booking_datetime` (agent) / `_validate_booking` (backend) only checked the
   appointment's **start** time against **business-wide** hours — never `start + duration` (the
   actual end time), and never the specific staff member's `user_availability` at all.
2. The employee-specific, duration-aware logic already existed —
   `_compute_available_slots` correctly bounds slot generation by the staff member's `end_time` —
   but it was only used by the advisory `get_available_slots` / `find_next_available_slot` tools,
   never enforced at actual booking time. So a time the caller stated directly (rather than one
   read back from those tools) sailed through unchecked. The agent's `update_appointment`
   (reschedule) had no hours validation at all, and the dashboard's manual-booking API
   (`booking_service.py`) had the identical bug independently.

**Fix:**
- `_validate_booking_datetime` / `_validate_booking` gained a `duration_minutes` param and now
  check `start + duration <= close_time` instead of `start < close_time`.
- New `_validate_staff_availability` (both repos) checks the requested `[start, start+duration)`
  against the assigned staff member's `user_availability`, `user_availability_overrides`, and
  existing bookings (proper interval overlap, not just an exact-start-time match) — called from
  `book_appointment` and `update_appointment` (agent) and `create_appointment`/`update_appointment`
  (backend, gated on date/time/assignee actually changing).
- Skips enforcement (falls back to business-hours-only) if the staff member has zero
  `user_availability` rows configured at all, so staff who haven't set up individual hours aren't
  suddenly unbookable.
- `Calendar.tsx`'s hint now surfaces the assigned staff member's hours alongside business hours.

## Bug fixed 2026-09-01 (AIE-43 regression) — agent still reluctant, even for a named date
The 2026-08-29 fix above only patched the `find_next_available_slot` path. QA reported the agent
was *still* reluctant to offer a later time even when the caller named a specific day, suspecting
the search window was effectively ~14 hours.

Root cause, two separate bugs:
1. **UTC vs. business-local time.** `_validate_booking_datetime`, `_compute_available_slots`, and
   `_find_next_slots` (`agent/supabase_helpers.py`), plus the day-boundary calc in
   `find_next_available_slot` (`agent/agent.py`), all computed "now"/"today" via
   `datetime.now(timezone.utc)` — but compared it against **business-local wall-clock values**
   (open/close hours, staff availability, the caller's requested time, all stored/spoken as local
   HH:MM). `self._business_timezone` (e.g. `America/Toronto`) was already loaded on the agent but
   was only ever passed to the Google Calendar event-creation helpers, never into any availability
   or validation function. For a business behind UTC, this rejected genuinely-future local times
   as "already passed," and could roll the "today" date boundary over at the wrong local moment —
   this is the effective "~14 hour window" QA observed, not a literal constant anywhere.
2. **No retry path for a named date.** `get_available_slots` (used once the caller names a
   specific date, per booking step 6) had no `after_time` parameter at all, and instruction 6a only
   told the agent to retry via `find_next_available_slot`. So "something later" had literally no
   mechanism when a specific date was already in play.

**Fix:**
- New `_local_now(business_timezone)` helper in `agent/supabase_helpers.py` (stdlib `zoneinfo`,
  falls back to UTC on an unrecognised timezone string) — returns a naive local datetime so it
  compares directly against the naive HH:MM datetimes already used everywhere else in this module.
- `business_timezone` threaded through `_compute_available_slots`, `_validate_booking_datetime`,
  `_validate_booking_date`, and `_find_next_slots` (all default to `"UTC"`, so any caller that
  doesn't pass one keeps the old — now-correct-for-UTC — behavior).
- `agent/agent.py` passes `self._business_timezone` at every call site: `get_available_slots`,
  `find_next_available_slot`, `book_appointment`, and `update_appointment`'s reschedule-hours check.
- `get_available_slots` gained an `after_time` parameter mirroring `find_next_available_slot`, so
  the named-date path can also be asked for something later on the same day.
- `agent/prompt_builder.py` step 6a now covers both tools: retry whichever one made the last offer
  with `after_time` set to the last time offered.
- Added regression tests in `agent/tests/test_booking_validation.py` (`_local_now` real-offset
  check, `_validate_booking_datetime`/`_compute_available_slots` with a mocked local "now" in a
  non-UTC timezone) and fixed two pre-existing test issues surfaced while touching this file: a
  wall-clock-dependent flaky test (`test_accepts_today`) and a mock signature that didn't accept
  the new `business_timezone` positional arg.
- **Not fixed in this pass:** `backend/app/services/booking_service.py` (the dashboard's manual
  booking API) has the identical UTC-vs-local pattern — out of scope for AIE-43 since the voice
  agent doesn't use it, flagged for a future ticket.

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
