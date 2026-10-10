# Business Gmail Integration (send-as-business email)

## What it does
Lets a business connect a Gmail account under **Settings → Business Settings → Integrations**
so the platform can send email *as that business* — booking confirmations, reschedule/cancellation
notices, staff new-booking notifications, PDF documents sent during calls, report-scheduler
digests, and anything Remi (the Executive Agent) sends on request (ad-hoc "send an email" /
bulk customer email).

This is distinct from two other Google-ish things that live nearby and are unrelated:
- **Profile Settings → Connected Accounts → Gmail** — personal sign-in identity linking
  (`supabase.auth.linkIdentity`). See `docs/features/profile-gmail-signin.md`.
- **Profile Settings → My Google Calendar** — per-staff calendar sync, separate OAuth token/table.

## Key files
- **Frontend:** `ai-employees-app/src/components/business/IntegrationsTab.tsx` — the single
  "Connect Gmail" / "Connected" / "Disconnect" toggle. No per-location or per-user selector exists
  here; it never sends a `location_id` on connect.
- **Backend OAuth routes:** `backend/app/routers/gmail_integrations.py` — `/integrations/gmail/auth-url`,
  `/callback`, `/status`, `/disconnect`.
- **Backend shared token helpers:** `backend/app/services/email_service.py` — `get_token_row`,
  `get_valid_access_token`, plus the actual MIME-building/send functions used by booking-flow emails
  (`send_appointment_confirmation_email`, `send_staff_notification`, etc.).
- **Agent (Remi) token helpers + sends:** `agent/gmail_helpers.py` — `_gmail_get_valid_token`,
  `_gmail_connection_diagnostic`, `_gmail_send_confirmation`/`_staff_notification`/
  `_reschedule_confirmation`/`_cancellation_confirmation`/`_document_notification`. Remi's live
  "send email" and bulk-customer-email tools call `_gmail_get_valid_token` directly from
  `agent/executive_agent.py`.
- **Report digests:** `backend/app/routers/report_scheduler.py` has its own independent
  `_get_business_gmail_token_row`/`_get_business_gmail_access_token` — already business-wide
  (picks a NULL-location row, else the first location-scoped one), predating this fix, left as-is.
