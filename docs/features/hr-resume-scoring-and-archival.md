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
