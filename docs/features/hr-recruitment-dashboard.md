# HR Recruitment Dashboard — real numbers (AIE-70)

## What it does
The HR dashboard's top stat cards (Total Applicants / Pending Review / Active Interviews),
the Recruitment Funnel (Applicants → AI Screened → Interviewed → Hired), and each posting's
`applicants` count are now computed from real data instead of hardcoded mock values.

## The bug
Three separate fakes, found by tracing `HrDashboard.tsx` end-to-end into `sam-backend`:
1. `HrDashboard.tsx` fetched real data via `getHrJobsWorkspace`, but its `.then` callback
   immediately did `setStats(recruitmentStats); setStages(funnelStages)` — re-applying module-level
   mock constants on top of the response every time. Only the postings table used real data.
2. `_native_job_to_response()` (`backend/app/routers/hr.py`) hardcoded `"applicants": 0` for every
   job posting — the sole source feeding every `applicants` field in the app (dashboard table and
   the Job Postings workspace payload, the latter unused in the UI today).
3. `/hr/jobs/workspace` never returned dashboard-level stats or funnel data at all — nothing for
   the frontend to consume even if it had wired the response through correctly.

## Data sources / definitions
- **Total Applicants** = count of all `hr_job_applications` rows for the business.
- **Pending Review** = count where `status = 'new'`.
- **Active Interviews** = count of `hr_interview_sessions` where
  `status in ('invited', 'opened', 'in_progress')`.
- **Per-job Applicants** (dashboard table + Job Postings workspace payload) = count of
  `hr_job_applications` grouped by `job_posting_id`.
- **Funnel:** Applicants = total applications; AI Screened = count of `hr_interview_sessions`
  where `interview_kind = 'ai_screen'` and `status != 'draft'` (invite actually sent); Interviewed =
  count of `hr_interview_sessions` where `status in ('completed', 'reviewed')` (either kind);
  Hired = count of applications where `status = 'hired'`.
- **Trend ("+X%")** = current 7-day window vs. prior 7-day window, same `pct_change` math as
  `analytics.py`'s `get_period_dates`/`pct_change` (no shared util exists between routers — this is
  a third, localized copy, matching the existing convention of `analytics.py`/`reports.py` each
  having their own). Total Applicants and Pending Review key off `submitted_at`; Active Interviews
  keys off `invited_at`.

## Key files
**Backend (sam-backend)**
- `backend/app/schemas/hr.py` — added `HrDashboardStatCard` (`title`, `value`, `change`, `icon`)
  and `HrFunnelStage` (`label`, `value`). Deliberately no `width`/`tone` fields — those are display
  concerns computed on the frontend from `value`, not static strings that can drift from the
  number next to them (which was effectively the bug for the funnel bars before this fix).
- `backend/app/routers/hr.py`:
  - `_fetch_hr_applications` / `_fetch_hr_interview_sessions` — single `select` per table per
    request, business-scoped, no date filter (matches `list_hr_candidates`'s existing fetch-all-
    then-process-in-Python style — no SQL aggregate/view exists for either table).
  - `_native_job_to_response` now takes an `applicants: int` param instead of hardcoding `0`;
    `_load_native_jobs` and `_get_hr_jobs_payload` thread a `Counter(job_posting_id)` built from
    the applications fetch through to it.
  - `_build_dashboard_stats(applications, interview_sessions)` computes the three stat cards and
    four funnel stages described above.
  - `get_hr_jobs_workspace` now fetches applications + interview sessions once per request and
    merges `stats`/`funnel_stages` into the existing `dashboard` payload.

**Frontend (ai-employees-app)**
- `src/lib/voiceAgentApi.ts` — `HrJobsWorkspaceResponse.dashboard` extended with `stats` and
  `funnel_stages` matching the new backend shape.
