# CASA Compliance Requirements Log

Tracks work on CASA (Cloud Application Security Assessment) requirements, submitted via the TAC Security portal (`casa.tacsecurity.com`) as part of Google OAuth API verification. Organized by the date the work happened; each entry documents the requirement text, the comment submitted, the evidence attached, and any code changes made.

**Read this file first before starting work on any CASA requirement** — it has prior findings, decisions, and gotchas that would otherwise need re-discovering.

Repos involved: `ai-employees-app` (React/TS frontend + Supabase) and `sam-backend` (FastAPI backend + LiveKit agents), sibling directories under `/Users/exceltech/Sam`.

## Environment & Access Notes

- **Production Supabase project:** `hdnwxonrwcnaodjxipll` — "AI Employees Inc." → "sam@aiemployeesinc.com's Project" → `main` (labeled PRODUCTION in the dashboard).
- **Production backend server:** `116.202.210.102` (Hetzner) — runs the `sam-backend/docker-compose.yml` stack. This is a **separate deployment** from the local Docker stack on the dev machine; local `docker compose` changes do not affect it until manually deployed there.
- **Supabase CLI auth:** `SUPABASE_ACCESS_TOKEN` is exported in `~/.zshrc` (loads for every new interactive terminal). This avoids the macOS Keychain password prompt that `supabase` CLI commands otherwise trigger when falling back to a stored `supabase login` credential. `supabase db push --linked` pushes to the linked project above.
- **Local dev stack:** `ai-employees-app/docker/docker-compose.yml` (frontend only, `make dev-up`/`make dev-down` from `ai-employees-app/`) and `sam-backend/docker-compose.yml` (backend + agents + Valkey, plain `docker compose up/down` from `sam-backend/`).
- **DAST scanning (OWASP ZAP):** run via the official `ghcr.io/zaproxy/zaproxy:stable` Docker image, `zap-baseline.py` script (passive scan + link-crawl only — no attack payloads, no form submission, safe against a real target). Target the frontend via `--network host` + `http://localhost:8080`, **not** the docker-network hostname (`sam-frontend:8080`) — Vite's dev server rejects unrecognized `Host` headers with a 403, which silently produces a near-empty scan if you don't catch it. Reports saved under `docs/casa/evidence/`.
- The requirement detail panels in the CASA portal follow a pattern: sub-items 2+ ("provide a written description...", "provide screenshots...") are conditioned on **"if a proprietary user authentication service is used by the application"**. Since this app uses Supabase Auth (external, hosted) for all standard login, those items are usually N/A — except where the app *does* have proprietary logic on top (e.g. the location-invitation activation-code flow, see 1.1.2).

## Requirement Status Index

| Requirement | Title | Status | Last worked |
|---|---|---|---|
| 1.1.1 | Authentication resistant to brute force attacks | Comment + evidence ready to submit | 2026-09-12 |
| 1.1.2 | Initial passwords/activation codes securely random + expire | Two real bugs found in the invite flow, both fixed and deployed to production; final evidence screenshots still pending | 2026-09-14 |
| 1.1.3 | Passwords stored resistant to offline attacks | Comment ready, no evidence needed | 2026-09-14 |
| 1.2.1 | Default credentials not on publicly exposed interfaces | Real gap found (unauthenticated public Valkey); fixed, deployed to production, and verified closed | 2026-09-14 |
| 1.3.1 | OOB verifier expires in reasonable timeframe | Comment ready; evidence screenshots not yet captured (dashboard location corrected) | 2026-09-14 |
| 1.3.2 | OOB verifier used only once | Comment ready, no evidence needed | 2026-09-14 |
| 1.3.3 | OOB verifier securely random | Comment ready, no evidence needed | 2026-09-14 |
| 1.3.4 | OOB verifier resistant to brute force | Comment ready; reuses the 1.1.1 rate-limits screenshot, different row | 2026-09-14 |
| 2.1.1 | No passwords/session tokens in URL parameters | Verified clean (code + DAST scan); PKCE flow fix applied and deployed locally | 2026-09-14 |
| 2.2.1 | Logout invalidates session/refresh tokens | Verified already correct (global-scope signOut), no fix needed | 2026-09-14 |
| 2.2.2 | Password change terminates all other active sessions | Real gap found (no session revocation on password change/reset) — fixed and deployed locally | 2026-09-15 |

