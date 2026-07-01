# Executive Agent — Rich Card UI Design

**Date:** 2026-06-24 (session 52)
**Repo:** `sam-backend` (`agent/executive_agent.py`) + `ai-employees-app` (frontend)
**Status:** Design — not yet built. Builds on the existing preview/data-channel mechanism.
**Scope note:** This is **beyond the approved overview doc** (`docs/executive-agent-overview.md` has no rich-cards concept — it describes text/preview interactions). Treat as a net-new addition: either internal quality polish or a scope item to flag to Sam (it's real extra frontend work and may affect the 2-week estimate).

---

## Goal

For structured results (emails, calendar, appointments), render purpose-built **cards** in the frontend instead of plain conversational text. The agent emits a typed card payload over the LiveKit data channel; the frontend renders the matching component. Cards appear in the main column above the input bar, with a fixed default height (scroll/expand inside). Voice/text stays the conversation; cards carry the structured detail.

Use cards **only where structured data benefits from it** — keep plain text for confirmations, errors, simple answers, and chit-chat.

---

## Core Principles

### 1. Cards are emitted by TOOLS, not by the model's text
When a tool runs (`list_emails`, `get_schedule`, `list_appointments`, …), the **tool itself** publishes the card with real, server-side data, and returns a **short summary string** for the agent to speak/type. The model never hand-writes card JSON (avoids hallucinated fields + flakiness). This mirrors the existing `_send_preview()` pattern.

### 2. Reuse/generalize the existing preview channel
Today: `_send_preview(preview)` → `_publish(room, {"type":"preview", **preview})` → frontend preview panel; `_clear_preview()` → `{"type":"preview_cleared"}`. Generalize this into a typed **card** envelope (preview becomes one card kind among several).

### 3. Voice + card are complementary, never redundant
Prompt rule: when a card is shown, speak a **short** summary ("Here are your 5 latest emails") — do **not** enumerate aloud. The spoken summary must stand alone for a listening-only user.

### 4. Card actions round-trip through the agent
State-changing buttons (Send, Confirm, Reschedule, Cancel) send a structured message back over the data channel that resolves exactly like the verbal "yes" — keeping the agent's conversational state coherent. Pure-navigation actions (expand/collapse, scroll) are frontend-only.

---

## Data-Channel Contract

### Agent → Frontend: render a card
```jsonc
{
  "type": "card",
  "card": "email_list",        // card type (see catalog)
  "id": "card_<uuid8>",        // unique; used to target actions/updates
  "ephemeral": true,            // true = replace/dismiss on resolve; false = persists
  "data": { /* card-type-specific payload */ },
  "actions": [                  // optional buttons
    { "id": "send",   "label": "Send",   "style": "primary" },
    { "id": "cancel", "label": "Cancel", "style": "ghost"   }
  ]
}
```

### Agent → Frontend: dismiss / update
```jsonc
{ "type": "card_dismiss", "id": "card_xxx" }
{ "type": "card_update",  "id": "card_xxx", "data": { /* partial */ } }
```
(`card_dismiss` replaces the current `preview_cleared`.)

### Frontend → Agent: action clicked
```jsonc
{ "type": "card_action", "id": "card_xxx", "card": "email_draft", "action": "send" }
```
Handled in the agent's `data_received` handler: map `card_action` → resolve the pending tool (e.g. send the stored draft) **or** inject a synthetic user turn ("send it") so the LLM stays in the loop. Recommendation: synthetic turn for approve/reject; direct resolve for deterministic confirms.

### Frontend → Agent: text input (already exists)
```jsonc
{ "type": "user_text", "text": "…" }
```

---

## Card Catalog (start small)

| Card | Emitted by | Data | Actions | Ephemeral |
|---|---|---|---|---|
| `email_list` | `list_emails` | `[{id, from, subject, snippet, date, unread}]` | open(id) | no |
| `email_detail` | `read_email` | `{from, subject, date, body}` | reply, close | no |
| `email_draft` | `draft_reply` | `{to, subject, body}` | send, edit, cancel | yes |
| `calendar_schedule` | `get_schedule` | `{range, events:[{title, start, end, attendees}]}` | — | no |
| `free_slots` | `find_free_slots` | `{date, duration, slots:[{start,end}]}` | pick(slot) | yes |
| `calendar_event_preview` | `create_calendar_event` | `{title, date, time, duration, description}` | confirm, edit, cancel | yes |
| `event_created` | `confirm_create_calendar_event` | `{title, date, time}` | — | no (brief) |
| `appointment_list` | `list_appointments` | `[{ref, date, time, client, service, status}]` | cancel(ref), reschedule(ref) | no |

`email_draft` and `calendar_event_preview` already exist as `preview` kinds — migrate them into this envelope first.

---

## Frontend Architecture

- **Card registry**: `cardType → React component`, with a **text fallback** for unknown types (forward-compatible).
- **Render slot**: main (left) column, stacked above `InputBar`. Fixed default height (e.g. `max-h-72`) with internal scroll; expand toggle for taller content.
- **Ephemeral vs persistent**:
  - *Ephemeral* (draft, event preview, free slots): one active at a time; dismissed on resolve.
  - *Persistent* (lists, schedule, detail): remain as the latest result; leave a compact trace in the `TranscriptPanel` ("📧 Showed 5 emails") so history stays coherent.
- **Actions**: buttons dispatch `card_action` over the data channel via the existing `useExecutiveSession` send path.

Touch points: `useExecutiveSession.ts` (parse `card`/`card_dismiss`/`card_update`, send `card_action`), new `components/executive/cards/*`, `AgentDisplay.tsx` (render slot + registry).

---

## Voice / Card Discipline (prompt additions)
- "When a tool shows a card on screen, give a brief spoken summary — do not read the items one by one."
- "Refer to the card naturally ('I've put your schedule on screen')."
- "For drafts and new events, the card shows a preview with buttons; the owner can click or just say 'send it' / 'go ahead'."

---

## Phasing (protect the 2-week estimate)

**Phase A (high value, partly exists):**
- Generalize preview → card envelope (`type:"card"`, `card_action`, `card_dismiss`).
- `email_draft` card (migrate existing preview) + `calendar_event_preview` card.
- `email_list` + `calendar_schedule` cards.
- Card registry + text fallback + render slot + action round-trip.

**Phase B (after first usable pass):**
- `email_detail`, `free_slots` (pick-to-book), `appointment_list` (cancel/reschedule buttons), `event_created`.

**Note:** This is real added frontend work (components + registry + action loop). If the full catalog is wanted inside Phase 1, flag the extra time to Sam rather than absorbing it silently. Recommend Phase A first.

---

## Decisions (made 2026-06-24)
1. **Persistence:** single active card slot (latest result shown) + a compact breadcrumb in the `TranscriptPanel` ("📧 Showed 5 emails") so older results are recoverable. NOT a full multi-card scrolling canvas in Phase 1. Info cards persist until replaced; action cards dismiss on resolve.
2. **Actions:** support BOTH buttons and voice, sharing one resolve path (`card_action` ≡ verbal "yes"). Buttons for screen users, voice for hands-free.
3. **Catalog:** the 8 cards above are the Phase-1 set — no additions. Future (P2+): client/contact card (pairs with not-yet-built client-history tool), task/reminder card.

## Still for Sam (optional, since cards are beyond the approved doc)
- Whether to treat rich cards as internal polish or formal scope (and timeline impact).

---

## Related
- `docs/executive-agent-personality-and-flows.md` — personality/emotion plan + test flows
- `docs/executive-agent-overview.md` — Sam-facing Phase 1/2 scope
- `agent/executive_agent.py` — `_send_preview`/`_clear_preview`/`_publish`/`_set_state` + tools
