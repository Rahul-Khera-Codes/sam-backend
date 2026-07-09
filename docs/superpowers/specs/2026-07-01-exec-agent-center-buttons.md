# Exec Agent — Center Start Session + Unmute Mic Buttons
**Date:** 2026-07-01
**Branch:** `feature/exec-agent-improvements`
**Status:** Spec approved — pending implementation

---

## Request (from Sam, Jun 25–30)
1. Move "Start session" button to the center of the screen (currently top-right header)
2. Add "Unmute Mic" button to the center of the screen when connected (currently only in the bottom InputBar)

---

## Phase 1 — Verified State (on `feature/exec-agent-improvements`)

### Current layout
- **`ExecutiveAgent.tsx:60-74`** — "Start session" button lives in the top-right of the page title bar. When not connected, `AgentDisplay` shows only text: *"Press 'Start session' to connect"* — no actual button in the center.
- **`AgentDisplay.tsx:93-107`** — Session ended state shows *"Start a new session to continue."* — also no button, user is stuck.
- **`InputBar.tsx:46-66`** — Mic toggle is a small `h-8 w-8` ghost icon button in the bottom bar. Only accessible from there.
- `AgentDisplay` does not receive `onConnect`, `isConnecting`, `onToggleMic`, or `isMicEnabled` as props.

### Key difference from `fix/avatar-aec`
`InputBar.tsx:97` on this branch reads **"Mic is live — speaking works alongside typing"** (original text). The headphone notice ("Use headphones with voice mode to prevent echo") is only on `fix/avatar-aec` and is not part of this task.

---

## Phase 2 — Spec

### Files + exact changes

#### `AgentDisplay.tsx`
- Add 4 new props to interface: `onConnect: () => void`, `isConnecting: boolean`, `onToggleMic: () => void`, `isMicEnabled: boolean`
- **Fresh empty state (L82-92):** Replace `<p>Press "Start session"…</p>` with an actual `<Button onClick={onConnect}>` with connecting spinner
- **Session ended state (L93-107):** Add `<Button onClick={onConnect}>Start new session</Button>` — currently no button here; user cannot restart without scrolling to the top-right
- **Connected state (L108-117):** Add a centered mic toggle button below the activity caption — larger and more prominent than the InputBar version

#### `ExecutiveAgent.tsx`
- Pass new props down to `AgentDisplay`: `onConnect={connect}`, `isConnecting={isConnecting}`, `onToggleMic={toggleMic}`, `isMicEnabled={isMicEnabled}`
- **Header (L60-74):** Keep "End session" button when connected. Remove "Start session" when not connected — header is clean; the center is now the single source of truth for starting

#### `InputBar.tsx`
- Remove the mic toggle button (L46-66) — it moves to center
- Remove `onToggleMic` from props interface and destructuring
- Keep `isMicEnabled` prop — still needed for placeholder text ("Speak or type…" vs "Type a message…") and the mic-live hint text (L96-100)
- `ExecutiveAgent.tsx` stops passing `onToggleMic` to `InputBar`

### No other files affected
No other component consumes `AgentDisplay` or `InputBar`. Changes are fully isolated to the exec agent feature.

---

## Commit Plan (2 commits, each self-contained and compilable)

| # | Commit message | Files |
|---|---|---|
| 1 | `feat(exec-agent): move Start Session button to center` | `AgentDisplay.tsx` (empty + ended state buttons) + `ExecutiveAgent.tsx` (prop wiring + header cleanup) |
| 2 | `feat(exec-agent): move Unmute Mic button to center` | `AgentDisplay.tsx` (connected state mic button) + `ExecutiveAgent.tsx` (pass toggleMic/isMicEnabled) + `InputBar.tsx` (remove mic button + prop) |

---

## Risks / Decisions
- **Two mic buttons removed from InputBar** — one source of truth (center) is less confusing. InputBar becomes text + send only.
- **Session ended state** — adding a "Start new session" button here is an improvement over the current dead-end state (no button). Not in Sam's original request but correct product behavior.