- `src/pages/dashboard/hr/HrDashboard.tsx` — removed the `recruitmentStats`/`funnelStages`/
  `activeJobPostings` mock constants and the overwrite in the `useEffect`; state now starts empty
  and is set entirely from the API response. Icon/tint lookup and funnel bar width/tone are now
  computed on the frontend from the `icon` key and `value` respectively (see "no width/tone
  fields" above). Also fixed a latent bug where the funnel's connector-line condition compared
  against the module-level mock array's length (`funnelStages.length`) instead of the live `stages`
  state — harmless while they were the same array, would have broken once `stages` became
  dynamically sized.

## Decisions / tradeoffs
- **No new DB aggregation (view/RPC).** Every other HR endpoint in this router fetches full rows
  and processes them in Python; adding a SQL-level `GROUP BY` here would be inconsistent with that
  and isn't needed at current data volumes. Revisit if a business's application/interview volume
  grows large enough that fetching all rows per dashboard load becomes a real cost.
- **Funnel stages aren't strictly monotonic by construction.** "Interviewed" counts any completed/
  reviewed interview session regardless of `interview_kind`, so a `human_external` interview that
  bypassed AI screening could make "Interviewed" include candidates never counted in "AI Screened".
  Accepted as a reasonable real-world approximation rather than adding kind-crossing logic to force
  strict funnel monotonicity.
- **Trend badges are a real but coarse proxy.** "Pending Review" change is `submitted_at`-in-window
  filtered by *current* `status = 'new'`, not a true historical snapshot of backlog size at each
  point in time (the table doesn't record status-transition history) — it answers "how many of
  this week's new applications are still pending" vs. last week's, which is close to but not
  exactly "change in Pending Review backlog."
- **Out of scope for this pass:** deleting `/hr/mock-workspace` and `getHrMockWorkspace()` — both
  confirmed dead code (unused by any live page) during investigation, left alone as unrelated
  cleanup rather than bundled into this bug fix.

## Gotchas / follow-ups
- A business with zero applications/interviews returns all-zero stats and an all-zero funnel
  (no divide-by-zero — `_pct_change_label` and the frontend's funnel-width calc both guard the
  zero case) — this is the correct "real" empty state, not a bug.

## UI redesign (same day, presentation-only)
Once the real data was wired up, the dashboard's visual design was upgraded — purely a frontend
presentation change in `HrDashboard.tsx`, no backend/API/schema changes:
- Stat cards now use the shared `StatCard` component (`src/components/ui/stat-card.tsx`), already
  used by `AgentPerformance.tsx`/`PaymentSummaryReport.tsx`, instead of bespoke markup. This picks
  up correct positive/negative coloring for the `change` badge (previously always rendered green
  regardless of sign) via a `statChangeType()` helper that reads the backend's `+`/`-` prefix.
- The funnel is now a real `recharts` `FunnelChart` (recharts was already a dependency, no new
  package) plus a stage-breakdown grid below it showing each stage's count and % of total
  applicants, following the same chart-card + legend-row pattern already established in
  `AgentPerformance.tsx`'s "Call Distribution" panel.
- Added explicit loading (skeleton placeholders matching final layout, same convention as
  `AgentPerformance.tsx`) and empty states (`No applicants yet...`, `No active postings yet.`)
  for the stat cards, funnel, and postings table — previously there was no loading state at all,
  so the page would flash empty before data arrived.
- Used the existing `animate-fade-in` Tailwind utility (already defined in `tailwind.config.ts`,
  used elsewhere in the app) for the loading-to-loaded transition rather than adding a new
  animation library.
- Deliberately did not change: color tokens/palette (still the existing CSS-variable theme), icon
  library (still `lucide-react`, matching the rest of the app), font, or any interactive
  behavior/routing (the header's search box and "New Posting" button remain the same
  non-functional placeholders they were before this pass).

## Draft postings were invisible on the dashboard (same day, follow-up fix)
Root cause: `_workspace_view_from_jobs()` (`hr.py`) filtered the dashboard's postings list to
`job["status"] == "Active"` only. A business whose native postings are all still `Draft` (not yet
published) saw an empty "Active Job Postings" table with no explanation, even though the postings
existed and were real. Verified against business `f46ce260-45da-4db8-9bc1-b0af01ec3acc`, whose 3
postings are all `status: "draft"` — none appeared before this fix.

Also investigated as part of this: whether "external" (non-native) job postings exist anywhere in
the system. They don't. A Greenhouse ATS connector was built (source `'native' | 'greenhouse'`,
per `20260721123000_greenhouse_hr_section1.sql`) but fully removed before any real data used it
(`20260825120000_remove_greenhouse_integration.sql`; `docs/hr-employee.md` confirms zero production
rows ever had `source = 'greenhouse'`). The `hr_job_postings.source` column is now DB-constrained
to `'native'` only (`hr_job_postings_source_check`). So today every posting is native by
definition — there is no dormant external-source data being hidden.

**Fix:**
- `HrDashboardPostingResponse` (`schemas/hr.py`) gained `status: Literal["Draft","Active","Closed"]`
  and `source: Literal["native"]`.
- `_workspace_view_from_jobs()` no longer filters by status — it returns the 5 most-recently-updated
  native postings regardless of status, each carrying its real `status`/`source`.
- `HrDashboard.tsx`: card renamed "Active Job Postings" → "Job Postings" (it's no longer
  active-only); added a "Status" column (Active/Draft/Closed badge) and a "Source" column (badge,
  currently always "Native" — the `sourceLabel` lookup is written to extend cleanly if a non-native
  source is ever reintroduced); Draft rows get an inline "Draft, needs to be completed" caption
  under the title so it's clear why they're not live.
- Left the `[:5]` cap on the dashboard's postings list as-is (matches the existing pre-fix
  behavior) — the full, uncapped list of every native posting regardless of status was already
  available on the "Job Postings" tab (`job_postings.postings` in the same endpoint response,
  rendered by `HrJobPostings.tsx`).
