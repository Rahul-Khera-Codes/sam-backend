# Spec: HeyGen LiveAvatar POC — Executive Agent Phase 2 Avatar

**Date:** 2026-06-30
**Workstream:** WS4-P2 (Phase 2 avatar — HeyGen LiveAvatar replacing abstract orb)
**Status:** Approved for implementation

---

## Context

Sam confirmed HeyGen as the avatar platform (~Jun 29). Phase 1 built an abstract animated orb (`AgentAvatar.tsx`) with a clearly marked PHASE 2 SWAP POINT. This spec delivers the end-to-end POC that replaces the orb with a real talking HeyGen avatar, starting in sandbox mode (free, no credits).

**Decision (no toggle):** No toggle between orb and avatar — one experience. The orb is the loading/fallback state only (before avatar video track arrives). Once avatar video is live, it replaces the orb seamlessly.

---

## Verification Findings

### Backend
- `requirements.txt` — `livekit-agents[openai]~=1.4` only; no liveavatar plugin
- `agent/.env.local` — no HeyGen keys; plugin reads `LIVEAVATAR_API_KEY` + `LIVEAVATAR_AVATAR_ID`
- `backend/.env` — has `HEYGEN_API_KEY` + `HEYGEN_AVATAR_ID` (user-added 2026-06-30)
- `executive_agent.py` — `session = AgentSession(...)` at L955, `await session.start(...)` at L1059; avatar must start between these two lines
- `ctx.connect(auto_subscribe=AUDIO_ONLY)` at L903 — agent side only; frontend manages its own subscriptions independently; no change needed

### Frontend
- `AgentAvatar.tsx` — PHASE 2 SWAP POINT marked at L42; the orb `<div>` is the exact swap target
- `useExecutiveSession.ts` — attaches all remote audio via `attachRemoteAudio`, no video track handling
- `AgentDisplay.tsx` — passes `{agentState, isConnected}` to `<AgentAvatar>`; needs `avatarVideoRef` threaded through

### Plugin API (verified from LiveKit docs 2026-06-30)
- Env vars: `LIVEAVATAR_API_KEY` (mandatory), `LIVEAVATAR_AVATAR_ID` (optional — can also pass to constructor)
- Constructor: `liveavatar.AvatarSession(avatar_id="...")`
- Start: `await avatar.start(session, room=ctx.room)` — MUST be called BEFORE `session.start()`
- Avatar joins room as a **separate participant** publishing both audio + video tracks
- Install: `livekit-plugins-liveavatar~=1.4` — compatible with our `livekit-agents 1.4.5`; no framework bump needed
- **Double audio:** avatar republishes session audio synchronized to lip movements → must play avatar participant's audio only; skip original agent audio once avatar is active

---

## Changes (5 files)

### Change 1 — `agent/requirements.txt`
Replace:
```
livekit-agents[openai]~=1.4
```
With:
```
livekit-agents[openai,liveavatar]~=1.4
```
Single line — `[liveavatar]` extra installs `livekit-plugins-liveavatar~=1.4` at the correct version without bumping the framework.

---

### Change 2 — `agent/.env.local`
Add two lines (same values as `HEYGEN_API_KEY` / `HEYGEN_AVATAR_ID` in `backend/.env`):
```
LIVEAVATAR_API_KEY=<value from HEYGEN_API_KEY>
LIVEAVATAR_AVATAR_ID=<value from HEYGEN_AVATAR_ID>
```
The plugin reads these specific env var names. Agent loads `.env.local`; backend `.env` is not read by the agent.

---

### Change 3 — `agent/executive_agent.py`

**Import** (top of file alongside other livekit imports):
```python
from livekit.plugins import liveavatar
```

