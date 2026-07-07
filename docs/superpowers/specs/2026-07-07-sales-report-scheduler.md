# Sales Employee — Report Scheduler (backend, MVP)
**Date:** 2026-07-07
**Branch:** `feature/sales-lead-researcher`
**Status:** Implemented and verified end-to-end — created a real schedule, previewed it, and confirmed real email delivery via `send-test` (Gmail), correctly formatted across all 3 sections. One real bug found and fixed during testing: the Gmail token lookup was location-scoped (via the shared `email_service.get_valid_access_token`), but this business's Gmail connection was tied to a specific `location_id`, not business-wide — added a location-agnostic lookup specific to this module rather than changing the shared helper (other callers correctly rely on its per-location behavior). XSS/HTML-injection review also caught and fixed: digest content (indirectly sourced from scraped competitor posts and Exa search results) is now HTML-escaped before embedding in the email; recipient emails are now format-validated.

---

## Request
Fourth and last Sales Employee module. Lets the owner set up an automatic email digest (daily/weekly/monthly) combining highlights from Lead Researcher, Competitor Agent, and Market Agent, sent to a recipient list. Live preview of the email, plus a "Send Test Email" button before turning it on.

## Phase 1 — Verified

**This module needs no new external API.** Unlike the other 3, it's pure aggregation of data already sitting in `lead_lookups`, `competitor_reports`, and `market_analysis_cards`/`market_analysis_runs` — no Apify/Exa/YouTube calls. The only external dependency is sending email, which this codebase already does via the business's connected Gmail account (`backend/app/services/email_service.py` — `get_valid_access_token` + `send_email`), the exact same mechanism used for appointment confirmations. Confirmed this requires the business to have Gmail connected — if not, sending fails gracefully (same behavior as `send_appointment_confirmation`, which returns `False` rather than erroring, per existing convention).

**Scheduling precedent:** the reminder/reschedule/no-show jobs in `scheduler_service.py` use an hourly *sweep* pattern (check all active configs, act on the ones that are due) rather than one APScheduler job per row. Report Scheduler needs the same — one hourly sweep job checking every active `report_schedules` row against its frequency + `last_sent_at`, not a per-schedule cron job (which APScheduler can't dynamically manage as cleanly for a variable, user-editable set of schedules).

**Preview/test-send need no async job either** — since all the underlying data already exists, building the digest is just synchronous DB reads + one HTML template, fast enough to return directly in a request.

## Phase 2 — Architecture

### Data model (1 new table)
**`report_schedules`** — `id`, `business_id`, `name`, `frequency` (`daily`/`weekly`/`monthly`), `recipients` (jsonb array of emails), `include_lead_researcher`/`include_competitor_agent`/`include_market_agent` (bool each), `is_active`, `last_sent_at`, `created_at`, `updated_at`.

**"Custom" frequency from the mockup is out of scope for this pass** — daily/weekly/monthly covers the real need; open-ended custom scheduling (specific days, intervals) adds real complexity without a confirmed use case, same reasoning as deferring "Add Custom Report" complexity elsewhere.

### Runtime flow
1. `POST /schedules` / `PATCH /schedules/{id}` / `DELETE /schedules/{id}` / `GET /schedules` — standard CRUD, `verify_business_access` throughout.
2. `GET /schedules/{id}/preview` — builds the digest HTML synchronously from current data (no send) — for the live preview in the UI.
3. `POST /schedules/{id}/send-test` — builds the digest and sends it to the requesting user's own email (their JWT's email claim) via the business's connected Gmail, **without updating `last_sent_at`** — test sends don't count as real scheduled sends.
4. New hourly sweep job (`run_report_scheduler_digests`, same pattern as `run_reminder_calls`) in `scheduler_service.py`: for each active schedule, check if due (`daily`: >24h since `last_sent_at` or never sent; `weekly`: >7 days; `monthly`: >30 days), build the digest, send to all `recipients`, update `last_sent_at` immediately before sending (same double-send prevention pattern as the existing reminder-call jobs).

### Digest content (per included module)
- **Lead Researcher:** completed lookups since `last_sent_at` (or the 5 most recent if never sent) — name, company, headline.
- **Competitor Agent:** most recent completed report per tracked competitor — overview line per competitor.
- **Market Agent:** the latest run's `whats_changing_summary` + card headlines.

If a business has no data for an included module (e.g. never used Competitor Agent), that section is simply omitted from the email rather than showing an empty placeholder.

### Files
- `ai-employees-app/supabase/migrations/<timestamp>_report_schedules.sql` — 1 table + RLS.
- `backend/app/schemas/report_scheduler.py` (new).
- `backend/app/routers/report_scheduler.py` (new) — CRUD + preview + send-test.
- `backend/app/services/email_service.py` — add a digest-email builder function, following the existing `build_appointment_confirmation_email` template style.
- `backend/app/services/scheduler_service.py` — add the hourly sweep job.
- `backend/app/main.py` — register router.

## Not in scope
- "Custom" frequency (deferred, see above).
- Per-recipient personalization — one email body sent to everyone on the list.
