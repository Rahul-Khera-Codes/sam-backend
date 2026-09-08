# HR Employee: Candidates screening view (AIE-73)

## What it does
Redesigns the "Candidates" tab to surface real interview data instead of a plain applicant
table only. The page now has two views:
- **Interviewed** (default) — a card per candidate whose interview has actually started or
  finished, showing AI score / recommendation, a per-criterion highlights grid, AI-identified
  strengths as tags, and resume/cover-letter links — modeled on the AIE-73 mockup but built
  entirely from real `hr_interview_sessions`/`hr_interview_outcomes` data, not placeholder
  content.
- **All Candidates** — the original plain table (name/job/email/phone/status/actions), unchanged,
  kept for triaging brand-new applicants who haven't been interviewed yet.

## Why not just match the mockup literally
The attached mockup (`Candidates Screen.html`) shows fields the app has no real data for:
`years experience`, `education`, a numeric `source` like "LinkedIn"/"Indeed" (Greenhouse/Indeed
integrations were removed — `hr_job_applications.source` is `'native'`-only), and fabricated
skill tags. Rather than inventing these, the real equivalents are used: interview kind (AI vs.
human) as the source-style badge, AI-outcome `strengths` as tags, and criterion scores from actual
interview scoring as the highlights grid.

## Data model
No new tables/columns. This joins three existing tables at request time (same "no aggregation
views, Python-side joins" style as `hr-recruitment-dashboard.md`):
- `hr_job_applications` — the candidate/application row.
- `hr_interview_sessions` — one row per AI screen or human interview.
- `hr_interview_outcomes` — AI scoring output (`total_score`, `recommendation`,
  `criterion_scores`, `strengths`), only present for completed AI screens.

**The Interviewed view is sourced FROM `hr_interview_sessions`, not `hr_job_applications`.**
In practice, most real interview sessions today were created via the ad hoc invite flow on the
Interviews page (freeform name/email, no application behind them) — verified against the live DB
while building this: 15 sessions existed across businesses, 5 completed/3 human, and precisely 0
of them had a matching `hr_job_applications` row. Sourcing this view from applications (as
originally planned) would have shown nothing for real interviewed candidates. So `_list_interviewed_candidates`
enumerates distinct interviewed candidates from sessions first, then best-effort-enriches each
with its application (by `application_id` or email) when one exists. When no application exists,
the response is still fully populated from the session/outcome data, with `prospect: true` and an
empty `application_id` signaling "no application on file" — the frontend disables the resume/cover-
letter actions for those rows (nothing to show), and repoints "Move to Final Round" at the new
promote-from-interview flow below instead of hiding it.

### Promoting a session-only candidate to Final Round
`POST /hr/candidates/promote-from-interview` (`business_id`, `session_id`) closes the gap for
`prospect` candidates: it looks up the interview session, re-checks (by application match or by
email) whether an application already exists, and if not — creates one from the session's real
`candidate_name`/`candidate_email`/`candidate_phone`/`job_posting_id` with `stage='final_round'`
set immediately, then links it back onto the session's `application_id` column so future lookups
resolve it directly. Rejects with 422 if the session isn't `completed`/`reviewed` yet. This is the
first real fix (not just a workaround) for the "ad hoc invites never carry an application_id" gap
described in `hr-final-round.md` — every session promoted this way gets a permanent application
record and will appear under "All Candidates" from then on.

### "Interview taken" definition
A candidate is considered interviewed if they have an `hr_interview_sessions` row with
`status IN ('in_progress', 'completed', 'reviewed')` — i.e. the interview has at least started.
`in_progress` rows have no `hr_interview_outcomes` row yet (scoring only runs on completion), so
their card shows "Interview in progress" instead of a fabricated score.

### Session ↔ application linkage
Same pre-existing gap as Final Round (see `hr-final-round.md`): interview sessions aren't
reliably linked to an application by id, so matching is done by `application_id` OR lowercased
`candidate_email`, whichever is present.

### Picking "the" session for a candidate
A candidate can have multiple sessions (e.g. an AI screen and a human interview). The one shown
is picked by status rank (`reviewed` > `completed` > `in_progress`), tie-broken by the most recent
`completed_at`/`started_at`.

## Key files
**Backend (sam-backend)**
- `backend/app/schemas/hr.py` — `HrCandidateResponse` gained `interview_kind`, `interview_status`,
  `interview_started_at`, `interview_completed_at`, `human_interview_provider`, `ai_score`,
  `recommendation`, `recruiter_score`, `criterion_scores`, `strengths`, `has_resume`,
  `has_cover_letter`. New `HrCandidateFileUrlResponse`.
- `backend/app/routers/hr.py`:
  - `_fetch_interview_activity(business_id)` — all in-progress/completed/reviewed sessions merged
    with their outcome. `_group_interview_activity_by_key` reduces that to one best session per
    application_id/email (used to enrich the "All Candidates" table and lookup/stage-update
    responses). `_distinct_interviewed_candidates` instead reduces it to one row per unique
    candidate identity (application_id, else session `candidate_id`, else email) — used by the
    Interviewed view so session-only candidates (no application) aren't lost or double-counted.
  - `_interviewed_candidate_response` — builds an `HrCandidateResponse` per interviewed candidate,
    preferring application fields when a match exists, falling back to the session's own
    `candidate_name`/`candidate_email`/`candidate_phone` otherwise.
  - `_list_interviewed_candidates(business_id)` — the full Interviewed-view query, called directly
    by `GET /hr/candidates?interviewed=true` (bypasses the applications-table query entirely).
  - `GET /hr/candidates` — new `interviewed: bool` query param routes to
    `_list_interviewed_candidates`; the plain (no-param) path is otherwise unchanged.
    `GET /hr/candidates/lookup` and `PATCH /hr/candidates/{id}/stage` also populate the new
    interview fields via `_interview_activity_by_key` (unchanged behavior otherwise).
  - `GET /hr/candidates/{application_id}/resume` and `.../cover-letter` — new endpoints returning
    a 1-hour signed URL for the file in the private `hr-job-applications` bucket, reusing the same
    `create_signed_url` pattern as `hr_interview_runtime_service._signed_recording_url`.
  - `POST /hr/candidates/promote-from-interview` — new endpoint (see above) that creates the
    missing application for a session-only candidate and sets it straight to `final_round`, or
    promotes an existing matched application if one is found after all.
  - `HrCandidateResponse` also gained `interview_session_id`, populated on every response path, so
    the frontend always has a session id to promote from when there's no `application_id` yet.

**Frontend (ai-employees-app)**
- `src/lib/hrInterviewPresentation.ts` — new shared module: `RECOMMENDATION_META`,
  `recommendationLabel`, `criteriaFor` (parses `criterion_scores` into `{name, score}` clamped
  0–5), extracted out of `HrInterviews.tsx` so both pages use identical logic.
- `src/pages/dashboard/hr/HrInterviews.tsx` — now imports those helpers instead of defining them
  locally; no behavior change.
- `src/lib/voiceAgentApi.ts` — `HrCandidateRecord` gained the same new fields plus
  `interview_session_id`; `getHrCandidates` gained an `interviewed?: boolean` param; new
  `getHrCandidateResumeUrl`/`getHrCandidateCoverLetterUrl`/`promoteHrCandidateFromInterview`
  functions.
- `src/pages/dashboard/hr/HrCandidates.tsx` — rewritten with an "Interviewed" / "All Candidates"
  tab toggle (default: Interviewed). The All Candidates tab is the original table, untouched. The
  Interviewed tab renders `InterviewedCandidateCard` per candidate (score box, highlights grid,
  strength tags, resume/cover-letter buttons gated on `has_resume`/`has_cover_letter`).
  "Move to Final Round" now branches: candidates with a real `application_id` use the existing
  `updateHrCandidateStage` path unchanged; `prospect` candidates (completed/reviewed interview,
  no application) use `promoteHrCandidateFromInterview` keyed by `interview_session_id` instead.

## Decisions / tradeoffs
- **In-progress interviews count as "taken".** Chosen so a recruiter watching a live AI screen
  sees the candidate show up immediately, not just after scoring finishes — those cards simply
  show "Interview in progress" instead of a score.
- **No new columns/migration.** Everything is computed live from existing tables, consistent with
  how `eligible_for_final_round` and the dashboard stats already work.
- **Kept the old table as a second tab instead of replacing it.** The Candidates page was also the
  only place recruiters could see brand-new, not-yet-interviewed applicants; removing that
  entirely would have been a workflow regression beyond what was asked.

## Error handling: no more raw "Failed to fetch"
Every fetch/API call in this flow (Candidates page, Interviews page, and the public candidate-
facing careers-apply + interview-join pages) ultimately funnels through either `fetchWithAuth` or
one of five raw `fetch()` calls in `voiceAgentApi.ts` for the unauthenticated public endpoints.
None of them caught a network-level failure — if `fetch()` itself rejects (offline, DNS failure,
CORS block, backend down), the browser's bare `TypeError` ("Failed to fetch" in Chrome,
"NetworkError..." in Firefox, "Load failed" in Safari) propagated untouched into every
`catch (error) { toast.error(error instanceof Error ? error.message : ...) }` block across both
files — and since a `TypeError` always satisfies `instanceof Error`, the fallback string was never
actually reachable in this exact failure mode.

