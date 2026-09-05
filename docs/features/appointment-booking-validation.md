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
- `src/components/business/BusinessDateOverrideModal.tsx` / `BusinessDateOverridesList.tsx` (AIE-46,
  2026-09-03) — simplified single-date add/list UI over `useCustomSchedules`, restricted to
  `schedule_type: "one_time"` rows. Surfaced in Business Settings → Business Hours tab as "Business
  Date Overrides", separate from the pre-existing per-user "Team Member Date Overrides" card
  (`DateOverrideModal`/`DateOverridesList`, `useUserAvailability`) that sits below it on the same
  tab. See AIE-46 below for why these are two distinct cards.
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

## Bug fixed 2026-09-02 (AIE-43 regression #2) — LLM misresolved "Tuesday afternoon" to the wrong date
QA reported the agent couldn't book an afternoon slot on a Tuesday even after the 2026-09-01 fix
(call id `fa3c7eab-a118-4493-a2e7-c450375e2ebb`).

Root cause: the 2026-09-01 fix made every *validation/slot-computation* function timezone-correct,
but none of them are what maps a caller's spoken relative day ("this Tuesday", "tomorrow") to a
concrete `YYYY-MM-DD` — that conversion is done entirely by the LLM (OpenAI Realtime model) before
it calls `get_available_slots`/`find_next_available_slot`. `agent/prompt_builder.py`'s
`build_instructions` (the CSE agent's system prompt) never told the LLM what today's date or
day-of-week is at all — unlike `executive_agent.py`/`hr_onboarding_agent.py`, which both inject a
"Today is {date}." line. With no anchor, the LLM could resolve "Tuesday" to the wrong calendar date
(e.g. last week's or next week's Tuesday), which then correctly had no afternoon slots per the
now-accurate validation — read back to the caller as "no availability."

Also found in the same file: the active-custom-schedule hours override (`build_instructions`) keyed
its "today" row off naive `datetime.now().strftime("%A")` (container/UTC clock) instead of the
business's local day — same bug class as 2026-09-01, missed in that pass since it lives in
`prompt_builder.py` rather than `supabase_helpers.py`.

**Fix:**
- `build_instructions` now derives `business_timezone` from the fetched `business` row (falls back
  to `"America/Toronto"`, matching `agent.py`'s existing default) and prepends a grounding line —
  `"Current date: today is {weekday}, {Month Day, Year} ({timezone}). Use this to resolve any
  relative day the caller mentions..."` — computed via the existing `_local_now(business_timezone)`
  helper, right after the welcome block.
- The custom-schedule override's `today_dow` now also uses `_local_now(business_timezone)` instead
  of naive `datetime.now()`.
- `agent/agent.py`'s `find_appointments`, `update_appointment`, and `cancel_appointment` had three
  more naive `datetime.now()` "today" filters (`.gte("appointment_date", ...)`, unrelated to new
  bookings but same bug class, flagged by Rahul on 2026-09-01 as still open) — switched to
  `_local_now(self._business_timezone)` in the same pass.
- Added regression tests in `agent/tests/test_prompt_builder.py`: the grounding line is present and
  uses the business's own timezone (not just the default), and the custom-schedule override calls
  `_local_now` with the business timezone rather than the server clock.
- **Not fixed in this pass:** `executive_agent.py`/`hr_onboarding_agent.py` also compute their
  "Today is ..." line via naive `datetime.now()` — out of scope for AIE-43 (CSE booking agent only),
  flagged here for a future ticket since it's the same underlying pattern.

## Feature added 2026-09-03 (AIE-46) — Business-level Date Overrides UI
Original ticket asked to move the "Date Override" section from Profile settings into Business
Settings, under Business Hours. That move (2026-09-01) only relocated the UI — the override it
manages was, and still is, scoped to the *logged-in user* (`user_availability_overrides`, `user_id`
only, no `business_id`/`location_id`). Sam reopened the ticket: a business needs two independent
override concepts shown together — the business itself can be closed for a holiday while an
individual team member's own vacation override is a separate thing, and vice versa (business open,
one staff member out).

**Decision: reuse `custom_schedules`, don't add a new table.** That table is already
business+location-scoped and already the sole source `_fetch_active_custom_schedule` (see above)
checks *before* regular weekly hours, with `is_agent_disabled` already meaning "business closed."
Its existing UI (`CustomScheduleDialog`/Scheduler page) supports this but is built for the richer
recurring/priority/named-schedule case. Rather than fork the data model, a second, simpler
add/list UI (`BusinessDateOverrideModal`/`BusinessDateOverridesList`) was added that only creates
and lists `schedule_type: "one_time"` rows (multi-date calendar picker, "Mark Business as Closed" or
custom hours, optional reason → `name`), mirroring the UX of the pre-existing per-user override
modal. Because it's the same table, a business-level override added from either surface (Business
Hours tab or Scheduler) is immediately enforced by the existing backend/agent booking validation —
no backend change was needed for this ticket.

