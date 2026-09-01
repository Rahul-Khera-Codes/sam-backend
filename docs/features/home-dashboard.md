# Home Dashboard (AIE-47)

## What it does
The `/dashboard` route — previously an 18-line "Coming Soon" placeholder — is now a real
home dashboard answering "what are my AI employees doing, what needs me, how's the business
today" without duplicating each module's own detail pages. Built from a mockup
(`aie-dashboard-mockup.html`, attached to the Linear ticket) but wired entirely to **real
data**, not the mockup's demo numbers. Sections: a 5-card AI-employee roster (Customer
Service, Marketing, Sales, HR, Executive Assistant/Remi), a "Needs your attention" queue,
a cross-module recent-activity feed, today's appointments, a revenue-this-week card,
a plan-usage card, and a setup checklist.

## Data model
No new tables or migrations — every new endpoint computes from existing tables at read
time (`appointments`, `appointment_payments`, `appointment_payment_entries`, `calls`,
`marketing_scheduled_posts`, `hr_job_applications`, `business_phone_numbers`,
`business_hours`, `google_calendar_tokens`, `marketing_platform_integrations`,
`business_documents`, `hr_job_postings`).

## New backend endpoints

- **`GET /appointments`** (`routers/appointments.py`) — the first list/today view for
  appointments (previously CRUD-by-id only). `business_id` required; `location_id`,
  `date_from`/`date_to` (default: today in `businesses.timezone`), `status` optional.
  Excludes cancelled. Returns `AppointmentListItemResponse[]` with batched staff-name and
  payment-status joins (no N+1).