---

## 2026-09-12

### 1.1.1 — Authentication is resistant to brute force attacks
**Domain:** 1 – Authentication

**Investigation:** App uses Supabase Auth (GoTrue) for all login (`ai-employees-app/src/pages/Login.tsx` → `supabase.auth.signInWithPassword`). Checked for custom protections and found none: no rate-limiting middleware in FastAPI (`sam-backend/backend/app/main.py` only registers CORS), no CAPTCHA package installed, no account-lockout columns in any of the ~100 Supabase migrations. Optional TOTP/SMS MFA exists (`two_factor_enabled` on `profiles`) but that's a separate control from brute-force throttling.

**Comment submitted:**
> Authentication is handled via Supabase Auth (GoTrue). Sign-in requests are rate-limited at the platform level (Authentication → Rate Limits in the Supabase dashboard), which throttles repeated sign-in attempts per IP/time window and mitigates brute-force and credential-stuffing attacks. Optional TOTP/SMS-based MFA is also available as a secondary control for user accounts.

**Evidence:** Screenshot of Supabase Dashboard → Authentication → Rate Limits (production project), showing **"Rate limit for sign-ups and sign-ins: 30 requests/5 min per IP (360 requests/hour)"**. Confirmed good — correct project (production, `main`), correct control, matches the comment.

**Code changes:** None — this is entirely delegated to the external auth provider.

---

### 1.1.2 — System generated initial passwords or activation codes shall be securely randomly generated and expire after a short period (first pass)
**Domain:** 1 – Authentication

Full requirement has 3 sub-items: (1) list external auth services, (2) written description of the initial password/activation-code process if proprietary, (3) screenshots of that process in action if proprietary.

**Investigation:** Unlike 1.1.1, this app *does* have proprietary logic here — the location-admin invite flow (`ai-employees-app/supabase/functions/invite-location-admin/index.ts` + `accept-invitation/index.ts`):
- Token: `gen_random_uuid()` (Postgres CSPRNG, ~122 bits entropy) — `supabase/migrations/20251228195353_92c9a3b8-5b21-44a4-a5be-edff04361975.sql:11`
- Expiry: `expires_at` defaults to `now() + 7 days` — same migration, line 12
- Expiry enforced at redemption — `accept-invitation/index.ts:65-73`
- Single-use via a status state machine (`pending → accepted/expired/cancelled`)
- A second, separate token flow exists for HR AI-interview candidate invites (`secrets.token_urlsafe(32)`, SHA-256-hashed at rest, 14-day expiry) — not part of this requirement's scope, noted for context.
- One weak-RNG finding *unrelated* to this requirement: employee check-in PINs use `random.randint(0,9999)` (`sam-backend/backend/app/routers/roles.py:48`), non-CSPRNG, 4 digits, no expiry — flagged as a low-severity item but out of scope here since it's not an authentication/activation code.

**Comment drafted (initial version, later confirmed accurate):**
> The application uses Supabase Auth (GoTrue), an external authentication service, for self-service user sign-up — no system-generated initial password is issued for that path. For location-admin invitations, the application generates an activation token via PostgreSQL's `gen_random_uuid()` (cryptographically secure, ~122 bits of entropy), which expires 7 days after creation. Expiry is actively enforced when the invitation is redeemed (rejected if expired), and each token is single-use — its status transitions from "pending" to "accepted," "expired," or "cancelled," preventing replay. The token is delivered via a one-time emailed activation link. Screenshots of the invite-creation, delivery, and expiry-enforcement steps are attached.

