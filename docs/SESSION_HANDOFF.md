# Session Handoff — 2026-06-20 (Session 49)

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

Both repos are on `feature/google-calendar-timezone`, deployed to VPS. Ready to merge to main.

---

## System Status (2026-06-20)

### Core — Working end-to-end ✅
- Inbound SIP call → agent answers → books appointment → transcript + summary → emails → shows in UI
- Agent fully **location-scoped**: services, staff, hours, settings, KB all scoped to called location
- Agent refuses cross-location bookings; provides other branch's PSTN phone number
- Outbound calls (reminder/follow-up) — working
- **Call Forwarding Option C** — SIP REFER live transfer via `forward_call(contact_id)`; checks available hours window
- Calendar full CRUD
- Agent Settings feature flags — load + save with audit log
- Communication Settings — load + save
- Call Forwarding contacts + rules — full CRUD
- Custom Schedules — create/edit/toggle/delete; agent applies active schedule
- Gmail OAuth per location — confirmation + cancellation + reschedule emails to customer + staff
- Google Calendar per staff — creates/updates/deletes events on booking/reschedule/cancel (**now uses business timezone**)
- SMS — confirmation on booking, missed call text-back (Twilio)
- Phone Numbers page — search/provision/release US + Canadian numbers
- Team Management — invite by email, role assignment, location assignment, Option B (reassign before remove)
- Roles & Permissions v2 — editable matrix; create/delete custom roles; DB-driven page access
- Business soft delete / deactivation — super_admin only
- Stripe Billing — Checkout, Customer Portal, webhooks, usage bar
- Booking validation guards — past dates, closed days, out-of-hours, double-booking, same-day past time
- PDF document library — upload in Business Settings → agent emails PDF via Gmail on request
- Agent OFF → silent SIP REFER to business phone
- Google OAuth token refresh logging — all 4 paths log exact error on failure

### Known Bugs — None ✅
All previously tracked bugs resolved this session.

### Blocked / Waiting
- **Google OAuth app verification** — reply sent to Google Jun 15 with test credentials. Waiting on Google's response.
- **SMS 2FA** — blocked on client A2P 10DLC campaign approval
- **Resend DNS** — re-add DKIM/SPF/DMARC for `aiemployeesinc.com` on Hostinger
- **Sam's old test accounts** — waiting on Sam to send list of emails to delete from Supabase auth

---

## Infrastructure

| Container | Port | Notes |
|---|---|---|
| `sam-backend-sam-backend-1` | 8003 | FastAPI, hot reload |
| `sam-backend-sam-agent-1` | — | LiveKit agent, hot reload |

Key env files:
- `backend/.env` — all backend secrets
- `agent/.env.local` — SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, LIVEKIT_*, OPENAI_API_KEY, TWILIO_*, GOOGLE_CLIENT_ID/SECRET, AGENT_NAME

**Important:** When switching Google Cloud projects, update BOTH `backend/.env` AND `agent/.env.local`. Backend creates OAuth tokens; agent refreshes them. Mismatched credentials = silent `invalid_client` failures every hour.

---

## Live Client Businesses (DB wiped Jun 8, fresh setup)

| Business | ID | Gmail | Documents |
|---|---|---|---|
| Divinity DJs | `9ae4cf35` | `info@canadastopdjs.com` (connected) | Divinity Packages Prices |
| Mirage Banquet | `5b8e077d` | `info@mirageedmonton.ca` (may be expired) | 7 documents (menus, packages) |
| AI Employees inc. | `e45c5ffd` | Sam's account | — |

**Google OAuth test credentials** (sent to Google for verification):
- URL: https://portal.aiemployeesinc.com
- Email: `info@canadastopdjs.com`
- Password: Sanjeev123#@!

---

## Architecture Overview

### Agent Context Resolution (priority order)
1. `ctx.job.metadata` — JSON `{business_id, location_id, call_id}` from LiveKit dispatch rule
2. `participant.metadata` — same JSON, set by backend token (web calls)
3. `participant.attributes` — SIP attrs
4. DB lookup by `sip.trunkPhoneNumber` in `business_phone_numbers` (last resort)

### Key Backend Patterns
- All Supabase reads use `supabase_admin` (service role) to bypass RLS
- `verify_business_access(user_id, business_id)` enforced on all routers
- `require_business_access()` — FastAPI dependency factory
- Settings endpoints use SELECT + INSERT/UPDATE (not upsert) for partial unique index compatibility

### Phone Number / SIP Architecture
- One shared Twilio Elastic SIP trunk for all businesses
- One LiveKit inbound SIP trunk
- One LiveKit dispatch rule per phone number — carries `{business_id, location_id}` in metadata
- US + CA numbers supported

