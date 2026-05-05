---
name: Voice Agent Project Overview
description: Full architecture, current state, key decisions, blocked items, and test business IDs for sam-backend + ai-employees-app. Updated 2026-05-01 session 40.
type: project
originSessionId: 29becce9-ad8f-4b26-8540-59f05b3f8002
---
Two repos form the voice agent system:
- **Backend + Agent:** `/home/lap-68/Documents/gt-rahul/sam-backend`
- **Frontend:** `/home/lap-68/Documents/gt-rahul/ai-employees-app`

**Why:** Multi-tenant, multi-location AI voice agent SaaS for service businesses.
**How to apply:** Always consider both repos. Always check `TODO.md` and `docs/SESSION_HANDOFF.md` at session start.

## Current Branches
- `feature/strip-integration` (sam-backend) — Stripe billing complete, not yet merged
- `feature/custom-roles-v2` (both repos) — QA done, 2 bugs must be fixed before merge
- `feature/location-scoped-architecture` (sam-backend) — ready to merge, not yet merged

## What's Working (as of session 39)
- Inbound SIP calls → agent answers → books appointments → emails + SMS → shows in UI
- Agent fully location-scoped: services, staff, hours, settings, KB all scoped to called location
- Outbound calls, custom schedules, Gmail OAuth, Google Calendar, Twilio SMS
- Call Forwarding Option C (SIP REFER) — checks available hours window
- **Roles & Permissions v2** — editable matrix; create/delete custom roles; DB-driven page access
- **Canadian + US phone numbers** — CA country selector verified with Toronto 647 numbers
- Team management with custom role invite; business soft delete/deactivation
- Setup checklist wired to real API data; integrations search bar
- Resend DNS live — password reset + signup confirmation emails working
- Migrations 20260428000001–000003 applied; edge functions deployed
- **Stripe Billing** — Checkout (Starter/Growth/Pro plans), Customer Portal, webhooks sync to DB, usage bar + period dates shown in UI (verified working)
- **Booking validation guards** — `_validate_booking_datetime` in supabase_helpers; agent tools reject past dates, closed days, out-of-hours, double-booking
- **TC-ROLES-002 fixed** — `togglePermission` receives explicit `roleId` param; `isAdminUser && selectedRole` null guard at call site
- **TC-TEAM-006 fixed** — AlertDialog confirmation; `isRemoving` guard; Escape-key protection on `onOpenChange`

## Open Bugs
None — all pre-launch bugs fixed.

## Blocked
- **SMS 2FA** — blocked on client A2P 10DLC approval
- **Resend DNS (recurring)** — Sam keeps breaking Resend TXT records when editing Google MX records in Hostinger. SPF must include both Google + Resend: `v=spf1 include:_spf.google.com include:amazonses.com ~all`. MX and TXT records do not conflict — Sam must not delete TXT records when adding MX.
- **Billing UI update** — new pricing table shared by Sam (2026-04-30); not yet implemented. Minutes-based metric, 5 tiers (Free/Starter/Growth/Professional/Enterprise), overage section needed. Stripe price IDs for Growth ($149) and Professional ($299) need to be recreated.
- **Per-agent billing** — confirmed by Sam (2026-05-01): future agents billed as monthly add-ons. Architecture: Stripe subscription line items + `active_agents` tracking in DB. Not yet built.

## Test Business
- **Name:** Downtown Barber Shop
- **business_id:** `da9fc4fb-2b16-48ab-8856-696870d0a18a`
- **Locations:**
  - Mirage: `fd7d1823-3d86-44cf-8039-cbaca6bfdd01`, PSTN +14157077538
  - Downtown office: `a5e3a2b8-ee37-4022-8acb-7b9f3989d6a2`, PSTN +14158559408
- **Super admin:** Rahul Khera (`14a3739a-8e89-486c-aefc-ac8ad4d61038`)

## QA Artifacts to Clean Up
- "QA Test Role" (id: fb9b7b29-aaf9-443f-a99a-275e325e12bd) — delete from Supabase dashboard
- "QA Test Location" — delete from Supabase dashboard

## Key Architecture Decisions
- All Supabase reads in backend use `supabase_admin` (service role) — bypasses RLS
- `verify_business_access(user_id, business_id)` enforced on all backend routers
- Dispatch rules carry `{business_id, location_id}` in metadata — agent reads this first
- `custom_role_id` on `user_roles` links user to specific named role; `useRolePermissions` uses it to load that role's page permissions directly

## Pending Manual Steps
- **Merge `feature/strip-integration` → main (both repos)** — all work ready
- **Update `BILLING_SUCCESS_URL` + `BILLING_CANCEL_URL`** in `backend/.env` → `http://116.202.210.102:20252/...`
- **`docker compose up --build -d`** after backend merge
- **Fix Resend DNS on Hostinger** — re-add DKIM/SPF/DMARC records for `aiemployeesinc.com`
- **Update Stripe webhook URL** to prod domain when HTTPS is set up
- `POST /phone-numbers/sync-dispatch` — re-stamp existing dispatch rules with location_id
- E2E test Option C: real SIP call → transfer → confirm forwarded status in DB
- AI behavior tests (voice-only — must use "Test with Web Call" or real phone)

## Applied Migrations (all done)
- All through `20260428000003` ✅ applied

## Full Detail
`docs/SESSION_HANDOFF.md` and `docs/CLIENT_LAUNCH_CHECKLIST.md` in sam-backend repo.
