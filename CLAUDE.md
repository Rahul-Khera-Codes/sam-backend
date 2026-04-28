# Claude Code Instructions — sam-backend

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
- `sam-backend/` — FastAPI backend + LiveKit agent (`agent/agent.py`)
- `ai-employees-app/` — React/TypeScript frontend (sibling directory)

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
