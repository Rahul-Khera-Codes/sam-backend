# HR Employee: Resume scoring + pipeline archival (AIE-74 rework, 2026-09-15)

## What it does
Closes the two real gaps identified when Sam rejected the original AIE-74 scope on 9/14 and
spec'd the full pipeline (see the note at the top of `hr-interviews-scorecard.md`):

1. **Resume-vs-job-requirements AI scoring.** Every application is scored against its job
   posting's stated requirements/qualifications the moment it's submitted. The score/summary
   drive the redesigned "All Candidates" table and its eye-icon scorecard (see
   `hr-candidates-screening-view.md`).
2. **Archiving.** Candidates are automatically retired out of the active pipeline once a job
   closes or a candidate is marked hired — previously there was no `archived` concept anywhere,
   and no UI action even existed to close a job.

## Data model
- `hr_job_applications.stage` check constraint extended: `applied` / `interviewing` /
  `final_round` / **`archived`** (new).
  (`ai-employees-app/supabase/migrations/20260915130000_hr_resume_scoring_and_archive.sql`)
- New table `hr_application_resume_scores` (same migration), one row per application:
  `total_score` (0–100), `summary`, `strengths`/`concerns` (jsonb arrays), `criterion_scores`
  (jsonb array of `{requirement, met, evidence}` — a fit checklist against the job's stated
  requirements, not a 1–5 rubric like interview scoring, since job postings don't have a formal
  rubric the way interview banks do).

## Resume scoring
- `backend/app/services/hr_resume_scoring_service.py` —
  `generate_and_store_resume_score(business_id, application_id)`, modeled directly on
  `hr_interview_scoring_service.generate_and_store_interview_outcome` (same `AsyncOpenAI`
  pattern, `gpt-4o-mini`, temp 0.2, JSON-object response, upsert-by-application). Downloads the
  resume from the `hr-job-applications` storage bucket and reuses
  `hr_document_embedding_service.extract_pdf_text` (same helper `hr_careers.py::parse_resume`
  already uses for contact-info extraction) — no new PDF-parsing code.
- `score_application_resume_safe(...)` — the actual entrypoint, wraps the above and swallows all
  exceptions (missing/corrupt resume, LLM failure). It must never surface an error to the
  candidate applying.
- Triggered via `BackgroundTasks.add_task(...)` from `hr_careers.py::submit_application` right
  after the application row is inserted — fire-and-forget, doesn't block the apply response. This
  means a freshly submitted application briefly shows "Scoring…" on the Candidates table until the
  background task finishes (seconds, typically).
- `GET /hr/candidates` now left-joins `hr_application_resume_scores` by `application_id` and
  populates the new `resume_score`/`resume_summary`/`resume_strengths`/`resume_concerns`/
  `resume_criterion_scores` fields on `HrCandidateResponse`. Only that endpoint's default
  (non-interviewed) path does this — `_list_interviewed_candidates` and the single-candidate
  lookup/stage-update paths don't join resume scores, since those views are keyed off interview
  session data, not the applications table directly.
- `HrCandidateResponse` also gained `job_posting_id` (previously absent — needed by the frontend
  to call the existing `POST /hr/interviews/invite`, which requires it).

## Archival
- `PATCH /hr/candidates/{application_id}/status` (new) — sets `hr_job_applications.status`
  (`new`/`reviewed`/`rejected`/`hired`). No such endpoint existed before this; only `stage` had a
  PATCH route. Setting `status="hired"` also sets `stage="archived"` in the same update — a hired
  candidate's pipeline is done.
- `PUT /hr/jobs/{job_id}` (existing endpoint) — when `status` is set to `"closed"`, bulk-sets
  `stage="archived"` on every one of that job's applications not already archived. The backend
  already fully supported `status="closed"` (`HrJobPostingUpsertRequest` schema, DB check
  constraint) — the only actual gap was that no frontend action ever sent it. Added a "Close Job"
  button + confirmation dialog on `HrJobPostings.tsx` (visible on `Active` postings only) that
  loads the full job via `getHrJob` and re-saves it with `status: "closed"` through the existing
  `updateHrJobPosting`, same pattern `openNativeJobForEdit`/`saveJob` already use.
- List views default to hiding archived candidates: `GET /hr/candidates` excludes
  `stage='archived'` unless an explicit `?stage=` filter is passed, and
  `_list_interviewed_candidates`'s application join does the same. No dedicated "Archived" tab
  was added — out of scope for this pass, see below.

## Key files
**Backend (sam-backend)**
- `backend/app/schemas/hr.py` — `HrCandidateStage` gained `"archived"`; new `HrCandidateStatus`
  literal + `HrCandidateStatusUpdateRequest`; `HrCandidateResponse` gained `job_posting_id` and
  the five `resume_*` fields.
