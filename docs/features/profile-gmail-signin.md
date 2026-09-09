# Profile Settings — Gmail Sign-in & Password (AIE-57)

## What it does
Under Profile Settings → "Connected Accounts", a user can link their personal Gmail account as
an *additional sign-in method* via Supabase Auth identity linking (`supabase.auth.linkIdentity`).
This is entirely separate from two other "Google" integrations that happen to live nearby:
- **My Google Calendar** (same page, lower section) — backend-managed OAuth token for calendar
  sync, unrelated to sign-in.
- **Business Settings → Integrations → Gmail** — backend-managed OAuth token for sending email as
  the business, also unrelated to sign-in.

A "Disconnect" button lets the user remove the Gmail sign-in identity, but only if they have
another way to sign in afterward (a password, or another linked identity) — otherwise they'd be
locked out of their own account.

## The bug (AIE-57) and root cause
The ticket ("Unable to disconnect Gmail") turned out to be two layered problems, found via a QA
round on the first fix attempt:

1. **The Disconnect button didn't exist at all** — the Gmail card only ever rendered a "Connect"
   button, even when Gmail was already linked. Fixed by adding a real Disconnect button
   (`handleGoogleIdentityDisconnect`) gated on having another sign-in method.

2. **The gate was correct in principle but the "set a password" escape hatch it pointed to didn't
   actually work** for the exact account shape it was trying to unblock. This is the real reason
   QA (Heather W.) got stuck: her account's only identity was Google (she'd signed up or accepted
   an invite via "Sign in with Google", never email+password — see `Login.tsx`/`Signup.tsx`'s
   Google buttons and `AuthContext.signInWithGoogle`). The app's existing "Change Password" form
   requires entering and verifying a *current* password (`supabase.auth.signInWithPassword`)
   before allowing a new one — which is impossible for an account that has no password yet. There
   was no way to set an initial password, so the Disconnect gate's own suggested fix was a dead
   end.

   Compounding this: even if that verification step were bypassed, **Supabase Auth has a known
   gap** (confirmed via Supabase's own GitHub issues, e.g. `supabase/auth#2085` and the "ghost
   password" discussion) — calling `supabase.auth.updateUser({ password })` on an OAuth-only
   account successfully sets a working password credential, but does **not** add an `"email"`
   entry to `user.identities`. So even after setting a password, `identities.length` would still
   read `1`, and the original identities-count-based Disconnect gate would keep blocking forever.

3. **A raw Supabase error string could leak to the user** — `"User must have at least 1 identity
   after unlinking"` is GoTrue's own literal error text (not app copy), surfaced verbatim via
   `toast.error(error.message)` in the rare case where `unlinkIdentity` itself rejects the call
   (e.g. stale local identity state bypassing the client-side guard). QA flagged this as
   unfriendly/unexplained.

## Fix
- **`src/pages/dashboard/AccountSettings.tsx`** — the password card is now dual-mode based on a
  new `hasPasswordCapability` flag:
  ```ts
  const hasPasswordCapability =
    (user?.identities?.some((i) => i.provider === "email") ?? false) ||
    user?.user_metadata?.has_password_set === true;
  ```
  - `true` → unchanged "Change Password" flow (current password required + verified).
  - `false` → "Set Password" flow: no Current Password field, no verification step (nothing to
    verify against), heading/button text adjust accordingly.
  - The Disconnect guard (`handleGoogleIdentityDisconnect`) now checks
    `hasOtherIdentity || hasPasswordCapability` instead of `identities.length <= 1` alone, so a
    password set via the new flow actually unblocks disconnecting Gmail.
  - The `unlinkIdentity` error branch no longer passes through `error.message` raw — it shows the
    same friendly guard copy when the error text mentions "identity", or a generic fallback
    otherwise, so GoTrue's raw string can never reach the user.
  - Added a small inline hint under the Gmail row ("Set a password above to be able to disconnect
    Gmail.") when disconnect is currently blocked, so the block isn't only ever explained
    reactively via a toast after clicking Disconnect.
  - Reworded the Connected Accounts description to distinguish this card from the Google Calendar
    section right below it and Business Settings' Gmail integration (QA's confusion in point 1).

- **`src/contexts/AuthContext.tsx`** (`updatePassword`) — every successful password update now
  also sets `user_metadata.has_password_set = true` via `supabase.auth.updateUser({ password,
  data: { has_password_set: true } })`. This is the workaround for the Supabase Auth gap above:
  since GoTrue won't add an `"email"` identity retroactively, the app tracks "this account has a
  working password" itself. Harmless to set on every password change, not just the first one.

## Round 2 (9/9): stale state after unlinkIdentity, and a follow-up on the fix above
QA (Heather W.) sent it back to In Development after re-testing round 1's fix, with three
symptoms on an account that already had a password (email/password auth, `hasPasswordCapability`
correctly `true`, "Change Password" correctly shown):
1. Still got the "set a password / link another sign-in method" error when disconnecting.
2. Gmail still showed "Connected" after the first disconnect attempt — confirmed not a stale-render
   issue.
3. After a password-change attempt that errored, Gmail ended up disconnected anyway.

**Root cause (confirmed by reading `@supabase/auth-js`'s `GoTrueClient.js` directly):**
`supabase.auth.unlinkIdentity()` only issues the `DELETE /user/identities/{id}` call — it never
calls `_saveSession` or emits an `onAuthStateChange` event on success. `AuthContext`'s `user` state
(and therefore `user.identities`, which the whole Connected Accounts card and
`hasPasswordCapability` are derived from) is only ever refreshed by auth events or `getSession()`,
so a successful disconnect left the local `user` object silently stale until something *unrelated*
happened to refresh the session.

That one gap explained all three symptoms:
- **#2** — the disconnect had actually succeeded server-side; the UI just never found out.
- **#3** — `handleUpdatePassword`'s current-password check calls
  `supabase.auth.signInWithPassword()` to verify, which *does* create a fresh session and fire
  `onAuthStateChange`. That incidental refresh is what finally surfaced a disconnect that had
  already succeeded earlier — the password step itself never touches identities.
- **#1** — clicking Disconnect again against the still-"Connected" stale card sent the
  already-deleted `identity_id` back to the server, which replies with GoTrue's structured
  `identity_not_found` error code. Round 1's error handling (`/identity/i.test(error.message)`)
  mapped *any* identity-related error text to the "set a password" copy, regardless of whether
  that was actually true.

**Fix (`src/pages/dashboard/AccountSettings.tsx`):**
- `handleGoogleIdentityDisconnect` now calls `await supabase.auth.refreshSession()` right after
  `unlinkIdentity()` resolves (success or error). `refreshSession()` triggers GoTrue's refresh-token
  grant, which does call `_saveSession` + emit `TOKEN_REFRESHED` — so `AuthContext`'s `user` picks
  up the server's true current identity list immediately, no page reload needed.
- The error branch now checks `error.code` instead of pattern-matching `error.message`:
  - `"single_identity_not_deletable"` → real guard, show the "set a password / link another
    method" copy.
  - `"identity_not_found"` → already removed server-side (e.g. an earlier click succeeded before
    the UI caught up) — treated as a successful disconnect, since `refreshSession()` just
    confirmed that state.
  - anything else → generic "Failed to disconnect Gmail. Please try again."
- Applied the same `refreshSession()` call to the separate mismatched-Google-email auto-unlink
  effect in the same file (lines ~63–82) — identical defect, same root cause, different trigger.

**Verified:** `npx tsc --noEmit` clean; confirmed via SDK source (`errors.js`, `GoTrueClient.js`)
that `AuthApiError.code` is a real, typed field (not message-parsing) and that
`_callRefreshToken` unconditionally calls `_saveSession` + `_notifyAllSubscribers('TOKEN_REFRESHED', ...)`,
which is exactly the listener `AuthContext` already subscribes to — no new context API needed.

## Decisions / tradeoffs
- **No schema/migration for this** — `user_metadata` (already synced into the client `User`
  object via the existing `onAuthStateChange` listener in `AuthContext`) was enough; a
  `profiles` column or backend endpoint would have been redundant plumbing for the same fact.
- **`hasPasswordCapability` is a client-tracked flag, not a server-verified one.** It's only ever
  used to decide UI affordances (show/hide a form field, allow/block a client-initiated
  `unlinkIdentity` call) — the actual security boundary (can you sign in) is enforced by Supabase
  Auth itself regardless of what this flag says, so there's no integrity risk in it being
  client-side.
- **Business Settings' Gmail integration and "My Google Calendar" were confirmed untouched** —
  both already worked correctly; this ticket only ever concerned the Profile Settings sign-in
  identity.