**Result:** Business Settings → Business Hours tab now shows three cards top to bottom: the weekly
hours grid, "Business Date Overrides" (new, `custom_schedules`), and "Team Member Date Overrides"
(renamed from "Date Overrides", unchanged behavior, `user_availability_overrides`).

**Tradeoff flagged, not acted on:** a one-time row created via this new card is indistinguishable
from one created via the Scheduler's Custom Schedule dialog — both just filter to
`schedule_type: "one_time"` — so they'll cross-appear in both UIs. Considered acceptable/desired
(a holiday added from either screen should show up everywhere), but worth knowing if the two UIs
ever need to diverge in meaning.

## Feature updated 2026-09-04 (AIE-46) — Team Member Date Overrides moved back to Profile
Sam asked (comment on AIE-46, with a screenshot of the "Team Member Date Overrides" card as it
looked in the Business Hours tab) to move that card specifically — not "Business Date Overrides" —
back into Profile Settings, under "My Availability."

**Result:** `ai-employees-app/src/pages/dashboard/AccountSettings.tsx` now renders a "Team Member
Date Overrides" card (same `DateOverrideModal`/`DateOverridesList` components, unchanged behavior,
still `user_availability_overrides`) directly below the "My Availability" weekly-hours section.
Removed from `ai-employees-app/src/pages/dashboard/BusinessSettings.tsx`'s Business Hours tab,
which now shows only two cards: the weekly hours grid and "Business Date Overrides"
(`custom_schedules`, unchanged). No component or data-model changes — this was a pure relocation of
the existing per-user override UI, same as the underlying components take no props tied to Business
Settings context.

**Access control:** `custom_schedules` RLS restricts INSERT/UPDATE/DELETE to `admin`/`super_admin`.
Business Settings (`/dashboard/settings/business`) is already gated to those same roles by default
(`RESTRICTED_PAGES` in `src/lib/roles.ts`), so no new permission gap was introduced — confirmed
before implementing, not assumed.

