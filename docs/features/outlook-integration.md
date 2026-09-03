# Outlook Email Integration

## What it does
Business Settings → Integrations → Email Integrations → "Microsoft Outlook Email" card lets
a tenant connect a Microsoft Outlook / Microsoft 365 account via OAuth. **Connect-flow only
for now** — connecting/disconnecting and showing status works, but nothing actually sends
mail through Outlook yet. Gmail (`email_service.py`, `gmail_tokens`) remains the only wired-up
sender for appointment confirmations, reminders, staff notifications, and the sales digest.

This started as a pure UI stub (`handleStub` → "coming soon" toast, tracked as Linear AIE-34)
until the client provided a real Azure AD app registration (client id, secret, redirect URI,
Graph API permissions) on 2026-09-03.

## Azure app registration
- Display name: "AI Employees - Outlook Integration"
- Application (client) ID: `4e52c9aa-976a-4fec-898e-a8e37d15c40a`
- Tenant ID: `fa0e222c-9982-4865-91cf-2fe826f62b3e` (not used in code — see "Account type" below)
- Supported account types: "All Microsoft account users" → mapped to the `common` OAuth
  endpoint (accepts both personal Microsoft accounts and work/school org accounts)
- Redirect URI (Web): `https://portal.aiemployeesinc.com/integrations/outlook/callback`
  (the client's screenshot had `//` — confirmed as a typo, must be a single slash in both
  Azure's registered URI and `OUTLOOK_REDIRECT_URI`)
- Microsoft Graph permissions granted (Delegated, admin consent given): `Mail.Send`,
  `offline_access`, `User.Read`. **No `Mail.Read` or `Calendars.ReadWrite`** — those would
  need to be added in Azure + re-consented before requesting them in `OUTLOOK_SCOPE`.

## Data model
`outlook_tokens` table (`ai-employees-app/supabase/migrations/20260903000000_outlook_tokens.sql`)
— same shape as `gmail_tokens`: `business_id`, `location_id` (nullable, one sender per
location, falls back to the business-wide row), `microsoft_email`, `access_token`,
`refresh_token`, `token_expiry`. RLS enabled, no policies — service-role (`supabase_admin`)
access only, same as Gmail.

## OAuth flow (mirrors Gmail exactly)
1. Frontend calls `GET /integrations/outlook/auth-url` → backend builds
   `https://login.microsoftonline.com/common/oauth2/v2.0/authorize` URL with a JSON `state`
   (`user_id`, `business_id`, `location_id`, `return_to`, `integration: "outlook"`).
2. User authorizes on Microsoft's consent screen, gets redirected to
   `/integrations/outlook/callback` — the generic `GoogleOAuthCallback` route in `App.tsx`
   (shared across all OAuth providers) re-navigates to `return_to` carrying `code`/`state`,
   where `IntegrationsTab.tsx`'s callback effect picks it up (branches on
   `parsedState.integration === "outlook"`).
3. Frontend calls `POST /integrations/outlook/callback` with `{code, state, business_id}` →
   backend exchanges the code at `https://login.microsoftonline.com/common/oauth2/v2.0/token`,
   verifies the `Mail.Send` scope was actually granted, fetches the account's email via
   `GET https://graph.microsoft.com/v1.0/me`, and upserts the `outlook_tokens` row.

## Key files
**sam-backend**
- `backend/app/core/config.py` — `microsoft_client_id`, `microsoft_client_secret`,
  `outlook_redirect_uri` settings
- `backend/app/services/outlook_email_service.py` — auth URL builder, token
  exchange/refresh, scope check, `/me` email lookup
- `backend/app/routers/outlook_integrations.py` — `auth-url` / `callback` / `status` /
  `disconnect` endpoints, registered in `main.py`

**ai-employees-app**
- `supabase/migrations/20260903000000_outlook_tokens.sql`
- `src/integrations/supabase/types.ts` — `outlook_tokens` type block (added by hand;
  run `supabase gen types` after the migration is pushed to confirm it matches exactly)
- `src/lib/voiceAgentApi.ts` — `getOutlookAuthUrl` / `completeOutlookOAuth` /
  `getOutlookStatus` / `disconnectOutlook` + `OutlookStatus` type
- `src/components/business/IntegrationsTab.tsx` — real connect/disconnect state and
  handlers, replacing the old `handleStub` call on the Outlook card
- `src/App.tsx` — `/integrations/outlook/callback` route → shared `GoogleOAuthCallback`

## Known limitations / decisions
- **No server-side token revocation.** Unlike Google, Microsoft Graph has no revoke endpoint
  for delegated user consent. "Disconnect" only deletes the local `outlook_tokens` row — the
  user's actual consent grant persists until they remove it themselves at
  https://myaccount.microsoft.com/consents. Worth surfacing in the disconnect UI copy if this
  causes confusion in QA.
- **Send-only scope, and not even wired to send yet.** Scope is intentionally limited to what
  Azure already granted (`Mail.Send`, `offline_access`, `User.Read`) — no calendar or inbox
  reading. This is Phase 1 (connect flow) only; wiring Outlook into the actual transactional
  email call sites (`send_appointment_confirmation`, `send_staff_notification`,
  `send_reschedule_confirmation`, `send_cancellation_confirmation`,
  `report_scheduler.py`'s sales digest) is an explicitly separate, not-yet-scoped follow-up —
  those all still use Gmail exclusively.
- **Migration not yet pushed.** `supabase db push` needs to be run and confirmed separately
  before this works end-to-end (see SESSION_HANDOFF.md).
