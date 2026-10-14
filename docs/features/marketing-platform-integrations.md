# Marketing Platform Integrations (Instagram, X, LinkedIn)

## What it does
Business Settings → Integrations → Marketing Integrations lets a tenant connect its own
social profiles so the Marketing Employee can auto-publish generated campaign assets on a
schedule. Instagram and X shipped first; LinkedIn (personal-profile posting) went live
2026-09-04 (AIE-32) once a real LinkedIn Developer app ("AI Employees Inc.") was created.
LinkedIn Company Page posting is a separate follow-up — see "LinkedIn" below.

> **TikTok was removed (AIE-52, 2026-09-03).** It was previously "fully wired, credentials
> live" (OAuth, video/photo publish, privacy picker) but never passed TikTok's Content Posting
> API audit and had zero production connections (`marketing_platform_integrations.provider`
> only ever allowed `instagram`/`x` at the DB level, so a TikTok row could never actually
> persist). All TikTok OAuth/publish code, the `/marketing/public/assets/{token}` endpoint it
> alone justified, and its config vars were deleted; `marketing_assets.platform`'s CHECK
> constraint no longer allows `'tiktok'`. No data migration was needed.

## Data model
Single generic table, no schema change needed to add a provider:
- `marketing_platform_integrations` — `business_id`, `provider` (`instagram` | `x` |
  `linkedin`), `connected_by`, `provider_account_id`, `provider_account_name`,
  `provider_page_id`, `encrypted_access_token`, `encrypted_refresh_token`, `token_expires_at`,
  `scopes`, `is_connected`, `last_error`, `metadata`. Tokens are Fernet-encrypted with
  `MARKETING_TOKEN_ENCRYPTION_KEY` before storage.

## OAuth flow (all providers share the same shape)
1. Frontend calls `GET /integrations/marketing/{provider}/auth-url` → backend returns a
   provider auth URL with a base64-encoded JSON `state` (provider, business_id, user_id,
   return_to, redirect_uri, plus a PKCE `code_verifier` for X).
2. User authorizes on the provider's site, gets redirected to
   `/integrations/marketing/{provider}/callback` in the frontend — a generic route
   (`GoogleOAuthCallback` in `App.tsx`) that just re-navigates to `return_to` carrying
   `code`/`state`, where `IntegrationsTab.tsx`'s effect picks it up.
3. Frontend calls `POST /integrations/marketing/{provider}/callback` with `{code, state,
   business_id}` → backend exchanges the code for tokens and upserts the integration row.

## Provider specifics

### Known gaps (not fixed by this work, flagged for whoever picks them up next)
- **Marketing video generation is a complete stub.** `POST /marketing/assets/{asset_id}/video`
  (`start_video_job_disabled` in `marketing_generation_service.py`) makes no HeyGen API call —
  it synchronously writes a fake `disabled` job/asset row. The `HEYGEN_API_KEY`/
  `HEYGEN_AVATAR_ID` in `backend/.env` are unused dead config, architecturally distinct from
  the real, working `LIVEAVATAR_*` credentials that power the voice agents' talking-avatar
  feature (a different HeyGen product). Building real video generation would need: confirming
  what HeyGen product those credentials are actually for, a new async video-generation client,
  and a polling/webhook job pipeline. Until then, publishing uses AI-generated **photos**, not
  video.

### LinkedIn — personal-profile posting live (AIE-32, 2026-09-04)
- Auth: standard `https://www.linkedin.com/oauth/v2/authorization` → token exchange at
  `/oauth/v2/accessToken`. Scopes: `openid profile email w_member_social` (self-serve
  "Sign In with LinkedIn using OpenID Connect" + "Share on LinkedIn" products — both
  auto-approved instantly). Identity via OIDC `GET https://api.linkedin.com/v2/userinfo`.
- Publish: `_publish_to_linkedin` — image-only, posts as the connected **member** (author URN
  `urn:li:person:{id}`), not a Company Page. Registers an image upload
  (`POST /rest/images?action=initializeUpload`), PUTs bytes, then
  `POST /rest/posts` with `LinkedIn-Version` + `X-Restli-Protocol-Version: 2.0.0` headers.
  Post id comes back in the `x-restli-id` response header.
- Config: `MARKETING_LINKEDIN_CLIENT_ID`/`_SECRET` set in `backend/.env` (LinkedIn Developer
  app "AI Employees Inc.", client ID `86q1jafz5xj00p`). Redirect URIs and
  `MARKETING_LINKEDIN_API_VERSION` (`202502`) use their existing defaults.
- **Fixed 2026-09-04**: `marketing_platform_integrations.provider` CHECK constraint only ever
  allowed `('instagram', 'x')` — LinkedIn OAuth would complete but fail to persist. Migration
  `20260904120000_add_linkedin_provider.sql` added `'linkedin'` to the allow-list.