## Bug fixed 2026-09-04 (AIE-56) — agent kept re-offering the same day for "afternoon, any day this week"
Filed by Heather as a deliberate follow-up to AIE-43 ("I will report a separate ticket for the
'any day of the week' issue") once the same-day "later time" fix was verified. Reported behavior:
asking for an afternoon appointment without naming a specific day made the agent keep circling back
to the first day it had already offered instead of checking other days in the week, until pressed
repeatedly.

Root cause: `find_next_available_slot` → `_find_next_slots` (`agent/supabase_helpers.py`) scans
forward day-by-day and returns the first day with *any* slots — but its only "steer the search"
parameter, `after_time` (added for AIE-43's "later, same day" fix), is deliberately restricted to
`from_date` only (`if after_time and i == 0`) so a later day's untouched morning slots aren't hidden.
That's correct for "later than what you just offered, same day," but gave the model no way to
express "any day, but only afternoons" — a standing time-of-day preference that should hold across
every day scanned, not just the first. The prompt's only instruction for "a different day" (step 6a)
told the model to retry the *same* `from_date`/`date` with a bumped `after_time` and only "naturally"
fall through to the next day once that came back empty — nothing told it to carry a time-of-day
constraint forward across days, so it either kept re-checking the same day or landed on a different
day's non-matching (e.g. morning-only) slots.

**Fix:**
- Added a new `min_time` parameter to `_find_next_slots` (`agent/supabase_helpers.py`), distinct from
  `after_time`: it filters every day in the scan (not just `i == 0`), so `min_time="12:00"` finds the
  first day that actually has an afternoon slot, skipping non-matching days entirely rather than
  stopping on the first day that has *some* (possibly wrong-time-of-day) opening.
- Threaded `min_time` through `find_next_available_slot` (`agent/agent.py`) as an optional tool
  parameter, with its own docstring explaining when to use it instead of `after_time`.
- Added prompt step 6a-2 (`agent/prompt_builder.py`) telling the model: when the caller's ask is a
  standing time-of-day preference not tied to the day already offered ("anything in the afternoon
  this week", "any day, just not mornings"), call `find_next_available_slot` again with `min_time`
  instead of re-checking the same day.
- Added regression tests in `agent/tests/test_booking_validation.py`:
  `test_find_next_slots_min_time_applies_across_every_day` (Monday morning-only + Tuesday
  afternoon-only availability, `min_time="12:00"` must skip Monday and return Tuesday) and
  `test_find_next_slots_after_time_does_not_leak_into_later_days` (locks in the pre-existing
  `after_time`-is-`from_date`-only invariant this fix depends on, so a future change can't
  accidentally make `after_time` and `min_time` collide). Full `agent/tests/` suite run: 52 passed,
  1 pre-existing unrelated failure (`test_prompt_builder.py::test_build_instructions_custom_greeting_replaces_welcome_block`,
  flagged during AIE-43's 2026-09-03 pass, not touched here).
- **Not investigated:** the ticket notes "Brand Voice is set to Friendly and Conversational in
  Global Settings" — no code path connects brand-voice tone/style to search or tool-call behavior
  (`_format_brand_voice` only affects phrasing), so this is very likely incidental context from the
  business used to reproduce, not a causal factor. Flagged here rather than assumed away.

## Bug fixed 2026-09-05 (AIE-56 round 2) — agent fabricated "the latest this week" from one day's data
QA bounced the 2026-09-04 `min_time` fix back with a fresh repro (call id
`13eef36c-98ef-4227-bcc4-672f1d00a3e3`, pulled and read via the `transcripts` table): caller asked
"what's your latest appointment during the week?", agent found Tuesday's afternoon slot (via
`min_time`, working as designed) and correctly stated Tuesday's own last time (3:00 PM). Caller
pushed further ("anything later during the week?"), and the agent replied "the latest available
consultation we have during the week is ... Tuesday ... 3:00 PM" — restating the same single day's
last time as if it were the whole week's answer, without checking any other day. When the caller
then named Thursday specifically, the agent found a 5:45 PM slot — proving Tuesday's 3:00 PM was
never actually the week's latest, the agent just had no way to know that and answered anyway.

Root cause: `min_time`/`after_time` and `_find_next_slots` only ever answer "the first day that
matches a filter" — the scan stops at the first hit and never looks at, or compares against, any
later day. There was no tool capability at all for "collect every matching day and tell me the
single latest one" — a structurally different question from "the soonest match." The 2026-09-04
fix closed the "any day, standing time-of-day preference" gap but never touched this one; QA's new
repro is a different request shape ("the latest/last", not "an afternoon, any day"), not a
regression of that fix.

**Fix:**
- Added `_find_latest_slot` (`agent/supabase_helpers.py`) — a sibling to `_find_next_slots` that
  scans forward across a bounded `within_days` window (default 7, i.e. "this week") and returns
  the single slot with the greatest `(date, time)`, not the first day with any match. Supports the
  same `min_time` floor semantics for "latest afternoon slot this week"-style asks.
- Added a new tool, `find_latest_available_slot` (`agent/agent.py`), rather than overloading
  `find_next_available_slot` with a mode flag — keeps "find soonest" and "find latest" as two
  distinct, unambiguous tool choices for the model instead of one tool with a hidden behavior
  switch. Its docstring explicitly tells the model not to answer a "latest this week" question
  from a single day's result.
- `agent/prompt_builder.py` gained step 6c: caller asks for the latest/last appointment across a
  period (not a single named day) → call `find_latest_available_slot`, never answer from a prior
  single-day result. Step 6b was tightened to explicitly forbid describing one day's last time as
  "the latest this week" without qualifying it to that day. Step 5 also now tells the model to go
  straight to `min_time`/`find_latest_available_slot` when the caller states a time-of-day or
  latest/last preference *before* any offer has been made, instead of only reacting after an
  initial (wrong) offer — the "must be pressed" complaint in the ticket title was partly this:
  every fix so far only ever triggered reactively, after a correction round-trip.
- Added regression tests in `agent/tests/test_booking_validation.py`:
  `test_find_latest_slot_picks_max_across_days_not_first_match` (direct repro shape: two earlier
  matching days plus a later, later-still day — must return the later-still day, not stop early),
  `test_find_latest_slot_respects_min_time_floor`, `test_find_latest_slot_within_days_bounds_the_search`,
  `test_find_latest_slot_returns_none_when_nothing_matches`. Full `agent/tests/` suite: 56 passed,
  same 1 pre-existing unrelated failure as before (`test_build_instructions_custom_greeting_replaces_welcome_block`).
- **Note on "this week" semantics:** `within_days` is a rolling N-day window from `from_date`
  (default 7), not a calendar-week (Mon–Sun) boundary — simpler to reason about and matches how
  callers actually use "this week" mid-week (meaning "the next several days," not strictly through
  Sunday). Flagged here in case a future ticket wants literal calendar-week semantics instead.

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
