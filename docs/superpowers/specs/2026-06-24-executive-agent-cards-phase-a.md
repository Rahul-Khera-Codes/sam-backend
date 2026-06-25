# Spec — Executive Agent Rich Cards, Phase A

**Date:** 2026-06-24 · **Workstream:** WS3 (Phase A) · **Repos:** `sam-backend` (`agent/executive_agent.py`) + `ai-employees-app`
**Design doc:** `docs/executive-agent-cards-design.md` (full contract/catalog/decisions)

## Goal
Generalize the existing preview mechanism into a typed **card** system, and add two high-value info cards. Tools emit cards with real data; frontend renders them via a registry with text fallback.

## Verified current state
- Backend: `_send_preview(preview)` → `_publish(room, {"type":"preview", **preview})`; `_clear_preview()` → `{"type":"preview_cleared"}`. `draft_reply` and `create_calendar_event` already emit previews (`kind: "email_draft"|"calendar_event"`).
- Frontend (`useExecutiveSession.ts`): `PreviewItem = EmailDraftPreview | CalendarEventPreview`; sets `previewItem` on `type:"preview"`, clears on `preview_cleared`. `approvePreview()` → sends "yes, go ahead"; `rejectPreview()` → "cancel that" (synthetic text turns). `AgentDisplay.tsx` renders the preview panel with buttons.
- So 2 card kinds + approve/reject round-trip ALREADY work. Phase A generalizes + adds info cards.

## Scope — Phase A only
**Cards:**
1. `email_draft` — migrate existing preview (actions: send/cancel — already wired via approve/reject).
2. `calendar_event_preview` — migrate existing preview (actions: confirm/cancel — already wired).
3. **`email_list`** — NEW. Emitted by `list_emails`. Data: `[{id, from, subject, snippet, date}]`. No actions (Phase A).
4. **`calendar_schedule`** — NEW. Emitted by `get_schedule`. Data: `{range, events:[{title, start, end}]}`. No actions (Phase A).

Phase B (separate, later): `email_detail`, `free_slots` pick-to-book, `appointment_list` with cancel/reschedule buttons, `event_created`.

## Backend changes (`agent/executive_agent.py`)
- Add `_send_card(card_type, data, *, actions=None, ephemeral=False, card_id=None)` → publishes `{"type":"card","card":card_type,"id":...,"ephemeral":...,"data":...,"actions":...}`. Keep `_clear_preview` semantics as `{"type":"card_dismiss","id":...}` (or keep `preview_cleared` for back-compat short-term).
- Migrate `draft_reply` → `_send_card("email_draft", {...}, actions=[send,cancel], ephemeral=True)`; `create_calendar_event` → `_send_card("calendar_event_preview", {...}, actions=[confirm,cancel], ephemeral=True)`. Preserve the existing `_pending_draft` values (WS0 depends on `_start_iso`/`_end_iso`).
- `list_emails`: after fetching, `_send_card("email_list", {emails:[...]})` and return a SHORT summary string (e.g. "Here are your 5 most recent emails."). Do NOT enumerate in text.
- `get_schedule`: `_send_card("calendar_schedule", {range, events:[...]})` + short summary.
- `data_received`: handle `{"type":"card_action", id, card, action}` → map approve/confirm → resolve like verbal "yes" (synthetic user turn or direct resolve); cancel → dismiss. (Info cards have no actions in Phase A.)
- Prompt: add "When a card is shown on screen, give a brief spoken summary — don't read items one by one."

## Frontend changes (`ai-employees-app`)
- `useExecutiveSession.ts`: parse `type:"card"` → `activeCard` state (replaces/extends `previewItem`); `card_dismiss` → clear; keep `approvePreview`/`rejectPreview` for draft/event. Add `sendCardAction(id, card, action)` publishing `{type:"card_action",...}`.
- New `src/components/executive/cards/` — `EmailDraftCard`, `CalendarEventCard` (migrate existing preview UI), `EmailListCard`, `CalendarScheduleCard`, plus an `index.tsx` **registry** (`cardType → component`) with a **text fallback** for unknown types.
- `AgentDisplay.tsx`: render the active card in the slot above the input (where the preview panel is now). Fixed default height + internal scroll. One active card at a time; leave a compact breadcrumb in `TranscriptPanel` (per design-doc decision).

## Decisions (from design doc)
- Single active card slot + transcript breadcrumb (not a multi-card canvas).
- Actions: buttons + voice share one resolve path.
- Catalog above is the Phase-1 set.

## Verification plan
- Backend `ast.parse` clean; frontend `tsc`/build clean.
- Live (after `docker compose restart sam-executive-agent` + frontend rebuild):
  - "Show my recent emails" → `email_list` card renders; Remi gives a short summary (doesn't read all aloud).
  - "What's on my calendar today?" → `calendar_schedule` card renders.
  - "Draft a reply to …" → `email_draft` card (unchanged behavior) → approve sends.
  - "Block off Friday 10am" → `calendar_event_preview` card → confirm creates (WS0 still works).
  - Unknown card type → text fallback (no crash).

## Risks / notes
- Keep `_pending_draft` intact — WS0 calendar fix reads it.
- Back-compat: migrate preview→card in both repos together, or temporarily accept both `preview` and `card` in the hook to avoid a deploy-order break.
- **Beyond the approved overview doc** — flag to Sam if it affects the 2-week estimate (real frontend work).

## Out of scope
WS4 (central avatar), Phase B cards, mood→avatar.
