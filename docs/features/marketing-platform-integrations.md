# Marketing Platform Integrations (Instagram, X, TikTok, LinkedIn)

## What it does
Business Settings → Integrations → Marketing Integrations lets a tenant connect its own
social profiles so the Marketing Employee can auto-publish generated campaign assets on a
schedule. Instagram and X shipped first; this doc adds TikTok (fully wired, credentials live)
and LinkedIn (fully wired, but **unverified** — no LinkedIn Developer app exists yet).

## Data model
Single generic table, no schema change needed to add a provider:
- `marketing_platform_integrations` — `business_id`, `provider` (`instagram` | `x` | `tiktok` |
  `linkedin`), `connected_by`, `provider_account_id`, `provider_account_name`,
  `provider_page_id`, `encrypted_access_token`, `encrypted_refresh_token`, `token_expires_at`,
  `scopes`, `is_connected`, `last_error`, `metadata`. Tokens are Fernet-encrypted with
  `MARKETING_TOKEN_ENCRYPTION_KEY` before storage.

## OAuth flow (all four providers share the same shape)
1. Frontend calls `GET /integrations/marketing/{provider}/auth-url` → backend returns a
   provider auth URL with a base64-encoded JSON `state` (provider, business_id, user_id,
   return_to, redirect_uri, plus a PKCE `code_verifier` for X/TikTok).
2. User authorizes on the provider's site, gets redirected to
   `/integrations/marketing/{provider}/callback` in the frontend — a generic route
   (`GoogleOAuthCallback` in `App.tsx`) that just re-navigates to `return_to` carrying
   `code`/`state`, where `IntegrationsTab.tsx`'s effect picks it up.
3. Frontend calls `POST /integrations/marketing/{provider}/callback` with `{code, state,
   business_id}` → backend exchanges the code for tokens and upserts the integration row.

## Provider specifics

### TikTok (Content Posting API) — live credentials, sandboxed
- Auth: `https://www.tiktok.com/v2/auth/authorize/` (PKCE S256 required). Token exchange /
  refresh: `POST https://open.tiktokapis.com/v2/oauth/token/`. Access tokens expire in 24h,
  refresh tokens in 365 days — refreshed proactively in `_access_token_for_provider`.
- Scopes: `user.info.basic,video.publish`.
- Avatar: `user/info/` is queried with `fields=open_id,display_name,avatar_url` at connect
  time; `avatar_url` is stored in the integration row's `metadata.avatar_url` and surfaced via
  `MarketingIntegrationStatusResponse.account_avatar_url` — rendered on the connect card in
  `IntegrationCard` (`IntegrationsTab.tsx`) in place of the static brand icon once connected.