### Google OAuth Architecture
- **Supabase Auth Google** — controls "Sign in with Google" login. Separate credentials, not ours.
- **`backend/.env` GOOGLE_CLIENT_ID/SECRET** — controls Gmail + Calendar integrations per location
- **`agent/.env.local` GOOGLE_CLIENT_ID/SECRET** — MUST match backend. Agent refreshes tokens; backend creates them.
- Current project: `870924190939-gqnop6gsjdm698eg5n2oog9bb1qi3kt4.apps.googleusercontent.com`
- Scopes used: `gmail.send`, `calendar.events`, `userinfo.email`, `openid`

---

## Key Files

### Backend
- `backend/app/core/auth.py` — `verify_business_access`, `require_business_access`, `get_user_id`, `require_role`
- `backend/app/routers/calls.py` — call CRUD + initiate + outbound
- `backend/app/routers/settings.py` — agent settings, state, schedule, communication, deactivate
- `backend/app/routers/forwarding.py` — contacts + rules CRUD
- `backend/app/routers/documents.py` — PDF document library CRUD
- `backend/app/services/email_service.py` — Gmail send functions + token refresh
- `backend/app/services/google_calendar_service.py` — Calendar CRUD + token refresh (**timezone bug here**)

### Agent
- `agent/agent.py` — main agent, all tools
- `agent/prompt_builder.py` — builds full system prompt
- `agent/supabase_helpers.py` — DB fetch helpers, slot computation, feature flag checks
- `agent/gmail_helpers.py` — all Gmail send functions + `_gmail_get_valid_token`
- `agent/gcal_helpers.py` — Google Calendar CRUD + token refresh
- `agent/sms_helpers.py` — Twilio SMS

### Frontend (ai-employees-app/src)
- `lib/voiceAgentApi.ts` — all backend API calls
- `contexts/AuthContext.tsx` — session, user, roles, canAccess(), permissionsLoading
- `components/business/IntegrationsTab.tsx` — Gmail/Calendar connect/disconnect UI
- `pages/dashboard/TeamManagement.tsx` — invite, remove (Option B reassign), roles
- `pages/dashboard/BusinessSettings.tsx` — all business settings tabs including Documents

---

## Pending Manual Steps

- [ ] **Merge `feature/google-calendar-timezone` → main** on both repos (both deployed to VPS, ready to merge)
- [ ] **Deploy scheduler fix to VPS** — `git pull && docker compose restart sam-backend` (fixes hourly 400 errors in logs)
- [ ] **Sam sets business timezone** — Business Settings → Company Info → Business Timezone dropdown → Save
- [ ] **Forgot password email spam** — improve Supabase Auth email template + Resend DKIM alignment
- [ ] **Deploy edge functions** — `supabase functions deploy invite-location-admin accept-invitation`
- [ ] **Resend DNS on Hostinger** — re-add DKIM/SPF/DMARC for `aiemployeesinc.com`
- [ ] **Create Stripe price IDs** — Growth ($149) + Pro ($299) → add to `backend/.env`
- [ ] **Update billing URLs on server** — `BILLING_SUCCESS_URL=http://116.202.210.102:20252/...`
- [ ] **Update Stripe webhook URL** to prod domain when HTTPS is set up
- [ ] **VPS deploy on Hostinger** — both repos, SSL, subdomain
- [ ] **`POST /phone-numbers/sync-dispatch`** — re-stamp existing dispatch rules with `location_id` (one-time run)
- [ ] **Delete Sam's old test accounts** — waiting on Sam's email list
- [ ] **IntegrationsTab loading state** — show spinner during initial Gmail status fetch instead of "Connect" flash

## Applied Migrations (all done)
- All through `20260428000003` ✅ applied
- `20260522000001` — profiles team visibility RLS ✅
- `20260522000000` — business_documents table ✅

## Pending Migrations (not yet applied)
- `20260618000000_businesses_timezone.sql` — add `timezone TEXT DEFAULT 'America/Toronto'` to businesses. File exists in `ai-employees-app/supabase/migrations/`. Run `supabase db push`.

---

## What Was Done This Session (Session 50, 2026-06-22)

**Website KB scraper complete (both backend + frontend). Two security fixes. Executive Agent plan written.**

### 1. Website KB Scraper — backend security fixes
- `knowledge_base.py`: replaced direct sitemap fetch with Jina AI Reader fetch — eliminates SSRF DNS-rebinding TOCTOU window
- Removed `defusedxml` dependency (no longer parsing XML directly)
- Added `location_id` ownership validation against `business_id` before delete/insert — prevents IDOR cross-business writes
- Commit: `52ab917` on `feature/google-calendar-timezone` (sam-backend)

