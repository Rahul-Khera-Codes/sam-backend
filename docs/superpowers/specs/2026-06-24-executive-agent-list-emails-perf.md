# Spec — Executive Agent `list_emails` Performance (N+1 fix)

**Date:** 2026-06-24 · **Workstream:** WS7 · **Repo:** `sam-backend` (`agent/executive_agent.py`)

## Problem (verified in logs)
One `list_emails` call took ~11s. Inside it: 1× `messages.list`, then per message a sequential `_gmail_get_message` that BOTH re-fetches the Gmail token from the DB (`_gmail_get_valid_token` → `gmail_tokens` query) AND does `messages.get`. For 10 emails that's ~10 redundant token lookups + 10 sequential metadata fetches.

## Fix
1. Fetch the token **once** in `list_emails`; reuse it.
2. **Parallelize** the per-message `messages.get` with `asyncio.gather`.
3. Add optional `token` param to `_gmail_list_messages` + `_gmail_get_message` so callers can pass a pre-fetched token (skip the DB lookup).
4. Bonus: distinguish "Gmail not connected" (no token) from "no emails" (empty result) in the returned message — removes the earlier ambiguity.

## Out of scope
Card rendering (WS3). This only speeds up the existing text path.

## Verify
- Backend `ast.parse` clean.
- Live: "list my emails" returns in ~1–2s (was ~11s); same correct results.
- "not connected" message only when token truly missing.
