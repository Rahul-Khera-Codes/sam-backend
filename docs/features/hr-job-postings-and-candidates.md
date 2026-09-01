# HR Job Post Public Webpage + Candidates (AIE-31)

## What it does
The client asked for three linked pieces on top of the existing native HR "Job Postings" feature:
1. A public, no-login webpage for **every** job posting (LinkedIn-style: title, company,
   location/employment tags, description sections, Apply button) — reachable regardless of
   status so a recruiter can preview/test it before publishing, per an AIE-31 follow-up
   (2026-09-01) asking for the public-page link to work for any created job, not just Active ones.
2. An apply flow: candidate uploads a resume (+ optional cover letter), contact info
   (name/email/phone/location) is **auto-filled from the resume** via an LLM extraction step, the
   candidate reviews/edits it (Indeed-style "Review your application"), then submits — but only
   for postings that are actually `status = 'active'` (see "Preview vs. accepting applications"
   below, another same-day follow-up).
3. Submitted applicants show up in the existing dashboard **Candidates** tab, which previously was
   a permanently hardcoded "unavailable" stub.

## Data model
- `hr_job_applications` (new table, `ai-employees-app/supabase/migrations/20260901120000_hr_job_applications.sql`):
  `business_id`, `job_posting_id` (FK → `hr_job_postings`), `candidate_name/email/phone/location`,
  `resume_storage_path/file_name`, `cover_letter_storage_path/file_name` (nullable),
  `status` (`new`/`reviewed`/`rejected`/`hired`, default `new`), `source` (`native` only for now),
  `submitted_at`. Service-role-only RLS, same pattern as every other `hr_*` table — the frontend
  never queries this directly, only through sam-backend.
- Storage bucket `hr-job-applications` (private) holds the uploaded PDFs, keyed
  `{business_id}/{application_id}_resume_{filename}` / `..._cover_letter_{filename}`.
- No new table for the public job page itself — it reads straight from the existing
  `hr_job_postings` row (filtered to `status = 'active'`), returning only a public-safe subset.