### 2. Website KB Scraper — frontend (Task 2)
- `ai-employees-app/src/lib/voiceAgentApi.ts`: added `scrapeWebsiteToKB()` function (POST /knowledge-base/scrape)
- `ai-employees-app/src/pages/dashboard/BusinessSettings.tsx`: "Generate from Website" card added above file upload in KB tab
  - If `business.website` set → button scrapes immediately, shows URL as hint
  - If not set → opens dialog to enter URL (saves to Company Info + scrapes)
  - Loading spinner + "Generating…" text + "20–30 seconds" note
  - On success: toast with entry count + KB list auto-refreshes
  - Imports: Globe + Loader2 icons added
- Commit: `efdb03d` on `feature/google-calendar-timezone` (ai-employees-app)
- Tested by user: scraping works, data saves and renders ✅

### 3. Sales Agent — put on HOLD
- Sam confirmed 2026-06-22: legal concerns about outbound cold-calling
- Meeting lawyer this week — do NOT build until Sam gives green light
- Sam sent 7 UI mockup screenshots (saved locally at `/home/lap-68/Downloads/Screen 1-7.png`)
- Mockups show: Dashboard, Lead Generator (CSV upload + built-in lead DB search), Call Lists, Scheduler, Recordings + Transcripts, Call Results, Settings (call goal, objection handling, forwarding)
- Much more detailed than originally scoped — includes built-in lead database, scheduler with sessions, objection handling config

### 4. Executive Agent — UI layout confirmed, plan locked, ready to build
- Sam confirmed: "Continue to build the Executive Agent"
- UI layout confirmed by Rahul — full plan: `docs/superpowers/plans/2026-06-22-executive-agent-plan.md`
- Layout: split view — left (agent chat interface like Dex sample) + right (collapsible transcript)
- Left: agent name + animated status header, agent responses in main area, input bar (text + mic toggle + send)
- Right: full back-and-forth transcript, toggle via ⓘ icon in header
- Mic: text-only by default; clicking mic enables voice in same LiveKit session via `setMicrophoneEnabled()` — no reconnect
- States: idle → listening (🎤 pulse) → thinking (··· dots) → speaking (▌▌▌ waveform bars)
- State driven by LiveKit data messages from agent (not inferred from audio)
- Also working on a Marketing Agent design (will share separately)

---

## What Was Done This Session (Session 49, 2026-06-20)

**Google Calendar timezone fix shipped, production debugging, Executive Agent doc.**

### 1. Google Calendar timezone fix — fully implemented and deployed
- Root cause: `timeZone: "UTC"` hardcoded in both `google_calendar_service.py` and `gcal_helpers.py`
- DB migration `20260618000000_businesses_timezone.sql` — adds `timezone TEXT NOT NULL DEFAULT 'America/Toronto'` to `businesses` table (applied)
- Backend: `_appointment_to_event`, `create_calendar_event`, `update_calendar_event` accept `timezone` param; `booking_service._get_business` now fetches timezone
- Agent: `gcal_helpers` all three build/create/update functions accept timezone; `agent.py` loads `business_timezone` from `_fetch_business`, stores as `self._business_timezone`, passes everywhere
- `.ics` attachments: `ics_helpers.generate_ics` uses `DTSTART;TZID=` format when timezone provided (anchors calendar invite in email clients)
- `gmail_helpers`: both confirmation and reschedule send functions accept and pass `business_timezone`
- Frontend: timezone dropdown in Business Settings → Company Info (13 options: full Canada + common US); pre-filled from browser on first load; saves with company info
- Supabase TS types regenerated; all `as any` casts removed
- Both repos committed on `feature/google-calendar-timezone`, deployed to VPS
- **Verified working**: 9 PM Eastern appointment shows as 6:30 AM in India (GMT+05:30) — correct UTC conversion

### 2. Scheduler location_id=None bug fixed (not yet deployed to VPS)
- `scheduler_service.py`: all 3 scheduler functions (reminder, reschedule, no-show) were passing Python `None` as string `"None"` to Supabase UUID queries → hourly 400 errors in logs
- Fix: `if not location_id: continue` guard added to all three loops
- Committed to feature branch — needs `git pull` + `docker compose restart sam-backend` on VPS

### 3. Production debugging — Gmail/Calendar false alarm
- Sam reported Gmail and Calendar not working on deployed app
- Verified: all tokens expired but refresh_token valid (confirmed by direct Google API test → got fresh access token)
- Root cause: tokens were idle 2 days with no activity, auto-refreshed fine on first real use
- VPS credentials (`backend/.env` and `agent/.env.local`) both verified correct
- Sam tested and confirmed everything working: PDF send, booking, confirmation email all ✅

### 4. Executive Agent overview doc
- Created `docs/executive-agent-overview.md` and HTML artifact for Sam
- Covers: live AI avatar character (3 states), how it works, capabilities, Voice Agent vs Executive Agent comparison, billing integration (add-on model, Stripe line item), two-phase build plan
- Sam asked for hour estimate — pending meeting