- **Known adjacent bug, not fixed here (out of scope for this pass):** `HrJobPostings.tsx`'s own
  "Source" column (line ~496) is hardcoded static markup (`&lt;Badge&gt;Native&lt;/Badge&gt;`) that
  ignores the real `posting.source` field the backend already sends — unlike the dashboard's new
  Source badge, it isn't actually data-driven. Flagging for a future pass.

## Indeed sync removed (2026-09-07)
Indeed will not be integrated, so `publish_in_indeed`/`indeed_status` were removed end-to-end —
LinkedIn is unaffected and stays exactly as-is.
- **Database:** dropped `hr_job_postings.publish_in_indeed`
  (`supabase/migrations/20260907130000_remove_indeed_sync_column.sql`), same pattern as the earlier
  Greenhouse-removal migration. It had zero real data (every row was `false`) and was never wired
  to a live Indeed integration — `docs/features/hr-job-postings-and-candidates.md` already
  documented the LinkedIn/Indeed toggles as "already labeled not-live."
- **Backend:** removed `publish_in_indeed`/`indeed_status` from `HrJobPostingUpsertRequest`,
  `HrJobPostingResponse`, and `indeed` from `HrDashboardPostingResponse` (`schemas/hr.py`); removed
  all corresponding read/write sites in `hr.py` (`_native_job_to_response`,
  `_workspace_view_from_jobs`, the job create/update handlers, and the dead `/hr/mock-workspace`
  sample data).
- **Frontend:** removed the matching fields from `voiceAgentApi.ts`'s `HrJobPostingRecord`,
  `UpsertHrJobPostingRequest`, and `HrJobsWorkspaceResponse`; removed `publish_in_indeed` from
  `HrJobPostings.tsx`'s form state; removed the dashboard's "Indeed Sync" column entirely
  (`HrDashboard.tsx` — table is back to 6 columns, LinkedIn Sync stays). Also hand-edited
  `src/integrations/supabase/types.ts` to drop the column from the generated `hr_job_postings`
  Row/Insert/Update types (no linked Supabase CLI codegen available in this environment).
- No builder UI toggle existed for this field before removal (it was plumbed through form
  state/save payload only, never rendered as a checkbox), so there was no interactive control to
  remove — just the data plumbing and the dashboard's status column.
