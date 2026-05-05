# Voice Agent - TODO Tracker

Covers: `sam-backend` (backend + agent) and `ai-employees-app` (frontend)
Last updated: 2026-05-05 (Session 41 — project structure created; billing UI update + per-agent billing in planning)

---

## ✅ Done

### Backend
- [x] FastAPI app with CORS, health check, JWT auth (Supabase)
- [x] `POST /calls/initiate` — creates LiveKit room, call record, returns token
- [x] `GET /calls`, `GET /calls/{id}`, `GET /calls/{id}/transcript`, `GET /calls/{id}/summary`, `GET /calls/{id}/recording`
- [x] `PUT /calls/{id}/status`
- [x] `POST /support/wishlist` — sends Wish List submissions through the business's connected Gmail account
- [x] `GET/PUT /settings/agent/schedule` — persists weekly scheduler state in `business_hours`
- [x] Settings router — 10 feature flag toggles, global on/off, audit log
- [x] Communication settings CRUD (call/email/SMS scripts stored, not sent)
- [x] Forwarding contacts + rules CRUD
- [x] Analytics — summary metrics, call volume trends, call distribution
- [x] LiveKit service — room creation, token generation (user + agent), room deletion
- [x] `USE_LIVEKIT_AGENT` feature flag switch in `/calls/initiate`
- [x] Legacy voice agent worker (`backend/worker/voice_agent.py`) — GPT-4o Realtime, writes transcripts + summaries

### Agent (`agent/agent.py`)
- [x] LiveKit Agents pattern — auto-dispatched by LiveKit Cloud
- [x] Reads participant metadata (business_id, location_id, call_id)
- [x] Builds system prompt from Supabase: business name, locations, global settings, brand voice, staff list
- [x] System prompt includes full business details: type, phone, email, address, website, payment methods, policies, service area
- [x] System prompt includes business hours from `business_hours` table
- [x] System prompt includes services list upfront (no tool call needed for basic "what do you offer?")
- [x] System prompt includes knowledge base text entries from `knowledge_base` table
- [x] **`get_services`** tool — lists active services with duration + price
- [x] **`get_staff_for_service`** tool — staff at a location who can perform a service (reads `user_services`, `user_locations`, `profiles`)
- [x] **`get_available_slots`** tool — computes free slots from `user_availability`, `user_availability_overrides`, existing `appointments`
- [x] **`book_appointment`** tool — inserts into `appointments` table, links `call_id` in notes, stores `client_phone` + `client_email` in dedicated columns
- [x] **`find_appointments`** tool — finds upcoming appointments by client name (ilike search)
- [x] **`update_appointment`** tool — reschedules by ref + client_name; availability check; sends reschedule emails to customer + staff
- [x] **`cancel_appointment`** tool — cancels by ref + client_name; sends cancellation emails to customer + staff
- [x] Preloads locations, services, staff + user_service_ids at call start (no per-tool DB round trips for lookups)
- [x] Post-call: `conversation_item_added` event captures all transcript turns in memory
- [x] Post-call: bulk-saves transcript utterances to `transcripts` table on call end
- [x] Post-call: updates call record — `status=completed`, `ended_at`, `duration_seconds`
- [x] Post-call: GPT-4o chat generates JSON summary → saved to `call_summaries` with `key_topics`, `insights`
- [x] Post-call: updates `calls.sentiment` from summary result

### Bugs Fixed (session 9)
- [x] SIP dispatch rule had `inbound_numbers=[phone_number]` causing calls to ring forever without agent pickup — removed, trunk `numbers` filter is sufficient
- [x] SIP calls created no `calls` DB row — agent now auto-creates the record at session start (status=`active`, caller_phone from SIP attrs)
- [x] `GET /calls` and analytics returned 0 rows — `supabase` anon client has no user JWT set, RLS blocks all reads; switched to `supabase_admin` (auth still enforced via `Depends(get_current_user)` + `business_id` filter)
- [x] Call transcript showed all bubbles as "Customer" — frontend used `msg.role`/`msg.content` but backend sends `msg.speaker`/`msg.text`; fixed type + rendering in `CallRecordings.tsx`

### Bugs Fixed (session 10)
- [x] `calls` INSERT failed with FK violation on `location_id` — dispatch rules had stale `location_id` (`9174e86b...`) deleted from `locations` table; `_create_dispatch_rule` now only stores `business_id` in attributes; agent Source 3 no longer reads `location_id` from SIP attributes
- [x] Location missing from agent greeting — `prompt_builder.py` now falls back to `locations[0]` when `location_id` is None
- [x] Fallback call record creation at finalization — if initial INSERT fails (transient error), retried just before saving transcript
- [x] SIP phone number not E.164 — `_normalize_phone_e164()` strips non-digits and prepends `+1` for North American numbers
- [x] `gmail_tokens.google_email` was empty — manually fixed in DB; emails now send correctly

### Frontend — Outbound Calls (session 11)
- [x] `OutboundCallDialog.tsx` — call type selector (Reminder / Feedback / Follow-up / General)
- [x] Appointment list auto-filters by call type (upcoming vs past) using `useAppointments`
- [x] Auto-fills client phone from appointment; falls back to manual entry if empty
- [x] Agent purpose preview shown before dialing
- [x] Wired to `POST /calls/outbound` via `initiateOutboundCall()`
- [x] Outbound call dialog implementation completed; temporary "New Call" header button on Call Recordings was later removed from the UI

### Bugs Fixed (session 11)
- [x] `GET /settings/agent` used anon `supabase` client → RLS blocked reads → page showed "0 of 0 features" on refresh; switched to `supabase_admin`
- [x] `GET /settings/agent/audit-log` same RLS issue — switched to `supabase_admin`
- [x] `GET /settings/communication` same RLS issue — switched to `supabase_admin`
- [x] Calendar Appointment Details modal missing client phone + email display
- [x] Calendar Edit Appointment modal missing client phone + email fields; not saved on update
- [x] `release_phone_number()` did not delete outbound SIP trunk → orphaned `ST_htrEWVP2hm6P` in LiveKit after releasing +14159935287; fixed by adding outbound trunk cleanup to release flow
- [x] `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` was a single shared env var (wrong for multi-tenant); moved to per-number `livekit_outbound_trunk_id` column in `business_phone_numbers`

### Bugs Fixed
- [x] `ai-employees-app/.env` — stray backtick on `VITE_VOICE_AGENT_API_URL` caused 404 on `/calls/initiate`
- [x] `user_services` RLS — staff could not select their own services; added policy `Users can manage their own service assignments` (migration `20260323000000_user_services_staff_rls.sql`)
- [x] `settings.py` `.maybeSingle()` AttributeError — Python supabase client has no `.maybeSingle()`; fixed to `.limit(1).execute()` + `result.data[0]`
- [x] `calls.py` `.maybeSingle()` AttributeError — same fix in `get_call`, `get_summary`, `get_recording`
- [x] `PUT /forwarding/contacts/bulk/toggle` 500 — FastAPI matched `"bulk"` as UUID param on `/{contact_id}/toggle`; fixed by moving `bulk/toggle` route above `/{contact_id}/toggle` in `forwarding.py`
- [x] `GET /settings/agent/state` 500 duplicate key — regular `supabase` client blocked by RLS returned empty → INSERT failed with unique constraint; fixed by switching SELECT to `supabase_admin` and changing INSERT to `.upsert(on_conflict="business_id")`
- [x] Gmail could show connected but still fail `users.messages.send` with insufficient scopes — Gmail OAuth callback now rejects tokens missing `gmail.send`, and Wish List submission now returns a reconnect-required error instead of a generic 502

