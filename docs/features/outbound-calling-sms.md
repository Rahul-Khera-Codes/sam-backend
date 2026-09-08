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

## Known related gaps (not touched — out of scope for AIE-62)
- `agent/sms_helpers.py::send_appointment_reminder_sms()` is defined but never called anywhere —
  reminder-day SMS doesn't exist today, only reminder *calls* do.
- `ai-employees-app/src/components/OutboundCallDialog.tsx` is dead code — not imported/rendered
  anywhere; `CustomerServiceEmployee.tsx`'s own "Outbound Test" tab is the live manual dialer.
- `booking_service.py` and `agent/sms_helpers.py` still have two independent Twilio
  confirmation-SMS code paths with different message templates (one per booking origin) —
  functionally fine post-fix (both now respect the toggle) but a future cleanup could unify them.
