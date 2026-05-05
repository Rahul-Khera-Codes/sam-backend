# Session Handoff — 2026-05-05 (Session 41)

Read this at the start of every session. It captures the full current state so you can pick up immediately.

---

## Quick Start

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
docker compose up -d                        # start all services
docker logs -f sam-backend-sam-agent-1      # agent logs
docker compose restart sam-agent            # restart agent after code changes
```

Two repos:
- **Backend + Agent:** `/home/lap-68/Documents/gt-rahul/sam-backend`
- **Frontend:** `/home/lap-68/Documents/gt-rahul/ai-employees-app`

Always check `TODO.md` in sam-backend for full task status.

---

## Current Branch

`feature/strip-integration` (sam-backend) — Stripe billing complete, not yet merged to main.

`feature/custom-roles-v2` (both repos) — QA done, 2 bugs must be fixed before merge.

`feature/location-scoped-architecture` (sam-backend) — **ready to merge to main**, not yet merged.

---

## System Status (2026-04-29)

### Working end-to-end ✅
- Inbound SIP call → agent answers → books appointment → transcript + summary → emails → shows in UI
- Agent is fully **location-scoped**: services, staff, hours, settings, KB all scoped to the called location
- Agent refuses cross-location bookings; provides other branch's PSTN phone number on request
- Outbound calls (reminder/follow-up) — working
- **Call Forwarding Option C** — SIP REFER live transfer via `forward_call(contact_id)` agent tool; checks available_start/available_end window; polite refusal if outside hours
- Calendar full CRUD
- Agent Settings feature flags — load + save with audit log
- Communication Settings — load + save
- Call Forwarding contacts + rules — full CRUD, agent reads rules verbally (Option B) + live transfer (Option C)
- Custom Schedules — create/edit/toggle/delete; agent applies active schedule to prompt
- Gmail OAuth per location — confirmation + cancellation + reschedule emails to customer + staff
- Google Calendar per staff — creates/updates/deletes events on booking/reschedule/cancel
- SMS — confirmation on booking, missed call text-back (Twilio)
- Phone Numbers page — search/provision/release US + **Canadian numbers** (CA added session 38)
- Team Management — invite by email (with custom role support), role assignment, location assignment
- **Roles & Permissions v2** — fully editable matrix; create/delete custom roles; permissions enforced on login via DB; custom roles assignable in invite dialog
- Business soft delete / deactivation — super_admin only, name confirmation, 90-day grace period
- Support page form — wired to `POST /support/submit`
- Integrations tab — Gmail OAuth wired; search bar filters all cards
- Business authorization enforced across all backend routers

### Also Working ✅ (added session 39–40)
- **Stripe Billing** — full integration: plan selection (Starter/Growth/Pro), Stripe Checkout redirect, Customer Portal for self-serve management, webhooks sync subscription state to DB, usage progress bar, period start/renewal dates shown
- **Booking validation guards** — `_validate_booking_datetime` in `supabase_helpers.py`; `get_available_slots` + `book_appointment` both reject past dates, closed days, out-of-hours times, custom schedule overrides, double-booking
- **TC-ROLES-002** — `togglePermission` now receives `roleId` explicitly from `selectedRole.id`; null-safety guard added
- **TC-TEAM-006** — AlertDialog confirmation before Remove User; `isRemoving` guard; Escape-key protection

### Blocked / Waiting
- **SMS 2FA** — blocked on client A2P 10DLC campaign approval
- **Resend DNS** — domain verification failed on Hostinger; email verification emails broken; re-add DKIM/SPF/DMARC in Hostinger DNS zone

---

## Infrastructure

| Container | Port | Notes |
|---|---|---|
| `sam-backend-sam-backend-1` | 8003 | FastAPI, hot reload |
| `sam-backend-sam-agent-1` | — | LiveKit agent, hot reload |

Key env files:
- `backend/.env` — all backend secrets
- `agent/.env.local` — SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, LIVEKIT_*, OPENAI_API_KEY, TWILIO_*, GOOGLE_CLIENT_ID/SECRET, AGENT_NAME

---

## Test Business: Downtown Barber Shop

**business_id:** `da9fc4fb-2b16-48ab-8856-696870d0a18a`

### Locations
| Name | location_id | Phone (PSTN) | Address |
|---|---|---|---|
| Mirage | `fd7d1823-3d86-44cf-8039-cbaca6bfdd01` | +14157077538 | 8170 50 St NW, Edmonton, AB |
| Downtown office | `a5e3a2b8-ee37-4022-8acb-7b9f3989d6a2` | +14158559408 | 115th main street, suncity, New Delhi |

### Staff
| Name | user_id | Role |
|---|---|---|
| Rahul Khera | `14a3739a-8e89-486c-aefc-ac8ad4d61038` | super_admin |
| Sam Maisuria | `1bc53b7c-8af6-406b-a2bb-b03dc27f182d` | user |

### Gmail
- Mirage location: `rahul.excel2011@gmail.com` (connected)
- Downtown office: check in UI

---

## Architecture Overview

### Agent Context Resolution (priority order)
1. `ctx.job.metadata` — JSON `{business_id, location_id, call_id}` from LiveKit dispatch rule
2. `participant.metadata` — same JSON, set by backend token (web calls)
3. `participant.attributes` — SIP attrs, reads `business_id` + `location_id`
4. DB lookup by `sip.trunkPhoneNumber` in `business_phone_numbers` (last resort)

### Custom Roles & Permissions (shipped session 38)
- Tables: `custom_roles` (one per business per role), `role_page_permissions` (page-level access per role)
- 3 system roles seeded per business: Admin (super_admin), Manager (admin), Team Member (user)
- Admins can create named custom roles (e.g. "Receptionist") based on any base role
- Page permissions per role are editable in the Roles & Permissions UI
- `custom_role_id` column added to `user_roles` + `location_invitations` — users can be assigned a specific custom role
- `useRolePermissions` hook: if user has `custom_role_id`, loads that role's permissions; else loads system role by base_role
- Backend: `sam-backend/backend/app/routers/roles.py` + `schemas/roles.py`
- Frontend enforcement: `ProtectedRoute` waits for `permissionsLoading`; `Sidebar` filters by `canAccess(path)`

### Key Backend Patterns
- All Supabase reads use `supabase_admin` (service role) to bypass RLS
- `verify_business_access(user_id, business_id)` — enforced on all routers
- `require_business_access()` — FastAPI dependency factory for query/path param endpoints
- Resource-ID endpoints use helper functions to look up resource's `business_id` and verify
- Settings endpoints use SELECT + INSERT/UPDATE pattern (not upsert) for partial unique index compatibility

### Phone Number / SIP Architecture
- One shared Twilio Elastic SIP trunk for all businesses
- One LiveKit inbound SIP trunk (matches Twilio)
- One LiveKit **dispatch rule per phone number** — carries `{business_id, location_id}` in metadata
- `business_phone_numbers` table: `business_id`, `location_id`, `phone_number`, `livekit_inbound_trunk_id`, `livekit_outbound_trunk_id`, `livekit_dispatch_rule_id`, `is_active`, `released_at`
- **US + CA numbers** — frontend has country selector (US/CA), backend passes to Twilio `available_phone_numbers(country)`

---

## Key Files

### Backend
- `backend/app/core/auth.py` — `verify_business_access`, `require_business_access`, `get_user_id`, `require_role`
- `backend/app/routers/roles.py` — custom roles CRUD + permissions API (NEW session 38)
- `backend/app/schemas/roles.py` — Pydantic schemas for roles (NEW session 38)
- `backend/app/routers/calls.py` — call CRUD + initiate + outbound
- `backend/app/routers/settings.py` — agent settings, state, schedule, communication, deactivate
- `backend/app/routers/forwarding.py` — contacts + rules CRUD
- `backend/app/routers/phone_numbers.py` — provision, release, list, sync-dispatch (supports country param)
- `backend/app/services/phone_number_service.py` — Twilio + LiveKit provisioning

### Agent
- `agent/agent.py` — main agent, all tools
- `agent/prompt_builder.py` — builds full system prompt
- `agent/supabase_helpers.py` — all DB fetch helpers, slot computation, feature flag checks
- `agent/gmail_helpers.py` — 6 email send functions
- `agent/sms_helpers.py` — Twilio SMS
- `agent/gcal_helpers.py` — Google Calendar CRUD

### Frontend (ai-employees-app/src)
- `lib/voiceAgentApi.ts` — all backend API calls including roles API
- `hooks/useRolePermissions.ts` — fetches DB permissions; supports customRoleId param
- `contexts/AuthContext.tsx` — session, user, roles, canAccess(), permissionsLoading
- `components/auth/ProtectedRoute.tsx` — waits for permissionsLoading before access check
- `components/layout/Sidebar.tsx` — filters nav items by canAccess()
- `pages/dashboard/RolesPermissions.tsx` — editable matrix, new/delete role dialog
- `pages/dashboard/TeamManagement.tsx` — invite with custom roles dropdown
- `pages/dashboard/PhoneNumbers.tsx` — US + CA country selector
- `supabase/functions/invite-location-admin/index.ts` — passes customRoleId through
- `supabase/functions/accept-invitation/index.ts` — stores customRoleId in user_roles

---

## Pending Manual Steps

- [x] **Run migrations** `20260428000001`, `20260428000002`, `20260428000003` — applied (QA Session 1 confirmed)
- [ ] **Deploy edge functions** — `supabase functions deploy invite-location-admin accept-invitation` — still needed for customRoleId in invites
- [ ] Resend DNS on Hostinger — add DKIM/SPF/DMARC for `aiemployeesinc.com`
- [x] **Apply Stripe migration** — `20260430000001_businesses_stripe.sql` — applied ✅
- [ ] **Merge `feature/strip-integration` → main (both repos)** — all TC fixes + Stripe + booking validation ready
- [ ] **Update billing URLs in `backend/.env` on server** — `BILLING_SUCCESS_URL=http://116.202.210.102:20252/dashboard/settings/billing?success=true` and `BILLING_CANCEL_URL=http://116.202.210.102:20252/dashboard/settings/billing`
- [ ] **`docker compose up --build -d`** after backend merge
- [ ] **Fix Resend DNS on Hostinger** — re-add DKIM/SPF/DMARC; domain verification failed, email verification broken
- [ ] **Update Stripe webhook URL** to prod domain when HTTPS is set up
- [ ] Merge `feature/custom-roles-v2` → main (both repos) — after TC-ROLES-002 + TC-TEAM-006 fixed
- [ ] **`POST /phone-numbers/sync-dispatch`** — re-stamp existing dispatch rules with `location_id`
- [ ] E2E test Option C: make real SIP call → ask to transfer → confirm `status=forwarded` in DB

