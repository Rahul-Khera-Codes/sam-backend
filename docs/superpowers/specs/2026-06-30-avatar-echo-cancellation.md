# Avatar Echo Cancellation — Research & Fix Spec
**Date:** 2026-06-30  
**Branch:** `fix/avatar-aec` (both repos)  
**Status:** Researched — pending implementation go-ahead

---

## Problem

When the HeyGen LiveAvatar is active and the user enables their microphone, Remi's responses get cut off mid-sentence. The session becomes unusable for voice interaction.

### Symptoms (from logs 2026-06-30 10:30–10:32)

- Remi's responses truncated after 6–10 words: `"Hey, sounds like"`, `"Sure, go ahead and"`, `"Ah, I see. You want to optimize your schedule,"`
- Repeated `OpenAI Realtime API response done but not complete with status: cancelled (type=cancelled, reason=turn_detected)`
- Fake "user" utterances in foreign languages: `"Tabii ki"` (Turkish), `"うん。"` (Japanese), `"Угу"` (Russian), `"ishtimad"` — these are Remi's English speech echoing back through the mic and mis-transcribed by STT
- `playback_finished called more times than playback segments were captured` — secondary symptom, framework noise from avatar audio track

### Root Cause

**Browser-side audio echo loop:**

1. HeyGen avatar audio plays through browser speakers (via `document.createElement("audio")` element)
2. User's microphone picks up the speaker output (echo)
3. Echo is sent to the OpenAI Realtime API as user microphone input
4. STT mis-transcribes the echoed English as garbage/foreign-language strings
5. Realtime API sees "user spoke" → fires `turn_detected` → cancels Remi's current response
6. Loop repeats every time Remi speaks

**Key evidence:** Truncation begins EXACTLY when mic stream starts (`10:30:47 start reading stream`). Remi's greeting before mic was enabled (`10:30:41`) played completely without interruption.

The `playback_finished` extra calls are a separate symptom (liveavatar plugin publishes avatar audio back to the room, confusing the framework's segment tracker) but are NOT the primary cause of truncation.

---

## Why the Current Audio Routing Can't Be Echo-Cancelled

We play remote audio via:
```typescript
const el = document.createElement("audio");
track.attach(el);
document.body.appendChild(el);
```

The browser's WebRTC AEC works by referencing what's being played through the **WebRTC peer connection's audio output path**. A raw `<audio>` DOM element is completely decoupled from this path — the AEC has no reference signal and cannot cancel the echo.

---

## Research Findings (livekit-client v2.9.0)

Researched 2026-06-30 via Context7 (official livekit-client docs).

### What's Available

**`webAudioMix` Room option:**
```typescript
const audioContext = new AudioContext();
const room = new Room({
  webAudioMix: { audioContext },
});
```
Routes all remote audio through a shared Web Audio API `AudioContext`. Some browsers (Chrome desktop) monitor `AudioContext.destination` as an AEC reference signal — meaning audio played this way may be cancelled from the mic capture. Not guaranteed across all platforms.

**`audioCaptureDefaults`:**
```typescript
const room = new Room({
  audioCaptureDefaults: {
    echoCancellation: true,   // enabled by default in LiveKit
    noiseSuppression: true,
    autoGainControl: true,
  },
});
```
Our current code creates `new Room()` with no options — these defaults may or may not be applied.

**`participant.setVolume(value: 0–1)`:**
Available on `RemoteParticipant`. Can reduce avatar audio volume to give AEC a better chance at cancellation.

### What Was Ruled Out

| Approach | Why Ruled Out |
|---|---|
| Server-side VAD threshold | OpenAI Realtime uses server-side turn detection — not configurable from our side (`turn_detection is ignored` in logs) |
| Custom DSP / software AEC (Speex, RNNoise) | Weeks of work; out of scope |
| Auto-mute mic while agent speaks | Breaks barge-in — the core voice AI feature of interrupting the agent |
| `playback_finished` framework warnings | Secondary symptom, not root cause; liveavatar plugin behavior |

---

## Honest Assessment

**There is no guaranteed browser-only full fix.** The echo problem is a fundamental acoustic issue. The correct user-behavior solution is headphones (physically breaks the loop). The `webAudioMix` approach is the best available code-side attempt but is:
- Effective on Chrome desktop (likely ~60–80%)
- Not guaranteed cross-browser
- Not a substitute for headphones in a noisy environment

This is standard for all voice AI products with audio output — every product (Zoom, Meet, Teams) recommends headphones for voice interaction.

---

## Proposed Fix (fix/avatar-aec branch)

### Layer 1 — Browser AEC best effort (frontend only)

**File:** `ai-employees-app/src/hooks/useExecutiveSession.ts`

Changes:
1. Create a shared `AudioContext` (lazily on first user gesture — browser autoplay restriction)
2. Pass `webAudioMix: { audioContext }` + explicit `audioCaptureDefaults` to `new Room(...)`
3. Remove manual `document.createElement("audio")` routing — LiveKit handles playback via AudioContext automatically when `webAudioMix` is set
4. Replace `cleanupAudio()` / `attachRemoteAudio()` "drop original agent audio when avatar joins" logic with `participant.setVolume(0)` on the original agent participant — cleaner, operates at the AudioContext mixer level
5. On avatar `TrackUnsubscribed`, restore original agent participant volume

**What stays unchanged:** all video track subscription, avatar identity tracking, avatar video rendering, card/transcript/data message logic.

### Layer 2 — User guidance (belt-and-suspenders)

**File:** `ai-employees-app/src/components/executive/InputBar.tsx`

Change the existing mic-enabled notice (line 97–99) from:
> "Mic is live — speaking works alongside typing"

To:
> "Use headphones with voice mode to prevent echo"

This is honest product guidance, not a workaround.

### No backend changes

The echo is 100% browser-side. `sam-backend` and `executive_agent.py` are untouched in this branch.

---

## What This Branch Does NOT Fix

- The `playback_finished called more times than playback segments were captured` warnings — these are a liveavatar v1.4 plugin behavior; not causing conversation breakage; monitor if they cause issues in v1.5+
- Environments where browser AEC is weak (Linux Chrome, some mobile browsers) — headphones required
- The ~2min `LiveAvatar connection closed unexpectedly` HeyGen session timeout — separate issue, tracked in `feature/google-calendar-timezone`

---

## Merge Plan

1. Implement on `fix/avatar-aec` (both repos)
2. Test: start session → enable mic → speak → Remi responds without being interrupted → no foreign-language echo utterances in logs
3. Merge `fix/avatar-aec` → `feature/google-calendar-timezone` (NOT to main directly — keep exec agent work consolidated)
4. Then merge `feature/google-calendar-timezone` → main as planned