## Key files
**Backend (sam-backend)**
- `backend/app/routers/hr_careers.py` — new **unauthenticated** router (`/careers/...`), mirroring
  the existing public HR-interview-join pattern (`hr_interviews.py`'s `/hr/interviews/join/{token}`):
  - `GET /careers/jobs/{job_id}` — public job details for **any** status (404 only if the job
    doesn't exist), so the page also works as a recruiter preview link for Draft/Closed postings.
    Response includes `is_accepting_applications` (`true` only when `status == "active"`) so the
    frontend knows whether to render Apply.
  - `POST /careers/jobs/{job_id}/parse-resume` and `POST /careers/jobs/{job_id}/apply` both call
    `_fetch_job_accepting_applications()`, which 409s with "This job isn't accepting applications
    yet." unless `status == "active"` — Draft/Closed jobs are viewable but not applicable-to.
    `parse-resume` extracts resume PDF text (`hr_document_embedding_service.extract_pdf_text`,
    reused as-is) and makes one `gpt-4o-mini` call (`response_format={"type": "json_object"}`,
    same structured-JSON pattern as `hr_interview_scoring_service.py`) to pull
    `{name, email, phone, location}`. No DB write — purely powers the auto-fill step before the
    candidate reviews and submits. `apply` uploads resume (required) + cover letter (optional) to
    `hr-job-applications` and inserts the application row.
- `backend/app/routers/hr.py` `list_hr_candidates` — previously always returned
  `available=False`. Now queries `hr_job_applications` for the business (joined in Python to
  `hr_job_postings` for the title, not a DB-level join), maps rows into the existing
  `HrCandidateResponse` shape (`source="native"`, `stage="Applied"`), and returns
  `available=True` once there's at least one applicant.
- `backend/app/schemas/hr.py` — added `HrJobPublicResponse`, `HrParsedResumeResponse`,
  `HrJobApplicationSubmitResponse`. `HrCandidateResponse`/`HrCandidatesResponse` already existed
  and needed no changes — their shape already matched an inbound-applicant list.
- `backend/app/main.py` — registered `hr_careers.router` alongside `hr_interviews.router`
  (deliberately **not** behind `require_business_access`/`get_user_id` — candidates are not app
  users).

**Frontend (ai-employees-app)**
- `src/pages/CareersJobPage.tsx` — public job page (`/careers/jobs/:jobId`), outside
  `ProtectedRoute` in `App.tsx`, same as `/hr/interview/join/:token`.
- `src/pages/CareersApplyPage.tsx` — public apply flow (`/careers/jobs/:jobId/apply`):
  upload step → parse-resume call → review step (auto-filled, editable fields) → submit →
  confirmation screen.
- `src/lib/voiceAgentApi.ts` — `getPublicCareersJob`, `parseCareersResume`,
  `submitCareersApplication`: plain unauthenticated `fetch` calls (no `fetchWithAuth`/bearer
  token), matching `getPublicHrInterviewJoinInfo`'s pattern exactly.
- `src/pages/dashboard/hr/HrJobPostings.tsx` — added an `ExternalLink` icon button in the
  actions column, shown for every posting regardless of status, opening the public job page in
  a new tab (a recruiter preview link, not gated to Active).
- `src/pages/dashboard/hr/HrCandidates.tsx` — renders a real applicant table when
  `getHrCandidates` returns `available: true`; keeps the original dashed empty-state card for the
  genuine zero-applicants case (copy changed from "Candidate sourcing is unavailable" to
  "No candidates yet" since sourcing/search was never actually built — see Decisions below).

## Decisions / tradeoffs
- **LLM-based resume parsing, not regex.** Chosen over a free regex-only extraction because
  resumes vary too much in layout for reliable name/location extraction with pattern matching;
  the client's ask ("portal will auto pull his contact information") implies more than
  email/phone. Cost is one small `gpt-4o-mini` call per application attempt (not per successful
  submission — a candidate can retry).
- **The "Candidates" tab was repurposed, not replaced.** Its stub (`available: False`,
  "Candidate sourcing isn't available right now") was originally built for a different, unbuilt
  feature — outbound candidate *sourcing/search* (the "Talent Finder" panel on the job builder
  page, which still says sourcing is unavailable — untouched by this work). Its response schema
  already fit an inbound-applicant list almost exactly, and the client's mockup shows applicants
  landing in this same section, so we wired real data into it rather than building a parallel
  page.
- **Out of scope for this pass:** real candidate sourcing/search; actual LinkedIn/Indeed
  publishing (those toggles already exist, already labeled not-live); recruiter-side stage
  management beyond listing (moving an applicant through interview stages); rate limiting /
  abuse hardening on the public apply endpoint beyond PDF-type validation.
- **Preview vs. accepting applications (2026-09-01 follow-up).** Initially the public page and
  apply flow were gated to `status == "active"` end-to-end (icon hidden, 404 on view). The client
  clarified they want to preview/test the full page for any job they've created before publishing
  it, so viewing was opened up to all statuses — but they explicitly do **not** want candidates to
  actually submit an application to a Draft/Closed posting. So the gate moved: `GET
  /careers/jobs/{id}` never 404s on status, but exposes `is_accepting_applications` so the
  frontend hides the Apply button and shows "This job isn't accepting applications yet." instead;
  `parse-resume`/`apply` still hard-enforce `status == "active"` server-side (409) as the real
  gate, since the frontend check alone wouldn't stop a direct API call to `/apply`.

## Gotchas / follow-ups
- The public apply endpoints have no rate limiting or CAPTCHA — acceptable for initial rollout
  but worth adding if abuse shows up, since `/careers/jobs/{id}/apply` is fully unauthenticated
  by design.
- `parse-resume` failures (unreadable PDF, LLM error) don't block the flow — the frontend falls
  back to blank/editable fields rather than hard-failing, since the whole point of auto-fill is
  convenience, not a gate.