## Applied Migrations (all done)
- `20260430000001` — businesses Stripe columns ✅ applied
- `20260327000000–20260327000001` — appointments columns + status
- `20260328000000` — business_phone_numbers table
- `20260331000000` — bpn outbound trunk column
- `20260410000000–20260410000005` — location_id columns on all settings/hours/KB/forwarding tables
- `20260411000000` — location_services junction table
- `20260411000001` — gmail_tokens location_id
- `20260413000000–20260413000003` — custom_schedules table + backfill + drop old table + forwarding_rule column
- `20260414000000` — settings_audit_log location_id
- `20260414000001` — backfill NULL appointments location_id
- `20260416000000` — businesses soft delete (is_deleted, deleted_at) ✅
- `20260416000001` — calls.forwarded_to UUID FK → forwarding_contacts ✅
- `20260417000000` — appointments call tracking ✅
- `20260417000001` — cleanup null location rows ✅
- `20260428000000` — forwarding_contacts available_start/available_end ✅

## Pending Migrations (not yet applied)
- `20260428000001` — custom_roles + role_page_permissions tables + seed
- `20260428000002` — custom_roles policy fixes + index
- `20260428000003` — user_roles.custom_role_id + location_invitations.custom_role_id

---

## What Was Done This Session (Session 41, 2026-05-05)