### Location-Scoped Phone Plan (session 27)
- [x] LiveKit dispatch rules now store both `business_id` and `location_id` for newly provisioned numbers
- [x] Added `POST /phone-numbers/sync-dispatch` to refresh existing active dispatch rules to the new metadata format
- [x] SIP agent context now keeps the resolved `location_id` authoritative by reading dispatch metadata, SIP attributes, and DB lookup by called number
- [x] Prompt builder no longer falls back to `locations[0]`; the called location is now explicit and treated as the primary branch context
- [x] Appointment lookup, update, and cancellation now search the anchored location first and only expand cross-location when the tool is called with `search_other_locations=true`
- [x] Outbound calling now resolves caller ID and outbound trunk by location and rejects numbers that are not attached to a location
- [x] SMS sender selection now uses the resolved location's number instead of a first business-wide number

### Location-Scoped Architecture (session 28)
- [x] DB migration: `location_id` column added to `business_hours`, `agent_settings`, `agent_state`, `communication_settings`, `forwarding_rules`, `knowledge_base`
- [x] DB migration: `location_services` junction table created (maps services to locations)
- [x] DB migration: backfill script copies business-wide data into location-specific rows for all existing locations
- [x] Partial unique indexes for all migrated tables (location-scoped + legacy NULL rows)
- [x] `location_seed_service.py` — copies business-wide defaults (hours, settings, services, KB) into a new location on creation
- [x] `POST /locations/{id}/seed` endpoint — called by frontend after location creation
- [x] Backend: `location_id` filter added to `GET /calls`, `GET /calls/recent-activity` (2 endpoints)
- [x] Backend: `location_id` filter added to all 3 analytics endpoints (`/summary`, `/call-volume-trends`, `/call-distribution`)
- [x] Backend: `location_id` filter added to all settings endpoints (agent settings, agent state, schedule, communication settings) — uses SELECT+INSERT/UPDATE pattern for partial index compatibility
- [x] Backend: `location_id` filter added to forwarding contacts + rules endpoints
- [x] Agent: `_fetch_business_hours_for_location`, `_fetch_services_for_location`, `_fetch_knowledge_base_for_location`, `_is_feature_enabled_for_location` — no fallback, return empty if not configured
- [x] Agent: prompt builder uses location-scoped hours, services, KB; brand voice stays business-wide (Global Settings)
- [x] Agent: feature flag checks use `_is_feature_enabled_for_location` for SMS decisions
- [x] Agent: services loaded via `location_services` junction table
- [x] Design: NO silent fallbacks — empty data = empty state in UI, not wrong data from another source
- [x] Design: brand voice stays business-wide (part of Global Settings, not location-scoped)

### Custom Schedules (session 28 — current)
- [x] DB migration `20260413000000_custom_schedules.sql` — table + RLS (admin/super_admin write, members read, service_role full access) + partial unique indexes + updated_at trigger + check constraints (one_time vs recurring fields, hours required when not agent-disabled)
- [x] DB migration `20260413000001_custom_schedules_backfill.sql` — copies existing `business_hours_overrides` rows into `custom_schedules` as one-time entries on first location of each business
- [x] DB migration `20260413000002_drop_business_hours_overrides.sql` — drops the old table (run AFTER frontend deploy)
- [x] Backend Pydantic schemas (`backend/app/schemas/custom_schedules.py`)
- [x] Backend CRUD router `/custom-schedules` with `_require_admin` enforcement
- [x] Agent `supabase_helpers._fetch_active_custom_schedule` — picks highest-priority enabled match (one_time date range or recurring day-of-week)
- [x] Agent `prompt_builder` — when active and is_agent_disabled, replaces hours block with closure notice; otherwise overrides today's row in weekly hours
- [x] Agent `agent.py` — when is_agent_disabled active, plays a short "we're closed" message and disconnects after ~6s
- [x] Frontend `useCustomSchedules` hook — CRUD + toggleEnabled + deriveStatus
- [x] Frontend components: `CustomScheduleCard`, `CustomScheduleSidebar`, `CustomScheduleDialog`, `CustomScheduleDetail`
- [x] Frontend `Scheduler.tsx` — 2-column layout, weekly grid on left by default, selected schedule detail when one is clicked, sidebar on right
- [x] Removed `BusinessDateOverrides` component, `useBusinessHoursOverrides` hook, and its rendering in BusinessSettings
- [x] Danger Zone moved from below-tabs standalone section into its own "Danger Zone" tab in BusinessSettings — tab only visible to super_admin, shown in red (session 31)
- [x] Run 3 new migrations in Supabase: `20260413000000`, `20260413000001`, `20260413000002` (applied — see session 28 manual steps)
- [x] Regenerate Supabase TS types after migrations (done — session 28)

### Integrations → Business Settings + Per-Location Gmail (session 28)
- [x] Migration `20260411000001_location_scope_gmail_tokens.sql`: add `location_id` to `gmail_tokens` with partial unique indexes; backfill assigns existing business-wide token to the first location
- [x] Backend `gmail_integrations.py`: auth-url/callback/status/disconnect accept `location_id` (encoded in OAuth state)
- [x] Backend `email_service.py`: `get_token_row` + `get_valid_access_token` accept `location_id`
- [x] Backend `support.py` (Wish List): accepts `location_id` in body
- [x] Agent `_gmail_get_valid_token` + all 6 `_gmail_send_*` helpers accept `location_id`
- [x] Agent `agent.py`: passes `self._location_id` to all Gmail send call sites
- [x] Frontend: `IntegrationsTab` component (refactored from Integrations.tsx) — uses `selectedLocationId` for Gmail
- [x] Frontend: BusinessSettings adds "Integrations" tab; sidebar removes the Integrations item
- [x] Frontend: `getGmailAuthUrl/getGmailStatus/disconnectGmail` accept `locationId`
- [x] Frontend: OAuth `return_to` now points to `/dashboard/settings/business?tab=integrations`
- [x] Frontend: old `/dashboard/settings/integrations` URL redirects to the new tab
- [x] Per-staff Google Calendar card stays (still works the same way)

### Bug Fixes (session 28 — post-migration testing)
- [x] `idx_unique_pending_invitation` duplicate key on re-invite — edge function `invite-location-admin` now cancels existing pending invite before creating new one
- [x] Resend "Failed to send invitation email" generic error — surface actual error reason; roll back invitation row on email failure so retry works
- [x] `location_services` RLS only had SELECT for members — added INSERT/UPDATE/DELETE policies (services were silently failing to map to locations)
- [x] `useTabParam` hook — active tab now persists in URL across refresh; applied to BusinessSettings, GlobalSettings, CustomerServiceSettings, CustomerServiceEmployee

### Location-Scoped Bug Fixes (session 28 — post-migration testing)
- [x] `useBusinessHours` hook — fetch/insert now filter by `location_id`; accepts `locationId` param; `BusinessSettings` passes `selectedLocationId` (fixed cross-location hours leakage)
- [x] `BusinessSettings` Knowledge Base tab — fetch filters by `location_id`; new KB entries include `location_id` on insert
- [x] `Calendar.tsx` — `createAppointment` passes `selectedLocationId` as `location_id` (new appointments now visible in location-filtered view)
- [x] `useServices.createService` — auto-inserts `location_services` row for the selected location so new services show up in the location-filtered list
- [x] `CallForwarding.tsx` — "Add Contact" dialog passes `selectedLocationId` when creating
- [x] `voiceAgentApi.createForwardingContact` — moved `location_id` from query param to body (backend reads it from `CreateForwardingContactRequest`)
- [x] `Locations.tsx` — fixed import (LocationsTab uses default export, not named)

### Frontend — Location-Scoped Architecture (session 28)
- [x] `voiceAgentApi.ts` — `locationId` param added to 17 API functions + `seedLocation` function
- [x] `useAppointments.ts` — filters by `selectedLocationId`
- [x] `useServices.ts` — filters via `location_services` junction table; shows empty if no services mapped
- [x] `LocationEmptyState.tsx` — reusable empty state component for unconfigured location data
- [x] All 5 CS pages (AgentPerformance, CallRecordings, Scheduler, AgentSettings, CallForwarding) pass `selectedLocationId` to API calls
- [x] Sidebar: "Locations" nav item added under Account Settings
- [x] `Locations.tsx` — standalone Locations page (moved from tab in Business Settings)
- [x] `BusinessSettings.tsx` — Locations tab removed (now its own page)
- [x] `LocationsTab.tsx` — calls `seedLocation` after creating a new location
- [x] `Onboarding.tsx` — calls `seedLocation` after `createBusinessWithLocation`
- [x] `useLocationServices` hook + `LocationServicesTab` component for toggling services per location

