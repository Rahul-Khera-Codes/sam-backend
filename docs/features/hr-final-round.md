# HR Employee: Final Round (AIE-75)

## What it does
Adds a "Final Round" section to the HR Employee nav, sitting between Interviews and Onboarding.
It lists candidates a recruiter has manually shortlisted after they've completed at least one
interview. This also replaces the previously hardcoded `stage="Applied"` on every candidate with
a real, persisted pipeline stage.

## Data model
- `hr_job_applications` (`ai-employees-app/supabase/migrations/20260908000000_hr_candidate_stage.sql`)
  gained two columns:
  - `stage` — `applied` (default) / `interviewing` / `final_round`. Independent of the existing
    `status` column (`new`/`reviewed`/`rejected`/`hired`), which tracks disposition, not pipeline
    position.
  - `final_round_at` — timestamp set when a candidate enters Final Round, cleared if moved back.
- No new column tracks "Onboarding" — that page remains independent of `stage` (document
  library + chat, unrelated to this pipeline), unchanged by this work.

## Key files
**Backend (sam-backend)**
- `backend/app/schemas/hr.py` — `HrCandidateStage` literal, `stage`/`eligible_for_final_round`/
  `final_round_at` added to `HrCandidateResponse`, new `HrCandidateStageUpdateRequest`,
  `HrCandidateLookupResponse`.
- `backend/app/routers/hr.py`:
  - `GET /hr/candidates` — now returns the real `stage` value (was hardcoded), accepts an
    optional `?stage=` filter (used by the Final Round page), and computes
    `eligible_for_final_round` per candidate via `_completed_interview_keys`.
  - `GET /hr/candidates/lookup?business_id=&email=` — resolves a candidate application by email
    (see "Interview → application linkage" below).
  - `PATCH /hr/candidates/{application_id}/stage` — the manual move. Rejects (`422`) a move to
    `final_round` unless the candidate has at least one `completed`/`reviewed` interview session.
- `backend/app/services/hr_interview_runtime_service.py` — `_mark_application_interviewing`
  best-effort-advances an application from `applied` → `interviewing` whenever an AI screen invite
  or human interview is created for that candidate's email.

**Frontend (ai-employees-app)**
- `src/components/layout/HrEmployeeLayout.tsx` / `src/App.tsx` — new "Final Round" nav item + route
  (`/dashboard/hr/final-round`), positioned between Interviews and Onboarding.
- `src/pages/dashboard/hr/HrFinalRound.tsx` — new page, table styled like `HrCandidates.tsx`,
  listing `stage=final_round` candidates with a "Move back to Interviewing" action.
- `src/pages/dashboard/hr/HrCandidates.tsx` — added a "Move to Final Round" button per row,
  enabled only when `eligible_for_final_round` is true.
- `src/pages/dashboard/hr/HrInterviews.tsx` — added the same action on `completed`/`reviewed`
  interview rows; resolves the candidate application by email via the new lookup endpoint first
  (see below), since interview session rows aren't reliably linked to an application.
- `src/lib/voiceAgentApi.ts` — `HrCandidateStage` type, `eligible_for_final_round`/
  `final_round_at` on `HrCandidateRecord`, `lookupHrCandidateByEmail`, `updateHrCandidateStage`,
  optional `stage` param on `getHrCandidates`.

## Decisions / tradeoffs
- **Interview → application linkage is by email, not `application_id`.** `hr_interview_sessions`
  has an `application_id` column and the AI-invite request schema even accepts one, but
  `HrInterviews.tsx`'s invite forms are freeform (recruiter types a name/email directly) and never
  actually pass it — so in practice no interview session is linked to an application by id today.
  Both the eligibility check and the Interviews-page "Move to Final Round" button match on
  `business_id + candidate_email` instead. This is a pre-existing gap, not introduced by this
  ticket — fixing the invite flow to always carry `application_id` is future work if the email
  match proves too loose (e.g. two applications sharing an email across different job postings).
- **`stage` is separate from `status`.** `status` already meant application disposition
  (new/reviewed/rejected/hired); overloading it with pipeline position would have required
  redefining what every existing status value means. A new column avoids that.
- **No backfill migration.** Existing applications default to `stage='applied'` rather than being
  retroactively classified as `interviewing`. `eligible_for_final_round` is computed live from
  `hr_interview_sessions`, so an already-interviewed candidate is still correctly eligible even
  though their `stage` display value hasn't caught up — this is cosmetic staleness only.

## Out of scope for this pass
- Adding a "Final Round" bucket to the recruitment funnel chart on `HrDashboard.tsx`.
- Any transition into the `onboarding` stage — the Onboarding page stays independent.
- Fixing the interview-invite flow to carry a real `application_id` end-to-end (see linkage
  decision above).