- `backend/app/routers/hr_careers.py` — `submit_application` takes `BackgroundTasks`, fires
  `score_application_resume_safe` after insert.
- `backend/app/routers/hr.py` — `_candidate_response`/`list_hr_candidates` join resume scores and
  default-exclude archived; new `update_hr_candidate_status`; `update_hr_job` archives on close.
- `backend/app/services/hr_resume_scoring_service.py` — new.

**Frontend (ai-employees-app)**
- `src/lib/voiceAgentApi.ts` — `HrCandidateStage` gained `"archived"`; new `HrCandidateStatus`
  type + `updateHrCandidateStatus`; `HrCandidateRecord` gained `job_posting_id` and the
  `resume_*` fields.
- `src/pages/dashboard/hr/HrCandidates.tsx` — "All Candidates" tab rewritten (see
  `hr-candidates-screening-view.md`); new `ResumeScorecardDialog`.
- `src/pages/dashboard/hr/HrFinalRound.tsx` — manual-handoff banner (see `hr-final-round.md`).
- `src/pages/dashboard/hr/HrJobPostings.tsx` — "Close Job" action + confirmation dialog.

## Decisions / tradeoffs
- **Resume `criterion_scores` is a met/unmet checklist, not a 1–5 rubric.** Interview scoring has
  a real per-job rubric (`hr_interview_rubric_criteria`) with anchors to calibrate a 1–5 scale
  against. Job postings have no equivalent structured rubric — just free-text
  `qualifications`/`requirements_skills` — so forcing a 1–5 scale here would be inventing
  precision the input doesn't support. A boolean fit-check per stated requirement is honest about
  what the model can actually judge from free text.
- **Score bands (Exceptional/Strong/Average/Low Match) are display-only**, computed client-side
  from `total_score` — not stored as a separate enum. Keeps the table consistent with how
  `hr_interview_outcomes.total_score` already works (numeric, banded only in presentation).
- **Scoring is fire-and-forget on submission, not on-demand/re-triggerable.** Matches Sam's "AI
  should read and check each resume" as an automatic step. No "rescore" action was added — out of
  scope, see below.
- **No dedicated "Archived" view.** Sam's spec says archived candidates should be retired, not
  necessarily that recruiters need a dedicated place to browse them. Excluding them from default
  list queries was the minimal change that satisfies "archived out of the active pipeline."

## Out of scope for this pass
- A "Rescore resume" manual action (e.g. after a job's requirements are edited post-application).
- A dedicated "Archived" tab/filter in the UI to browse retired candidates.
- Bulk-invite as a real backend batch endpoint — `POST /hr/interviews/invite` is still strictly
  one candidate per call; the frontend's bulk "Invite to Interview" button loops client-side.

## Update (2026-09-15, same day): job-scoped Candidates table to match Sam's reference screenshot
Sam's original 9/14 comment included a screenshot ("Candiview" template) of a single-job Candidates
table — badge for the job + applicant count, Export CSV / View Job Details, a circular AI-score
gauge, candidate avatar + current role + years experience, search + status filter, pagination. The
first pass above shipped the data plumbing but kept a flat "all jobs mixed together" table. This
pass matches the reference layout with real data, no fabricated fields:

- **Job scoping**: `GET /hr/candidates` gained an optional `job_posting_id` filter
  (`backend/app/routers/hr.py`). `HrCandidates.tsx`'s "All Candidates" tab now loads the job list
  (`getHrJobs`) and renders a job-picker styled as the mockup's blue badge, defaulting to the first
  Active job; applicant count comes from the job's existing real `applicants` field (`hr.py`'s
  native-jobs applicant counter — no new counting logic).
- **Candidate's own current title/company/years experience** (real gap from the first pass, which
  reused the *job posting's* title where the mockup actually wants the *candidate's* most recent
  title/employer): `hr_resume_scoring_service.py`'s prompt now also extracts
  `candidate_current_title`/`candidate_current_company`/`candidate_years_experience` straight from
  the resume's work history, stored in three new columns on `hr_application_resume_scores`
  (migration `20260915140000_hr_resume_score_candidate_profile.sql`) and surfaced as
  `resume_current_title`/`resume_current_company`/`resume_years_experience` on
  `HrCandidateResponse`. Empty/0 when the resume has no work history (e.g. new grad) — not guessed.
- **Circular AI-score gauge**: `ScoreGauge` in `HrCandidates.tsx`, plain inline SVG (stroke-dasharray
  ring), no chart library added.
- **Avatar**: no photo-upload field exists on applications, so candidates get an initials avatar
  (`CandidateAvatar`, deterministic color per name) rather than a fabricated photo.