- **Schema:** `ai-employees-app/supabase/migrations/20260325000000_gmail_tokens.sql` (original table,
  `20260411000001_location_scope_gmail_tokens.sql` (added `location_id`).

## Table: `gmail_tokens`
`id, business_id, location_id (nullable, FK → locations), google_email, access_token (encrypted),
refresh_token (encrypted), token_expiry, created_at, updated_at`. No `user_id` column.

Two partial unique indexes allow a business to have one row per `location_id`, plus one legacy
row where `location_id IS NULL`.

## History — how this table's model changed
1. **2026-03-25** — created as explicitly **business-level**: *"one sending Gmail account per
   business"*, unique on `business_id` alone.
2. **2026-04-11** — added `location_id` *"so each location can have its own sender Gmail"* — a real
   planned feature (different physical locations sending as different inboxes). Backfilled every
   business's existing single connection onto that business's **oldest location** (by
   `created_at`). **No settings UI to manage per-location connections was ever built** — the
   frontend toggle stayed single/business-wide. This silently reassigned every existing connection
   from "works everywhere" to "works only at whichever location happened to be created first," with
   no warning and no way to manage it.
3. **2026-10** — **AIE-90 / AIE-99**: Remi (and Settings) reported "Gmail isn't connected" even
   though a connection existed, for any business whose connection predated/survived the April
   backfill under a location that didn't match the current session. Root cause confirmed via live
   production data: e.g. one business had 3 `gmail_tokens` rows, **all the same `google_email`**,
   just saved under different `location_id` values from different reconnect attempts over time —
   i.e. real usage has always been "one inbox per business," never genuinely per-location.
4. **2026-10-07 fix (this doc)** — lookup logic reverted to the original business-wide model,
   described below. `location_id` is now effectively vestigial for *lookup* purposes (the column,
   FK, and partial unique indexes still exist; connect/disconnect still accept a `location_id` param
   for compatibility, but nothing reads tokens by location anymore).

## Current lookup logic (as of the 2026-10-07 fix)
All three lookup implementations (`agent/gmail_helpers.py::_gmail_get_valid_token`,
`backend/app/services/email_service.py::get_token_row`/`get_valid_access_token`,
`backend/app/routers/gmail_integrations.py::_get_business_token_row`) now:
1. Fetch **every** `gmail_tokens` row for the `business_id`, ignoring `location_id` entirely
   (it's accepted as a parameter purely for call-site compatibility — no caller needed to change).
2. Try rows **newest-first** (`created_at desc`).
3. For each row: use it directly if not expired; if expired, attempt a refresh; if the refresh
   fails (dead/revoked token), **skip to the next row** instead of giving up.
4. Return the first row that actually works. Only if *none* work does sending fail.

This fixes two distinct problems that existed before:
- **Location shadowing (AIE-90):** previously, an exact-location match (even a dead one) was tried
  first and, if found, the NULL/business-wide fallback was never even attempted. A stale row under
  the "wrong" location could permanently block a working newer one.
- **No skip-on-dead-token:** previously, if the one row the lookup found had a dead refresh token,
  the function simply failed — it never tried any other row for the business.

`agent/gmail_helpers.py::_gmail_connection_diagnostic` was simplified to match: it no longer
reasons about "connected for a different location" (misleading once location is ignored). It now
only distinguishes "nothing connected yet" vs. "was connected, but nothing currently works
(expired/revoked) — reconnect it."

### Explicit scope decisions made during this fix
- **Disconnect stays scoped to the location_id it's called with** (does *not* delete all of a
  business's rows) — a deliberate, conservative choice; orphaned duplicate rows from repeated
  reconnects can still accumulate over time. Not a functional problem today (the newest-first +
  skip-invalid logic handles coexistence fine), but worth revisiting if the table grows noisy.
- **Per-user Gmail (each staff member connecting their own inbox) was considered and deferred.**
  Remi's session already carries a `self._user_id` distinct from business/location (see
  `backend/app/routers/executive.py` `ExecutiveSessionRequest` → agent metadata), and the OAuth
  callback already knows the connecting user (`initiating_user_id`) but discards it — no `user_id`
  column exists on `gmail_tokens`. Live data check (2026-10-07) found **zero businesses** with more
  than one distinct `google_email` connected — no evidence of real multi-user Gmail use today, and
  most sends (confirmations, reschedule/cancel, staff/document notifications, digests) fire from
  background jobs with no logged-in user in context at all, so only Remi's live send/bulk-email
  tools could ever key off a personal connection. Treated as a separate future feature, not folded
  into this bugfix. If revisited: add `user_id`, store it on connect, prefer the current user's own
  token, **fall back to the business's shared connection** if the user hasn't personally connected
  one (confirmed preference — not a hard per-user requirement).

## Verification (2026-10-07)
- All three lookup functions unit-verified end-to-end against disposable test rows on a scratch
  business (`will_test`, no real customer data touched, rows deleted after): confirmed (a) a
  business-wide row is found regardless of the session's `location_id`, (b) the newest row is
  preferred, (c) a dead newest row is skipped in favor of an older still-valid one (real Google
  token-refresh calls made against dummy tokens, correctly rejected with `invalid_grant`), (d) the
  diagnostic message no longer mentions location once nothing resolves.
- Docker rebuilt (`docker compose down && up --build -d`), both `sam-backend` and
  `sam-executive-agent` containers start clean with no errors.
- **Live real-send test (2026-10-07):** every `gmail_tokens` row in the system was dead at the time
  (Testing-mode expiry / client mismatch — see below), so the dev reconnected Gmail on the `Woyce
  Tech` test business (`rahul.excel2011@gmail.com`) to get one genuinely live token. Then, using the
  real `_gmail_get_valid_token` with a session `location_id` matching neither of that business's two
  saved rows (the exact AIE-90 scenario), a self-addressed email was sent via the real Gmail API —
  `200` response, real message ID, landed in `SENT`+`INBOX`. This confirmed the fix end-to-end
  through actual Google infrastructure, not just DB-level logic.
- **Live product test (2026-10-07), through Remi's own chat UI** (not a script): asked Remi, in a
  normal conversation, to send an email to `rahul.excel2011@gmail.com`. Remi drafted it, the draft
  was approved, and Remi confirmed "The email has been sent" — delivery confirmed. This is the same
  fixed lookup exercised through the full real user-facing flow (chat → draft → approve → send),
  giving end-to-end confidence beyond the direct API test above.

## Second fix (2026-10-07, later same day) — a "valid" token still got rejected by Gmail

After the first fix shipped, a live Remi session failed to send with `Gmail send failed 401:
invalid authentication credentials` — on a token whose stored `token_expiry` said it still had
~51 minutes left, and which `tokeninfo` had independently confirmed valid shortly before. So the
lookup fix (which trusts stored expiry to decide whether to refresh) was correct, but stored
expiry turned out to not be sufficient ground truth — something external had invalidated the
token despite our bookkeeping saying it was fine.

**Resolved root cause:** the user had connected Gmail on **local** that morning, then later also
ran the full Connect flow on **production** for the same business while local's connection was
still active. Both environments share the same `gmail_tokens` row — two independent full OAuth
consent grants for the same Google account in quick succession from different environments is
enough for Google to invalidate the earlier-issued token. Not a config bug, not a code bug — a
real hazard of local dev and production sharing one Supabase project's OAuth token tables.
Reconnecting once more (after disconnecting first) issued a fresh, self-consistent token that
verified immediately (`tokeninfo` 200 + a real send, message landed in `SENT`+`INBOX`).

**Defensive fix added regardless** (since stored expiry can never be a perfect guarantee — clock
drift, external revocation, or this exact cross-environment case can all produce a "should be
valid" token Gmail rejects live): every Gmail **send** call site — the 7 automated functions in
`agent/gmail_helpers.py` (now consolidated through one shared `_gmail_send_raw` helper instead of
7 duplicated inline POSTs), both of `agent/executive_agent.py`'s interactive send paths, and
`backend/app/services/email_service.py`'s `send_email`/`send_email_with_attachment` (plus their 6
wrapper functions and the `report_scheduler.py` caller) — now react to a live 401 by forcing every
token row for that business to be treated as expired, re-resolving a fresh one via the existing
business-wide/skip-invalid lookup, and retrying the send exactly once before giving up. Verified
by deliberately feeding a bogus access token into `_gmail_send_raw` and confirming it correctly
attempted a real refresh (rejected as expected, since the underlying refresh token was also dead
at that moment) rather than silently failing — then, after the fresh reconnect, confirmed a real
send succeeds end-to-end through the same code path.

**Operational note for future sessions:** avoid connecting/reconnecting Gmail (or Outlook/Calendar)
on both local and production for the same business around the same time — it can invalidate
whichever one was connected first, surfacing as a confusing "token looked valid but Gmail
rejected it" failure rather than a clear error.

## Known remaining issue — NOT fixed by this change (as of 2026-10-07)
The Google Cloud OAuth consent screen for this app is still in **Testing** publishing status
(unverified — `gmail.readonly` is a restricted scope requiring a CASA assessment, in progress; see
`docs/casa/CASA_REQUIREMENTS_LOG.md` and `docs/GOOGLE_OAUTH_VERIFICATION.md`). Google expires
**every** refresh token issued by a Testing-status app after exactly 7 days, regardless of use.
This means connections will keep silently dying roughly weekly **for every business**, independent
of the lookup fix above, until the app is moved to "In Production" in Google Cloud Console (removes
the 7-day cap immediately; sensitive scopes remain capped at 100 cumulative unverified users until
full verification completes — current usage is well under that). Tracked in AIE-90 comments,
assigned to Sam via Google Cloud Console access.

**Update 2026-10-07:** Sam confirmed the consent screen is already "In Production" — this was not
(or no longer) the blocker. See the next section for what actually was.

## Fourth root cause (2026-10-10) — redirect_uri still pointed at localhost

After the Testing/Production toggle was confirmed already correct, Sam/Charles still reported
disconnect+reconnect failing on the real deployed app ("tried 2 different accounts, both did not
work"). Every fix up to this point (location-wide lookup, skip-dead-tokens, 401-retry) was real and
had been verified — but verification was done by the developer testing from his own local machine,
which masked this.

**Root cause:** `GOOGLE_REDIRECT_URI` and `GMAIL_REDIRECT_URI` in `backend/.env` were still set to
`http://localhost:8080/...` — a dev placeholder never switched to production, unlike every sibling
integration in the same file (`OUTLOOK_REDIRECT_URI`, `MARKETING_*_REDIRECT_URI_PRODUCTION`), which
correctly point at `https://portal.aiemployeesinc.com/...`. Confirmed the Google Client ID/Secret
pair itself is valid (probed `oauth2.googleapis.com/token` directly — got `invalid_grant` for a bad
code, not `invalid_client`/`unauthorized_client`, meaning client auth passes). The redirect alone was
wrong: any real user outside the developer's own laptop would have their browser sent to
`localhost:8080` after granting consent, which does nothing on their machine (or Google rejects the
request outright if that URL isn't a registered redirect URI for the client at all).

**Fix:** both values changed to `https://portal.aiemployeesinc.com/integrations/google/callback` and
`.../integrations/gmail/callback`, matching the already-working Outlook pattern exactly. **This is an
env-only change — no application code was touched.** `backend/.env` is gitignored, so this does not
ship via git; it must be corrected by hand in every environment's own `.env` (confirmed done in local
dev as of this writing; production's `backend/.env` still needs the same two lines updated manually
during the next deploy).

**Still required before this is confirmed fixed:** `https://portal.aiemployeesinc.com/integrations/gmail/callback`
and the `/google/callback` equivalent must be present in **Google Cloud Console → Credentials → [this
OAuth client] → Authorized redirect URIs** — if they aren't already there (Outlook's equivalent URI
works today, so this is likely just adding the two missing Google/Gmail entries alongside it), Google
will reject with `redirect_uri_mismatch` even after the env fix. Needs an actual disconnect/reconnect
test against the real production app after both the env var and Console changes are in place — not
just a clean container start — before moving this back to Ready for QA, given this ticket's history
of fixes that looked correct locally but didn't hold up for real users.
