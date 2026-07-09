# Exec Agent — Document Freshness Prompt Fix
**Date:** 2026-07-01
**Branch:** `feature/exec-agent-improvements`
**Status:** Spec approved — pending implementation

---

## Bug Report (Rahul, live re-test after the live-refresh fix, 2026-07-01)

Reproduction, same session:
1. Asked Remi to send a document — none existed yet. `list_documents` correctly ran and returned "no documents available."
2. Added a new document to the business library mid-call.
3. Asked Remi to send that new document. **Remi said it didn't have that document** — without calling the tool again.
4. Told Remi to "search for it again." Remi then called the tool, got the fresh list (including the new doc), and successfully attached + sent it.

The live-refresh fix (`c615ba2`, this session) is confirmed working — the tool returns fresh data every time it actually runs. Step 3 is the remaining gap: the model didn't re-run the tool on its own.

---

## Phase 1 — Root Cause (Verified)

Checked `EXECUTIVE_INSTRUCTIONS` (`executive_agent.py:184-214`) and the docstrings on `list_documents`, `draft_email`, `draft_reply`, `send_email_draft`. **Nothing in the prompt or any docstring says document state can change during a conversation.**

This is standard LLM tool-use behavior, not a code defect: once `list_documents` returns "no documents" earlier in the transcript, that result is now conversation history. On a later, similarly-worded request the model treats it as an already-answered fact and responds from that prior turn instead of re-invoking the tool — it only re-calls when explicitly told to check again, because that's an unambiguous instruction to act rather than recall.

---

## Phase 2 — Spec

### File changed
Only `agent/executive_agent.py` — the `EXECUTIVE_INSTRUCTIONS` prompt string.

### Change
Add one line under "How to behave" (after the existing tool-use rules, before the Security section):

> Documents in the library can change at any time — the owner may add one mid-conversation. Always call `list_documents` (or resolve an attachment) fresh before saying none are available or telling the owner what's there; never rely on an earlier `list_documents` result from earlier in this same conversation.

### Impact
Prompt-only change. No tool code touched — the tools already fetch live (`c615ba2`). No other file affected.

### Risk
None identified. Slightly increases tool-call frequency for document-related follow-ups (one extra `list_documents` call per re-ask), same cost class as any other tool call.

---

## Commit Plan

| # | Commit | Files |
|---|---|---|
| 1 | `fix(exec-agent): instruct Remi to always re-check documents fresh, never from memory` | `executive_agent.py` (`EXECUTIVE_INSTRUCTIONS`) |
