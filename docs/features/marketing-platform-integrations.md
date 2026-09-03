# Marketing Platform Integrations (Instagram, X, LinkedIn)

## What it does
Business Settings → Integrations → Marketing Integrations lets a tenant connect its own
social profiles so the Marketing Employee can auto-publish generated campaign assets on a
schedule. Instagram and X shipped first; LinkedIn was added fully wired, but **unverified** —
no LinkedIn Developer app exists yet.

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
- `backend/app/schemas/marketing.py` — `MarketingIntegrationProvider` literal (3 providers).
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
