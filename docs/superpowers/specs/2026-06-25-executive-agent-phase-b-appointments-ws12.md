# Spec — Executive Agent WS12 (Phase B slice 2): appointment_list with Cancel / Reschedule

**Date:** 2026-06-25 · **Workstream:** WS12 (WS3 Phase B, slice 2) · **Repos:** `sam-backend` + `ai-employees-app`
**Builds on WS11** `card_action` round-trip (synthetic-turn + preview/confirm gate).

## Verified current state
- `list_appointments` returns a text list with `[REF]` = `id[:8].upper()`. `cancel_appointment(appointment_ref, reason)` and `reschedule_appointment(appointment_ref, new_date, new_time)` resolve a row by ref prefix.
- WS11 `_on_data` already routes `{type:"card_action", action, …}`; `book_slot` implemented.
- Single `activeCard` slot; `sendCardAction(action, payload)` exists in the hook and is threaded to `AgentCardView`.

## Build — backend (`agent/executive_agent.py`)
- `list_appointments`: emit `appointment_list` card with rows `{ref, date, time, client, service}`; return a SHORT summary + a reference list (so the model can also act verbally), not the long text list.
- `_on_data`: add two actions (synthetic-turn resolve):
  - `cancel_appointment` `{ref}` → the in-card confirm IS the approval, so the prompt tells the model the owner already confirmed: *"The owner has confirmed cancelling appointment {ref}. Call cancel_appointment for reference {ref} now."* → model calls `cancel_appointment` directly (no double-confirm).
  - `reschedule_appointment` `{ref}` → conversational (needs a new time): *"The owner wants to reschedule appointment {ref}. Ask them for the new date and time, then call reschedule_appointment for reference {ref}."* → model asks → owner answers → model reschedules.
  - Prompts built from the typed `ref` only — never echo frontend free-text.

## Build — frontend (`ai-employees-app`)
- Hook: add `AppointmentListCard` to the union: `{type:"card", card:"appointment_list", id, data:{appointments:{ref,date,time,client,service}[]}}`.
- `AgentCardView`: render `appointment_list` via a small stateful `AppointmentListCard` subcomponent (needs local "which row is confirming" state):
  - Each row: `date time — client (service)` + **Cancel** and **Reschedule** buttons.
  - **Cancel = two-step (destructive):** first click swaps the row's buttons for "Cancel this appointment? [Yes, cancel] [No]". Yes → `onCardAction("cancel_appointment", {ref})` + reset; No → reset.
  - **Reschedule = one tap:** `onCardAction("reschedule_appointment", {ref})` (the model then asks for the new time conversationally).
  - Scroll within the card if many rows (`max-h` + overflow).

## Safety / notes
- Cancel never fires on a single tap — the in-card Yes/No is the confirmation, and the backend prompt reflects that so the model doesn't re-ask.
- Reschedule is non-destructive at tap time (just starts a conversation); the actual change goes through the model with explicit new date/time.

## Out of scope
In-card date/time picker for reschedule (conversational is fine for now); `email_detail` (slice 3).

## Verify
- Backend `ast.parse` clean; frontend `tsc --noEmit` clean.
- Live: "show my appointments" → list card with buttons; tap Cancel → confirm step → Yes → appointment cancelled (and gone on next list); tap Reschedule → Remi asks for the new time → provide it → moved. Unknown action logged, no crash.
