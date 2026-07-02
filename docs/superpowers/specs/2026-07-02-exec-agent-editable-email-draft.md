# Exec Agent — Editable Email Draft Card (body / recipient / subject)
**Date:** 2026-07-02
**Branch:** `feature/exec-agent-improvements` (both repos)
**Status:** Spec approved — pending implementation

---

## Request (Sam, Jul 1, items #3/#4/#5)

Add an edit section for the email body (fix a typo without asking Remi to redo it), the recipient address, and the subject — all on the `email_draft` preview card, before sending.

---

## Phase 1 — Verified

**Frontend, `AgentCardView.tsx:245-260`** — the `email_draft` card renders `d.to`, `d.subject`, `d.body` as plain read-only text. No input fields exist. The Send/Cancel buttons go through the generic `CardActions` component, which calls `onApprove`/`onReject`.

**`onApprove` (`useExecutiveSession.ts:399-402`)** just sends the plain text `"yes, go ahead"` to the model — it does **not** carry the card's current field values. The model calls `send_email_draft` from its own conversational memory of the draft.

**`onCardAction` is already fully wired** end-to-end (`ExecutiveAgent.tsx:108` → `AgentDisplay.tsx:76/158` → `AgentCardView`) for the existing `free_slots`/`appointment_list`/`email_detail` cards — no new prop plumbing needed, only a new card_action case + a new card render path.

**The exact same bug class WS0 already fixed for calendar events.** `confirm_create_calendar_event` (`executive_agent.py:790-816`) used to trust LLM-retyped tool-call arguments for the approved event, which silently dropped the timezone offset. The fix: read the exact values from `self._pending_draft` (the server-side stored preview) instead, falling back to LLM args only if no pending draft exists:
```python
draft = self._pending_draft if (self._pending_draft or {}).get("kind") == "calendar_event" else None
if draft:
    title = draft.get("title") or title
    ...
```
`send_email_draft` (`executive_agent.py:520-629`) has never had this fix — it takes `to`/`subject`/`body` purely as LLM tool-call arguments today. If we let the user edit the card, we'd hit the identical risk: the model might not retype the edited text faithfully when it calls the tool in response to a generic "yes, go ahead."

**`self._pending_draft` already stores everything needed** — `_send_preview` (`executive_agent.py:272-278`) sets `self._pending_draft = preview`, and both `draft_email`/`draft_reply`'s preview dicts already include `to`, `subject`, `body`, `emailId`, `attachmentDocName` (confirmed by reading both call sites). `assistant` (the `ExecutiveAssistant` instance) is in closure scope inside `_on_data`, alongside every other card_action handler.

---

## Phase 2 — Spec

### The design: WYSIWYG-locked send, no model retyping required

Rather than a synthetic turn that asks the model to relay possibly-long edited text (real risk of paraphrasing), mirror WS0 exactly: the **Send** button carries the current (possibly edited) field values directly in the `card_action` payload, which updates `self._pending_draft` server-side *before* the model is even asked to act. `send_email_draft` then reads from `self._pending_draft` the same way `confirm_create_calendar_event` reads calendar fields — so what's shown in the card is *exactly* what gets sent, regardless of what the model's own tool-call arguments say.

### Files changed

**`agent/executive_agent.py`:**
1. New `card_action == "send_email_draft"` case in `_on_data` (alongside `book_slot`/`cancel_appointment`/etc.): reads `to`/`subject`/`body` from the payload, updates `assistant._pending_draft` in place if it's an `email_draft` kind, then issues a simple synthetic turn ("owner confirmed sending the email draft as shown — call send_email_draft now"). Guards on `to`/`subject` present, same pattern as `book_slot`'s date/start guard.
2. `send_email_draft` (the tool): add the same "prefer pending draft" block WS0 uses, right after the docstring:
   ```python
   draft = self._pending_draft if (self._pending_draft or {}).get("kind") == "email_draft" else None
   if draft:
       to = draft.get("to") or to
       subject = draft.get("subject") or subject
       body = draft.get("body") or body
       email_id = draft.get("emailId") or email_id
       attachment_doc_name = draft.get("attachmentDocName") or attachment_doc_name
   ```
   Falls back to LLM args if there's no matching pending draft (same safety net WS0 has). Everything downstream (attachment resolution, MIME building, `clean_body` stripping) is unchanged.

**`ai-employees-app/src/components/executive/AgentCardView.tsx`:**
- Extract the `email_draft` block into its own small component (matching the existing `AppointmentListCard` pattern, which already holds local `useState` inside this file).
- `to`/`subject` become simple `<input>` elements, `body` becomes a `<textarea>` — all initialized from `d.to`/`d.subject`/`d.body`, local component state.
- **Send button** calls `onCardAction("send_email_draft", { to, subject, body, emailId: d.emailId, attachmentDocName: d.attachmentDocName })` with the current (edited-or-not) field values — replaces the generic `CardActions`/`onApprove` wiring for this card only.
- **Cancel button** stays wired to `onReject()` — unchanged.

### Not changed
- `draft_email`/`draft_reply` — unaffected, they still build the initial preview the same way.
- The attachment-note stripping (`clean_body = body.split(...)[0]`) in `send_email_draft` — unchanged, still strips the "📎 Attachment:" display line before the real send regardless of edits.
- `calendar_event_preview` card — out of scope, Sam's request was specifically about email.

### Impact
Fixes a typo-in-the-body / wrong-recipient / wrong-subject scenario without a full re-dictation round trip through Remi. Closes the same WYSIWYG gap WS0 already closed for calendar events — send now always matches exactly what's on screen.

### Risk
None identified — mirrors an already-shipped, already-verified pattern (WS0) applied to a second tool.

---

## Commit Plan

| # | Commit | Files |
|---|---|---|
| 1 | `fix(exec-agent): send_email_draft reads to/subject/body from the pending preview, not LLM args` | `executive_agent.py` (tool + `send_email_draft` card_action case) |
| 2 | `feat(exec-agent): editable email draft card — recipient, subject, body` | `AgentCardView.tsx` |