- **`GET /reports/revenue-summary`** (`routers/reports.py`, new `schemas/reports.py`) —
  **this calendar week vs last calendar week** (Mon–Sun, business timezone — deliberately
  not a rolling window, unlike `analytics.py`'s calls periods), plus an **all-time**
  outstanding-balance total and the oldest outstanding invoice.
- **`GET /dashboard/activity-feed`** (new `routers/dashboard.py`) — merged, time-sorted feed
  across calls, appointments, payment entries, published marketing posts, and HR
  applications. Sequential fan-out queries (not `asyncio.gather` — no precedent for it
  anywhere in this codebase and each query is a fast, indexed `LIMIT 20`). Returns one
  `items` list (see "Deviations" below — the frontend does not get a separate
  attention-queue payload from this endpoint).
- **`GET /dashboard/setup-checklist`** (new `routers/dashboard.py`) — 6 independent
  existence checks, computed fresh every call (nothing stored): phone number claimed,
  business hours set (row-count check directly on `business_hours` — bypasses
  `GET /settings/agent/schedule`'s default-schedule fallback, which can't distinguish
  "configured" from "never touched"), Google Calendar connected, Instagram connected,
  knowledge base has content, and "publish your first job posting" (`hr_job_postings`)
  — this last item **replaces "Connect Greenhouse"** from the original ticket, since
  Greenhouse was fully removed from the product the same day this ticket was scoped
  (`20260825120000_remove_greenhouse_integration.sql`). Google Calendar, Instagram, and
  job-posting checks are inherently business-wide (no `location_id` column on those
  tables) regardless of the `location_id` param passed in.

All 4 endpoints use `Depends(require_business_access())` + `_apply_location_filter` per
existing convention (`analytics.get_summary` is the template).

### Shared helper extracted
`compute_invoice_status(grand_total, entries, refunded_at)` in
`services/booking_service.py` — the paid/owing/status derivation logic that was
independently duplicated in `appointments.py`'s `_build_full_payment_response` and
`reports.py`'s `get_payment_summary_report`. Both now call the shared function; the new
`GET /appointments` endpoint uses it too. Similarly, `reports.py`'s subtotal/tax/tip
entry-splitting math was extracted into `_split_entry`, shared between the existing
payment-summary report and the new revenue-summary endpoint.

## Frontend
- **`src/pages/dashboard/Dashboard.tsx`** — full rewrite: location-gate
  (`SelectLocationPrompt` when no location selected) → header → 5-card roster grid →
  two-column grid (Attention Queue + Activity Feed on the left; Appointments, Revenue,
  Plan Usage, Setup Checklist on the right).
- **`src/hooks/useAgentState.ts`** (new, shared) — the Customer Service quick on/off
  toggle logic (fetch, optimistic update, `toggleAgentState` + `inbound_calling`-preserving
  `updateAgentSettings` sync, revert-on-error, toast) was previously duplicated in
  `Scheduler.tsx` and `AgentSettings.tsx` (the latter also had dead code,
  `handleToggleAgent`, never wired to any JSX). Extracted into one hook; both pages and
  the new dashboard roster card now consume it. Polls every 60s.
- **`src/hooks/{useDashboardRoster,useTodaysAppointments,useRevenueSummary,useActivityFeed,useAttentionQueue,usePlanUsage,useSetupChecklist}.ts`**
  — one hook per widget, matching the app's existing manual `useState`/`useEffect`
  convention (TanStack Query is installed but unused anywhere in this app; deliberately
  not introduced here either — see Decisions below). Only `useAgentState` and the
  Customer Service slice of `useDashboardRoster` poll (60s); everything else fetches once
  per mount/location-change.
- **`src/components/dashboard/*`** — `DashboardHeader`, `RosterCard` + `AgentStatusDot`,
  `AttentionQueueCard`, `ActivityFeedCard`, `AppointmentsListCard`, `RevenueCard` (recharts
  bar chart, same template as `AgentPerformance.tsx`), `UsageMeterCard`,
  `SetupChecklistCard`, `SelectLocationPrompt` — all built from shadcn primitives
  (`Card`/`Badge`/`Switch`/`Progress`/`Skeleton`), not the mockup's raw CSS.
- **`src/lib/voiceAgentApi.ts`** — new functions `getTodaysAppointments`,
  `getRevenueSummary`, `getDashboardActivityFeed`, `getSetupChecklist`, following the
  existing `fetchWithAuth` + `URLSearchParams` pattern.

## Decisions / deliberate deviations from the mockup and original ticket
- **Greenhouse checklist item → "Publish your first job posting."** Greenhouse no longer
  exists in the product; posting a job is the closest one-time "setup" action (reviewing
  candidates is ongoing, not a setup step).
- **Remi is the only roster card with an "un-hired" gated state** (checked via
  `executive_agent_addon_enabled` from billing). Customer Service/Marketing/Sales/HR
  always render active with real zero-states — there's no general "which modules has
  this business hired" concept in the schema to gate the other four on.
- **No live Remi session-tracking was built.** `POST /executive/session` is ephemeral;
  there's no persistent "is Remi connected right now" table. The Remi card's status is a
  static enabled/disabled read of the billing add-on, not a live indicator.
- **Plan-usage second meter shows "calls this week" as a plain count, not a
  limit-progress-bar** — billing is minutes-only; there is no real call-count cap to
  render a meaningful progress bar against. The mockup's "Calls / 200" is fabricated data
  that was deliberately not reproduced.
- **Revenue card's 7-day bar chart pulls from the existing `GET /reports/payment-summary`
  endpoint's `by_date` breakdown**, not from `revenue-summary` (which only returns weekly
  aggregates, no daily series) — an extra network call, but avoids fabricating a daily
  breakdown that endpoint doesn't provide.
- **"Needs your attention" is a client-side composition, not a distinct backend payload.**
  `GET /dashboard/activity-feed` returns one merged `items` list; the attention-queue
  widget (`useAttentionQueue.ts`) instead composes 5 already-real sources directly:
  marketing drafts awaiting approval, outstanding balance (from revenue-summary), HR
  candidates pending, documents with `embedding_status !== "ready"`, and unanswered
  forwarded calls. All real data — no fabrication — but this deviates from the plan's
  original assumption that the backend would pre-split attention items from activity
  items.
- **Marketing's roster stat and workspace/drafts calls have no `location_id` filter** —
  `marketingEmployeeMock.ts` (the file that actually makes these real backend calls,
  despite its name) has no location parameter at the API layer today. The roster's
  Marketing card is therefore business-wide regardless of the selected location. Flagged
  as a known gap, not fixed as part of this ticket.
- **Kept the app's manual `useState`/`useEffect` hook convention** rather than introducing
  TanStack Query for this dashboard, even though a multi-widget dashboard with mixed
  polling/one-shot semantics is arguably the best-fit case for it in the whole app —
  confirmed with the user as a deliberate choice to avoid setting a new, unreviewed
  pattern with zero existing examples to follow.