- **Redirect URI gotcha**: the LinkedIn app's Auth tab must have
  `https://portal.aiemployeesinc.com/integrations/marketing/linkedin/callback` registered
  (note the `/marketing/` segment — this repo's older setup docs, written before the app
  existed, incorrectly said `/integrations/linkedin/callback` with no `/marketing/`; that's
  what got registered first and had to be corrected by adding the right URL alongside it).
- **No refresh tokens on this product tier.** `w_member_social` access tokens last 60 days and
  LinkedIn does not issue a `refresh_token` outside the Marketing Developer Platform — the only
  path to a new token is sending the member through the LinkedIn consent screen again.
  `_refresh_linkedin_access_token` exists in code but will never actually run since no refresh
  token is ever stored. Current handling is minimal: `token_expires_at` is stored, and a
  scheduled-post publish attempt against an expired/broken token fails and surfaces
  "Reconnect" in the Integrations tab like any other provider error — no proactive
  before-expiry reminder yet.
- **Company Page posting — code shipped, gated behind LinkedIn-side approval (AIE-100,
  2026-10-09).** Posting as an organization instead of a member requires the
  `w_organization_social` scope via LinkedIn's **Community Management API**, which is not
  self-serve: Sam needs to add that product in the LinkedIn Developer Portal and get it
  reviewed/approved (use-case application, verified Company Page, 1–4 weeks for
  Development-tier approval). Flagged to Sam on AIE-100.
  - All code is additive and off by default via `MARKETING_LINKEDIN_ORGANIZATION_ACCESS_ENABLED`
    (`settings.marketing_linkedin_organization_access_enabled`, defaults `False`) — current
    personal-profile behavior is unchanged until this is flipped on post-approval.
  - When enabled: `build_linkedin_auth_url` adds `LINKEDIN_ORGANIZATION_SCOPES`
    (`w_organization_social`, `r_organization_admin`, `rw_organization_admin`) to the auth-url
    scope; `complete_linkedin_oauth` calls `_fetch_linkedin_organizations` (`GET
    /rest/organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED`) and stores the
    result in `metadata.available_organizations` on the integration row (no auto-select).
  - New endpoints: `GET /integrations/marketing/linkedin/organizations` (list available pages +
    current selection) and `POST /integrations/marketing/linkedin/select-organization` (sets
    `provider_page_id`, or `null` to revert to personal) — see `select_linkedin_organization` /
    `get_linkedin_organizations` in `marketing_social_service.py`.
  - `_publish_to_linkedin` now posts as `urn:li:organization:{provider_page_id}` when a page is
    selected, falling back to `urn:li:person:{provider_account_id}` otherwise.
  - Frontend: `IntegrationsTab.tsx`'s LinkedIn card renders a "Post as" dropdown (Personal
    Profile vs. each returned Company Page) only when `getLinkedInOrganizations` returns a
    non-empty list — invisible to everyone until the flag is on and the user has pages to pick
    from.

## Key files
**Backend (sam-backend)**
- `backend/app/core/config.py` — all provider env vars.
- `backend/app/schemas/marketing.py` — `MarketingIntegrationProvider` literal (3 providers).
- `backend/app/services/marketing_social_service.py` — all OAuth build/complete/refresh and
  `_publish_to_*` functions per provider; `publish_scheduled_post` dispatches by
  `platforms` list on the scheduled post row.
- `backend/app/routers/marketing_integrations.py` — `/integrations/marketing/*` routes.

**Frontend (ai-employees-app)**
- `src/lib/voiceAgentApi.ts` — `MarketingIntegrationProvider` type + generic status/auth-url/
  callback/disconnect calls (provider is just a path param, no per-provider branching needed);
  `MarketingIntegrationStatus.account_avatar_url`; `getLinkedInOrganizations` /
  `selectLinkedInOrganization` for the Company Page picker (AIE-100).
- `src/components/business/IntegrationsTab.tsx` — Marketing Integrations cards (avatar image
  when connected, falls back to the static brand icon) + OAuth callback handling; LinkedIn card
  has an optional `footer` slot rendering the "Post as" page picker (`IntegrationCardProps.footer`).
- `src/App.tsx` — `/integrations/marketing/linkedin/callback` route reuses the existing
  generic `GoogleOAuthCallback` redirector.
- `src/lib/marketingEmployeeMock.ts` — `MarketingPlatform` type + scheduled-post API calls.
- `src/pages/dashboard/marketing/MarketingCreatePost.tsx` — post composer/scheduler;
  `publishablePlatforms` gates which platforms can be posted to.

