# Exec Agent — Document Library Live Refresh (Bug Fix)
**Date:** 2026-07-01
**Branch:** `feature/exec-agent-improvements`
**Status:** Spec approved — pending implementation

---

## Bug Report (Rahul, live test 2026-07-01, 05:02–05:05 PM)

Asked Remi to email a business information document. Remi said "there aren't any business documents available to attach" — even after adding a document to the business's document library **during the same live session** and asking Remi to "try again."

Two things reported:
1. No document existed in the business library when the session started (confirmed — the first "no documents" response was correct).
2. A document added mid-call was still invisible to the agent on "try again" — raising the question of whether the doc library is loaded once per session (static) or checked live per request (dynamic).

---

## Phase 1 — Root Cause (Verified)

**Confirmed: the document library is a one-time snapshot taken at session start, not a live query.**

`agent/executive_agent.py:243-245` (added in the `2026-07-01-exec-agent-attach-doc-email` fix, same session):
```python
self._documents = _fetch_documents_for_location(supabase, business_id, location_id) if supabase else []
self._doc_by_name = {d["name"].lower(): d for d in self._documents if d.get("name")}
```
This runs exactly once, inside `ExecutiveAssistant.__init__()`, when the LiveKit job starts. `list_documents` (L419-423) and every attachment lookup in `draft_email`/`draft_reply`/`send_email_draft` (L452, 493, 547) read from that same in-memory dict. There is no re-fetch anywhere in the file — "try again" re-runs the tool against the same stale snapshot, so it can never see a document added after the session started.

**Ruled out:** `location_id` ordering. `location_id` is resolved from participant/job metadata (L1002-1027) before `ExecutiveAssistant(...)` is instantiated (L1057) — so the fetch at `__init__` does use the correct location, it's just a one-time fetch.

**Confirmed inconsistency:** every other data-reading tool in the file queries live on every call — `list_emails` (Gmail API), `get_schedule` (Google Calendar), `list_appointments` (Supabase). The document library is the only tool whose data is cached at startup, and only because it was added that way in the attach-doc fix earlier this session.

---

## Phase 2 — Spec

### Files changed
Only `agent/executive_agent.py`. No frontend, no schema, no other file.

### Change — remove the `__init__`-time cache, fetch live per call
- **`__init__` (L243-245):** delete `self._documents` / `self._doc_by_name`. Keep `self._business_id` / `self._location_id` / `self._supabase`, which the live fetch needs.
- **`list_documents` (L419):** call `_fetch_documents_for_location(self._supabase, self._business_id, self._location_id)` directly, build the name list from the fresh result.
- **`draft_email` (L485), `draft_reply` (L430), `send_email_draft` (L520):** each currently does `self._doc_by_name.get(attachment_doc_name.lower())`. Replace with a live fetch + inline dict build at the top of each function when `attachment_doc_name` is set, then do the same lookup (exact match, `send_email_draft`'s fuzzy substring fallback stays as-is) against the fresh dict.

### Impact
One extra Supabase query per call to `list_documents`/`draft_email`/`draft_reply`/`send_email_draft` when an attachment is involved — same overhead class as the Gmail token lookup `list_emails` already pays every call. No behavior change for the no-attachment path. A document added mid-session becomes visible on the very next tool call, no new session required.

### Risk
None identified. This makes the doc-library tool consistent with the rest of the codebase's "always query live" pattern rather than introducing new behavior.

---

## Commit Plan

| # | Commit | Files |
|---|---|---|
| 1 | `fix(exec-agent): fetch document library live per call instead of caching at session start` | `executive_agent.py` (`__init__`, `list_documents`, `draft_email`, `draft_reply`, `send_email_draft`) |