### Frontend (`ai-employees-app`)
- [x] React 18 + TypeScript + Vite + shadcn-ui + Tailwind
- [x] Supabase Auth with MFA/TOTP support
- [x] ProtectedRoute + role-based access (super_admin, admin, user)
- [x] Onboarding flow (2-step: business + location creation)
- [x] Select location screen (persisted in localStorage)
- [x] Dashboard layout with sidebar navigation
- [x] `/dashboard/customer-service` — voice agent UI: setup checklist, test call button, agent activity log
- [x] Customer Service module — 5-page nested layout with CS sub-sidebar (`CustomerServiceLayout`)
- [x] CS1 — Agent Performance dashboard: stat cards, call volume area chart, call distribution donut, response time bar chart, recent activity feed
- [x] CS2 — Call Recordings & Transcripts: searchable call list, transcript/summary/insights tabs, audio playback bar, chat-bubble transcript view
- [x] CS3 — AI Agent Scheduler: agent toggle, per-day schedule with time selectors, custom schedules, quick presets
- [x] CS4 — Call Forwarding: contact list with role/priority badges, forwarding rules, quick actions, today's stats
- [x] CS5 — AI Agent Settings: feature toggles grouped by category, configuration presets, recent changes
- [x] Reusable `StatCard` component (`components/ui/stat-card.tsx`)
- [x] Reusable `FeatureToggleRow` component (`components/ui/feature-toggle-row.tsx`)
- [x] Dashboard layout max-width constraint removed — all pages now use full available width
- [x] LiveKit client integration — Room(), mic enable, remote audio via Web Audio API
- [x] Brand voice wizard (5-step: tone, style, vocabulary, do-not-say, review)
- [x] Global settings page (language, region, date/time format)
- [x] Communication settings page UI (call/email/SMS scripts) — UI only, no DB save yet
- [x] Team management (invite, roles, permissions, location assignments)
- [x] `voiceAgentApi.ts` — `/calls/initiate`, `/calls/recent-activity`
- [x] Account Settings copy tweak — Google Calendar section renamed to "My Google Calendar"
- [x] Help navigation — added `Wish List` item and wired wishlist submissions through the backend using the business's connected Gmail account
- [x] Customer Service analytics page title renamed from "Agent Performance" to "Customer Service Agent Performance"
- [x] Customer Service scheduler page title renamed from "AI Agent Scheduler" to "Customer Service Agent Scheduler"
- [x] Customer Service settings page title renamed from "AI Agent Settings" to "Customer Service Agent Settings"
- [x] Customer Service settings header no longer shows the temporary Reset to Default and Save Changes buttons
- [x] Customer Service settings page no longer shows the Active Features / Configuration summary strip
- [x] Customer Service settings page no longer shows the right-side Quick Actions, Configuration Presets, Recent Changes, and Help panels
- [x] Customer Service scheduler header no longer shows the temporary `New Schedule` button
- [x] Customer Service weekly scheduler now loads and saves real business hours; the summary cards reflect saved schedule data instead of a fake save toast
- [x] Customer Service scheduler no longer shows the extra Quick Presets and This Week side panels
- [x] Call Forwarding page no longer shows the extra right-side cards for rules, quick actions, statistics, and help
- [x] Call Recordings page header no longer shows the temporary `New Call` button
- [x] Call Recordings detail toolbar now keeps only the Download action; Share and more-actions buttons were removed
- [x] **Calendar page** — fully implemented, month/week/day/list views, full CRUD (`Calendar.tsx`, 824 lines)
- [x] **Calendar list view enhancements** — month/week/day/list switcher shown beside "Make Appointment" plus date-range filter in list view; CSV export button was later removed
- [x] **Appointments** — `useAppointments.ts` full CRUD, saves to `appointments` table in Supabase
- [x] **Services** — `useServices.ts` full CRUD + `ServicesTab.tsx` UI, saves to `services` table
- [x] **Staff ↔ Services mapping** — `useUserServices.ts` full CRUD, saves to `user_services` table
- [x] **Staff working hours** — `useTeamMemberAvailability.ts` + `useUserAvailability.ts`, saves to `user_availability` table
- [x] **Staff time off / date overrides** — `user_availability_overrides` table, full CRUD + UI (TeamMemberHoursDialog, DateOverrideModal)
- [x] Employee placeholder pages — Marketing, Sales, HR, and Executive routes now show a dedicated "Coming Soon" page instead of the generic dashboard
- [x] Main dashboard route now shows a simple "Coming Soon" placeholder instead of mock analytics content
- [x] Phone Numbers page now groups numbers by location, enforces one-number-per-location assignment in the UI, and highlights legacy numbers missing a location link
- [x] Outbound call UIs now automatically use the appointment location or currently selected location instead of letting users pick a mismatched business-wide number
- [x] Phone Numbers page now includes a per-location `Test with Web Call` action that launches a browser call using that row's `location_id` and clearly labels it as an agent-context test, not a PSTN routing test

---

## 🔄 In Progress

### Manual Steps Required
- [x] Run all SQL migrations (20260410000000–20260413000003) — all applied
- [x] Deploy `invite-location-admin` edge function
- [x] Regenerate Supabase TypeScript types (done twice — after location-scope + after custom_schedules)
- [x] Run `20260414000000_audit_log_location_id.sql` — applied
- [x] Run `20260414000001_backfill_null_appointments.sql` — applied
- [x] Regenerate TS types — done; settings_audit_log includes location_id; tsc clean
- [x] **Run migration** `20260416000000_businesses_soft_delete.sql` in Supabase — applied
- [x] **Us + client:** reconfigure `aiemployeesinc.com` DNS on Hostinger for Resend — **DONE** (domain verified in Resend Apr 16 8:00 PM). Next: confirm Supabase SMTP "From address" is `@aiemployeesinc.com` + test forgot-password email.
- [x] **Google sign-in** — working (session 33)
- [x] **Sign-up flow** — working after Resend SMTP fix (session 33)
- [ ] **Client task:** complete A2P 10DLC registration for SMS 2FA (`docs/SMS_2FA_SETUP.md`)
- [x] **Client task:** enable Call Transfers on Twilio trunk — done session 32
- [ ] Merge `feature/location-scoped-architecture` branch to main (sam-backend)
- [ ] **E2E test Option C** — make real SIP call to Mirage (+14157077538) or Downtown (+14158559408), ask agent to transfer to a forwarding contact, confirm caller is bridged and `calls.status=forwarded` + `forwarded_to` is set in DB
- [x] **Auth emails fixed** — Resend DNS verified on Hostinger, Supabase SMTP password set, edge function `RESEND_API_KEY` secret set. All auth emails + team invitations now working (session 32)
- [x] **Gmail OAuth fixed** — `GoogleOAuthCallback` double-`?` URL bug fixed; OAuth flow now correctly passes `code` + `state` to IntegrationsTab (session 33)
- [x] **Agent services fallback removed** — `_fetch_services_for_location` no longer falls back to all-business services when `location_id` is None; returns empty + warning log instead (session 33)
- [x] **Null-location data cleanup** — migration `20260417000001_cleanup_null_location_rows.sql` created; run `supabase db push` in `ai-employees-app`
- [x] **Migrations moved to correct dir** — `20260416000001_calls_forwarded_to.sql` + `20260417000000_appointments_call_tracking.sql` moved to `ai-employees-app/supabase/migrations/`; run `supabase db push`
- [x] **Run `supabase db push`** — all 3 migrations applied: `20260416000001`, `20260417000000`, `20260417000001`
- [ ] **Run `POST /phone-numbers/sync-dispatch`** — re-stamps dispatch rules with `location_id` so agent resolves correct location on inbound SIP calls
- [ ] **httpx stale connection** — `verify_business_access` now retries once on `RemoteProtocolError`; monitor if issue recurs

