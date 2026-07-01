# Claude Code Instructions — sam-backend

## Working Rules (ALWAYS enforced — every session, every task)

1. **Don't assume — ask first.** If anything about the task, scope, or intent is unclear, ask a clarifying question before writing any code. One good question beats a wrong implementation.

2. **Web search before adding packages or configuring them.**
   - Before adding any new package (Python or Node), search for the latest compatible version against the existing runtime and installed dependencies.
   - Before following any configuration pattern, search for the docs for the *exact installed version* — config APIs change between versions and stale knowledge causes silent bugs.
   - Do this explicitly and show the version chosen + why.

3. **Disagree openly.** If there's a better approach, a risk in the plan, or something that seems wrong, say so before implementing. Discuss first — don't silently do the dumb thing.

4. **Verify and trace before fixing.** For every issue:
   - Reproduce or confirm the bug exists.
   - Trace the full call flow (frontend → API → backend → agent → DB) to find the real root cause.
   - Identify all places the fix touches and what else could break.
   - Only then implement.

5. **Confirm what was verified after each fix.** State what was checked (syntax, types, logic trace, related flows) so it's clear the fix is solid, not just plausible.

6. **Think as engineer + product owner — full resolution, no patches.**
   - For new functionality: before writing any code, (a) verify technical feasibility in the current stack, (b) map every layer affected (frontend → hook → API router → backend → agent → DB → side effects on existing flows), (c) identify what existing features could break or change behavior, (d) present the full impact and wait for confirmation.
   - For bugs: same — never patch the symptom, solve the root cause completely.
   - "Product owner" means: how does this change what the end user experiences? Does it conflict with another flow, create confusion, or introduce a hidden cost?
   - **Mandatory sequence: verify → spec → implement. No exceptions.**

---

## Dev Process (ALWAYS follow — every task, every session)

Every piece of work — bug fix or new feature — follows three explicit phases.
Do not skip or merge phases. Do not start the next phase without completing the current one.

### Phase 1 — Verify
- Reproduce or confirm the issue/requirement exists.
- Trace the full call flow end-to-end (frontend → hook → API → backend → agent → DB).
- Identify the real root cause (bugs) or the exact gap (features) — not the surface symptom.
- Read every file that will be touched. Understand current behavior before proposing any change.
- **Output:** a clear statement of what is actually wrong or missing, with evidence.

### Phase 2 — Spec
- List every file that needs to change and exactly what changes in each.
- Map the full impact: what existing flows are affected, what could break, what edge cases exist.
- State any risks, tradeoffs, or open questions.
- **Present this to the user and wait for explicit confirmation before writing any code.**
- If the spec reveals the task is bigger or different than described, say so now — not mid-implementation.

### Phase 3 — Implement
- Only after Phase 2 is confirmed ("yes, go ahead" / "start").
- Implement one logical unit at a time. Do not bundle unrelated changes.
- **Incremental commits — no large commits.** Each commit = one coherent change (one file fixed, one tool added, one bug resolved). If a task touches 4 files for 4 different reasons, that is 4 commits.
- Commit message must say what changed and why in one line. No vague "fix" or "update" messages.
- After completion, state what was verified (syntax, types, logic trace, related flows).

---

## Session Start Checklist (ALWAYS do this first)
1. Read `TODO.md` — understand what's done, in progress, and pending
2. Read `docs/SESSION_HANDOFF.md` — full current system state, known issues, uncommitted changes
3. Read memory files (`~/.claude/projects/.../memory/`) — blockers, project state, feedback

## TODO Tracking (REQUIRED throughout every session)
- Mark tasks **in progress** when you start them
- Mark tasks **completed** and move to ✅ Done when finished
- **Add new tasks** to TODO.md as you discover bugs or new work
- Update the `Last updated` line at the end of every session

## Memory + Docs (REQUIRED at end of every session)
- Update `docs/SESSION_HANDOFF.md` — rewrite the "What Was Done This Session" block with this session's work; update System Status, Pending Manual Steps, Applied Migrations
- Update `memory/project_voice_agent.md` — keep "What's Working" and "Blocked" current
- Update `memory/project_blockers.md` — remove resolved blockers, add new ones
- These must be updated **before ending the session** — not optional

## Project Overview
AI voice agent SaaS — multi-tenant, multi-location. Two repos:
- `/home/lap-68/Documents/gt-rahul/sam-backend` — FastAPI backend + LiveKit agent (`agent/agent.py`)
- `/home/lap-68/Documents/gt-rahul/ai-employees-app` — React/TypeScript frontend (sibling directory)

Active agent: `agent/agent.py` (`USE_LIVEKIT_AGENT=1`). Legacy worker in `backend/worker/` is bypassed.

## Key Conventions
- All Supabase reads in backend routers use `supabase_admin` (service role) to bypass RLS
- Agent reads Supabase directly (service role key in `agent/.env.local`)
- Dispatch rules carry only `business_id` in attributes — no `location_id`
- `prompt_builder.build_instructions` falls back to `locations[0]` when `location_id` is None
- Phone numbers normalized to E.164 via `_normalize_phone_e164()` before any DB write or SMS send

## Running the Stack
```bash
docker compose up -d                          # start all services
docker logs -f sam-backend-sam-agent-1        # agent logs
docker compose restart sam-agent              # restart agent (if hot reload missed a change)
```

## QA Agent Rules (read when in QA mode)
- Read docs/qa_state.md and docs/QA_FINDINGS.md at session start
- Update docs/qa_state.md coverage map and last-run stats before ending
- Append all failures to docs/QA_FINDINGS.md using TC-[id] format
- Update client_launch_checklist.md statuses as tests pass/fail
- NEVER edit any source file during QA — document findings only
- Use Playwright via Node.js for browser simulation
- Screenshot failures → save to docs/qa-screenshots/TC-[id].png