**Project planning started for billing UI update; code analysis complete.**

1. **Client comms logged** — `docs/CLIENT_COMMS_LOG.md` created; Sam's pricing table, per-agent billing decision, DNS root cause all logged
2. **Project folder structure** — `docs/projects/` created with `billing-ui-update/` and `per-agent-billing/` subfolders (overview → analysis → plan → specs)
3. **`billing-ui-update/00-overview.md`** — high-level theory doc complete: 5-tier structure, architecture decisions, risks, scope
4. **`billing-ui-update/01-analysis.md`** — code analysis complete: all exact touch points identified across 4 files; no DB migration needed; Stripe dashboard prereqs documented
5. **Next:** `02-plan.md` — detailed implementation steps (pending)

---

## What Was Done Previous Session (Session 40, 2026-05-01)

**TC-ROLES-002 + TC-TEAM-006 fixed; booking validation layer added; Stripe billing URLs/config documented.**

1. **TC-TEAM-006 fixed** — `TeamManagement.tsx`: AlertDialog confirmation before Remove User fires; `isRemoving` loading guard prevents double-click; `onOpenChange` guards against Escape-key dismiss mid-request. Commits: `943b35b`, `f0a58a3`, `5f13a80`

2. **TC-ROLES-002 fixed** — `RolesPermissions.tsx`: `togglePermission` now accepts `roleId: string` as explicit first param; call site passes `selectedRole.id`; `isAdminUser && selectedRole` null guard added. Commits: `b2c04db`, `81305dd`

3. **Booking validation** — `agent/supabase_helpers.py`: `_validate_booking_datetime()` rejects past dates, closed days, out-of-hours times, custom schedule overrides; `get_available_slots` and `book_appointment` in `agent.py` both guarded; double-booking check in `book_appointment`. 11 unit tests in `agent/tests/test_booking_validation.py`.

4. **Resend DNS issue identified** — `aiemployeesinc.com` domain verification failed in Resend (likely Hostinger DNS records dropped). Email verification emails are broken. Fix: re-add DKIM/SPF/DMARC in Hostinger DNS zone.

5. **Billing URLs** — need to update `BILLING_SUCCESS_URL` + `BILLING_CANCEL_URL` in `backend/.env` on server to `http://116.202.210.102:20252/...` before merging.