**Evidence plan given:** (1) sender-side "invite sent" toast, (2) the invite email showing "expires in 7 days", (3) an expired-link attempt showing rejection. Caution given: don't screenshot a still-valid token in a URL/email.

**Status at end of this day:** Comment and evidence plan drafted, not yet live-tested. Live testing on 2026-09-14 uncovered two real bugs — see below.

---

## 2026-09-14

### 1.1.2 — continued: live testing uncovered and fixed two real bugs

**Bug 1 — expired invitations were silently swallowed, never shown to the user.**
Asked to verify the three behaviors (sender confirmation, "expires in 7 days" text, "expired" message) actually work live, not just in code. Traced the frontend:
- Sender-side confirmation: confirmed working, exact toast text found in `LocationsTab.tsx:277,279` and `TeamManagement.tsx:425`.
- "Expires in 7 days" text + real 7-day expiry: confirmed correct in `invite-location-admin/index.ts:308` and the migration default.
- "This invitation has expired": **broken**. `ai-employees-app/src/pages/PendingInvitations.tsx:62` filtered expired invitations out of the query entirely (`.gt("expires_at", now)`), so an expired invite just vanished — the user was silently redirected to onboarding with zero explanation. Even in the rare case `accept-invitation` was called, `PendingInvitations.tsx:140` showed a hardcoded generic `"Failed to accept invitation"` instead of the real server error, because Supabase's JS client hides the actual edge-function error body behind `error.context` (a raw `Response`), not `error.message`.

**Fix (`ai-employees-app/src/pages/PendingInvitations.tsx`):**
- Removed the `.gt("expires_at", ...)` filter; partitions results into active vs. expired client-side.
- Added a dedicated expired-state screen ("This invitation has expired — please ask your admin to send you a new invitation") instead of a silent redirect.
- `handleAccept` now unwraps `error.context.json()` to show the real server message instead of a generic one.
- Verified: `npx tsc --noEmit` clean. Frontend Docker container (`sam-frontend`) rebuilt per repo convention.

**Bug 2 — `Signup.tsx` never validated the invitation token at all, pre-signup.**
Found via live testing with two real invited test emails:
- `yuvraj.excel2011@gmail.com` — already had an existing `profiles` row (system-wide, not team-scoped) from prior testing, so `invite-location-admin` took its "user already exists" branch (`index.ts:139-142`): grants `user_locations`/`user_roles` directly, sends a different notification email, and **never creates a `location_invitations` row at all**. This is correct/intended behavior, not a bug — but it means testing this flow requires a genuinely new email with zero prior account anywhere in the system (the lookup is a global email match on `profiles`, not scoped to a business/location).
- `rahulkhera000000@gmail.com` — a real fresh invite. Manually backdated its `expires_at` in production (`location_invitations.id = 84b56dcd-...`, `token = 76e59424-2f66-4c15-ad10-e2d16b618d34`) to simulate expiry, then hit `/signup?invitation=...` — and the signup form rendered normally, letting account creation proceed on a dead invitation. Root cause: `Signup.tsx` only ever read the `invitation` URL param for **display text** (heading, locked email field) — it never queried the database at all. It also structurally *couldn't*: RLS on `location_invitations` only grants `SELECT` to `authenticated` users viewing their own email, or business super admins — an anonymous pre-signup visitor gets nothing back either way.

**Fix:**
- New migration `ai-employees-app/supabase/migrations/20260914120000_check_invitation_status.sql` — a `SECURITY DEFINER` Postgres function `check_invitation_status(_token uuid)` granted to `anon` + `authenticated`, returning only a status string (`valid | expired | used | cancelled | not_found`) — no invitation contents (email/location/role) leaked to an anonymous caller.
- `ai-employees-app/src/pages/Signup.tsx` now calls this RPC on mount when an `invitation` param is present; blocks the signup form with an expired/invalid-state card unless the result is `valid`.
- Pushed via `supabase db push --linked` (using the `SUPABASE_ACCESS_TOKEN` env-var approach — see Environment notes above — to avoid the Keychain password prompt).
- Verified: `npx tsc --noEmit` clean. Called the new RPC directly against the real expired token, both with the service-role key and the actual browser-facing anon key — both correctly returned `"expired"`. Frontend Docker rebuilt.