### Client Call — 2026-04-16 Action Items
Priority items from call with client (Charles + Rahul):

**CRITICAL — blocking client testing (all same root cause — no code change needed):**
- [ ] Fix all auth emails (forgot password, sign-up, Google sign-in, team invites) — ALL use Resend with `aiemployeesinc.com` domain. Supabase Auth SMTP configured in Supabase dashboard to use Resend. Edge function sends from `notifications@aiemployeesinc.com` + `invites@aiemployeesinc.com`. DNS moved Ionos → Hostinger so Resend domain verification is broken. Fix: add Resend DKIM/SPF/DMARC records in Hostinger DNS → verify in Resend dashboard. Verified in `supabase/functions/invite-location-admin/index.ts`.

**Agent — location isolation (client confirmed: keep strictly separate):**
- [x] Verify agent only shows services from the specific called location — no cross-location service bleed. Fixed: `_fetch_services_for_location` scopes by `location_services` junction; staff filtered to called location at load time.
- [x] If caller asks about services at another location, agent should offer that location's phone number (not book across locations). Fixed: `get_staff_for_service` blocks cross-location lookups; new `get_other_location_phone` tool looks up PSTN number from `business_phone_numbers`.
- [x] Remove cross-location appointment booking from agent if currently present. Fixed: staff `_staff_by_name` map only contains current-location staff; `get_staff_for_service` returns redirect message for other branches.

**Already done (confirmed on call):**
- [x] Tutorials removed from sidebar
- [x] Soft delete / account deactivation (business archive with 90-day grace period)
- [x] Deactivation modal correctly asks for business name — confirmed "Downtown" is the actual business name (Downtown Barber Shop), not a location name. No bug.

**Deferred by client:**
- [x] Integrations search bar — added to IntegrationsTab; filters by name + description across all sections, collapses empty sections, shows "no results" message (session 31)
- [ ] Roles & Permissions v2 (custom role creation) — client confirmed only super_admin/admin can create roles. Deferred.

### Business Authorization Hardening (session 29)
- [x] `verify_business_access(user_id, business_id)` helper in `backend/app/core/auth.py` — queries `user_roles`, returns role or raises 403
- [x] `require_business_access()` dependency factory — reads business_id from query/path params, enforces membership
- [x] `calls.py` — list/recent/get/transcript/summary/recording/status/initiate endpoints now verify caller owns the business; added `_verify_call_access` helper for resource-ID endpoints
- [x] `analytics.py` — all endpoints switched to `require_business_access()`
- [x] `settings.py` — all GET/PUT endpoints (agent, schedule, state, communication, audit-log) enforce business access
- [x] `forwarding.py` — list/create endpoints use `require_business_access()`; update/delete/toggle look up the resource's business_id and verify; added `_verify_contact_access`/`_verify_rule_access` helpers
- [x] `integrations.py` (Google Calendar) — auth-url/status/disconnect all verify business access
- [x] `gmail_integrations.py` — auth-url/status/disconnect all verify business access
- [x] `support.py` — wishlist endpoint uses standardized `verify_business_access`
- [x] `custom_schedules.py`/`locations.py`/`phone_numbers.py` already derive business_id from user's own `user_roles` row → inherently safe (no user-supplied business_id trusted)
- [x] `ast.parse` syntax check clean on all 8 modified files
- Note: still need manual smoke test — hit a user's endpoint with another business's ID and confirm 403

