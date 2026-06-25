# Spec — Executive Agent: restore email IDs to model + quiet DEBUG logs

**Date:** 2026-06-25 · **Workstream:** WS9 (bug) · **Repo:** `sam-backend` (`agent/executive_agent.py`)

## Bug 1 — model loses email IDs (regression from WS3 A.1)
`list_emails` sends the id/subject/from to the **card** but returns only
`"Showing your N most recent emails on screen."` to the model. So a follow-up like
"open the one about 20" has no real IDs in context → the model **hallucinates** IDs
(`appointment20`, `20prunf8`, `20`) → `read_email`/`draft_reply` → "Could not fetch email" → loops.
Logs even show a bad `function_call_output` tripping `InvalidStateError` in the OpenAI plugin.

**Fix:** keep the card, but ALSO return a compact `id | subject — from` list to the model.
The prompt already says to speak only a brief summary, so the model won't read it all aloud —
it just needs the IDs in context to resolve references. Same idea applies to follow-up actions.

## Bug 2 — logs unreadable (hpack/httpx DEBUG firehose)
Dev mode runs the root logger at DEBUG, so `hpack.hpack`/`hpack.table`/`httpx` emit hundreds
of lines per request. Raise those third-party loggers to WARNING at import (does not touch our
own `executive-agent` logger or livekit.agents).

## Out of scope (observed, not fixed here)
- `conversation_already_has_active_response` + "speech not done in time … cancelling": voice
  barge-in/thrash; should drop sharply once Bug 1 stops the failure loop. Re-observe after.
- Transcript language drift ("どうぞ", "Nu plaibom") — these are **user** bubbles = realtime
  input STT mis-hearing English audio, not Remi's output. Audio/STT quality, not a code fix.

## Verify
- `ast.parse` clean. Live: "list emails" → card shows + Remi brief; "open the one about X" →
  reads the RIGHT email (no hallucinated ID). Logs no longer flooded with hpack lines.