- Disconnect: `disconnect_marketing_integration` calls TikTok's
  `POST /v2/oauth/revoke/` (client_key/client_secret/token) before deleting the local row —
  best-effort (a revoke failure doesn't block disconnecting locally).
- **Publish supports both video and photo** (`_publish_to_tiktok`, dispatches on the asset's
  `content_type`):
  - **Video** (`_publish_video_to_tiktok`) — `FILE_UPLOAD` source (raw bytes PUT to TikTok's
    `upload_url`). Chosen over `PULL_FROM_URL` because that path requires the media host
    domain to be TikTok-verified, which our Supabase storage domain isn't.
  - **Photo** (`_publish_photo_to_tiktok`) — TikTok's photo endpoint
    (`/v2/post/publish/content/init/`) **only** supports `PULL_FROM_URL`, no `FILE_UPLOAD`
    option exists for photos. So generated images are served from our own backend via a new
    unauthenticated endpoint (`GET /marketing/public/assets/{token}`,
    `build_public_asset_url()`/`get_public_marketing_asset_bytes()` in
    `marketing_social_service.py`) on `MARKETING_PUBLIC_BACKEND_URL` — a domain we control and
    that must be verified for this app in the TikTok Developer Portal (DNS TXT record). The
    token is a Fernet-encrypted asset id with a 2-hour TTL (`PUBLIC_ASSET_TOKEN_TTL_SECONDS`),
    not a business-scoped check — access is gated purely by unguessability + expiry, since
    TikTok's servers fetch it directly with no auth headers.
  - Photo posting is the currently-used path for the TikTok demo/review flow: Marketing
    Employee video generation is an unbuilt stub (see "Known gaps" below), so TikTok content
    is generated via the existing, working OpenAI image pipeline and posted as a photo, not a
    video.
- **Privacy/interaction picker**: per TikTok's UX guidelines (mandatory for review), the user
  must be shown their account's actual `privacy_level_options` and choose one before every
  publish — not just a hardcoded default. `GET /integrations/marketing/tiktok/creator-info`
  (`get_tiktok_creator_info`) exposes TikTok's `creator_info/query` response; the frontend
  (`MarketingCampaignOverview.tsx`, `tiktokDialogOpen` state + `Dialog`) calls it and shows a
  privacy-level `RadioGroup` + a "turn off comments" checkbox before Post Now/Schedule when
  TikTok is a selected platform. The choice is sent as `tiktok_options` on
  `MarketingScheduledPostCreateRequest` (`TikTokPublishOptions` schema), stored in the
  scheduled post's `metadata.tiktok_options`, and read by `_publish_to_tiktok` at publish time
  — if absent (e.g. a non-TikTok-aware caller), it falls back to querying creator_info fresh
  and defaulting to `MARKETING_TIKTOK_PRIVACY_LEVEL`.
- **Sandbox limitation**: per TikTok's docs, "all content posted by unaudited clients will be
  restricted to private viewing mode" — regardless of the `privacy_level` we send. We default
  to `SELF_ONLY` via `MARKETING_TIKTOK_PRIVACY_LEVEL` anyway, since that's the honest state
  until the app passes TikTok's Content Posting API audit for the `video.publish` scope.
- No public permalink is returned by the status endpoint, so `provider_post_urls.tiktok` stays
  empty — only `provider_post_ids.tiktok` (the `publish_id`) is recorded.
- Config: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `MARKETING_TIKTOK_REDIRECT_URI_LOCAL`/
  `_PRODUCTION`, `MARKETING_TIKTOK_PRIVACY_LEVEL`, `MARKETING_PUBLIC_BACKEND_URL` (set to
  `https://portal.aiemployeesinc.com/api`).
- **Manual steps still owed (all TikTok Developer Portal / DNS, not code)**:
  1. Register both redirect URIs (local + production) under Login Kit.
  2. Add the Content Posting API product with Direct Post enabled; request `video.publish`
     scope approval.
  3. Add the account used for testing as a Target User / sandbox tester.
  4. Verify `portal.aiemployeesinc.com` (or the `/api` URL prefix) as an owned domain/URL
     prefix in the Developer Portal — **required for photo posting to work at all**, since
     `PULL_FROM_URL` fetches will 403 (`url_ownership_unverified`) until this is done.

### Known gaps (not fixed by this work, flagged for whoever picks them up next)
- **Marketing video generation is a complete stub.** `POST /marketing/assets/{asset_id}/video`
  (`start_video_job_disabled` in `marketing_generation_service.py`) makes no HeyGen API call —
  it synchronously writes a fake `disabled` job/asset row. The `HEYGEN_API_KEY`/
  `HEYGEN_AVATAR_ID` in `backend/.env` are unused dead config, architecturally distinct from
  the real, working `LIVEAVATAR_*` credentials that power the voice agents' talking-avatar
  feature (a different HeyGen product). Building real video generation would need: confirming
  what HeyGen product those credentials are actually for, a new async video-generation client,
  and a polling/webhook job pipeline. Until then, TikTok (and any other platform) publishing
  uses AI-generated **photos**, not video.

### LinkedIn — built but unverified (no Developer app yet)
- Auth: standard `https://www.linkedin.com/oauth/v2/authorization` → token exchange at
  `/oauth/v2/accessToken`. Scopes: `openid profile email w_member_social`. Identity via OIDC
  `GET https://api.linkedin.com/v2/userinfo`.
- Publish: `_publish_to_linkedin` — image-only. Registers an image upload
  (`POST /rest/images?action=initializeUpload`), PUTs bytes, then
  `POST /rest/posts` with `LinkedIn-Version` + `X-Restli-Protocol-Version: 2.0.0` headers.
  Post id comes back in the `x-restli-id` response header.
- Config: `MARKETING_LINKEDIN_CLIENT_ID`/`_SECRET` (currently blank — integration 501s until
  set), redirect URIs, `MARKETING_LINKEDIN_API_VERSION` (defaults `202502`, bump when tested).
- **Known risk**: this was built from LinkedIn's current public docs but has never been
  exercised against a real LinkedIn Developer app. When a real app is created, verify: the
  exact API products granted ("Share on LinkedIn" vs "Community Management API" have
  different scope names/approval flows), and bump `MARKETING_LINKEDIN_API_VERSION` to
  whatever's current at that time.

## Key files
**Backend (sam-backend)**
- `backend/app/core/config.py` — all provider env vars.
- `backend/app/schemas/marketing.py` — `MarketingIntegrationProvider` literal (now 4 providers).
- `backend/app/services/marketing_social_service.py` — all OAuth build/complete/refresh and
  `_publish_to_*` functions per provider; `publish_scheduled_post` dispatches by
  `platforms` list on the scheduled post row.
- `backend/app/routers/marketing_integrations.py` — `/integrations/marketing/*` routes.

**Frontend (ai-employees-app)**
- `src/lib/voiceAgentApi.ts` — `MarketingIntegrationProvider` type + generic status/auth-url/
  callback/disconnect calls (provider is just a path param, no per-provider branching needed);
  `MarketingIntegrationStatus.account_avatar_url`.
- `src/components/business/IntegrationsTab.tsx` — Marketing Integrations cards (avatar image
  when connected, falls back to the static brand icon) + OAuth callback handling.
- `src/App.tsx` — `/integrations/marketing/{tiktok,linkedin}/callback` routes reuse the
  existing generic `GoogleOAuthCallback` redirector.
- `src/lib/marketingEmployeeMock.ts` — `getTikTokCreatorInfo`, `TikTokPublishOptions`, and
  `tiktok_options` added to `createMarketingScheduledPost`/`publishMarketingPostNow` bodies.
- `src/pages/dashboard/marketing/MarketingCampaignOverview.tsx` — `publishablePlatforms`
  includes `tiktok`; TikTok privacy/interaction `Dialog` shown before Post Now/Schedule
  whenever TikTok is a selected platform (`tiktokDialogOpen` state,
  `openTikTokPublishDialog`/`handleConfirmTikTokPublish`).

## Privacy Policy & Terms of Service
Both public, unauthenticated pages already existed (`src/pages/Legal.tsx`, routes `/privacy`
and `/terms`) before this work — they just weren't linked anywhere reachable pre-login. Added:
- Links to both in the shared `AuthLayout.tsx` footer (visible on Login/Signup/etc. — the
  closest thing this app has to a public homepage, since `/` redirects straight to `/login`).
- "Privacy Policy" and "Terms of Service" links in the dashboard sidebar's Help section
  (`src/components/layout/Sidebar.tsx`), for in-app navigation.
- Updated `/privacy`'s "Connected Services" section to mention TikTok and LinkedIn, and its
  "Contact" section to `support@aiemployeesinc.com` (was a personal email).

These are the URLs to submit as Privacy Policy / Terms of Service in the TikTok/LinkedIn
developer app configs.