## Privacy Policy & Terms of Service
Both public, unauthenticated pages already existed (`src/pages/Legal.tsx`, routes `/privacy`
and `/terms`) before this work — they just weren't linked anywhere reachable pre-login. Added:
- Links to both in the shared `AuthLayout.tsx` footer (visible on Login/Signup/etc. — the
  closest thing this app has to a public homepage, since `/` redirects straight to `/login`).
- "Privacy Policy" and "Terms of Service" links in the dashboard sidebar's Help section
  (`src/components/layout/Sidebar.tsx`), for in-app navigation.
- Updated `/privacy`'s "Connected Services" section to mention LinkedIn (and, at the time,
  TikTok — since removed along with the integration itself), and its "Contact" section to
  `support@aiemployeesinc.com` (was a personal email). The live legal content has since been
  substantially rewritten via the in-app editor and no longer resembles this seed text.

These are the URLs to submit as Privacy Policy / Terms of Service in the LinkedIn developer
app config.

## AIE-100 — LinkedIn integration audit (2026-10-14)
Triggered by a `redirect_uri does not match the registered value` error on Sam's new
"AI Employees - Community" LinkedIn app (client_id `86i9ylq4876wzc`, created 10/9 to pursue the
Community Management API product for Company Page posting). That specific error is pure LinkedIn
Developer Portal config — the new app has never had its Auth tab's "Authorized redirect URLs"
populated, so it needs `http://localhost:8080/integrations/marketing/linkedin/callback` and
`https://portal.aiemployeesinc.com/integrations/marketing/linkedin/callback` added there (only
Sam can do this — portal access). Not a code issue, nothing to fix on our side for that one.

While investigating, audited the rest of the LinkedIn integration and found two more real issues,
both now fixed:

1. **Stale `LinkedIn-Version` header.** `config.py`'s `marketing_linkedin_api_version` was hardcoded
   to `"202502"` (Feb 2025). LinkedIn supports each monthly version for ~12 months before sunset
   (confirmed via their current versioning docs) — `202502` was roughly 8 months past that window.
   Every `/rest/*` call (`organizationAcls` lookup, image upload, post creation) was at serious risk
   of already failing independent of anything else. Bumped the default to `202609` (current latest
   as of this audit). **This isn't a one-time fix** — this string needs bumping roughly yearly or
   LinkedIn will start rejecting the header again; nothing in the code tracks or warns about this.

2. **No realistic token refresh path, and a dead connection looked alive.** LinkedIn only issues an
   OAuth `refresh_token` to apps approved as **Marketing Developer Platform partners** — a
   separate/additional approval from the Community Management API product already in progress for
   AIE-100. Our requested scopes never get one, so `encrypted_refresh_token` is null for every real
   connection, and `_refresh_linkedin_access_token` always fails once the 60-day access token
   expires. Previously this only ever surfaced as a `publish_error` on individual scheduled posts —
   `marketing_platform_integrations.is_connected`/`last_error` were never updated, so
   Settings → Integrations kept showing LinkedIn as "Connected" indefinitely after it had actually
   died. Fixed: `_refresh_linkedin_access_token` (`marketing_social_service.py`) now calls a new
   `_mark_integration_disconnected()` helper that flips `is_connected` to `false` and writes
   `last_error` the moment a refresh fails, so the card goes back to showing "Connect" instead of a
   stale "Connected" badge. Also wired the (already-existing) `last_error` field through to the
   frontend — `IntegrationCard` now renders it under the description whenever a provider shows
   disconnected with a stored error, for Instagram/X/LinkedIn alike (only LinkedIn actually hits this
   today, but the other two providers share the same dead pattern, so the fix covers all three for free).
   **Not fixed, by design:** a mid-session 401 during an actual publish call doesn't flip
   `is_connected` — only a failed *refresh* does. A transient LinkedIn API error on `/rest/posts`
   shouldn't force a full reconnect; only an unambiguously dead token should.
   **Real fix for #2 is out of code's hands:** LinkedIn will keep killing every connection at ~60
   days until the app is approved for Programmatic Refresh Tokens (MDP partner status) — worth
   raising with Sam as a second, separate approval request alongside Community Management API,
   since without it every connected business will need to manually reconnect every two months.

3. **Operational gotcha, not a bug:** `available_organizations` (the Company Page list) is only ever
   fetched once, at the moment of OAuth connect (`complete_linkedin_oauth`). Flipping
   `MARKETING_LINKEDIN_ORGANIZATION_ACCESS_ENABLED` to `true` once LinkedIn approves the product will
   **not** retroactively show the page picker for already-connected businesses — each one needs to
   disconnect and reconnect LinkedIn after approval for the org list to populate. Flagging now so
   it's not a surprise later.
