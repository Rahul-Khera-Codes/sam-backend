# Exec Agent — Attach Document to Email (Bug Fix)
**Date:** 2026-07-01
**Branch:** `feature/exec-agent-improvements`
**Status:** Spec approved — pending implementation

---

## Bug Report (Sam, Jun 25–30)
`send_email_draft` sends plain text only. When Remi tried to attach a document, the body showed `[…inserted here]` as a placeholder — the PDF was never actually attached.

---

## Phase 1 — Root Cause (Verified)

**Two gaps in `executive_agent.py`:**

1. **Document library never loaded at startup.** No `self._documents`, no `self._doc_by_name`. The CS agent loads these in `__init__` via `_fetch_documents_for_location` (`supabase_helpers.py:667`) but exec agent does not import or call it.

2. **`send_email_draft` (L474) has no attachment support.** Only builds `MIMEMultipart("alternative")` + `MIMEText(body, "plain")`. No `MIMEBase`, no signed URL fetch, no PDF bytes. Remi was hallucinating a placeholder in the email body because no tool existed to actually attach a file.

**What's already available (no new infra):**
- `_fetch_documents_for_location` — `supabase_helpers.py:667`, fully working
- `_httpx`, `GMAIL_SEND_URL`, `_gmail_get_valid_token` — already imported in exec agent
- `self._supabase`, `self._business_id`, `self._location_id`, `self._business_name` — all present

---

## Phase 2 — Spec

### Files changed
Only `agent/executive_agent.py` — no frontend changes needed. The existing `EmailDraftCard` renders `data.body`; attachment info is appended to the body text so the user sees it in the preview before approving.

### Change 1 — Import + startup (`__init__`)
- Add `_fetch_documents_for_location` to the `supabase_helpers` import line (L29)
- In `__init__` after `self._card_seq = 0` (L240): load `self._documents` and `self._doc_by_name`

### Change 2 — `list_documents()` tool (new)
- Returns list of document names available to attach
- Allows Remi to answer "what documents can I attach?" without hallucinating

### Change 3 — `draft_email` + `draft_reply`
- Add `attachment_doc_name: str = ""` optional param to both
- When set: validate doc exists in `_doc_by_name`; include `attachmentDocName` in `preview` dict; append `\n\n📎 Attachment: {doc_name}` to confirmation message so it's visible in the card preview

### Change 4 — `send_email_draft`
- Add `attachment_doc_name: str = ""` optional param
- If set: look up in `_doc_by_name` → generate signed URL → download bytes → build `MIMEMultipart("mixed")` + `MIMEText` body + `MIMEBase` PDF attachment
- If not set: existing flow unchanged (`MIMEMultipart("alternative")` + plain text)
- Pattern ported exactly from `agent.py:780–816`

---

## Commit Plan

| # | Commit | Files |
|---|---|---|
| 1 | `feat(exec-agent): load document library at startup + add list_documents tool` | `executive_agent.py` (import + __init__ + new tool) |
| 2 | `feat(exec-agent): support PDF attachment in draft and send flow` | `executive_agent.py` (draft_email + draft_reply + send_email_draft) |