Fixed at the source in `ai-employees-app/src/lib/voiceAgentApi.ts`:
- New `safeFetch(url, options)` wraps every raw `fetch()` call (inside `fetchWithAuth`, plus the
  five public careers/interview-join functions) in a try/catch that turns a network-level failure
  into a clear `Error("Could not reach the server..." / "You appear to be offline...")` instead of
  the native browser string. No call site needed to change — they all already read `error.message`.
- `parseErrorResponse` now also handles FastAPI 422 validation errors (`detail` as an array of
  `{msg, loc}` objects, not a string — previously would've stringified to `[object Object]`), and
  caps a raw non-JSON text fallback at 300 chars so a proxy's HTML error page can't get dumped into
  a toast.
- `CareersApplyPage.tsx` previously conflated "job successfully loaded but not accepting
  applications" with "failed to load the job at all" — both landed on the same "Not accepting
  applications yet" card, silently telling a candidate a job was closed when the real cause was a
  network/server error. Split into a distinct `"unavailable"` state with its own honest message and
  a Try Again button.

## Out of scope for this pass
- Backfilling `years_experience`/`education`/structured skills onto applications — no such data
  exists; the UI intentionally shows only real fields.
- Fixing the underlying interview-invite flow to always carry a real `application_id` (see
  `hr-final-round.md` — pre-existing gap, unchanged by this work).