**Avatar start** (between `assistant = ExecutiveAssistant(...)` and `await session.start(...)`):
```python
_avatar_id = os.environ.get("LIVEAVATAR_AVATAR_ID", "")
if _avatar_id:
    _avatar = liveavatar.AvatarSession(avatar_id=_avatar_id, is_sandbox=True)
    await _avatar.start(session, room=ctx.room)
    logger.info("HeyGen LiveAvatar started (sandbox) — avatar_id=%s", _avatar_id)
else:
    logger.info("LIVEAVATAR_AVATAR_ID not set — running without avatar")
```

**Why the guard:** Agent still works without keys (falls back gracefully to audio-only + orb UI). `is_sandbox=True` for POC — remove when Sam confirms it looks right and wants to go production.

---

### Change 4 — `useExecutiveSession.ts`

**New state + ref:**
```ts
const avatarVideoRef = useRef<HTMLVideoElement>(null);
const [hasAvatarVideo, setHasAvatarVideo] = useState(false);
const avatarParticipantIdentityRef = useRef<string | null>(null);
```

**In `RoomEvent.TrackSubscribed`** — add video branch:
```ts
if (track.kind === "video") {
  // Avatar participant published its video — attach and mark active
  avatarParticipantIdentityRef.current = participant.identity;
  setHasAvatarVideo(true);
  if (avatarVideoRef.current) {
    (track as RemoteVideoTrack).attach(avatarVideoRef.current);
  }
} else if (track.kind === "audio") {
  // Only attach audio if it's from the avatar participant (synchronized audio),
  // OR if no avatar is active yet (original agent audio before avatar joins).
  const isAvatarParticipant = participant.identity === avatarParticipantIdentityRef.current;
  const isOriginalAgent = avatarParticipantIdentityRef.current === null;
  if (isAvatarParticipant || isOriginalAgent) {
    attachRemoteAudio(track as RemoteAudioTrack);
  }
}
```

**In `RoomEvent.TrackUnsubscribed`:**
```ts
if (track.kind === "video" && participant.identity === avatarParticipantIdentityRef.current) {
  avatarParticipantIdentityRef.current = null;
  setHasAvatarVideo(false);
  // Fallback: re-attach any remaining remote audio tracks
}
```

**Expose from hook:**
```ts
return { ..., avatarVideoRef, hasAvatarVideo };
```

---

### Change 5 — `AgentAvatar.tsx`

**New prop:**
```ts
interface AgentAvatarProps {
  agentState: AgentState;
  isConnected: boolean;
  className?: string;
  avatarVideoRef?: React.RefObject<HTMLVideoElement>;  // Phase 2
  hasAvatarVideo?: boolean;                             // Phase 2
}
```

**At PHASE 2 SWAP POINT** — replace the orb `<div>` block with:
```tsx
{/* PHASE 2: HeyGen talking avatar video (rendered when avatar participant is live) */}
<video
  ref={avatarVideoRef}
  autoPlay
  playsInline
  muted={false}
  className={cn(
    "w-20 h-20 rounded-full object-cover transition-opacity duration-300",
    hasAvatarVideo ? "opacity-100" : "opacity-0 absolute"
  )}
/>
{/* Phase 1 orb — hidden once avatar video is live, shown as connecting/fallback state */}
{!hasAvatarVideo && (
  <div className={cn(/* existing orb classes */)}>
    {/* existing orb content */}
  </div>
)}
```

**Thread through `AgentDisplay.tsx`:** pass `avatarVideoRef` + `hasAvatarVideo` from `ExecutiveAgent.tsx` (which destructures them from `useExecutiveSession`) down to `<AgentAvatar>`.

---

## Rollout

1. Backend: add plugin + env keys + avatar.start() → rebuild docker image
2. Frontend: video track handling + AgentAvatar swap → Vite HMR
3. Verify POC: start session → avatar video renders → audio syncs to lip movement → no double audio
4. Show Sam for feedback
5. If approved: remove `is_sandbox=True` → production

## Out of Scope (this spec)
- Avatar size/shape polish (POC uses same w-20 h-20 rounded-full as orb)
- Sam picking a different avatar ID
- Resizing the avatar to fill more screen real estate
- HR / CS agent avatar (reuse this pattern once Exec Agent is verified)
