# Spec — Executive Agent WS10: avatar-centric display + tool activity feed

**Date:** 2026-06-25 · **Workstream:** WS10 · **Repos:** `sam-backend` (`agent/executive_agent.py`) + `ai-employees-app`
**Decision (2026-06-25):** Center = avatar + a single status/activity caption. Remove the large `lastAgentMessage` paragraph. Full replies live in the transcript panel, which **auto-opens** once a session has activity. Cards = results, transcript = conversation, avatar = presence/status.

## Verified current state
- `AgentDisplay` connected view = `<AgentAvatar>` + a big `<p>{lastAgentMessage}>` (this paragraph is what we remove).
- Hook exposes `agentState` (idle/listening/thinking/speaking). `_set_state(room,…)` drives it. Tools currently set state="thinking" but emit no per-tool detail.
- `ExecutiveAgent.tsx`: `transcriptOpen` is `useState(false)` (manual toggle via header info button).
- Data channel already carries `state`, `card`, `card_dismiss`, `preview*` — parsed in hook `handleDataMessage`.

## Backend (`agent/executive_agent.py`)
- Add an async context-manager helper:
  ```python
  @contextlib.asynccontextmanager
  async def _activity(self, label: str):
      await _publish(self._room, {"type": "activity", "state": "start", "label": label})
      try:
          yield
      finally:
          await _publish(self._room, {"type": "activity", "state": "done"})
  ```
  (import `contextlib`). `finally` guarantees the spinner always clears, even on error.
- Wrap each tool body: `async with self._activity("<friendly label>"):`. Labels:
  - list_emails → "Reading your inbox…" · read_email → "Opening that email…"
  - draft_reply / draft_email → "Drafting…" · send_email_draft → "Sending your email…"
  - get_schedule → "Checking your calendar…" · create_calendar_event → "Preparing the event…"
  - confirm_create_calendar_event → "Adding to your calendar…" · find_free_slots → "Finding open slots…"
  - appointment tools → "Looking up appointments…" / "Updating the appointment…"
- Optional "done" label for confirmations (send/create): pass a result label on the closing event, e.g. emit `{state:"done", label:"Email sent"}` for terminal actions (keep `_activity` simple; for these two, publish the done-with-label explicitly inside the `with` before returning, or extend helper with an optional `done_label`). Keep generic done (no label) for read-only tools.

## Frontend (`ai-employees-app`)
- **Hook:** parse `type:"activity"` → `agentActivity: {state:"start"|"done", label?:string} | null`; expose it. Clear on disconnect.
- **`AgentDisplay`:** remove the `lastAgentMessage` paragraph. Under the avatar render one **caption**:
  - `activity.state==="start"` → small spinner + `label`.
  - `activity.state==="done"` → ✓ + done label, held ~1.2s then fades to the idle hint (min-display so fast tools don't flicker).
  - else → state caption ("Listening" / "Working on it…") or the idle hint "Ask me anything — emails, calendar, or appointments." when idle.
- **Auto-open transcript:** in `ExecutiveAgent.tsx`, effect: when `transcript.length` first becomes >0, `setTranscriptOpen(true)`. Track a `userToggledTranscript` ref so we only auto-open once and never fight a manual close.
- Keep `lastAgentMessage`/`streamingAgentText` flowing into the transcript panel (unchanged) — that's now the sole home for worded replies.

## Polish / guardrails
- One calm caption line only — no competing badges (keeps focus on the orb).
- Caption min-display ~600ms; done-state lingers ~1.2s then fades.
- `activity` is decorative → `aria-hidden` on the caption; transcript carries the accessible text.

## Out of scope
Per-token streaming into the caption; multi-line activity history; sound.

## Verify
- Backend `ast.parse` clean; frontend `tsc --noEmit` clean.
- Live: run a tool → caption shows "Reading your inbox…" with spinner, then ✓ briefly; card appears; transcript auto-opens with Remi's words; no stuck spinner on an error; no horizontal scroll / layout jump when a card mounts.
