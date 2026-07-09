# Exec Agent — Avatar Toggle Button
**Date:** 2026-07-01
**Branch:** `feature/exec-agent-improvements`
**Status:** Spec — pending implementation go-ahead

---

## Request
- Avatar toggle button in the exec agent header (left of transcript toggle)
- Only toggleable BEFORE session starts — disabled/locked during active session
- Backend respects the toggle — don't start HeyGen if avatar is off (saves $0.10/min)
- Future: billing controls toggle visibility (avatar is a paid add-on tier)

---

## Phase 1 — Verified Current State

**Backend:** `executive_agent.py` checks `LIVEAVATAR_AVATAR_ID` env var at agent startup — server-level switch only. Every session gets avatar or nothing. No per-session control.

**Frontend:** No avatar toggle exists. `POST /executive/session` body carries only `business_id` + `location_id` — no `avatar_enabled` flag.

**Why frontend-only toggle won't work:** Even if frontend ignores the video track, backend still starts HeyGen session → still charges $0.10/min. Toggle MUST propagate to backend.

---

## Phase 2 — Architecture

### Runtime flow
1. User sets avatar toggle (default ON if avatar available, persisted in localStorage)
2. User clicks "Start session"
3. Frontend sends `avatar_enabled: bool` in `POST /executive/session` body
4. Backend includes `avatar_enabled` in agent job metadata
5. Agent reads `avatar_enabled` from metadata at startup
6. If `avatar_enabled=false` OR `LIVEAVATAR_AVATAR_ID` not set → skip `AvatarSession.start()`
7. Session response includes `avatar_available: bool` (env var set + future: subscription tier check) → frontend only shows toggle if true

### Toggle UX rules
- Default: ON (if avatar available)
- Persisted: localStorage so user preference survives page refresh
- Locked: `disabled` when `isConnected || isConnecting` — cannot change mid-session
- Hidden: if `avatar_available=false` (env var not set / not on billing tier) — no toggle shown at all

### Billing hook (future — no code now)
- `avatar_available` in session response is the gate
- When billing is implemented: backend checks business subscription tier before setting `avatar_available=true`
- Zero frontend code changes needed at that point — just backend logic in `executive.py`

---

## Files + Changes (5 files)

### 1. `backend/app/routers/executive.py`
- Add `avatar_enabled: bool = True` to request body schema
- Pass `avatar_enabled` in agent job metadata (alongside `business_id`, `location_id`)
- Add `avatar_available: bool` to response (checks `LIVEAVATAR_AVATAR_ID` env var)

### 2. `agent/executive_agent.py`
- In `entrypoint`: read `avatar_enabled` from job metadata (default True if not present — backwards compatible)
- Change avatar startup: `if _avatar_id and avatar_enabled:` instead of `if _avatar_id:`

### 3. `ai-employees-app/src/lib/voiceAgentApi.ts`
- Add `avatarEnabled: boolean` param to `createExecutiveSession()`
- Include in request body
- Update return type to include `avatar_available: boolean`

### 4. `ai-employees-app/src/hooks/useExecutiveSession.ts`
- Add `avatarEnabled` state (default `true`, synced to localStorage)
- Add `toggleAvatarEnabled()` fn — only callable when not connected
- Pass `avatarEnabled` to `createExecutiveSession()` in `connect()`
- Expose `avatarEnabled`, `toggleAvatarEnabled`, `avatarAvailable` from hook

### 5. `ai-employees-app/src/components/executive/AgentStatusHeader.tsx`
- Add avatar toggle button left of transcript toggle
- Only shown if `avatarAvailable=true`
- Disabled when `isConnected || isConnecting`
- Visual: camera/video icon, active = accent color, inactive = muted

---

## Commit Plan (4 commits)

| # | Commit | Files |
|---|---|---|
| 1 | `feat(exec-agent): pass avatar_enabled through session creation API` | `executive.py` + `voiceAgentApi.ts` |
| 2 | `feat(exec-agent): agent respects avatar_enabled metadata flag` | `executive_agent.py` |
| 3 | `feat(exec-agent): avatar toggle state in useExecutiveSession hook` | `useExecutiveSession.ts` |
| 4 | `feat(exec-agent): avatar toggle button in header` | `AgentStatusHeader.tsx` |

---

## Open Decision (confirmed before implementation)
- **localStorage persistence:** YES — user preference survives refresh. Default = ON if avatar available.