## What Was Done This Session (Session 48, 2026-06-17/18)

**Production debugging, PDF send fully verified, Google OAuth status, repo divergence resolved.**

### 1. PDF send — diagnosed, verified, stress tested
- Sam connected Gmail (`info@canadastopdjs.com`) for Divinity DJs
- Ran full pipeline replication: Gmail token → signed URL → PDF download → Gmail API send ✅
- Token refresh stress test: 3 rounds, each with forced expiry → 3/3 passed, refresh ~410ms, send ~3s
- **Subject line fixed**: `"Document from Divinity DJs: Divinity Packages Prices"` → `"Divinity Packages Prices"` (`agent/agent.py` line 794)
- Email confirmed arriving in inbox with PDF attached

### 2. IntegrationsTab — fetch error no longer flashes "Connect"
- Bug: if `getGmailStatus` errors on page load, initial `connected: false` state showed "Connect" even when connected
- Fix: comment clarified — don't reset to disconnected on fetch error
- `ai-employees-app` commit: `110d909`

### 3. Google OAuth verification
- Google replied Jun 12: justification insufficient + couldn't test app
- Sam replied Jun 15 with detailed justification + test credentials
- Test account set up: `info@canadastopdjs.com` on portal.aiemployeesinc.com
- Waiting on Google's next response

### 4. Google Calendar timezone bug — spec written, not yet implemented
- Root cause: `timeZone: "UTC"` hardcoded in `google_calendar_service.py` line 150-151
- Fix: store `timezone` on `businesses` table, use it in calendar event `timeZone` field
- Full spec: `docs/superpowers/specs/2026-06-18-business-timezone.md`
- Browser API used as default suggestion only; DB is source of truth; agent reads from DB

### 5. Same-day past time restriction (from session 47 — was missing from handoff)
- `_compute_available_slots` — skips slots at/before current UTC time when date is today
- `_validate_booking_datetime` — rejects same-day times ≤ now with clear error message
- `prompt_builder.py` — explicit rule added to LLM instructions

### 6. Repo divergence resolved
- Both repos had diverged histories: a Windows machine (same GitHub account) had force-pushed commits
- Evidence: `temp_auto_push.bat` + `temp_interactive_push.bat` in `.gitignore` from origin
- Fixed with `git rebase origin/main` on both repos, then pushed
- Both repos now in sync with origin ✅

### Commits this session (sam-backend)
- `b8584a5` — fix PDF email subject line
- `f326e65`, `af904e5` — client comms log updates
- `94e02fb` — Google OAuth verification guide for Sam
- `349e739` — business timezone spec
- `4e7f759`, `07ec3ac` — session handoff docs

### Commits this session (ai-employees-app)
- `110d909` (rebased → `82a620a`) — IntegrationsTab fetch error fix

---

## What Was Done (Session 47, 2026-06-08)

**8 items shipped, 1 deferred, full DB wiped clean for fresh start.**

1. **Gmail OAuth credential fix** — `agent/.env.local` had old Google Cloud project (`902808969705`) + truncated secret. Fixed to match `backend/.env` (`870924190939`).
2. **Google OAuth token refresh hardening** — all 4 paths now log exact Google error on failure. Null `token_expiry` treated as expired.
3. **Agent OFF → silent SIP REFER** — Quick Agent Control OFF + real SIP call + `businesses.phone` set → 1s pause → SIP REFER to business phone. Confirmed working.
4. **Team Management Option B** — per-appointment replacement with conflict validation before removing user.
5. **Same-day past time blocking** — `_compute_available_slots` + `_validate_booking_datetime` + prompt rule.
6. **Business notification when PDF sent** — `_gmail_send_document_notification()` in `gmail_helpers.py`.
7. **Database wiped clean** — tables + auth users. Scripts in `scripts/`.
8. **Deferred**: background office noise (Q6) — STT interference risk, v2.

---

## What Was Done (Session 46, 2026-06-05)

- PDF document library — `POST/GET/DELETE /documents`, Supabase Storage `business-documents` bucket, agent `email_document` tool
- Booking confirmation spelling — agent reads phone digit-by-digit, email letter-by-letter
- Agent farewell — "Anything else?" → "Thank you, have a great day!"
- Scheduler toggle preserves `greeting_message` — fetches existing config before update
- Team Management "Unknown User" RLS fix — `20260522000001` migration
- Calendar date off-by-one fixed — `parseISO()` instead of `new Date()`
- Date picker click area — `showPicker()` on all 4 date inputs
- Knowledge Base inline edit — pencil + textarea per text entry
- Services X button in appointment form
- Double-booking blocked by duration
- Change password verifies current password first
- Pro Feature badges removed
