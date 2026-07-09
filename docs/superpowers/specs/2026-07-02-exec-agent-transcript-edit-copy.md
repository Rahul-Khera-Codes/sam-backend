# Exec Agent — Edit + Copy Buttons on Transcript Bubbles
**Date:** 2026-07-02
**Branch:** `feature/exec-agent-improvements` (frontend only)
**Status:** Spec approved — pending implementation

---

## Request (Sam, Jul 1, item #7)

"Can we add an edit button and copy button for the speech to texts boxes to edit minor mistakes rather than having to repeat the entire speech."

---

## Phase 1 — Verified

`TranscriptPanel.tsx:61-85` — `TranscriptBubble` renders `entry.text` as plain, non-interactive text. No buttons of any kind exist on any bubble today. `TranscriptPanelProps` doesn't receive a way to send a new message — only `transcript`, `streamingAgentText`, `onClose`.

`ExecutiveAgent.tsx:131-135` — the only place `TranscriptPanel` is rendered; `sendMessage` already exists in this component's scope (from `useExecutiveSession()`) but isn't passed down.

---

## Phase 2 — Spec

### The key design call: what does "Edit" actually do?

By the time a spoken turn lands in the transcript, the Realtime model has already heard the audio and likely already replied — there's no way to retroactively change what the model understood. So "edit" can't mean rewriting history; it has to mean **sending a corrected version as a new turn**, which is exactly what "rather than having to repeat the entire speech" is asking for — type the fix instead of re-speaking the whole thing. This reuses the *existing* `sendMessage(text)` path unchanged — no new backend behavior, no new data-channel message type. The original (possibly mis-transcribed) bubble stays as-is in the history; the correction appears as a new bubble, same as if the owner had typed it fresh.

### Files changed
Frontend only, both in `ai-employees-app`:

**`TranscriptPanel.tsx`:**
- Add `onSendMessage: (text: string) => void` to `TranscriptPanelProps`, threaded down to `TranscriptBubble`.
- `TranscriptBubble` gains local edit-mode state (`useState`, matching the existing `AppointmentListCard`/`EmailDraftCard` pattern in `AgentCardView.tsx`).
- **Copy button** — on every bubble (user and agent both — useful either direction). Icon-only, `navigator.clipboard.writeText(entry.text)`, brief checkmark flip (~1.5s) for feedback, matching common copy-button UX.
- **Edit button** — user bubbles only (`entry.role === "user"`) — editing Remi's own generated replies doesn't make sense. Clicking reveals an inline textarea pre-filled with `entry.text` (pencil-icon pattern, matching the existing Knowledge Base inline-edit convention elsewhere in this app) with Save/Cancel. Save calls `onSendMessage(editedText)` — reusing `sendMessage` exactly as typing in the input bar would — and exits edit mode without mutating the original bubble. Cancel exits edit mode, no-op.

**`ExecutiveAgent.tsx`:**
- Pass `onSendMessage={sendMessage}` into `<TranscriptPanel>` (L131-135) — `sendMessage` is already in scope, just wasn't threaded down.

### Not changed
- No backend change — `sendMessage`'s existing data-channel path (`user_text` → `session.generate_reply(user_input=text)`) is reused verbatim.
- No change to how live speech is transcribed or how `transcript` entries are added.

### Impact
Owner can fix a misheard word by typing a quick correction instead of repeating the whole utterance out loud, and can copy any bubble's text (their own or Remi's) to the clipboard.

### Risk
None identified — purely additive UI, reuses an existing, already-tested send path.

---

## Commit Plan

| # | Commit | Files |
|---|---|---|
| 1 | `feat(exec-agent): copy button on all transcript bubbles` | `TranscriptPanel.tsx` |
| 2 | `feat(exec-agent): edit button on user bubbles — resend a correction instead of re-speaking` | `TranscriptPanel.tsx`, `ExecutiveAgent.tsx` |
