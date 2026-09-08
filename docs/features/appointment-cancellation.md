# Appointment Cancellation (phone + dashboard)

## What it does
Cancelling an appointment — whether a customer says "cancel my appointment" on a call, or staff
click Cancel in the dashboard — never deletes the row. Both paths set `appointments.status =
'cancelled'` and leave the record in place, so it stays visible in the calendar as a flagged,
grayed-out/struck-through card instead of disappearing.

## Key files
- **Voice agent cancel:** `sam-backend/agent/agent.py` `cancel_appointment()` — looks up the
  match via `find_appointments()` (name + service/date/time confirmed verbally first), then
  `UPDATE appointments SET status='cancelled'` on the matched row. Never issues a `DELETE`.
- **Dashboard cancel:** status is changed the same way via the appointment status endpoint in
  `sam-backend/backend/app/routers/appointments.py`.
- **Calendar display:** `ai-employees-app/src/pages/dashboard/Calendar.tsx` — cancelled
  appointments are now loaded (not filtered out of the query) and rendered with a "Cancelled"
  badge, grayed-out + line-through styling (`apt.status === "cancelled"`). Conflict checks and
  outbound-call/reschedule pickers explicitly exclude `status === "cancelled"` so a cancelled
  slot isn't treated as still booked or callable.
- **Voice agent instructions:** `sam-backend/agent/prompt_builder.py` `DEFAULT_INSTRUCTIONS` —
  "Rescheduling or cancelling" section governs the call flow; `find_appointments`,
  `cancel_appointment`, `update_appointment` tool docstrings in `agent/agent.py` are the
  function-calling contract the LLM sees.

## AIE-67 (2026-09-06 → 2026-09-08)

Reported as "cancelling over the phone deletes the card." First pass (2026-09-07) found the row
was never actually deleted — `cancel_appointment` always set `status='cancelled'`. The card
*looked* deleted because the calendar's own fetch query hard-excluded `status='cancelled'` rows.
Fixed by loading cancelled appointments too and flagging them in the UI (see Calendar display
above) instead of hiding them.

QA then surfaced the real end-to-end failure (2026-09-07 comment): the voice agent asks for the
customer's **full name** when cancelling, but only asked for a **first name** when booking. Since
`find_appointments`/`cancel_appointment` match via `ilike client_name, '%<query>%'`, a full-name
search (`%John Smith%`) can't match a row stored with just `client_name='John'` — the appointment
silently "isn't found," which is what actually blocked cancellation for affected callers (a
different failure mode from the calendar-hiding bug, and the real repro for the "card is gone"
report — the customer got told there was no matching appointment).

Fix (2026-09-08): `DEFAULT_INSTRUCTIONS` in `prompt_builder.py` now requires asking for **both**
first and last name during booking (step 7) and again before the cancel/reschedule lookup (step
1 of that section) — if the customer only volunteers a first name, the agent must explicitly ask
for the last name before proceeding either way. The `book_appointment`, `find_appointments`,
`cancel_appointment`, and `update_appointment` tool docstrings in `agent.py` were updated to
match, so the LLM's function-calling reasoning reinforces the same rule. No schema or query
change was needed — once both flows store/search the same full name, the existing `ilike`
substring match works correctly.
