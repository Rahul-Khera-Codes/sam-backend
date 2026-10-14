# Outbound Calling + Outbound SMS Toggles

## What it does
Outbound calling (via Twilio SIP + LiveKit) and outbound SMS (via Twilio) were both already
built and shipping before AIE-62 — reminder/reschedule/no-show calls, a manual test dialer, and
booking-confirmation texts. What was missing was enforcement: the `outbound_calling` and
`send_texts_during_after_calls` toggles in Customer Service → Agent Settings were stored and
rendered but had no effect on whether calls/texts actually went out. AIE-62 closes that gap.

- **`outbound_calling`** (Call Features section) is now a master switch checked at every place an
  outbound call can be placed: the manual test dialer / `POST /calls/outbound`, and the scheduler
  jobs for reminder, reschedule, and no-show calls. It sits above the existing per-purpose flags
  (`confirmation_reminder_calls`, `reschedule_cancel_appointments`, `noshow_followup`) — those
  still control *which* automated call types run; `outbound_calling` can shut off all of them
  (and the manual dialer) at once, per location.
- **`send_texts_during_after_calls`** (Messaging Features section) is now honored for *every*
  path that sends a booking-confirmation SMS, not just voice-agent bookings. Web/dashboard-created
  appointments (`booking_service.create_appointment`) previously sent a Twilio SMS unconditionally.

## Key files
- **Shared flag check:** `sam-backend/backend/app/services/settings_service.py` (new) —
  `is_feature_enabled(business_id, location_id, feature_key, default=True)`. Same location-scoped
  semantics as `settings.py::_apply_location_filter` and the agent's own
  `agent/supabase_helpers.py::_is_feature_enabled_for_location` (exact match on `location_id`, no
  fallback to the business-wide row).
- **Manual/API outbound calls:** `sam-backend/backend/app/routers/calls.py`
  `POST /calls/outbound` — checks `outbound_calling` after resolving the location-scoped number,
  before dispatching the agent or dialing. Returns `403` if disabled.
- **Scheduled outbound calls:** `sam-backend/backend/app/services/scheduler_service.py`
  `_trigger_outbound_call()` — single helper shared by `run_reminder_calls()`,
  `run_reschedule_calls()`, and `run_noshow_calls()`; checks `outbound_calling` once at the top,
  so all three cron jobs respect it without duplicating the check.
- **Outbound SMS:** `sam-backend/backend/app/services/booking_service.py`
  `create_appointment()` — booking-confirmation SMS now gated by
  `send_texts_during_after_calls`, matching the check the voice agent already does in
  `agent/agent.py` (~line 845) before calling `agent/sms_helpers.py::send_appointment_confirmation_sms()`.
- **Settings UI (pre-existing, unchanged):**
  `ai-employees-app/src/pages/dashboard/customer-service/AgentSettings.tsx` — Call Features
  (`inbound_calling`, `outbound_calling`, `call_forwarding`) and Messaging Features
  (`send_texts_during_after_calls`) sections already match the AIE-62 mockup; no frontend change
  was needed since it already reads/writes these exact `agent_settings` rows.

## Decisions / tradeoffs (confirmed for AIE-62)
- This ticket covers the existing appointment-related outbound calling (reminders, reschedule,
  no-show follow-up, manual test dial) — **not** the separate, previously client-deferred
  cold-calling "Outbound Calling Employee" product (paused for legal reasons; see TODO.md
  history). The two are unrelated despite similar names.
- "Outbound SMS ability" means enforcing the existing `send_texts_during_after_calls` toggle
  end-to-end. No new general-purpose/standalone SMS feature (e.g. a "text this customer" action)
  was built — that would be a separate, larger ticket (needs a messages table; none exists today).
- When `outbound_calling` is off, it blocks *all* outbound call paths for that location
  (scheduler-driven and the manual test dialer), not just automated ones.

## AIE-83 — reminder/reschedule/no-show calls dialing a non-E.164 number (2026-10-14)
Sam reported (again, after two earlier AIE-83 fix rounds covering answer-detection timing and
direction-agnostic "missed" status) that an `appointment_reminder` call showed as `missed` with
`duration_seconds: 0` and `miss_reason: "dialing"` — the SIP leg never progressed past the initial
dial step. Checked Twilio's Call Logs API directly for the number/time window of that call and of
a later `noshow_followup` retry on the same appointment: **neither outbound attempt ever reached
Twilio at all** — zero matching call records on the carrier side, even though both show up as
`missed` in our `calls` table after our own internal timeout. The failure is before the SIP
trunk, not a no-answer/ring-timeout case.

Root cause: `run_reminder_calls()`, `run_reschedule_calls()`, and `run_noshow_calls()` in
`scheduler_service.py` all read `appointments.client_phone` and pass it straight to
`_trigger_outbound_call()` → `livekit_service.create_sip_participant(to_number=...)` with no E.164
normalization. The affected appointment's `client_phone` was stored as `7809944331` (no `+1`); real
inbound calls from the same person show `+17809944331`. `create_sip_participant` builds the SIP
`sip_call_to` field from whatever string it's given — a bare 10-digit number without a `+` isn't a
dialable SIP URI, so LiveKit never forwards a request to the Twilio trunk at all. This is distinct
from the earlier AIE-83 fix that normalizes `client_phone` at `book_appointment` write-time (that
only prevents *new* bookings from storing a bad number; it never re-validates at dial-time, so any
appointment whose phone was stored before that fix, or via a path that bypasses it, still dials raw).

**Fix:** all three scheduler loops now call the existing `_normalize_phone_e164()` (already in
`backend/app/services/customers_service.py`, imported into `scheduler_service.py`) on `client_phone`
immediately after reading it from the appointment row, before it's ever used to dial. Defense at the
dial site, not just the write site.

**Also fixed in the same pass:** `miss_reason` was being written to `calls` (prior AIE-83 round)
but never reached the UI — `backend/app/schemas/calls.py::CallResponse` didn't declare the field, so
FastAPI's `response_model` silently stripped it even though `select("*")` fetched it from Supabase.
Added `miss_reason: Optional[str]` to the schema, `CallRecord.miss_reason` in
`ai-employees-app/src/lib/voiceAgentApi.ts`, and a conditional "Miss Reason" stat tile in
`CallRecordings.tsx` (shown only when `status === "missed"` and a reason is present) so a future
instant-dial-failure case is visible from the dashboard without a DB query.

**Not fixed / needs a decision:** the webhook backstop (`backend/app/routers/calls.py:553`,
`POST /calls/webhook`) finalizes orphaned calls when the agent's own code path doesn't run, but it
has no access to `sip.callStatus` and never writes `miss_reason` — the `noshow_followup` retry's
`miss_reason` came back `null` because it was finalized by the backstop, not the agent. Left open
pending a decision on how/where to persist the last-known SIP status somewhere the webhook (running
after the agent process has exited) can read it.

## Known related gaps (not touched — out of scope for AIE-62)
- `agent/sms_helpers.py::send_appointment_reminder_sms()` is defined but never called anywhere —
  reminder-day SMS doesn't exist today, only reminder *calls* do.
- `ai-employees-app/src/components/OutboundCallDialog.tsx` is dead code — not imported/rendered
  anywhere; `CustomerServiceEmployee.tsx`'s own "Outbound Test" tab is the live manual dialer.
- `booking_service.py` and `agent/sms_helpers.py` still have two independent Twilio
  confirmation-SMS code paths with different message templates (one per booking origin) —
  functionally fine post-fix (both now respect the toggle) but a future cleanup could unify them.