6. **All work on `feature/strip-integration`** — not yet merged to main. Ready to merge once billing URLs updated and DNS fixed.

---

## What Was Done Previous Session (Session 39, 2026-04-30)

**Full Stripe billing integration built end-to-end and verified working in browser.**

1. **Stripe billing router** — `sam-backend/backend/app/routers/billing.py` (new)
   - `GET /billing/subscription` — returns plan name, status, call usage, period dates
   - `POST /billing/create-checkout-session` — creates Stripe Checkout session, returns redirect URL
   - `POST /billing/customer-portal` — creates Stripe Customer Portal session, returns redirect URL
   - `POST /billing/webhook` — handles `checkout.session.completed`, `customer.subscription.created/updated/deleted`, `invoice.payment_succeeded`, `invoice.payment_failed`
   - `_attr()` helper for safe StripeObject/dict field access (Stripe SDK v15 uses attribute access, not `.get()`)
   - Period dates read from `sub.items.data[0]` (Stripe 2026 API moved them from subscription root)

2. **Billing schemas** — `sam-backend/backend/app/schemas/billing.py` (new)
   - `SubscriptionResponse`, `CreateCheckoutSessionRequest`, `CreateCheckoutSessionResponse`, `CustomerPortalResponse`

3. **Config** — `sam-backend/backend/app/core/config.py` — added 7 Stripe fields including price IDs for 3 plans

4. **Migration** — `ai-employees-app/supabase/migrations/20260430000001_businesses_stripe.sql` — 7 Stripe columns on `businesses` table (**not yet applied to Supabase — apply before launch**)

5. **TypeScript types** — `ai-employees-app/src/integrations/supabase/types.ts` — 7 Stripe fields added to businesses Row/Insert/Update

6. **Frontend API** — `ai-employees-app/src/lib/voiceAgentApi.ts` — `getBillingSubscription`, `createCheckoutSession`, `createCustomerPortalSession` functions

7. **Billing.tsx** — `ai-employees-app/src/pages/dashboard/Billing.tsx` — fully rewritten; shows plan cards (no sub) or usage progress + plan card (active sub); "Manage Plan" opens Stripe Customer Portal

8. **Bugs fixed during session:**
   - 503 on checkout: `STRIPE_SECRET_KEY` missing from backend `.env`; `STRIPE_PRICE_PRICE_ID` typo
   - 500 on webhooks: `AttributeError: get` — Stripe SDK StripeObjects don't support `.get()` → fixed with `_attr()` helper
   - 404 on success redirect: URL was `/dashboard/billing` but route is `/dashboard/settings/billing`
   - Period dates showing `—`: Stripe 2026 API moved `current_period_start/end` to `sub.items.data[0]`; DB patched directly + code fixed

9. **All verified live in browser** — subscription active, Starter plan shown, 0/150 calls, correct period start/renewal dates

---

## What Was Done This Session (38)

1. **Custom Roles & Permissions v2 — fully shipped** (continued from session 37)
   - Post-review fixes applied: `ProtectedRoute` now waits for `permissionsLoading`; `fetchRoles` stale closure fixed; `isAdminUser` aligned with backend (allows both super_admin and admin)
   - Custom roles in invite dialog: `TeamManagement` loads custom roles via API; non-system custom roles appear in invite dropdown; selecting a custom role sets both `base_role` + `customRoleId` in the invite
   - Migration `20260428000003`: added `custom_role_id` to `user_roles` + `location_invitations`
   - Edge functions updated: `invite-location-admin` + `accept-invitation` both store/read `customRoleId`
   - `useRolePermissions` hook: accepts `customRoleId` param — if set, looks up that role directly; else finds system role by base_role
   - `AuthContext`: threads `roles[0].custom_role_id` to `useRolePermissions`
   - Supabase generated types patched for both tables

2. **Canadian phone numbers** — added 🇺🇸/🇨🇦 country selector to PhoneNumbers page; switching resets results; placeholder text updates; backend already supported `country` param; verified working (Toronto 647 numbers shown)

3. **Client launch checklist saved to memory** — full checklist with ✅/⚠️/❌ status; only hard blocker remaining is Billing (no Stripe)

## What Was Done This Session (37)

1. **Pre-release checklist fixes — fully shipped**
   - Migration `20260428000000`: `available_start`/`available_end` on `forwarding_contacts`
   - Backend schemas updated; frontend UI time pickers added; agent enforces time window before SIP REFER
   - Setup checklist: `CustomerServiceEmployee.tsx` driven by real API data with click-to-navigate
   - 3 spec compliance fixes: forwarding contact types, Gmail status field name

2. **Automated test pass** — backend schemas, agent helpers, TypeScript, DB round-trip, auth enforcement all verified
