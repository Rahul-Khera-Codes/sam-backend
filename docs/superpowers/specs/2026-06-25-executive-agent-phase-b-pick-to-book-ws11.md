# Spec — Executive Agent WS11 (Phase B slice 1): card_action round-trip + free_slots pick-to-book

**Date:** 2026-06-25 · **Workstream:** WS11 (WS3 Phase B, slice 1) · **Repos:** `sam-backend` + `ai-employees-app`
**Decisions (2026-06-25):** card buttons resolve via a **synthetic user turn + the existing preview→approve gate** (not direct backend resolve). First interactive card = **free_slots pick-to-book** (non-destructive, proves the round-trip end-to-end).

## Verified current state
- `find_free_slots` returns a plain-text bullet list (no card). Walks 8am–6pm in 30-min steps, ≤6 slots.
- Approval flow exists: `create_calendar_event` → `_send_preview` (calendar_event_preview card) → owner approves → `confirm_create_calendar_event` (WS0 tz-safe). Single `activeCard` slot.
- Backend `_on_data` (entrypoint) handles only `{type:"user_text"}` via `session.generate_reply(user_input=…)`. `session` is in scope there.
- Frontend hook publishes data via `room.localParticipant.publishData(...,{reliable:true})` (see `sendMessage`). `AgentCardView` renders cards from a registry; single `activeCard`.

## Build — backend (`agent/executive_agent.py`)
- `find_free_slots`: build structured slots `{start:"14:00", label:"2:00 PM"}` (alongside the existing logic). Emit `_send_card("free_slots", {date, durationMinutes, slots:[…]})`. Return a SHORT summary to the model (+ slot labels as reference so it can also book verbally), not the long bullet list.
- `_on_data`: add `elif payload.get("type") == "card_action":` routing by `action`:
  - `book_slot` with `{date, start, durationMinutes}` → build a precise synthetic turn and `asyncio.ensure_future(session.generate_reply(user_input=f"Book a {dur}-minute appointment on {date} at {start}. Create the calendar event."))`. The model then calls `create_calendar_event` → preview card → owner approves → `confirm_create_calendar_event`. **Backend builds the prompt from the structured payload** (don't let the frontend craft the model prompt).
  - Unknown actions: log + ignore.

## Build — frontend (`ai-employees-app`)
- Hook: add `FreeSlotsCard` to `AgentCard` union: `{type:"card", card:"free_slots", id, data:{date:string, durationMinutes:number, slots:{start:string,label:string}[]}}`. Add `sendCardAction(action, payload)` → `publishData({type:"card_action", action, ...payload}, {reliable:true})`. Expose it.
- `AgentCardView`: render `free_slots` — header "Open slots — <date>", a wrap grid of tappable slot chips; `onClick` → `onCardAction("book_slot", {date, start, durationMinutes})`. Add optional `onCardAction` prop. Empty → "No open slots."
- Thread `sendCardAction` through `ExecutiveAgent` → `AgentDisplay` → `AgentCardView`.
- After tapping, the preview card replaces the slots card automatically (single slot) — no manual dismiss needed.

## Safety / notes
- Non-destructive: booking still requires the owner to approve the preview, so a stray tap can't create an event silently.
- `card_action` payload is owner-originated UI, but backend still constructs the actual model prompt from typed fields (date/start/duration) — never echoes free-form frontend text into the model.
- Title defaults to "Appointment" via the model; refining the title is out of scope for this slice.

## Out of scope (later Phase B slices)
- `appointment_list` Cancel/Reschedule (destructive → needs in-card confirm) — slice 2.
- `email_detail` card — slice 3.

## Verify
- Backend `ast.parse` clean; frontend `tsc --noEmit` clean.
- Live: "find free slots on Friday" → slot chips render; tap a chip → calendar preview appears with that date/time → approve → event created (WS0 tz holds). Verbal "book the 2pm" still works. Unknown action logged, no crash.
