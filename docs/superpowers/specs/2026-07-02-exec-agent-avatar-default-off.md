# Exec Agent — Avatar Default-Off (Cost Lever)
**Date:** 2026-07-02
**Branch:** `feature/exec-agent-improvements` (both repos)
**Status:** Spec approved — pending implementation

---

## Why

From `docs/executive-agent-cost-analysis.md` (audit resolved 2026-07-02, staying on Realtime): HeyGen LiveAvatar adds $0.10–0.20/min on top of the base Realtime cost. It's a real, optional add-on cost with no functional necessity — the avatar toggle already exists (session 55), it's just defaulted to on. Flipping the default is the smallest, safest item in the remaining Pass-1 lever list.

---

## Phase 1 — Verified

Two places carry the default, and both currently say `True`:
- **Frontend**, `ai-employees-app/src/hooks/useExecutiveSession.ts:114-121` — `avatarEnabled` state initializer: falls back to `true` when no `localStorage["executive-avatar-enabled"]` value exists yet (first-time visitor, or cleared storage).
- **Backend**, `sam-backend/backend/app/routers/executive.py:29` — `ExecutiveSessionRequest.avatar_enabled: bool = True`. The frontend always sends this field explicitly today, so this default is currently dormant — but leaving it `True` means "default off" only holds incidentally in the one UI path, not as an actual API-level default. Any other caller that omits the field would still get avatar-on.

Both need to flip for "default off" to mean something at the system level, not just in one component.

---

## Phase 2 — Spec

### Files changed
- `ai-employees-app/src/hooks/useExecutiveSession.ts` — line 117 and 119, `true` → `false` in the `avatarEnabled` initializer's two fallback branches.
- `backend/app/routers/executive.py` — line 29, `avatar_enabled: bool = True` → `avatar_enabled: bool = False`.

### Not changed
- The toggle UI, the `avatar_enabled` plumbing through dispatch metadata, the agent's `if _avatar_id and avatar_enabled:` gate — none of that changes. This is purely flipping which state a first-time user (or an omitted-field caller) starts from. Anyone with an existing `localStorage["executive-avatar-enabled"]` value keeps their own choice — this only affects new/cleared browser state.

### Impact
New sessions default to no avatar (saves $0.10–0.20/min per session unless the owner explicitly turns it on). Existing users who already toggled it on keep their preference (localStorage isn't touched). Fully reversible — same one-line-per-file revert as any other config default.

### Risk
None identified.

---

## Commit Plan

| # | Commit | Files |
|---|---|---|
| 1 | `fix(exec-agent): default avatar_enabled to False in the session request model` | `backend/app/routers/executive.py` |
| 2 | `fix(exec-agent): default avatar toggle to off for first-time sessions` | `ai-employees-app/src/hooks/useExecutiveSession.ts` |
