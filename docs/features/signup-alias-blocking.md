# Signup Alias Blocking

## What it does
Blocks new account signups that use an email-alias trick to create what's effectively a
duplicate account under a different-looking address. Three patterns are detected:

1. **Plus-addressing** — any local-part containing `+` (e.g. `example123+test@gmail.com`).
   Rejected outright; no legitimate primary email address contains a literal `+`.
2. **Disposable/temporary email domains** — checked against the `disposable-email-domains`
   PyPI package's maintained blocklist. Rejected outright.
3. **Gmail dot/domain duplicate detection** — Gmail ignores dots in the local part and treats
   `gmail.com`/`googlemail.com` as the same inbox. A *brand-new* dotted Gmail address with no
   existing account is allowed (dots are extremely common in real addresses — blocking on dots
   alone would reject huge numbers of legitimate first-time signups). It's only blocked when
   the normalized form is a **prefix match** against an already-registered account, e.g.
   `rahul.excel2011.test@gmail.com` is blocked because it starts with the normalized form of
   the existing `rahul.excel2011@gmail.com` account. Exact-duplicate normalized matches are
   caught by this too (a subset of prefix matching).

Enforcement is **signup-time only** — existing accounts are fully grandfathered, and login is
completely untouched by this feature (never calls the check endpoint).

Explicitly out of scope: Google OAuth signup (Google normalizes the email it returns, so these
tricks mostly can't reach that path), and a Supabase Auth Hook for true server-side enforcement
(deferred — the current check is called from the client before `supabase.auth.signUp()`, so it
can be bypassed by hitting Supabase's signup REST API directly instead of using the form).

## Key files
**Backend (sam-backend)**
- `backend/app/routers/auth_checks.py` — public (no auth) `POST /auth/check-signup-email`.
  Runs the three checks in order (plus → disposable domain → Gmail prefix-match against
  `profiles` table via `supabase_admin`) and returns `{blocked, reason}`.
- `backend/app/main.py` — router registered.
- `backend/requirements.txt` — `disposable-email-domains` package.

**Frontend (ai-employees-app)**
- `src/lib/voiceAgentApi.ts` — `checkSignupEmail(email)`, fails open (returns
  `{blocked: false}`) if the API is unreachable or misconfigured, so an outage never blocks
  all signups.
- `src/pages/Signup.tsx` — calls `checkSignupEmail` in `handleSignup` before
  `supabase.auth.signUp()`; shows the backend's `reason` via toast and stops if blocked.

## Decisions / tradeoffs
- **Prefix-match, not full substring-match**, for the Gmail dot-insensitivity rule — chosen to
  balance catching suffix-appended lookalikes (`.test`, `.dev`, etc.) against false positives
  on unrelated users. Still has a known false-positive edge case: if "john" already has an
  account, a genuinely different person named "johnson" would be incorrectly blocked from
  signing up with `johnson@gmail.com`. Accepted as a tradeoff, not fixed.
- **No login-time enforcement at all** — deliberate. Since existing accounts are fully
  grandfathered regardless of when they were created, there was no reliable way to distinguish
  "grandfathered" from "should have been blocked" at login time without a cutoff-date
  mechanism, so login was left untouched entirely.
- **Client-side trigger, not a Supabase Auth Hook** — the robust fix (can't be bypassed by
  calling Supabase's API directly, and would also cover Google OAuth) needs a Supabase
  "before user created" Auth Hook, which requires dashboard-side setup outside of what's
  scriptable here. Deferred; flagged as a known gap, not silently accepted as "done."
