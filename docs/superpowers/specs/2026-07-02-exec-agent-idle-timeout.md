# Exec Agent — Idle-Session Auto-Disconnect (Cost Lever)
**Date:** 2026-07-02
**Branch:** `feature/exec-agent-improvements`
**Status:** Spec approved — pending implementation

---

## Why

From `docs/executive-agent-cost-analysis.md` (audit resolved 2026-07-02): confirmed via grep that no idle/inactivity timeout exists anywhere in `executive_agent.py`. An owner who opens the Executive Agent tab, connects, and then walks away (or forgets to click "End session") keeps the LiveKit room — and the underlying OpenAI Realtime session — billing indefinitely. Small, isolated fix, no product downside for anyone actually using it.

---

## Phase 1 — Verified

- **`AgentSession` already tracks user activity** via a built-in `user_away_timeout` param (default `15.0`s — confirmed by inspecting the installed `livekit-agents` 1.6.4 in the running container). After this many seconds of both user and agent silence, `session`'s internal `user_state` flips to `"away"` (from `"listening"`/`"speaking"`) and emits a `user_state_changed` event (`UserStateChangedEvent(old_state, new_state)`, values are `Literal["speaking", "listening", "away"]`).
- **We aren't currently listening to this event at all** — confirmed via grep, no `user_state_changed` handler exists.
- **The disconnect call already exists as a pattern in this codebase**: `agent/agent.py` uses `await ctx.room.disconnect()` three times (L1744, 1797, 1810) to end a call — same call works for the exec agent's job context.
- **Local convention for state-driven handlers** (`executive_agent.py:1109-1123`): `@session.on("event")` decorator + `def handler(_ev) -> None: asyncio.ensure_future(...)` for any async side-effect. Following this exactly for consistency.

15 seconds of "away" is much too short to act on directly (an owner reading a long email card in silence would trip it) — so this needs its own longer timer layered on top of the state signal, not a change to `user_away_timeout` itself.

---

## Phase 2 — Spec

### File changed
Only `agent/executive_agent.py`. Placed right after the existing state-signaling handlers (L1107-1123), before the text-input handler section.

### Change
```python
# ── Idle-session auto-disconnect ────────────────────────────────────────────
IDLE_DISCONNECT_SECONDS = 180  # how long "away" must persist before we hang up

_idle_disconnect_task: asyncio.Task | None = None

async def _idle_disconnect() -> None:
    await asyncio.sleep(IDLE_DISCONNECT_SECONDS)
    logger.info("Executive session idle for %ds — auto-disconnecting", IDLE_DISCONNECT_SECONDS)
    await ctx.room.disconnect()

@session.on("user_state_changed")
def _on_user_state_changed(ev) -> None:
    nonlocal _idle_disconnect_task
    if ev.new_state == "away":
        _idle_disconnect_task = asyncio.ensure_future(_idle_disconnect())
    elif _idle_disconnect_task and not _idle_disconnect_task.done():
        _idle_disconnect_task.cancel()
        _idle_disconnect_task = None
```

- **3 minutes (180s)** chosen as the "away" duration before disconnect, on top of the existing 15s that gets the state to "away" in the first place — so a real abandoned session is closed after roughly 3m15s total silence, generous enough not to cut off someone reading a card or thinking, tight enough to cap real waste.
- Any resumed activity (`new_state` back to `"listening"` or `"speaking"`) cancels the pending disconnect task — no risk of hanging up on someone who was just quiet for a bit and then came back.

### Impact
Caps worst-case billing waste from an abandoned open tab. No effect on any session with actual back-and-forth activity. No change to any existing tool, card, or approval flow.

### Risk
None identified — mirrors an existing disconnect call and an existing handler pattern already used in this exact file.

---

## Commit Plan

| # | Commit | Files |
|---|---|---|
| 1 | `feat(exec-agent): auto-disconnect after 3 minutes of user inactivity` | `executive_agent.py` |

---

## Fix — live test found `ctx.room.disconnect()` doesn't disconnect the frontend (2026-07-02)

**Symptom:** live test confirmed the timer fires correctly at 180s and the agent's own logs show a clean disconnect (`"session closed", "reason": "user_initiated"`) — but the frontend UI stayed showing "connected," no auto-disconnect visible in the browser.

**Root cause:** `ctx.room.disconnect()` only detaches the **agent's own participant** from the LiveKit room — it does not close the room or disconnect the frontend's separate WebRTC connection. The frontend (`useExecutiveSession.ts:315`) only listens for `RoomEvent.Disconnected` (fires when *your own* connection ends), not `RoomEvent.ParticipantDisconnected` (fires when *another* participant, e.g. the agent, leaves) — so it never reacted.

**Fix:** delete the room server-side instead, which force-disconnects every participant (agent + frontend) and correctly fires `RoomEvent.Disconnected` on the frontend, triggering its existing (correct) cleanup handler. Precedent for this exact call already exists in `backend/app/services/livekit_service.py:237` (`api.room.delete_room(...)`). `JobContext.api` (a cached property, `job.py:396`, `from livekit import api`) gives the agent process its own authenticated `LiveKitAPI` client for the same call — confirmed `api.DeleteRoomRequest` is importable and `ctx.api.room.delete_room(...)` is the right call.

```python
from livekit import agents, api, rtc  # add `api` to the existing import

async def _idle_disconnect() -> None:
    await asyncio.sleep(IDLE_DISCONNECT_SECONDS)
    logger.info("Executive session idle for %ds — auto-disconnecting", IDLE_DISCONNECT_SECONDS)
    await ctx.api.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
```

No other change needed — the `user_state_changed` handler and cancellation logic are unaffected.

| # | Commit | Files |
|---|---|---|
| 2 | `fix(exec-agent): delete the room on idle-disconnect instead of only leaving it` | `executive_agent.py` |
