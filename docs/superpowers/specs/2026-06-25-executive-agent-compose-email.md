# Spec — Executive Agent: compose & send a NEW email

**Date:** 2026-06-25 · **Workstream:** WS8 (bug) · **Repo:** `sam-backend` (`agent/executive_agent.py`)

## Bug (verified in logs)
Asking Remi to send a brand-new email fails:
```
tried to call AI function `send_email_draft` with invalid arguments
1 validation error for SendEmailDraftArgs: email_id — Field required
input: {'to': '…', 'subject': 'Follow-up', 'body': '…'}
```
- `send_email_draft(email_id, to, subject, body)` makes **`email_id` required**, but a new email has none. Validation fails before the function runs (the body already treats `email_id` as optional via `if email_id:` for threading).
- There's **no preview tool for a new email** — `draft_reply` requires an existing `email_id`. So "send a new email from scratch" has no valid path; the agent loops with "still running into an error."

(Gmail token/refresh is healthy now — separate, resolved issue.)

## Fix
1. **`send_email_draft`:** make `email_id` optional — reorder to `(to, subject, body, email_id: str = "")`. Body unchanged (already guards `if email_id:`).
2. **Add `draft_email(to, subject, body)`** tool: previews a brand-new email (`emailId=""`) via `_send_preview` → owner approves → `send_email_draft`. Mirrors `draft_reply`'s approve-then-send flow.

## Out of scope
gmail.compose / saving to Gmail Drafts folder (would need a restricted scope). This sends directly via `gmail.send` after on-screen approval, same as replies.

## Verify
- Backend `ast.parse` clean.
- Live: "draft an email to X saying …" → preview card → "yes, go ahead" → sends (no ValidationError). Reply flow still works.
