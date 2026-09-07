# Appointment No-Show Follow-Up

## What it does
When staff mark an appointment `No Show` (Calendar → Edit Appointment → status buttons), an
hourly cron job (`run_noshow_calls()`) later places an outbound AI call offering to reschedule.
Call-only — no SMS (per the `noshow_followup` UI copy: "AI calls customers who didn't show up
and asks if they want to reschedule"). Configurable per business/location in Customer Service →
Agent Settings: `days` (how many days after the no-show to call) and `message_template` (the
opening script).

## Key files
- **Status set:** `sam-backend/backend/app/routers/appointments.py` `PATCH /appointments/{id}/status`
  — writes `status='no_show'`, `no_show_at`, `no_show_by_user_id`, `no_show_by_code`.
- **Cron job:** `sam-backend/backend/app/services/scheduler_service.py` `run_noshow_calls()`,
  registered hourly (`id="noshow_calls"`) in `start_scheduler()`. Reads config from
  `agent_settings` (`feature_key='noshow_followup'`), finds `no_show` appointments where
  `no_show_at` falls in the target day (`today - days`) and `noshow_called_at IS NULL`, marks
  `noshow_called_at` immediately (prevents double-calls), then dials via the shared
  `_trigger_outbound_call()` helper (same helper used by reminder/reschedule jobs).
- **Agent script:** `sam-backend/agent/agent.py` — outbound call handler checks
  `call_purpose in ("appointment_reminder", "appointment_reschedule", "noshow_followup")` to
  decide whether to open with the configured `message_template` verbatim vs. a generic greeting.
- **Feature flag seed:** `ai-employees-app/supabase/migrations/20260907140000_seed_noshow_followup_feature.sql`
  — adds `noshow_followup` to `seed_agent_settings_for_business()` (new businesses) and
  backfills existing businesses + locations. New locations pick it up via the existing
  `POST /locations/{id}/seed` → `location_seed_service.seed_location_data()` copy-forward path.
- **Settings UI:** `ai-employees-app/src/pages/dashboard/customer-service/AgentSettings.tsx`
  (`noshow_followup` entry, `APPOINTMENT_FEATURES` list, template editor).

## AIE-65 fix (2026-09-07)
The feature was fully wired end-to-end but never actually fired, for three independent reasons:
1. **`noshow_followup` was never seeded** into `agent_settings` — absent from
   `seed_agent_settings_for_business()` (missed when the feature was added after that trigger
   was last touched) and never backfilled. Every business/location had no row for this
   feature_key, so the cron job's `.eq("feature_key", "noshow_followup").eq("is_enabled", True)`
   query never matched anything. Fixed by the migration above.
2. **Agent whitelist gap** — `agent.py`'s `call_purpose` whitelist for using the custom
   `message_template` didn't include `"noshow_followup"` (copy-paste from reminder/reschedule
   never updated), so even a successfully-triggered call used a generic "how can I help you?"
   opener instead of the configured reschedule script. Fixed by adding `"noshow_followup"` to
   the tuple.
3. **Query keyed off the wrong timestamp** — `run_noshow_calls()` filtered on
   `appointment_date == today - days` (when the appointment *was scheduled*) instead of
   `no_show_at` (when it was *actually marked* no-show). Staff marking a no-show any day other
   than the appointment date itself meant the appointment was permanently skipped. Fixed to
   window on `no_show_at`, matching `run_reschedule_calls()`'s existing `updated_at` pattern.

## Known adjacent gap (not fixed, out of scope for AIE-65)
`agent_settings` per-location seeding for newly-created locations is best-effort: the frontend
calls `POST /locations/{id}/seed` after inserting the location, but the error is swallowed
(`try/catch` in `LocationsTab.tsx` and `Onboarding.tsx`) and there's no DB trigger or
server-side transaction as a safety net. If that call fails, the new location silently ends up
with zero `agent_settings` rows (all toggles read as off, no fallback to the business-wide
row — `_apply_location_filter` in `settings.py` is an exact match). This affects every feature
flag, not just this one — worth a separate hardening pass if it recurs.
