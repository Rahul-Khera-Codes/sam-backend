# HR Employee: Interviews Scorecard Redesign (AIE-74)

## What it does
Restyles the HR "Interviews" list from a dense table into a per-candidate scorecard (name,
recommendation, role, AI-generated metric breakdown, summary, key highlights, actions), matching
the client-supplied mockup attached to AIE-74. Every field on the card is sourced from the
existing real Supabase-backed pipeline data (`GET /hr/interviews/pipeline` /
`GET /hr/interviews/{id}`) — no mock/hardcoded values were introduced.

## Data-mapping decisions
The mockup assumes fields the product doesn't actually track. Rather than fabricate them, each
was mapped to the closest real field or omitted:

- **Score**: `outcome.total_score` is 0–100 in the DB; the card displays it divided by 10
  (`9.4` style) to match the mockup's scale.
- **Metric grid**: the mockup hardcodes 4 categories (Technical skills, Communication, Problem
  solving, Cultural fit). Real rubric criteria are configured per job posting via the interview
  bank (`hr_interview_rubric_criteria`) and vary in name/count — the grid is rendered dynamically
  from `outcome.criterion_scores`, not hardcoded.
- **Metric score scale**: `hr_interview_scoring_service.py`'s LLM prompt previously never stated
  a numeric scale for a criterion's `score` (only `total_score` was clamped 0–100). Fixed by
  adding an explicit 1–5 requirement to the prompt (calibrated against each criterion's existing
  `score_1_anchor`/`score_3_anchor`/`score_5_anchor`) and clamping server-side
  (`_clamp_criterion_score`, `hr_interview_scoring_service.py`). The frontend also clamps
  defensively (`criteriaFor` in `HrInterviews.tsx`) so older, pre-fix rows can't break the bar
  width. This only affects newly generated outcomes — no migration/backfill.
- **"Video interview"/"Phone interview" badge**: no interview-modality field exists. Replaced
  with the real `interview_kind` value — "AI screen" / "Human interview".
- **"Interviewed by [name]"**: no interviewer-name field exists. AI screens always show
  "AI Interviewer · Emily" (a static product fact, same avatar already hardcoded elsewhere in the
  HR module). Human interviews show "Via {human_interview_provider}" (the existing free-text
  provider/location field) instead of inventing a person's name.
- **Duration**: no session-level duration field exists. `started_at`/`completed_at` are populated
  by the live LiveKit runtime for AI screens only, so duration is computed client-side
  (`formatDuration`) and shown **only for AI screens** when both timestamps are present; omitted
  for human interviews rather than shown as a guess.
- **"Watch recording"**: recordings are audio-only (`hr_interview_recordings.recording_type =
  "audio"`), so the action is labeled "Listen to recording" for both interview kinds instead of
  "Watch"/"Listen" split by a modality that isn't tracked.

## Key files
**Backend (sam-backend)**
- `backend/app/services/hr_interview_scoring_service.py` — added the 1–5 criterion-score scale
  requirement to the LLM prompt and `_clamp_criterion_score` server-side clamp.

**Frontend (ai-employees-app)**
- `src/pages/dashboard/hr/HrInterviews.tsx` — replaced `InterviewTable` with
  `InterviewCardList`/`InterviewCard`; added `RECOMMENDATION_META`, `formatDuration`,
  `criteriaFor` helpers. Stat cards, invite/track forms, search, tabs, the below-list detail
  panel (transcript/recruiter notes/recording playback), and "Move to Final Round" logic are all
  unchanged — only the per-row rendering changed from table rows to cards.

## Out of scope for this pass
- Adding a structured interviewer-name field for human interviews, a session-level duration
  column, or a video/phone/onsite modality field — would require new DB columns/migration;
  deferred since the redesign could be done accurately with existing data.
- Changing the score scale shown in the below-list detail panel (`selected.session.outcome`
  block) — left as `/100` to minimize scope; only the new card list uses the `/10` scale.