- **"Shortlisted" status**: the mockup's status pill uses "Shortlisted", which isn't one of the
  real `status` enum values (`new`/`reviewed`/`rejected`/`hired`). Rather than adding a new enum
  value, `reviewed` is now displayed as "Shortlisted" (`statusDisplayLabel` map, display-only) and
  the frontend sets `status="reviewed"` right after a successful "Invite to Interview" — the
  existing `PATCH /hr/candidates/{id}/status` endpoint, no backend change. This matches Sam's
  original framing ("choose candidates he wants the AI to call for an interview" = shortlisting).
- **Search / status filter / pagination**: client-side in `AllCandidatesTable`, 10 rows/page —
  doesn't need a backend change since a job's applicant list is small enough to fetch in one call.
- **Export CSV**: client-side CSV built from the job-scoped candidate list (name/email/phone/
  score/status/applied date), downloaded via a Blob — no backend export endpoint added.
- **View Job Details**: opens the existing public `/careers/jobs/{id}` page in a new tab (same
  data the mockup's button implies — title/department/location/responsibilities/qualifications/
  pay) rather than building a new internal job-detail route that didn't exist before.

## Update (2026-09-17): client QA fixes (post 9/15 Ready-for-QA)
Three fixes from Sam's 9/15 evening QA comments on AIE-74:

- **Resume scores were uncalibrated ("everyone scores low even on a full match").** Root cause:
  the scoring prompt (`hr_resume_scoring_service.py`) told the model to produce `total_score` but
  never stated what numeric scale to use — the only signal was `"total_score": 0` in the example
  JSON shape. The backend clamps the result into `[0, 100]` afterward but never rescales, so a
  model returning e.g. `7` (as in "7/10") landed in the DB as `7`, not `70`. Fixed by adding an
  explicit instruction (both the system message and the `requirements` list) that `total_score` is
  a 0–100 integer, a full match should score 85+, and the model should use the whole range instead
  of compressing toward the low end. The response-schema example was also changed from `0` to `82`
  so the example itself doesn't anchor the model low.
  - **Backfill**: existing `hr_application_resume_scores` rows predated this fix and were still on
    the old uncalibrated scale. `scripts/rescore_hr_resume_applications.py` re-runs the (now-fixed)
    scoring prompt for every existing row and overwrites it in place — dry-run by default, requires
    `--apply` plus a typed confirmation to actually write. Run against the live DB on 2026-09-17
    (2 rows existed at the time): `8.0 -> 85.0` and `10.0 -> 95.0`, confirming the old scores were
    indeed on a compressed ~0-10 scale and the fix produces correctly-scaled results.
- **Duplicate "match" wording in the resume scorecard dialog.** `scoreBand()` in `HrCandidates.tsx`
  already returned `"Low Match"` as the low-score band label, and `ResumeScorecardDialog` appended
  its own `" match"` suffix to every band's label — so a low score rendered "Low Match match"
  while the other three bands rendered correctly ("Strong match", etc.). Fixed by renaming the
  low-score band label from `"Low Match"` to `"Low"`, matching the other three bands
  (`Exceptional`/`Strong`/`Average` — single words, no "Match"), so the dialog's `{band.label} match`
  now renders consistently ("Low match", "Average match", ...) and the table row's bare
  `{band.label}` also reads correctly on its own.
- **"Interviews" tab removed from the Candidates page.** The Candidates page had a tab toggle
  between "Interviewed" (see `hr-candidates-screening-view.md`) and "All Candidates". Sam asked to
  drop that toggle and only show All Candidates. `HrCandidates.tsx`: removed the `view` state /
  `Tabs` toggle and the `InterviewedCandidateCard` component entirely; the page now always renders
  the job-scoped `AllCandidatesTable`. **This did not touch the separate top-level "Interviews"
  sidebar page** (`/dashboard/hr/interviews`, `HrInterviews.tsx` — the Candidate Pipeline/report/
  scorecard page documented in `hr-interviews-pipeline-dashboard.md`); Sam's mockup/comment was
  about the in-page tab, not that sidebar item, which is unchanged and still reachable.
- **Candidate invite email said "screening".** `hr_interview_runtime_service.py::_send_interview_invite_email`
  — subject and both plain-text/HTML bodies said "AI screening interview"; changed to "AI interview"
  in all 4 occurrences, matching the frontend's existing candidate-facing label
  (`interviewKindLabel.ai_screen = "AI Interview"` in `HrCandidates.tsx`). Also caught and fixed the
  same wording on the candidate-facing interview join page (`HrInterviewJoin.tsx`'s "Meet Emily"
  greeting said "this structured screening interview" — now "this structured AI interview"), so the
  wording is consistent end-to-end from email through to the join page. Verified no other
  "screening" occurrences remain anywhere in either repo's candidate-facing code.