### Location-Scope Audit Findings — Fixed (session 28)
- [x] **Critical:** Agent `book_appointment` now falls back to `self._location_id` when location resolution fails (no more NULL location_id)
- [x] **Medium:** `bulk_toggle_contacts` accepts location_id and filters
- [x] **Medium:** `settings_audit_log` includes location_id; GET endpoint filters by it; AgentSettings page passes selectedLocationId
- [x] **Low:** `useAppointments` skips fetching when no location selected (was returning all-business data)
- [x] **Low:** `_get_business_number` deterministic ordering (oldest active first)
- [x] **Low:** Migration to backfill old NULL-location appointments
- See `docs/audits/2026-04-14-location-scope-audit.md` for full audit + remaining low-severity item (#7)

### Testing
- [x] Select Location A → verify all pages show only Location A data (business hours bug found + fixed)
- [x] Add services per location → verify they persist after refresh (RLS bug found + fixed)
- [ ] Create new location → verify seed runs and location has hours/settings/services
- [ ] Inbound call → verify agent uses location-scoped hours/services/settings
- [ ] Switch location → verify Gmail integration is per-location (after migration runs)
- [ ] Re-invite same email → verify it succeeds (after edge function deployed + Resend domain verified)

### Testing — Custom Schedules (after migrations run)
- [ ] Create one-time schedule "Holiday Hours" Dec 24–26, 10 AM – 2 PM → shows as Scheduled, then Active on Dec 24, then Ended Dec 27
- [ ] Create recurring "Every Friday" 8 AM – 8 PM → shows Active year-round
- [ ] Create "Maintenance" one-time with Agent Disabled → card shows "Agent Disabled"
- [ ] Toggle a schedule off → status badge becomes Disabled, agent stops applying it
- [ ] Delete a schedule → card disappears, detail pane clears
- [ ] Agent call during active Agent-Disabled schedule → agent says closure message, hangs up within ~6s
- [ ] Agent call during active custom-hours schedule → prompt's hours block reflects the override for today
- [ ] Agent call outside any active schedule → weekly hours unchanged, normal behavior
- [ ] Two overlapping schedules (priority 200 vs 100) → priority 200 wins
- [ ] Non-admin user tries to create a schedule → RLS blocks (403)
- [ ] Switch selected location → sidebar refreshes with that location's schedules only
- [ ] Old `business_hours_overrides` rows appear as one-time custom_schedules after backfill
- [ ] Business Settings → Business Hours tab no longer shows the old Date Overrides section

### QA Sessions 1–7 — Complete (2026-04-29)
- [x] **51 tests run** — 34 passed, 5 failed (3 false-fails, 2 real bugs), 13 blocked
- [x] Sessions 1–3: Calendar, Profile Settings, Business Settings — all ✅
- [x] Sessions 4–5: Global Settings, Team Management, Roles & Permissions, Phone Numbers, Locations — verified; 2 real bugs found
- [x] Session 6: CSE structural page checks ✅; AI behavior tests 🔲 BLOCKED (voice-only)
- [x] Session 7: TC-ROLES-002 retest (still failing — new root cause: stale closure); TC-TEAM-006 blocked; Support email functional (409 Gmail not connected expected)
- [x] **TC-ROLES-002** ✅ FIXED — `togglePermission` now receives `roleId` explicitly from `selectedRole.id` at call site; null-safety guard added (session 40)
- [x] **TC-TEAM-006** ✅ FIXED — AlertDialog confirmation with `isRemoving` guard + Escape-key protection (session 40)
- [ ] **DB cleanup** — delete "QA Test Role" (id: fb9b7b29-aaf9-443f-a99a-275e325e12bd) + "QA Test Location" from Supabase
- [ ] **AI behavior tests** — permanently blocked headlessly; must test via live voice call or "Test with Web Call" button in browser

### Roles & Permissions — PLANNED, NOT YET SHIPPED
Full plan doc: `docs/superpowers/plans/2026-04-14-roles-permissions.md`

Phase 1-5 (v1 — SHIPPED session 28):
- [x] Shared `roles.ts` constants (ROLE_LABELS, ROLE_OPTIONS, RESTRICTED_PAGES, canAccessPath)
- [x] Sidebar uses shared map; Locations + Phone Numbers now Admin-only per client spreadsheet
- [x] `ProtectedRoute` enforces role-based page access (redirects to /dashboard on URL-guessing)
- [x] Team Management: "Permissions" → "Manage Services" dialog (per-staff service assignment via user_services); role labels everywhere show Admin/Manager/Team Member
- [x] Roles & Permissions read-only page at /dashboard/roles-permissions (permissions matrix + role cards + disabled "New Role" placeholder)
- [x] Backend: `require_role()` in auth.py; refactored custom_schedules.py to use it

Phase 6 (v2 — SHIPPED session 38):
- [x] `custom_roles` + `role_page_permissions` tables (migrations 20260428000001–000003)
- [x] Dynamic sidebar + ProtectedRoute from DB-driven permissions (`useRolePermissions` hook)
- [x] Roles & Permissions page fully editable (CRUD for custom roles, toggle checkboxes)
- [x] `custom_role_id` added to `user_roles` + `location_invitations`; invite dialog shows custom roles
- [x] Backend: `roles.py` router + `schemas/roles.py` (GET/POST/DELETE roles, GET/PUT permissions)
- [ ] **Pending:** run migrations 20260428000001–000003 + deploy edge functions

### Awaiting Decision
- [ ] **SMS 2FA support** — extend `TwoFactorSetup.tsx` to support SMS codes alongside Authenticator App. Blocked on Twilio A2P 10DLC campaign approval (client doing this). Setup guide for client: `docs/SMS_2FA_SETUP.md`. Once approved + Supabase Phone provider is configured: add method picker → SMS enroll/verify flow → list both factor types → update `Login.tsx` for phone challenge.

### Editable SMS Templates + Appointment Management Settings (session 28)
- [x] `FeatureToggleRow` — added optional `onEdit` prop (pencil icon button)
- [x] `AgentSettings.tsx` — feature toggles now auto-save to backend immediately on flip (no global Save button exists anymore)
- [x] SMS template editor: "Send Texts During or After Calls" + "Missed Call Text-Back" each have an Edit button → dialog with message textarea + `{{placeholder}}` reference → saved directly to `config_value.message_template` in `agent_settings`
- [x] Agent `sms_helpers.py` — `send_appointment_confirmation_sms` + `send_missed_call_sms` accept `custom_template`; substitute `{{placeholders}}` if provided, else use hardcoded default
- [x] Agent `supabase_helpers.py` — `_get_feature_config_value()` reads `config_value` JSONB for a feature at the location level
- [x] Agent `agent.py` — both SMS call sites fetch config_value and pass `message_template` to the helpers
- [x] Removed "Callback Scheduling" feature from the list
- [x] Renamed "Confirmation & Cancel Calls" → "Reminder Calls" with updated description
- [x] Updated "Reschedule / Cancel Appointments" description to reflect automatic outbound calling post-cancellation
- [x] Both appointment features have Edit buttons → dialog with "days before/after" number + message/script textarea → saved to `config_value.days` + `config_value.message_template`
- [x] No migration needed — `config_value JSONB` column already exists on `agent_settings`

### Call Forwarding — Option B (Rules + Verbal Direction) — SHIPPED session 28
- [x] Migration `20260413000003_forwarding_contact_rule.sql` — adds `forwarding_rule TEXT` column
- [x] Backend schemas accept + return `forwarding_rule`
- [x] Backend `create_contact` persists the field (update already did via `exclude_none`)
- [x] Agent `_fetch_forwarding_contacts` returns enabled contacts for called location
- [x] Agent `_format_forwarding_contacts` adds a prompt block telling the agent to verbally direct callers to the matching contact
- [x] Frontend: Edit pencil button wired (was a dead button); opens dialog with Name / Title / Phone / Rule
- [x] Frontend: Add Contact dialog also gets Title + Rule fields
- [x] Run `20260413000003_forwarding_contact_rule.sql` — applied
- [x] Supabase TS types regenerated (includes forwarding_rule + custom_schedules)

### Call Forwarding — Option C (Real SIP Transfer) — SHIPPED session 32
- [x] Twilio trunk: Call Transfer (SIP REFER) enabled, Caller ID = Transferee, PSTN Transfer enabled
- [x] Migration `20260416000001_calls_forwarded_to.sql` — `forwarded_to UUID REFERENCES forwarding_contacts(id)` — applied
- [x] `livekit_service.py` — `transfer_sip_participant(room, identity, transfer_to)` wrapper
- [x] `prompt_builder.py` — forwarding contacts include `contact_id`; instruction tells agent to call `forward_call(contact_id)` after confirming with caller
- [x] `agent.py` — `forward_call(contact_id)` tool: looks up contact, sends SIP REFER via LiveKit, sets call `status=forwarded` + `forwarded_to` in DB
- [x] `agent.py` — `_finalize_call` skips status overwrite if already `forwarded`

### Pricing Strategy Research (session 35)
- [x] Full platform analysis — feature inventory, tech stack, target customer documented in `docs/PRICING_STRATEGY.md`
- [x] Twilio pricing researched — phone numbers ($1.15/mo), SIP trunking inbound ($0.0011/min), outbound ($0.0034/min), SMS ($0.012/msg total)
- [x] LiveKit pricing researched — agent session minutes ($0.01/min dominant cost), WebRTC caller ($0.0005/min), Ship plan $50/mo with 5,000 agent min
- [x] OpenAI Realtime API pricing researched — GPT-4o full ($0.29/call avg 3min), GPT-4o mini ($0.09/call avg 3min); mini is 68% cheaper
- [x] Supabase pricing researched — Pro $25/mo + Large compute $100/mo = $125/mo shared platform cost; negligible per-customer above 30 customers
- [x] Cost per call model built — total COGS ~$0.13/call (mini) or $0.33/call (full GPT-4o) for 3-min avg call
- [x] Pricing floor analysis — $100/mo flat viable only with GPT-4o mini + ~150-200 call cap; losing money at 300+ calls with full model
- [x] 4 pricing options documented: tiered buckets, usage-based, flat unlimited, per-location
- [x] Competitive analysis — Numa, Smith.ai, Retell, Bland.ai, GoHighLevel; $99-349 tiers are below-market for SMB AI receptionist
- [x] Recommended first launch: Starter $99 (150 calls), Growth $199 (400 calls, 3 locations), Pro $349 (800 calls, 5 locations) — 61-71% gross margin
- [x] Full document saved: `docs/PRICING_STRATEGY.md`

### UI Fixes (session 36 — client feedback)
- [x] `AgentSettings.tsx` — completed "No-Show Follow-Up" feature: added `noshow_followup` to `APPOINTMENT_FEATURES`, `EDITABLE_FEATURES`, dialog description, textarea placeholder; backend `reset_agent_settings` now includes `noshow_followup: True` in defaults
- [x] `AgentSettings.tsx` — removed "Feedback After the Call (1-5)" from Advanced Features section (client request)
- [x] `MyServicesSection.tsx` — hide price display when `price <= 0`; fixes `$-1.00` showing for services with "Price varies" toggled on

### Business Hours / Scheduler UI Fixes (session 35 — client feedback)
- [x] `CustomScheduleSidebar.tsx` — added "Regular Hours" card at top of right sidebar; shows green "Active" badge + green border when no custom schedule is enabled; dims with opacity when a custom schedule overrides it; "Edit in Business Settings →" link navigates to Business Hours tab
- [x] `Scheduler.tsx` — time formatting now respects `business.time_format` (12h/24h from Global Settings); `buildTimeOptions(use24h)` helper generates correct labels; `formatDisplayTime()` replaces hardcoded 12h `toMeridiemTime`
- [x] `Scheduler.tsx` — Weekly Schedule card subtitle now shows "Synced with Business Settings → Business Hours" as a clickable link (makes the data connection explicit to the user)
- [x] `Scheduler.tsx` — passes `defaultHoursLabel` and `onEditDefaultHours` to sidebar; imports `useNavigate`
- [x] `BusinessSettings.tsx` — Business Hours tab header now shows "Used by AI Agent Scheduler" badge to make the connection clear
- [x] `BusinessSettings.tsx` — `timeOptions` expanded from 24 hourly slots to 48 half-hour slots; format-aware labels (12h AM/PM or 24h) based on `business.time_format`

### Pre-Release Checklist Fixes (session 36–37 — shipped)
- [x] **Migration** `20260428000000_forwarding_contact_hours.sql` — `available_start`/`available_end` TEXT added to `forwarding_contacts` — applied via `supabase db push`
- [x] Backend schemas — `available_start`/`available_end` added to all 3 Forwarding Contact schemas (`ForwardingContactResponse`, `CreateForwardingContactRequest`, `UpdateForwardingContactRequest`)
- [x] Frontend type — `available_start?`/`available_end?` added to `ForwardingContact` in `voiceAgentApi.ts`; also added to `createForwardingContact` + `updateForwardingContact` data param types (spec fix session 37)
- [x] Frontend UI — Add/Edit Contact dialogs in `CallForwarding.tsx` have time pickers; contact cards show "Available HH:MM – HH:MM UTC" when set
- [x] Agent — `_is_within_available_hours()` in `supabase_helpers.py`; `forward_call` checks contact's hours before SIP REFER and returns polite refusal if outside window
- [x] Setup checklist — `CustomerServiceEmployee.tsx` derives completion from real API data (phone number, schedule, forwarding contacts, Gmail, services, recent calls); clicks navigate to relevant pages; Gmail check fixed to use `s.connected` (not `s.is_connected`)
- Full plan: `docs/superpowers/plans/2026-04-28-pre-release-checklist-fixes.md`

### Future Features — Not Yet Started
- [x] **TC-ROLES-002** ✅ FIXED session 40 — see QA section above
- [x] **TC-TEAM-006** ✅ FIXED session 40 — see QA section above
- [ ] **SMS 2FA UI** — method picker + SMS enroll/verify in TwoFactorSetup.tsx + Login.tsx phone challenge. Blocked on client A2P 10DLC approval. ~1 day.
- [x] **Call Forwarding Option C** — real SIP REFER transfer. Shipped session 32.
- [x] **Roles & Permissions v2** — custom roles with DB-driven permissions. Shipped session 38. Plan: `docs/superpowers/plans/2026-04-28-custom-roles-v2.md`.
- [x] **Reminder Calls / Reschedule Calls runtime** — APScheduler cron inside FastAPI lifespan; `scheduler_service.py` with `run_reminder_calls` + `run_reschedule_calls`; agent uses `message_template` for outbound opener. Migration `20260417000000_appointments_call_tracking.sql` (apply manually). Shipped session 33.
- [x] **Communication Settings save** — wired to `GET/PUT /settings/communication` with location_id. Loads on mount, merges with defaults, Save button works. Page renamed to "Communication Settings".
- [x] **`.ics` calendar attachment** — confirmation + reschedule emails now include `appointment.ics`. Uses same UID (confirmation ref) so reschedules update the original calendar event.
- [x] **Call recording** — LiveKit Egress → Supabase Storage S3. Agent starts/stops egress per call, writes `recordings` row. Frontend audio player wired with real `<audio>` element, progress bar (seekable), download button. Signed URL via `supabase_admin`. Shipped session 34.
- [ ] **Merge `feature/strip-integration` → main** (both repos) — all TC fixes + Stripe + booking validation ready
- [ ] **Update BILLING_SUCCESS_URL + BILLING_CANCEL_URL** in `backend/.env` on server → `http://116.202.210.102:20252/...`
- [ ] **`docker compose up --build -d`** after backend merge
- [ ] **Fix Resend DNS on Hostinger** — recurring; Sam deletes TXT records when editing MX; SPF must include Google + Resend; re-add DKIM/SPF/DMARC
- [ ] **Billing UI update** — new pricing table (5 tiers, minutes-based, overage section). Project: `docs/projects/billing-ui-update/`
- [ ] **New Stripe price IDs** — Growth ($149) + Professional ($299) need new Stripe prices; update `PLAN_KEY_MAP` in `billing.py`
- [ ] **Per-agent billing** — future sprint. Project: `docs/projects/per-agent-billing/`
- [ ] **HTTPS / domain setup** for production mic access (getUserMedia requires secure context). Ops task.
- [ ] **Backend appointment/service API endpoints** — frontend queries Supabase directly; backend is unaware. ~1 day.
- [x] **Business authorization check** — `verify_business_access` + `require_business_access()` enforced across 7 routers (session 29)

---

## 📋 TODO

### Agent — Appointment Update/Cancel Fixes ✅ DONE (session 7-8)

#### Step 1 — DB Schema
- [x] Migration `20260327000000_appointments_client_contact.sql`: add `client_email TEXT DEFAULT ''` column to `appointments`
- [x] Migration `20260327000000_appointments_client_contact.sql`: add `client_phone TEXT DEFAULT ''` column to `appointments`

#### Step 2 — book_appointment improvements
- [x] Store `client_email` in its own column when inserting appointment row
- [x] Store `client_phone` in its own column (removed from `notes`)
- [x] Made email collection required in agent instructions and as required `book_appointment` param

#### Step 3 — update_appointment fixes
- [x] Added `client_name` param — DB filters by name first (ilike), then Python prefix-matches ref on ≤50 rows
- [x] Added availability check: if rescheduling to an already-booked slot, returns error asking agent to check availability first
- [x] Send reschedule confirmation email to customer (reads `client_email` from DB row)
- [x] Send reschedule notification email to assigned staff member
- [x] Fixed UUID ILIKE bug — PostgREST doesn't support `id::text` cast in filter; reverted to Python-side prefix match with DB-level name filter

#### Step 4 — cancel_appointment fixes
- [x] Added `client_name` param — same efficient lookup as update_appointment
- [x] Send cancellation confirmation email to customer (reads `client_email` from DB row)
- [x] Send cancellation notification email to assigned staff member
- [x] **Soft delete** — cancel sets `status = 'cancelled'` instead of hard DELETE; row kept for analytics
- [x] Migration `20260327000001_appointments_status.sql`: add `status TEXT DEFAULT 'confirmed'` column
- [x] `find_appointments`, `update_appointment`, `cancel_appointment` lookups all filter `.neq("status", "cancelled")`
- [x] `_fetch_appointments_on_date` (availability check) also excludes cancelled rows
- [x] Frontend `useAppointments.ts` — added `.neq("status", "cancelled")` filter so cancelled appointments no longer show in Calendar

#### Note on existing appointments
- Old appointments (booked before migration) have `client_email = ''` so reschedule/cancel emails won't fire for them — expected. All new bookings will have it stored.

---

### Backend — Appointment & Service API Endpoints
These don't exist yet on the backend (frontend queries Supabase directly — backend is unaware):
- [ ] `GET/POST /appointments` — list + create
- [ ] `GET/PUT/DELETE /appointments/{id}` — detail, update, cancel
- [ ] `GET /appointments/availability` — available slots for a staff member on a date
- [ ] `GET/POST/PUT/DELETE /services` — service CRUD
- [ ] `GET /services/{service_id}/staff` — staff who offer this service

### Backend — Business Authorization
- [x] Add business_id authorization check — done in session 29 via `verify_business_access`/`require_business_access`

### Communication Settings — Fix Frontend Save
- [x] `CustomerServiceSettings.tsx` — "Save All Settings" wired to `PUT /settings/communication` (shipped in commit 87b6bab, verified session 29)

### Phone / Twilio + LiveKit SIP Integration

**Architecture decision:** Twilio Elastic SIP Trunking (not TwiML webhooks).
- One shared Twilio SIP trunk for all businesses
- One LiveKit inbound SIP trunk (matches Twilio)
- One LiveKit dispatch rule **per phone number** → carries only `{business_id}` in attributes (location_id removed to avoid stale FK issues)
- Business context flows: dispatch rule metadata → agent `ctx.job.metadata` → same context loading as web calls
- Outbound: `CreateSIPParticipant` API (agent in room first, then dial customer in)

#### Step 0 — One-time Infrastructure Setup (done once by dev, not per business)
- [x] `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` added to `backend/.env` (fixed typo from TWILLIO → TWILIO)
- [x] `scripts/setup_sip_trunks.py` written — fully automated setup script:
  - Creates LiveKit inbound SIP trunk (Twilio → LiveKit, with IP allowlist + digest auth)
  - Creates LiveKit outbound SIP trunk (LiveKit → Twilio termination domain)
  - Creates Twilio Elastic SIP Trunk
  - Adds LiveKit SIP endpoint as origination URI on Twilio trunk
  - Creates Twilio credential list for outbound auth (LiveKit → Twilio)
  - Assigns credential list to Twilio trunk
  - Outputs all IDs + secrets ready to paste into `.env`
- [x] `backend/.env.example` updated with all new Twilio/SIP env var placeholders
- [x] **RUN `python scripts/setup_sip_trunks.py`** — all IDs filled in `backend/.env`

#### Step 1 — Database Migration
- [x] Migration file: `supabase/migrations/20260328000000_business_phone_numbers.sql`
  - `business_phone_numbers` table with all columns + indexes
  - RLS: members can SELECT their own business's numbers; only service role can write
- [x] **RUN migration in Supabase** — applied

#### Step 2 — Backend: Phone Number Service (`backend/app/services/phone_number_service.py`)
- [x] `search_available_numbers(area_code, country, limit)` — Twilio available numbers API
- [x] `provision_phone_number(business_id, location_id, phone_number)` — purchase Twilio number, create LiveKit dispatch rule, create/update outbound trunk, insert DB row
  - Bug fixed: removed `inbound_numbers=[phone_number]` from dispatch rule — trunk's `numbers` filter is sufficient; the extra filter caused calls to keep ringing without agent pickup
- [x] `release_phone_number(phone_number_id)` — delete dispatch rule, release Twilio number, soft-delete DB row
- [x] `get_phone_numbers_for_business(business_id)` — returns active numbers for a business

#### Step 3 — Backend: Phone Number API Routes (`backend/app/routers/phone_numbers.py`)
- [x] `GET /phone-numbers/search?area_code=415&country=US`
- [x] `POST /phone-numbers/provision` — body: `{phone_number, location_id?}`
- [x] `GET /phone-numbers` — list active numbers for authenticated business
- [x] `DELETE /phone-numbers/{id}` — release number
- [x] Router registered in `main.py`; Twilio vars added to `config.py`

#### Step 4 — Agent: SIP Inbound Context Reading + Call Record Creation
- [x] Source 1: `ctx.job.metadata` (dispatch rule attributes — primary for SIP)
- [x] Source 2: `participant.metadata` (backend token — web call path, unchanged)
- [x] Source 3: `participant.attributes` (SIP participant attrs from dispatch rule)
- [x] Source 4: DB lookup by `sip.trunkPhoneNumber` (last resort)
- [x] Detect `sip.callDirection` — `"inbound"` or `"outbound"`
- [x] Outbound calls use different `generate_reply()` opener (introduce self + purpose)
- [x] SIP call record auto-created at session start (so calls appear in website logs with transcript + summary)

#### Step 5 — Frontend: Phone Number Picker in Onboarding
- [x] `voiceAgentApi.ts` — added `searchPhoneNumbers`, `provisionPhoneNumber`, `getPhoneNumbers`, `releasePhoneNumber`
- [x] `PhoneNumberStep.tsx` — area code search, selectable results list, provision + "Skip for now"
- [x] `Onboarding.tsx` — 3-step flow: business → location → phone number
- [x] `useOnboarding.ts` — `createBusinessWithLocation` now returns `{business_id, location_id}`; added `finishOnboarding()` for navigation

#### Step 6 — Frontend: Phone Number Management Page
- [x] `PhoneNumbers.tsx` — `/dashboard/settings/phone-numbers`
  - Lists active numbers with Active badge + formatted display
  - Empty state with "Get a phone number" CTA
  - Inline number picker (area code search → select → provision)
  - Release button with AlertDialog confirmation
- [x] Route registered in `App.tsx`
- [x] "Phone Numbers" added to Sidebar under Settings (admin + super_admin)

#### Step 7 — Outbound Calls (follow-up / reminder calls)
- [x] `livekit_service.create_sip_participant()` — dials PSTN number into a LiveKit room via outbound SIP trunk
- [x] `POST /calls/outbound` — looks up business's from_number → create room → dispatch agent (outbound metadata) → SIP dial → DB record
- [x] `OutboundCallRequest` / `OutboundCallResponse` schemas added
- [x] `initiateOutboundCall()` added to `voiceAgentApi.ts`
- [x] Agent already handles `call_direction == "outbound"` opener (Step 4)
- [x] Frontend `OutboundCallDialog` — call type selection, filtered appointment list, auto-fill phone, purpose preview
- [x] **Outbound trunk architecture fix** — each number has its own outbound trunk stored in DB (not shared env var)
  - `livekit_outbound_trunk_id` column added to `business_phone_numbers` (migration `20260331000000_bpn_outbound_trunk.sql`)
  - `livekit_service.create_sip_participant()` now accepts explicit `outbound_trunk_id` param
  - `POST /calls/outbound` fetches trunk ID from DB alongside `from_number`
  - `provision_phone_number()` creates per-number outbound trunk + stores ID in DB
  - `release_phone_number()` now also deletes outbound trunk on release (fixes orphaned trunk bug)
  - `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` removed from `config.py` and `.env`
- [x] **Manual steps needed for existing numbers:**
  - Run migration `20260331000000_bpn_outbound_trunk.sql` in Supabase (backfills `ST_WZ95dtKEntty` for +14157077538)
  - Delete orphaned trunk `ST_htrEWVP2hm6P` from LiveKit dashboard (from released +14159935287)
  - +14152555624 has no outbound trunk yet — provision via app or create manually in LiveKit
- [x] **Outbound calls tested end-to-end** — working (2026-04-02); fixed `livekit-api` upgrade 0.6→1.1 (`agent_dispatch` missing in 0.6)
- [ ] Wire up `missed_call_text_back` feature flag: on call end with `status=missed`, trigger outbound callback (future)

#### Step 8 — SMS via Twilio
- [x] `agent/sms_helpers.py` — `send_appointment_confirmation_sms`, `send_appointment_reminder_sms`, `send_missed_call_sms`
  - Reads `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` from env
  - Looks up business's provisioned `from` number from `business_phone_numbers` table
  - All functions are fire-and-forget (callers wrap in try/except)
- [x] `supabase_helpers._is_feature_enabled(supabase, business_id, feature_key)` — reads `agent_settings` table
- [x] `book_appointment` — sends confirmation SMS when `send_texts_during_after_calls` is enabled
- [x] `_finalize_call` — detects missed calls (inbound + empty transcript), marks status `missed`, sends text-back when `missed_call_text_back` is enabled
- [x] `agent/.env.local` — Twilio credentials added

### Google Calendar Integration
- [x] `google_calendar_tokens` table — `(staff_id, business_id, google_email, access_token, refresh_token, token_expiry)` with RLS
- [x] `google_event_id` column added to `appointments` table
- [x] Backend `google_calendar_service.py` — OAuth URL builder, token exchange, refresh, revoke, create/update/delete event
- [x] Backend `GET /integrations/google/auth-url` — returns OAuth consent URL
- [x] Backend `POST /integrations/google/callback` — exchanges code, saves tokens to DB
- [x] Backend `GET /integrations/google/status` — returns connected state + google_email
- [x] Backend `DELETE /integrations/google/disconnect` — revokes + deletes tokens
- [x] Backend config: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` settings
- [x] Frontend `Integrations.tsx` — fully wired: connect button → OAuth redirect, callback handling, disconnect, connected email shown
- [x] Frontend `voiceAgentApi.ts` — `getGoogleCalendarAuthUrl`, `completeGoogleCalendarOAuth`, `getGoogleCalendarStatus`, `disconnectGoogleCalendar`
- [x] Agent `book_appointment` — creates event on **both** staff calendar + superadmin calendar; stores `google_event_id` (staff) + `google_event_id_admin`
- [x] Agent `update_appointment` — PATCHes both staff + admin calendar events
- [x] Agent `cancel_appointment` — DELETEs both staff + admin calendar events before DB delete
- [x] Agent token auto-refresh — checks expiry before every API call, refreshes and updates DB
- [x] `google_event_id_admin` column added to `appointments` table (migration 20260319000001)
- [x] Account Settings — Google Calendar connect/disconnect section (all staff can connect their own calendar)
- [x] OAuth `return_to` flow — callback redirects back to the page that initiated OAuth (Integrations or Account Settings)
- [x] `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` added to `backend/.env`
- [ ] Customer confirmation: send `.ics` file via SMS or email on booking
- [ ] Super admin view: in-app calendar reads from `appointments` table across all staff (already partially done via Calendar.tsx)

### SMS Sending
- [ ] Choose provider: Twilio SMS (when available) or AWS SNS as alternative
- [ ] SMS service in backend (`backend/app/services/sms_service.py`)
- [ ] Send appointment confirmation SMS on booking
- [ ] Send reminder SMS N days before appointment (scheduler / cron job)
- [ ] Send missed-call text-back SMS (trigger on call end with status `missed`)
- [ ] Wire up `missed_call_text_back` and `send_texts_during_after_calls` feature flags to actual sending logic

### Email Sending — Gmail Integration
- [x] Gmail OAuth flow (business-level, one sending Gmail per business)
- [x] `gmail_tokens` table — business_id unique key, stores access/refresh tokens
- [x] `backend/app/services/email_service.py` — Gmail API send, token refresh, HTML template
- [x] `GET/POST /integrations/gmail/auth-url|callback|status|disconnect` — OAuth routes
- [x] `backend/app/core/config.py` — added `gmail_redirect_uri`
- [x] `agent/agent.py` — `_gmail_send_confirmation` helper; fires after `book_appointment` if client_email provided
- [x] `agent/agent.py` — `_gmail_send_staff_notification` helper; fires on every booking to assigned staff member (fetches staff email via `supabase.auth.admin.get_user_by_id`)
- [x] Agent collects required `client_email` in `book_appointment` tool (now a required parameter)
- [x] Frontend `voiceAgentApi.ts` — `getGmailAuthUrl`, `completeGmailOAuth`, `getGmailStatus`, `disconnectGmail`
- [x] Frontend `Integrations.tsx` — Gmail card fully wired (connect/disconnect/status badge)
- [x] `App.tsx` — `/integrations/gmail/callback` route added
- [ ] Add `.ics` calendar attachment to confirmation email
- [ ] Send reminder email N days before appointment (needs scheduler/cron)
- [ ] Wire up `confirmation_reminder_calls` feature flag to email trigger

### Support Page — Form Submission
- [x] Wire "Submit Request" form on Support page — `POST /support/submit` sends via business's connected Gmail to `support@aiemployeesinc.com`; both Support + Wish List modes fully wired (session 30)
- [x] Removed Tutorials from sidebar nav (session 30)

### Frontend — Remaining Stubs
- [ ] Marketing Employee page
- [ ] Sales Employee page
- [ ] HR Employee page
- [ ] Executive Assistant page
- [x] Billing page — full Stripe integration: Checkout, Customer Portal, webhooks, usage tracking (session 39)
- [x] Integrations page — Google Calendar OAuth fully wired (connect, callback, disconnect, status)
- [ ] Integrations page — wire up Twilio connection
- [ ] Setup checklist in `/dashboard/customer-service/setup` — sync state to backend (currently all mock/UI-only)
- [ ] CS pages — wire real data from backend/Supabase (call recordings, scheduler, forwarding contacts are currently mock data)

### CS Pages — API Wiring (frontend only, backend already exists)
- [x] **CS1 AgentPerformance** — replace mock stats with `GET /analytics/summary`
- [x] **CS1 AgentPerformance** — replace mock chart data with `GET /analytics/call-volume-trends?period=`
- [x] **CS1 AgentPerformance** — replace mock donut data with `GET /analytics/call-distribution`
- [x] **CS1 AgentPerformance** — replace mock activity feed with `GET /calls/recent-activity`
- [x] **CS2 CallRecordings** — replace mock call list with `GET /calls?business_id=&status=&direction=&search=&page=`
- [x] **CS2 CallRecordings** — load transcript on call select via `GET /calls/{id}/transcript`
- [x] **CS2 CallRecordings** — load summary + insights on call select via `GET /calls/{id}/summary`
- [x] **CS2 CallRecordings** — wire audio player to `GET /calls/{id}/recording` signed URL (shows "no recording" for test calls)
- [x] **CS3 Scheduler** — wire agent on/off toggle to `GET/PUT /settings/agent/state`
- [x] **CS3 Scheduler** — new backend endpoint `GET/PUT /settings/agent/schedule` (backed by `business_hours` table) + wire frontend
- [x] **CS4 CallForwarding** — replace mock contacts with `GET /forwarding/contacts`
- [x] **CS4 CallForwarding** — wire toggle to `PUT /forwarding/contacts/{id}/toggle`
- [x] **CS4 CallForwarding** — wire delete to `DELETE /forwarding/contacts/{id}`
- [x] **CS4 CallForwarding** — wire Enable All / Disable All to `PUT /forwarding/contacts/bulk/toggle`
- [x] **CS4 CallForwarding** — replace mock rules with `GET /forwarding/rules`
- [x] **CS4 CallForwarding** — wire today's stats to `GET /analytics/summary` (`forwarded_calls`, `completed_calls`)
- [x] **CS4 CallForwarding** — Add Contact modal wired to `POST /forwarding/contacts`
- [x] **CS5 AgentSettings** — load feature flags from `GET /settings/agent` on mount
- [x] **CS5 AgentSettings** — wire Save Changes to `PUT /settings/agent`
- [x] **CS5 AgentSettings** — wire Reset to Default to `POST /settings/agent/reset`
- [x] **CS5 AgentSettings** — load recent changes from `GET /settings/agent/audit-log`
- [x] **CS5 AgentSettings** — wire agent on/off (Quick Actions) to `PUT /settings/agent/state`
- [x] Add all new API functions to `voiceAgentApi.ts`: analytics, calls list, forwarding CRUD, agent settings CRUD
- [x] `useDebounce` hook added (`src/hooks/useDebounce.ts`)

### Deployment
- [x] `ai-employees-app/Dockerfile` — multi-stage build: Node 20 Alpine (Vite build) → nginx Alpine (serve)
- [x] `ai-employees-app/nginx.conf` — SPA fallback, static asset caching, gzip
- [x] `ai-employees-app/docker-compose.yml` — single service, reads VITE_* vars from `.env` at build time
- [ ] HTTPS / domain setup — `getUserMedia` (mic) requires secure context; bare IP HTTP doesn't work in browsers

---

## 🗒️ Architecture Notes

### What exists in Supabase DB (frontend writes directly, backend doesn't expose yet):
- `appointments` — full CRUD via frontend
- `services` — full CRUD via frontend
- `user_services` — staff↔service mapping
- `user_availability` — weekly recurring working hours
- `user_availability_overrides` — time off / date exceptions
- `business_hours_overrides`, `location_hours_overrides` — also present

### Agent tool strategy:
- Agent reads Supabase directly (same as frontend does) — no backend API layer needed for reads
- Writes (create/update/cancel appointment) also go directly to Supabase from agent
- This keeps the architecture consistent with how the frontend works

### Key switch:
- `USE_LIVEKIT_AGENT=1` → new `agent/agent.py` (LiveKit Agents, auto-dispatched) — CURRENT
- `USE_LIVEKIT_AGENT=0` → legacy `backend/worker/voice_agent.py` (subprocess, writes transcripts) — BYPASSED

### Metadata flow:
- Backend encodes `{call_id, business_id, location_id}` in LiveKit token
- Agent reads it on room join via `participant.metadata`

### Frontend API base:
- `VITE_VOICE_AGENT_API_URL` (default `http://localhost:8003`)
