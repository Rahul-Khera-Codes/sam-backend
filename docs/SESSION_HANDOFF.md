# Session Handoff — 2026-04-29 (Session 38)

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

`feature/custom-roles-v2` (both repos) — not yet merged to main.

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

### Blocked / Waiting
- **SMS 2FA** — blocked on client A2P 10DLC campaign approval
- **Billing** — static/placeholder UI, no Stripe integration built

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
- [ ] Merge `feature/location-scoped-architecture` → main (sam-backend)
- [ ] Merge `feature/custom-roles-v2` → main (both repos) — after manual testing
- [ ] **`POST /phone-numbers/sync-dispatch`** — re-stamp existing dispatch rules with `location_id`
- [ ] E2E test Option C: make real SIP call → ask to transfer → confirm `status=forwarded` in DB

## Applied Migrations (all done)
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

## What Was Done This Session (QA Sessions 4–7, 2026-04-29)

**This was a pure QA session block — no source files were modified. All entries are observational.**

1. **TC-ROLES-002 — permission toggle bug — root cause evolved**
   - Original bug (Sessions 4–5): guard `if (!selectedRoleId || !isAdminUser) return` ran AFTER the optimistic `setPermissions(updated)` call → zero PUTs sent to backend
   - Partial fix deployed (Session 7): guard moved before optimistic update in `RolesPermissions.tsx`
   - **New bug confirmed (Session 7)**: PUT now fires and returns 200 OK, but targets the WRONG role_id — the role that was auto-selected when the page loaded, not the tab the user clicked. Stale `selectedRoleId` closure in `togglePermission`. State still reverts after reload for the clicked role.
   - Status: ❌ STILL OPEN — new fix needed (fix stale closure, e.g. use `useRef` or pass role ID as param)

2. **TC-TEAM-006 — Remove User fires immediately — still open**
   - `TeamManagement.tsx:375` still calls `handleRemoveUser(member)` directly on `DropdownMenuItem` onClick with no confirmation dialog
   - Fix not deployed as of Session 7
   - Status: ❌ STILL OPEN

3. **TC-SUPPORT-001 — Support form submission — functional with environment constraint**
   - POST `/support/submit` reaches backend correctly
   - Returns 409 in test env because Gmail OAuth is not connected — expected behavior
   - Form logic is fully working; delivery works when Gmail connected in Settings → Integrations
   - Status: ✅ PASS (environment constraint)

4. **QA infrastructure complete — all headless tests done**
   - Sessions 1–7 covered: Auth, Calendar, Profile, Business Settings, Global Settings, Team Management, Roles & Permissions, Phone Numbers, Locations, CSE structural pages, Support
   - Total: 51 tests run — 34 passed, 5 failed (2 real bugs open), 13 blocked
   - AI behavior tests permanently blocked headlessly — voice-only (LiveKit WebRTC)
   - Remaining open items require developer fixes (TC-ROLES-002 + TC-TEAM-006) or live voice calls (AI behavior)

5. **Test artifacts still in DB** — "QA Test Role" + "QA Test Location" need manual cleanup

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
