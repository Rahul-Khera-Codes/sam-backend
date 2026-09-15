# HR Employee: Interviews pipeline dashboard + candidate scorecard page (AIE-74, 2026-09-15)

## What it does
Sam's 9/14 spec (see the note at the top of `hr-interviews-scorecard.md`) included a screenshot of
the Interviews page as a unified "Candidate Pipeline" table (not the AI/Human tabs + card list that
shipped on 9/8), with "View" opening a dedicated full-page scorecard (2nd screenshot: resume panel
+ tabbed scorecard). This pass rebuilds those two screens; the existing "Invite to AI Screen" /
"Track Human Interview" setup cards on `HrInterviews.tsx` are untouched, per Sam's own framing
("rest of the section stays the same which is setting up the interview and sending invite for it").

Four scope decisions were confirmed with the user before building (not guessed):
1. The mockup's "Interview Analysis & Feedback" report header is **real functionality** — a
   working date-range filter and a "Generate Full Report" action that calls an LLM, grounded in
   real computed stats (not invented numbers).
2. "View" opens a **dedicated full-page route**, not an inline panel.
3. The STATUS column reflects **interview progress only** (Pending / Interview Done) — shortlisting
   is a separate concept, already covered by the Candidates page's `status=reviewed`.
4. Of the detail screen's new-looking actions (Send Invite / Share / Shortlist / Reject / Prev-Next),
   **Send Invite and Share** were asked for; **Prev/Next paging** was explicitly declined — the
   detail page has a Back breadcrumb only.

## New backend surface
- **Report**: `GET /hr/interviews/report?business_id=&days=` → `app/services/hr_interview_report_service.py`.
  Computes real aggregates (total/completed/pending interviews, average score, recommendation
  counts, top 5 candidates by score) from `hr_interview_sessions`/`hr_interview_outcomes` in the
  window, then asks an LLM (`gpt-4o-mini`, temp 0.2) to write a 3-5 sentence narrative **grounded
  strictly in those numbers** (explicit "use only the provided numbers, never invent" instruction —
  same guardrail pattern as `hr_interview_scoring_service`/`hr_resume_scoring_service`). Route is
  registered before `GET /interviews/{session_id}` in `hr_interviews.py` — required, since FastAPI/
  Starlette matches same-arity routes in registration order and a literal path (`/report`) placed
  after a variable one (`/{session_id}`) would get silently swallowed by it. Same reasoning already
  applied to the pre-existing `/interviews/pipeline` route.
- **Scorecard**: `GET /hr/interviews/{session_id}/scorecard` → `get_candidate_scorecard()` in
  `hr_interview_runtime_service.py`. One call replaces what would otherwise be 2-3 round trips: it
  wraps the existing `get_detail()` (session/transcript/recordings) and adds candidate-application
  enrichment (resolved via the same application_id-then-email dual-key pattern used everywhere else
  in this file), resume/cover-letter availability, the candidate's real years-of-experience (from
  `hr_application_resume_scores`, the AIE-74-follow-up table), and a **real percentile** — computed
  by ranking this outcome's `total_score` against every other `hr_interview_outcomes.total_score`
  for the business, not a fabricated "Top X%".
  - `eligible_for_final_round` here is intentionally simpler than the Candidates-page version
    (`_is_eligible_for_final_round` in `hr.py`, which scans every session for the candidate): it
    just checks whether *this* session (the one being viewed) is `completed`/`reviewed`. Correct
    for the overwhelming common case — a recruiter looking at a finished scorecard to decide on
    shortlisting — without an extra cross-session query.
- **Share**: new table `hr_interview_share_links` (migration `20260915150000`), deliberately
  separate from `hr_interview_sessions.invite_token_hash` — that column is the *candidate's own*
  join link and gets invalidated the moment the interview completes (`_session_for_token` rejects
  `completed`/`reviewed`/etc.), which is the opposite of what a recruiter-facing share link needs
  (it should start working only once the interview is done). `POST /hr/interviews/{id}/share`
  upserts a fresh token per session (old link silently stops working — only the hash is stored, so
  there's no way to recover a previous raw token to "reuse" it); `GET /hr/interviews/share/{token}`
  is public and returns a deliberately narrow payload (candidate name, job title, outcome) — no
  transcript, recording, or resume, to keep a shared link's blast radius small.

## New frontend surface
- `HrInterviews.tsx`: the old AI/Human tabbed card list is gone, replaced by a single "Candidate
  Pipeline" table (avatar, position, AI score as a thin progress bar + number, status pill,
  date, recommendation pill, View + kebab actions) with search, a kind/status filter dropdown,
  client-side pagination, CSV export, and a Bulk Actions menu (Move to Final Round). The report
  header sits above it with the date-range `Select` and "Generate Full Report" (opens a `Dialog`
  showing the stat grid + narrative). The two setup cards and their submit/suggest handlers are
  byte-for-byte the same logic as before, just relocated in the file.
- `HrInterviewDetailPage.tsx` (new, route `/dashboard/hr/interviews/:sessionId`): resume panel
  (real PDF via `iframe` + Download/Fullscreen — not a fabricated parsed-resume layout, since the
  product has no structured resume data beyond the actual file) alongside a scorecard panel with
  Overview/Skill Scores/Transcript/Notes tabs. Transcript tab also carries the recording
  player/download/delete that used to live in the old inline detail panel — moved, not dropped.
  Send Invite re-runs the existing invite flow; Share calls the new share endpoint and copies the
  link; Shortlist/Reject call the existing `PATCH /hr/candidates/{id}/status` (both disabled with
  an explanatory tooltip when the session has no resolvable candidate application).
- `HrInterviewSharedScorecard.tsx` (new, public route `/hr/interviews/share/:token`): read-only,
  unauthenticated, mirrors the scorecard's Overview content only.
- `recommendationLabel`'s `"review"` value changed from `"Review"` to `"Borderline"`
  (`hrInterviewPresentation.ts`) to match the mockup's terminology — shared helper, so this also
  changes the label everywhere else it's used (e.g. `HrCandidates.tsx`'s Interviewed cards).
  `RECOMMENDATION_META` gained an explicit `ringClass` per tone (`border-emerald-500` etc.) instead
  of deriving a border color from `scoreClass` via runtime `.replace("text-", "border-")` — that
  pattern doesn't work with Tailwind's JIT scanner (it needs the literal class string in source,
  not a value built by string manipulation at runtime), caught and fixed before shipping.

## Out of scope for this pass
- A dedicated recruiter "manage share links" view (revoke early, see who has one, etc.) — a share
  link just expires after 30 days.
- Prev/Next candidate paging on the detail page — explicitly declined when asked.
- Making the "Interview Done" vs "Pending" status column configurable/composite with shortlist
  state — explicitly decided against when asked; kept as pure interview-progress signal.
