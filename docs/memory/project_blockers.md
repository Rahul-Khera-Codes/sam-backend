---
name: Current Blockers and Pending Actions
description: What's blocked, who's responsible, and what to do next — updated each session so future sessions don't waste time re-investigating.
type: project
originSessionId: 29becce9-ad8f-4b26-8540-59f05b3f8002
---
## Blocked on Client / External

**SMS 2FA**
- Blocked on client completing A2P 10DLC campaign registration with Twilio
- Setup guide: `docs/SMS_2FA_SETUP.md`

**Resend DNS** — ✅ RESOLVED (Session 1 QA confirmed working)
- Password reset + signup confirmation emails confirmed live
- No action needed

## Pre-Launch Bugs — ALL FIXED ✅

**TC-ROLES-002** — Fixed session 40. `togglePermission` now takes explicit `roleId` param; call site passes `selectedRole.id`; null guard added.

**TC-TEAM-006** — Fixed session 40. AlertDialog confirmation with `isRemoving` guard and Escape-key protection on `onOpenChange`.

**Clean up QA test artifacts in DB**
- "QA Test Role" (id: fb9b7b29-aaf9-443f-a99a-275e325e12bd) — created by QA Session 4
- "QA Test Location" — created by QA Session 5
- Developer should delete these manually from Supabase dashboard

## Pending Code / Dev Work

**Resend DNS (recurring issue)**
- Sam repeatedly breaks Resend TXT records when editing Google MX records in Hostinger
- Root cause: Google MX + Resend TXT records can coexist — Sam must not delete TXT records when adding MX
- SPF must include both: `v=spf1 include:_spf.google.com include:amazonses.com ~all`
- Fix each time: re-add DKIM/SPF/DMARC TXT records in Hostinger → verify in Resend dashboard
- Long-term: give Sam a DNS checklist so he stops breaking it

**Billing UI update — in planning (02-plan.md next)**
- Overview: `docs/projects/billing-ui-update/00-overview.md`
- Analysis done: `docs/projects/billing-ui-update/01-analysis.md`
- Touch points: `Billing.tsx` (PLANS array, grid, labels, overage section), `billing.py` (PLAN_KEY_MAP), `config.py` (rename stripe_pro_price_id → stripe_professional_price_id)
- Prereq: create new Stripe prices in dashboard — Growth $149, Professional $299 — before code changes
- No DB migration needed

**Per-agent billing (future work)**
- Sam confirmed (2026-05-01): each agent type billed as monthly add-on subscription
- Architecture: Stripe subscription line items + DB `active_agents` tracking + agent access gating
- Not yet planned or built

**Merge + deploy pending**
- Merge `feature/strip-integration` → main (both repos)
- Update `BILLING_SUCCESS_URL`/`BILLING_CANCEL_URL` in `backend/.env` to `http://116.202.210.102:20252/...`
- `docker compose up --build -d` after backend merge

**Deploy edge functions** (still pending)
- `supabase functions deploy invite-location-admin accept-invitation`
- Required for customRoleId to be stored in invites (session 38 changes)

**Merge feature branches**
- `feature/location-scoped-architecture` → main (sam-backend) — ready, not done
- `feature/custom-roles-v2` → main (both repos) — QA mostly done; 2 bugs above must be fixed first

**`POST /phone-numbers/sync-dispatch`**
- Re-stamps existing dispatch rules with `location_id`
- Must be run once after location-scoped-architecture branch merges

**E2E test Option C call forwarding**
- Make a real SIP call to Mirage or Downtown number
- Ask agent to transfer to a forwarding contact
- Confirm caller gets transferred, call record shows status=forwarded

## Pending QA (requires human + live environment)

**AI behavior tests** — all permanently blocked for headless Playwright
- Voice-only interface (LiveKit WebRTC + `useWebAgentCall` hook)
- Must test via "Test with Web Call" button in browser or real phone call
- 8 tests pending: company info, business hours, services list, service price/time, deactivated services, team availability, appointments, days off

**Support email delivery verification**
- Gmail OAuth must be connected first in Settings → Integrations
- Once connected: test form submission → verify email at support@aiemployeesinc.com

## Future (not started)
- Employee pages (Marketing, Sales, HR, Executive) — currently "Coming Soon" stubs
- Backend appointment/service API endpoints (frontend queries Supabase directly now)
- HTTPS/domain setup for production

**Why:** Keeping this separate from TODO.md so blockers and ownership are immediately clear at session start.
**How to apply:** Check this first when deciding what to work on next. Fix TC-ROLES-002 + TC-TEAM-006 before merging feature/custom-roles-v2. Billing is the only remaining hard launch blocker.