## Post-launch fix: loading flash on every re-visit
After initial ship, navigating away from `/dashboard` and back showed a full loading
skeleton every time, even when nothing had changed. Root cause: `Dashboard.tsx` fully
unmounts on route change (React Router tears down the whole component tree), and every
dashboard hook's `useState(true)` loading flag + empty initial data reset on remount —
there was no caching layer, by design (see "manual useState/useEffect" decision above).

Fix: added `src/lib/dashboardCache.ts`, a simple module-level `Map` keyed by
business/location (and any other relevant param, e.g. `limit`). Each of the 8 dashboard
hooks (`useAgentState`, `useDashboardRoster`, `useTodaysAppointments`, `useRevenueSummary`,
`useActivityFeed`, `useAttentionQueue`, `usePlanUsage`, `useSetupChecklist`) now:
1. Lazily initializes its state from the cache on mount (`useState(() => getDashboardCache(key) ?? ...)`)
   instead of always starting empty/loading.
2. On fetch, only shows the loading state if there's no cached value yet for the current
   key; a cache hit hydrates instantly and the real fetch happens silently in the
   background to refresh it.
3. Writes the cache on every successful fetch (and `useAgentState`'s optimistic
   toggle/revert also keeps the cache in sync so a remount doesn't show a stale value).

Cache keys are scoped to match each endpoint's actual filtering — e.g.
`useDashboardRoster`'s marketing/sales/hr/exec slices are keyed by `businessId` only (no
`location_id`), matching that those calls are business-wide, while its Customer Service
slice and every location-aware hook include `selectedLocationId` in the key. The cache is
in-memory only (cleared on a real page reload, not persisted to storage) — a fresh page
load is still expected to show a real loading state once.

## Known gaps / pending work
- **No automated browser verification was performed** — `tsc --noEmit` is clean and both
  Docker stacks were rebuilt and confirmed responsive, and all 4 new backend endpoints
  were curl-verified against real data, but nobody has clicked through the actual rendered
  page in a browser yet. This is the first thing to do before considering AIE-47 fully
  done.
- **Marketing dashboard data is business-wide, not location-scoped** (see above) — fixing
  this requires adding a `location_id` param to `marketingEmployeeMock.ts`'s API calls and
  to `marketing_platform_integrations`/`marketing_scheduled_posts` queries backend-side.
- **No live "is Remi in an active session" tracking** — would need a new table or
  in-memory registry keyed off active LiveKit rooms if a truly live indicator is wanted
  later.
- **Setup checklist items for Google Calendar / Instagram / job postings are business-wide
  only** — those tables have no `location_id` column, so a multi-location business sees
  the same checklist state regardless of which location is selected.
- **Activity feed and attention queue are read-time fan-outs, not a write-time events
  table.** Fine at current scale (5-6 small indexed queries per request); if this becomes
  a hot polled path or table sizes grow significantly, revisit with either
  `asyncio.to_thread`-based parallel fan-out or a dedicated
  `dashboard_activity_events` table populated by each write path.
- **Revenue card makes two backend calls** (`revenue-summary` for weekly figures +
  `payment-summary` for the daily chart) — could be collapsed into one endpoint later if
  `revenue-summary` grows a `daily_totals` field.

## Key files
**Backend (sam-backend)**
- `backend/app/routers/appointments.py` — `GET /appointments`, `compute_invoice_status` call sites
- `backend/app/routers/reports.py`, `backend/app/schemas/reports.py` — `GET /reports/revenue-summary`
- `backend/app/routers/dashboard.py` — `GET /dashboard/activity-feed`, `GET /dashboard/setup-checklist`
- `backend/app/services/booking_service.py` — `compute_invoice_status`
- `backend/app/schemas/appointments.py` — `AppointmentListItemResponse`
- `backend/app/main.py` — `dashboard_router` registration

**Frontend (ai-employees-app)**
- `src/pages/dashboard/Dashboard.tsx`
- `src/hooks/useAgentState.ts`, `useDashboardRoster.ts`, `useTodaysAppointments.ts`,
  `useRevenueSummary.ts`, `useActivityFeed.ts`, `useAttentionQueue.ts`, `usePlanUsage.ts`,
  `useSetupChecklist.ts`
- `src/components/dashboard/*`
- `src/lib/voiceAgentApi.ts` — new `// ── Dashboard (AIE-47) ──` section
- `src/pages/dashboard/customer-service/Scheduler.tsx`,
  `src/pages/dashboard/customer-service/AgentSettings.tsx` — refactored onto `useAgentState`
