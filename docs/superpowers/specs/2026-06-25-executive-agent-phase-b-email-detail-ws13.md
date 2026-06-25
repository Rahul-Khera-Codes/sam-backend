# Spec — Executive Agent WS13 (Phase B slice 3): email_detail card

**Date:** 2026-06-25 · **Workstream:** WS13 (WS3 Phase B, slice 3 — completes Phase B) · **Repos:** `sam-backend` + `ai-employees-app`

## Verified current state
- `read_email(email_id)` returns the email fenced as untrusted data (`<<<UNTRUSTED EMAIL…>>>`). No card.
- `draft_reply(email_id, reply_body, …)` exists. `card_action` round-trip (WS11) + `sendCardAction` threaded to `AgentCardView` (WS12).

## Build — backend (`agent/executive_agent.py`)
- `read_email`: additionally emit an `email_detail` card `{emailId, from, subject, date, body}`. **Keep returning the fenced untrusted text to the model** (it needs the body to summarise/answer questions). Card is for display only.
- `_on_data`: add `reply_email {emailId}` → conversational synthetic turn: *"The owner wants to reply to the email with id {emailId}. Ask them what they'd like to say, then draft the reply with draft_reply for that email."* → model asks → owner answers → `draft_reply` → existing email_draft preview → approve → send.

## Build — frontend (`ai-employees-app`)
- Hook: add `EmailDetailCard` to the union: `{type:"card", card:"email_detail", id, data:{emailId,from,subject,date,body}}`.
- `AgentCardView`: render `email_detail` — header (from / subject / date), scrollable body (`whitespace-pre-wrap`, `max-h` + overflow), and a **Reply** button → `onCardAction("reply_email", {emailId})`.
- Body is rendered as text content (React auto-escapes) → no XSS from attacker-controlled email HTML/script.

## Safety
- Reply is non-destructive at tap time (just starts a draft conversation); the actual send still goes through the email_draft preview→approve gate.
- Body stays fenced in the model context (injection defence unchanged); the card only renders it visually.

## Out of scope
Rich HTML rendering of the email body (plain text only); attachments.

## Verify
- Backend `ast.parse` clean; frontend `tsc --noEmit` clean.
- Live: "open the email about X" → email_detail card (from/subject/date + scrollable body); tap Reply → Remi asks what to say → provide it → draft preview → approve → sent. Model can still answer "what does it say?" from the body. No layout/scroll issues with a long body.