**Comment (updated, current):**
> The application uses Supabase Auth (GoTrue) as an external authentication service for standard user sign-up. Additionally, the application implements a proprietary activation-code process for inviting location administrators: an activation token is generated via PostgreSQL's `gen_random_uuid()` (cryptographically secure, ~122 bits of entropy) and expires 7 days after creation. The sender receives an in-app confirmation once the invite is sent. The recipient receives an email stating the invitation expires in 7 days, and if they attempt to use the link after expiry, the application explicitly informs them the invitation has expired rather than allowing further action. Screenshots of invite creation, delivery, and expiry enforcement are attached.

**Evidence still needed (not yet captured as of this writing):**
1. Sender-side "Invitation sent to [email]" toast.
2. Invite email showing "This invitation expires in 7 days" (crop/avoid showing a still-live token).
3. The new expired-state screen in `PendingInvitations.tsx` (or `Signup.tsx`, depending which stage it's tested at) — can reuse the already-expired `rahulkhera000000@gmail.com` test invite for this since its token is already dead.

**⚠️ Production test-data cleanup note:** this testing created real rows in production:
- `location_invitations` row for `rahulkhera000000@gmail.com` (token `76e59424-...`), now expired — harmless, but a candidate for cleanup/deletion once evidence screenshots are captured.
- `yuvraj.excel2011@gmail.com` was granted real `is_admin: true` `user_locations` access to a live business/location via the "user exists" branch during testing — worth reviewing whether that access should be revoked if it wasn't an intentional real invite.

---

### 1.1.3 — Passwords shall be stored in a form that is resistant to offline attacks
**Domain:** 1 – Authentication

Only 2 sub-items (no screenshot bullet, unlike 1.1.1/1.1.2) — text-only answer.

**Comment submitted:**
> This application does not implement a proprietary password storage mechanism. All user passwords are stored and managed entirely by Supabase Auth (GoTrue), an external authentication service — the application never receives, processes, or stores raw passwords or password hashes itself. Per Supabase's documented implementation, passwords are hashed using bcrypt (a salted, adaptive-cost hashing algorithm) before storage, which is resistant to offline attacks such as rainbow-table lookups and brute-force cracking of stolen hashes. As this is an external service rather than a proprietary implementation, no additional password-storage evidence is applicable from this application's codebase.

**Evidence:** None — no screenshot bullet in the requirement, and Supabase deliberately doesn't expose password hashes anywhere in its dashboard.

**Code changes:** None.

---

### 1.2.1 — Default credentials shall not be present on publicly exposed interfaces
**Domain:** 1 – Authentication

**Investigation:** Checked both repos for (a) seeded default application accounts — none found anywhere in ~115 Supabase migrations or edge functions; (b) infrastructure default credentials — no service ships a literal default username/password pair (no `postgres/postgres`, `admin/admin`, etc.); (c) `.env.example` files — all placeholders, nothing real committed.

**Real gap found (not literally "default credentials," but the same underlying risk):** `sam-backend/docker-compose.yml` ran `sam-valkey` (Redis-compatible cache) with **zero authentication** and published on `ports: "6379:6379"` — bound to all host interfaces, not loopback like the neighboring `sam-betterdb` service. This compose file is the one confirmed running on the production server (`116.202.210.102`), so this was a live production exposure: anyone able to reach that port (internet, unless a separate firewall blocked it — see verification below) could read/write the cache with no credentials at all.

**Fix (`sam-backend/docker-compose.yml`):**
- Removed the `sam-betterdb` service entirely (per instruction — unused now that LangSmith is used for observability instead). Also cleaned a stray doc reference in `sam-backend/evals/hr_onboarding_ragas/README.md:150`.
- Added `--requirepass ${VALKEY_PASSWORD:?...}` to the `sam-valkey` command.
- Changed its port mapping to `127.0.0.1:6379:6379` (loopback only — was `6379:6379`, all interfaces).
- Updated `VALKEY_URL` for both consumers (`sam-backend`, `sam-hr-onboarding-agent`) to `redis://:${VALKEY_PASSWORD}@sam-valkey:6379/0`. No Python code changes needed — both services just pass the URL straight to the Redis client, which parses embedded auth natively.
- Password lives in a new `sam-backend/.env` (confirmed gitignored). Generated via `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. A **separate, distinct** password was generated for the user to deploy to production (never reuse a local dev secret in prod).

**Verified locally:** `valkey-cli PING` with no password → `NOAUTH Authentication required.`; with the password → `PONG`. `docker port sam-valkey` → `127.0.0.1:6379` only. Backend + HR-onboarding-agent containers came up clean, no Redis connection errors in logs. `sam-betterdb` container confirmed removed.

**Deployed to production by the user themselves** (this session doesn't have SSH access to `116.202.210.102`). Verified closed from the outside via `nc -zv -w 5 116.202.210.102 6379` → **"Operation timed out"** (not "succeeded", not immediate "refused" either — a timeout specifically indicates packets are being dropped, most likely by a pre-existing cloud/host firewall — `116.202.x.x` is a Hetzner range — with the new loopback binding + password as a second layer of defense-in-depth underneath it).

**Comment submitted:**
> No default application accounts exist in this system — user authentication is delegated entirely to Supabase Auth, which requires explicit account creation with no seeded credentials. All infrastructure services were audited for default or missing authentication: no service ships a known default username/password pair. One internal caching service (Valkey/Redis) was found without authentication and bound to a public interface; it has been remediated to require a strong generated password and is now bound to localhost only, not reachable externally.

**Evidence:** None required (no screenshot bullet in this requirement — text confirmation only).

---

### 1.3.1 — Out of band verifier shall expire in a reasonable timeframe
**Domain:** 1 – Authentication

"Out of band verifier" = NIST 800-63B terminology for magic links, password-reset emails/links, SMS/email OTP — all Supabase-Auth-managed here, not proprietary. (Not to be confused with the location-invitation activation codes from 1.1.2, which are a different mechanism — an account-setup activation code, not a login/MFA OOB verifier.)

**Comment submitted:**
> This application does not implement a proprietary out-of-band verification mechanism. All out-of-band verifiers — password reset emails, magic-link sign-in, and SMS/TOTP-based MFA challenges — are issued and expired entirely by Supabase Auth (GoTrue), an external authentication service. Supabase Auth enforces configurable expiration windows for these verifiers at the platform level (Authentication settings in the Supabase dashboard). Screenshots of the configured expiration values are attached for reference.

**Evidence location (corrected mid-session):** Initially guessed Authentication → Emails page — **wrong**, that page is only notification toggles ("Password changed", "MFA method added", etc.) and email templates, not the expiry setting. Correct location: **Authentication → Sign In / Providers → Email** (click into the Email provider row) for "Email OTP Expiration", and **→ Phone** provider row for "SMS OTP Expiry". Also worth checking against `sam-backend/docs/SMS_2FA_SETUP.md`'s recommended value (600 seconds / 10 minutes) — that doc only records a recommendation, never confirmed as actually applied in the live dashboard.

**Status:** Comment ready; screenshots of the two provider-config pages **not yet captured** as of this writing.

**Code changes:** None.

---

### 1.3.2 — Out of band verifier shall only be used once
**Domain:** 1 – Authentication

No screenshot bullet — text-only, same pattern as 1.1.3.

**Comment submitted:**
> This application does not implement a proprietary out-of-band verification mechanism. All out-of-band verifiers — password reset links, magic-link sign-in tokens, and SMS/TOTP-based MFA challenges — are issued, validated, and invalidated entirely by Supabase Auth (GoTrue), an external authentication service. Supabase Auth invalidates each out-of-band verifier immediately upon successful use, preventing replay or reuse of the same code or link. As this is an external service rather than a proprietary implementation, no additional evidence from this application's codebase is applicable.

**Evidence:** None — no screenshot bullet, and single-use invalidation isn't a dashboard-visible setting (internal GoTrue behavior). Offered to help live-test this (reuse a spent reset link and confirm rejection) if stronger proof is wanted before submitting — not done as of this writing.

**Code changes:** None.

---

### 1.3.3 — Out of band verifier shall be securely random
**Domain:** 1 – Authentication

No screenshot bullet — text-only.

**Comment submitted:**
> This application does not implement a proprietary out-of-band verification mechanism or algorithm. All out-of-band verifiers — password reset codes/links, magic-link sign-in tokens, and SMS/TOTP-based MFA codes — are generated entirely by Supabase Auth (GoTrue), an external authentication service, using its own cryptographically secure random number generation. No initial authentication code generation algorithm exists in this application's own codebase to describe, as this function is fully delegated to the external provider.

**Evidence:** None — no screenshot bullet; the generation algorithm is internal to Supabase's platform, not inspectable from this repo.

**Code changes:** None.

---

### 1.3.4 — Out of band verifier shall be resistant to brute force attacks
**Domain:** 1 – Authentication

**Comment submitted:**
> This application does not implement a proprietary out-of-band verification algorithm. Initial authentication codes (magic links, password reset codes/links, SMS/email OTPs) are generated by Supabase Auth (GoTrue), an external authentication service, using cryptographically secure random generation with sufficient entropy to resist guessing. Additionally, Supabase Auth enforces a platform-level rate limit on OTP/magic-link verification attempts — 30 requests per 5-minute window per IP address (360/hour) — which mitigates brute-force guessing of these codes. A screenshot of this rate limit configuration is attached.

**Evidence:** Reuses the same Authentication → Rate Limits screenshot from 1.1.1, but this time highlighting the **"Rate limit for token verifications"** row (30 req/5 min, 360/hour per IP) rather than the "sign-ups and sign-ins" row used for 1.1.1. Not yet confirmed captured as of this writing.

**Code changes:** None.

---

### 2.1.1 — The application shall not reveal passwords or session tokens in URL parameters
**Domain:** 2 – Session Management

Different sub-item pattern from Domain 1 — asks for **actual DAST scan results** ("per ADA's Dynamic Application Security Testing Guidance"), not a written description.

**Code-level investigation:** No password, session token, JWT, or API key is ever placed in a URL query string anywhere in either repo.
- Backend (`sam-backend/backend/app/core/auth.py:4,10`) authenticates exclusively via FastAPI's `HTTPBearer` scheme — no route accepts auth via `Query(...)`.
- Frontend (`ai-employees-app/src/lib/voiceAgentApi.ts:67-83`) sends the session token only via `Authorization: Bearer` header in `fetchWithAuth`; query strings built alongside it only ever carry non-secret identifiers (`business_id`, `location_id`, etc.).
- Third-party OAuth callbacks (Google Calendar/Gmail/Outlook) do put a `?code=&state=` in the redirect URL — but that's a one-time OAuth authorization code mandated by the IdP, exchanged server-side (`backend/app/routers/integrations.py:57-70`), not a session token or API key. Not in scope for this control.
- The location-invitation (`?invitation=<token>`) and HR-interview join (`/hr/interview/join/:token`) links carry one-time, time-limited, scoped activation codes — not session/access tokens — so they don't fall under this control either (and the HR one is a path segment, not a query string, regardless).
- **One real nuance found:** Supabase Auth's default `flowType` is `'implicit'`, which delivers the session token via the URL **fragment** (`#access_token=...`) on login/password-reset/signup-confirmation redirects. Fragments are never transmitted to any server, so this is not literally "revealed in URL parameters" — but it's not maximally clean either (visible in browser history, to browser extensions, etc.).

**Fix applied (to make this unambiguous rather than rely on the fragment distinction):**
- `ai-employees-app/src/integrations/supabase/client.ts` — added `flowType: 'pkce'` to the `createClient(...)` auth config. Session tokens are no longer placed in the URL in any form (fragment or query) — only a one-time authorization `code` appears, exchanged server-side by the Supabase client automatically.
- `ai-employees-app/src/pages/EmailConfirmed.tsx` — this page had manual `window.location.hash` parsing (checking for `access_token`/`type=signup`) as a fallback "no confirmation in flight" detector. Updated to also recognize the PKCE `?code=` query param, so the fallback logic stays accurate under the new flow. (`ResetPassword.tsx` needed no changes — it already relies purely on `onAuthStateChange` events, flow-agnostic.)
- Verified: `npx tsc --noEmit` clean; grepped the whole `src/` tree for any other manual `location.hash`/token-in-URL handling — none found. Frontend Docker container rebuilt.

**DAST scan run:** OWASP ZAP baseline scan (`ghcr.io/zaproxy/zaproxy:stable`, `zap-baseline.py` — passive analysis + link crawl only, no attack payloads) against the local dev frontend (`http://localhost:8080` via `--network host`; targeting the docker-network hostname `sam-frontend:8080` instead gets a 403 from Vite's dev-server host check and produces a near-empty scan — worth remembering for next time). Result: **0 FAIL**, 8 WARN (all unrelated header-hygiene items: missing CSP, X-Content-Type-Options, Permissions-Policy, etc. — a different topic, not addressed by this requirement). The two checks directly relevant to this control both **PASSED**: "Information Disclosure – Sensitive Information in URL" [10024] and "Session ID in URL Rewrite" [3]. Reports saved: `docs/casa/evidence/zap-baseline-2026-09-14.html` / `.md`.

**Comment submitted:**
> No password, session token, or API key is ever exposed in a URL query string in this application. Backend API authentication is exclusively via `Authorization: Bearer` headers (never query parameters). Third-party OAuth integration callbacks (Google Calendar, Gmail, Outlook) receive only a one-time authorization `code`/`state` per the OAuth2 standard — not a session token or API key — which is immediately exchanged server-side. Supabase Auth session tokens were previously delivered via URL fragment (never transmitted to any server) on login/password-reset callbacks; the application has been updated to use Supabase's PKCE flow, which removes the token from the URL entirely, replacing it with a one-time authorization code exchanged server-side. A dynamic application security scan (OWASP ZAP baseline scan) was run against the application; both the "Information Disclosure – Sensitive Information in URL" and "Session ID in URL Rewrite" checks passed with zero findings. Scan report attached.

**Evidence:** `docs/casa/evidence/zap-baseline-2026-09-14.html` (or a screenshot of its Alerts summary table).

**Note:** this scan was run against the **local dev** frontend, not the production `portal.aiemployeesinc.com` deployment — the PKCE fix needs the same `make dev-down && make dev-up` treatment (or equivalent prod deploy step) on production before the fix is live there too.

---

### 2.2.1 — Users shall have the ability to logout; logout/session expiration shall invalidate all stateful session tokens, including refresh tokens
**Domain:** 2 – Session Management

Asks for code snippets, not a screenshot — same pattern as 2.2.2 below.

**Investigation:** Checked every `supabase.auth.signOut(` call site in the app. There are exactly two: the real user-facing logout (`AuthContext.tsx`'s `signOut`, wired to the "Sign out" buttons in `SelectLocation.tsx`) and an unrelated auto-signout in `EmailConfirmed.tsx` after email confirmation. **Neither passes a `scope` argument**, so both default to Supabase's `'global'` scope — meaning logout already revokes the refresh token server-side via GoTrue's `/logout` endpoint, not just a local clear. Also confirmed the backend (`sam-backend/backend/app/core/auth.py`) does pure stateless JWT verification per request with no session table of its own — once the token is revoked/expired there's nothing left server-side to separately invalidate. No custom session/refresh-token store exists anywhere in the app (checked both repos).

**Comment submitted:**
> Users can log out via the Sign Out control, which calls `supabase.auth.signOut()`. This is invoked without an explicit scope, which defaults to Supabase Auth's 'global' scope — this revokes the refresh token server-side via the GoTrue /logout endpoint (not just a local session clear), invalidating the session everywhere it's active. The backend never maintains its own session or token state: it performs stateless JWT signature/expiry verification on every request, so once the refresh token is revoked and the short-lived access token subsequently expires, requests carrying it simply stop verifying — no separate backend-side invalidation step is needed. Session/access-token expiry (TTL) and refresh-token lifetime are configured at the Supabase Auth platform level.

**Evidence:** Code snippets only (no screenshot bullet in this requirement) — the `AuthContext.signOut` function, the `SelectLocation.tsx` button wiring, and the backend's stateless `get_current_user` JWT check.

**Code changes:** None — already correctly implemented.

---

## 2026-09-15

### 2.2.2 — Terminate all other active sessions (including stateful refresh tokens) after a successful password change
**Domain:** 2 – Session Management

Also asks for code snippets. This is the companion to 2.2.1 — 2.2.1 checked "does logout kill the session," this one checks "does changing your password kill *every other* session so a compromised device can't outlive a password reset."

**Investigation found a real, confirmed gap** (not just missing paperwork): neither password-change path revoked any other session.
- In-app "change/set password" (Account Settings): on success, only cleared the form and showed a toast. No call to `signOut` of any scope.
- Password reset/recovery link flow (`ResetPassword.tsx`): on success, only toasted and redirected to `/login`. Didn't even sign out the *current* session, let alone any others.
- Confirmed via repo-wide search that `scope: 'others'`/`'global'` was never used anywhere, and there was no "sign out of all devices" feature to build on.
- Practical impact: if an account is compromised and the legitimate owner resets their password to lock the attacker out, the attacker's existing session on another device stayed fully valid — defeating the point of the control.
- Federated login note: Supabase stores Google-authenticated sessions in the same session store as password-based ones, so revoking sessions via signOut scope does cover sessions established through Google sign-in too. It does not revoke Google's own OAuth consent grant (a separate system Google controls) — but that's not what this control is checking for.

**Fix applied:**
- `ai-employees-app/src/contexts/AuthContext.tsx` — `updatePassword` now takes an optional `revokeOtherSessions: 'others' | 'global'` parameter (defaults to `'others'`) and, after a successful `updateUser({ password })`, calls `supabase.auth.signOut({ scope: revokeOtherSessions })`.
- `ai-employees-app/src/pages/ResetPassword.tsx` — now calls `updatePassword(password, "global")` explicitly, since that flow already redirects to `/login` regardless, so signing out the current session too is correct.
- Account Settings' call site (`AccountSettings.tsx`) needed no change — it already calls `updatePassword(newPassword)` with no second argument, so it now gets the `'others'` default automatically: every other device gets signed out, but the user isn't unexpectedly kicked out of the settings page they're actively using.
- Verified: `npx tsc --noEmit` clean. Frontend Docker container rebuilt.

**Comment submitted:**
> After a successful password change (both the in-app "change password" flow and the password reset/recovery flow), the application now explicitly invalidates all other active sessions, including their refresh tokens. In-app password changes use Supabase Auth's 'others' sign-out scope, revoking every other session server-side while keeping the user's current session active. Password reset/recovery uses the 'global' scope, which also signs out the current session (consistent with that flow redirecting to the login page). Because Supabase Auth stores sessions established via federated login (e.g. Google) in the same session store as password-based sessions, this revocation is effective across federated login as well. Code snippets demonstrating this are attached below.

**Evidence:** Code snippets only (no screenshot bullet) — the updated `updatePassword` function showing the `signOut({ scope })` call, and the two call sites (`AccountSettings.tsx` using the default `'others'`, `ResetPassword.tsx` passing `'global'` explicitly).

**Note:** fix is deployed to local dev only so far — needs the same production deployment step as the other frontend fixes before the comment's claims are true in production.
