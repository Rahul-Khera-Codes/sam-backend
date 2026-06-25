# Session Handoff — 2026-06-24 (Session 52)

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

Both repos are on `feature/google-calendar-timezone`, deployed to VPS. **NOT yet ready to merge** — Executive Agent calendar-create is broken (see Executive Agent section) and the timezone migration is unapplied.

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

### Executive Agent — BUILT, in active hardening (workstreams, session 52) ⚠️
Backend + frontend committed on `feature/google-calendar-timezone` (both repos), deployed and running from that branch. Earlier "SHIPPED" was wrong. Worked as separate trackable workstreams (verify → spec → implement); specs in `docs/superpowers/specs/2026-06-24-*`.
- **WS0 calendar-create timezone bug** — ✅ FIXED + live-verified. `confirm_create_calendar_event` now uses the approved preview's tz-aware ISO + adds `"timeZone": self._business_timezone`. Real event created at correct time.
- **WS1 naming (Remi)** — ✅ DONE + live-verified. Persona "Remi" in prompt/greeting/status-header/empty-state; product label "Executive Agent" kept on page H1 + cancel-note + dispatch names.
- **WS2 personality/emotion** — ✅ DONE + live-verified. Rewrote `EXECUTIVE_INSTRUCTIONS` (persona + emotion + behavior rules: answer identity Qs directly, only tool-call for real actions), `RealtimeModel(voice="cedar", temperature=0.9)`. Follow-ups: "ALWAYS respond in English" rule (was drifting to Turkish) + text handler now `generate_reply(user_input=text)` (was stuffing into `instructions` → identity didn't ground).
- **WS5 Gmail location context** — ✅ code done, pending live verify. `/executive/session` now passes `location_id` (FE sends `selectedLocationId`) into both metadata blocks → Gmail token lookup uses the right location.
- **WS6 Gmail read scope (403)** — ✅ code done. Added `gmail.readonly` to `GMAIL_SCOPE`. Diagnosed via DB+API test: token valid but Gmail returned `403 ACCESS_TOKEN_SCOPE_INSUFFICIENT` (integration only had `gmail.send`). Needs: backend restart + Google consent-screen scope add + Gmail reconnect. ⚠️ restricted scope → CASA for launch.
- **WS3 rich cards** — spec written (`…-cards-phase-a.md`), NOT implemented (beyond approved doc; awaiting go).
- **WS4 central avatar** — approved Phase-1 scope, spec not written. Phase-2 = HeyGen talking-avatar picker (per `Executive Assistant.pdf`).
- **Still open:** Calendar `reschedule_event` tool (overview Phase 1, only appointment reschedule exists); no-show/client-history tools; billing toggle (price TBD); migration `20260618000000` apply; merge to main.

### Blocked / Waiting
- **Gmail read scope verification (CASA)** — `gmail.readonly` is a Google *restricted* scope → public launch needs a paid annual CASA security assessment. Works now for test users. **Decision for Sam.** Also: don't escalate the core product's pending verification by jamming the read scope into it.
- **Local Gmail-read testing blocked** — dev's localhost callback isn't in Sam's OAuth client (can't edit it). Path: create a **dev OAuth client** (own Google project, Testing mode, localhost redirect URIs, gmail.send+readonly+calendar scopes, dev as test user) → set in local `backend/.env` + `agent/.env.local`. Or have Sam add the localhost redirect + test user.
- **OAuth verification status unknown** — Sam's personal Google account; need Sam to report current status.
- **Google OAuth app verification** — reply sent to Google Jun 15. Waiting (predates the gmail.readonly addition).
- **SMS 2FA** — blocked on client A2P 10DLC campaign approval.
- **Resend DNS** — re-add DKIM/SPF/DMARC for `aiemployeesinc.com` on Hostinger.
- **Sam's old test accounts** — waiting on Sam to send emails to delete.
- **Two-way Google Calendar sync** — direction confirmed (pull GCal events INTO portal); per-staff vs business-wide still open.

---

## Infrastructure

| Container | Port | Notes |
|---|---|---|
| `sam-backend-sam-backend-1` | 8003 | FastAPI, hot reload |
| `sam-backend-sam-agent-1` | — | LiveKit CS agent, hot reload |
| `sam-backend-sam-executive-agent-1` | 8002 | LiveKit Executive Agent, hot reload |

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
- `backend/app/routers/executive.py` — `POST /executive/session` — creates LiveKit room for Executive Agent
- `backend/app/services/email_service.py` — Gmail send functions + token refresh
- `backend/app/services/google_calendar_service.py` — Calendar CRUD + token refresh
- `backend/app/services/livekit_service.py` — includes `create_executive_agent_dispatch()`

### Agent
- `agent/agent.py` — CS agent, all tools
- `agent/executive_agent.py` — Executive Agent (Gmail + Calendar + Appointments tools, state signalling, preview-approve flow)
- `agent/prompt_builder.py` — builds full system prompt
- `agent/supabase_helpers.py` — DB fetch helpers, slot computation, feature flag checks
- `agent/gmail_helpers.py` — all Gmail send functions + `_gmail_get_valid_token`
- `agent/gcal_helpers.py` — Google Calendar CRUD + token refresh
- `agent/sms_helpers.py` — Twilio SMS

### Frontend (ai-employees-app/src)
- `lib/voiceAgentApi.ts` — all backend API calls (includes `createExecutiveSession`)
- `contexts/AuthContext.tsx` — session, user, roles, canAccess(), permissionsLoading
- `components/business/IntegrationsTab.tsx` — Gmail/Calendar connect/disconnect UI
- `pages/dashboard/TeamManagement.tsx` — invite, remove (Option B reassign), roles
- `pages/dashboard/BusinessSettings.tsx` — all business settings tabs including Documents
- `pages/dashboard/ExecutiveAgent.tsx` — Executive Agent split-pane UI
- `hooks/useExecutiveSession.ts` — LiveKit room, transcript, state, streaming, preview-approve
- `components/executive/AgentStatusHeader.tsx` — state indicator (pulse/dots/waveform) + transcript toggle
- `components/executive/AgentDisplay.tsx` — live agent text + preview panel (email draft / calendar)
- `components/executive/TranscriptPanel.tsx` — collapsible right panel with streaming bubble
- `components/executive/InputBar.tsx` — textarea + mic toggle + send button
- `components/layout/DashboardLayout.tsx` — FULL_HEIGHT_ROUTES pattern for no-padding full-height pages

---

## Pending Manual Steps

- [ ] **Executive Agent — activate Gmail reading (WS6):** `docker compose restart sam-backend` (new scope) + Google Cloud OAuth consent screen → add `gmail.readonly` (keep app Testing mode w/ test users) + Business Settings → Integrations → Gmail → Disconnect+reconnect to re-consent. Then test "list my emails".
- [ ] **Dev OAuth client for local Gmail testing** — own Google project, Testing mode, localhost redirect URIs (`http://localhost:5173/integrations/{gmail,google}/callback`), scopes gmail.send+gmail.readonly+calendar.events+userinfo.email+openid, dev as test user; put client id/secret in local `backend/.env` AND `agent/.env.local`.
- [ ] **Restart `sam-executive-agent`** to pick up WS5 (location_id) — and rebuild frontend.
- [ ] **Decision (Sam): Gmail CASA** — commit to restricted-scope assessment for launch, or narrow feature. Don't escalate the core product's pending verification.
- [ ] **Merge `feature/google-calendar-timezone` → main** on both repos (deployed to VPS, NOT ready until exec-agent hardening + timezone migration done)
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

## What Was Done This Session (Session 52, 2026-06-24)

**Executive agent log analysis, Sam client messages logged, memory + TODO updated.**

### 1. Docker log analysis — executive agent

Analyzed full terminal logs from first live executive agent sessions. Findings:

- **05:55 crash (`ValueError: expected RoomOptions, got NoneType`)** — old container image was still running before `docker compose up --build`. Resolved once rebuilt. No action needed.
- **Cancelled responses (session at 06:55)** — 12 `OpenAI Realtime API response done but not complete with status: cancelled` events. Normal turn-taking behavior — user was speaking while agent was generating. Not a bug.
- **`SOURCE_UNKNOWN` at attach time** — normal. Room pre-attaches an audio input before user mic connects; upgrades to `SOURCE_MICROPHONE` when participant publishes mic track.
- **GCal 400 bug confirmed live (job `AJ_BUkqK3XsRDGM`, 07:18:19 and 07:18:33)** — `confirm_create_calendar_event` sends `start_iso="2026-06-23T10:00:00"` as bare naive datetime. Google Calendar API returns `400: Missing time zone definition for start time`. Agent retried twice, same error both times. Root cause: event body missing `"timeZone"` key in `start`/`end` objects.

### 2. Sam client messages — logged

Three messages from Sam reviewed and logged:

- **Website KB as document** — Sam confirmed it does NOT need to be a document. No action.
- **Two-way Google Calendar sync (new request)** — Sam: "Is it possible to pull calendar events from a Google calendar into our portal appointment calendar — customers are asking for a two-way sync". Added to TODO backlog. Questions sent to Sam about scope (direction + per-staff vs business-wide).
- **Outbound Calling Employee rename** — Sam renamed original "Sales Employee" mockups (7 screens) to "Outbound Calling Employee". Separate new screenshots coming for "Sales Employee". Updated TODO + memory files. Questions sent to Sam about what Outbound Calling Employee does functionally and whether legal hold still applies.

### 3. Executive Agent — reconciliation, calendar fix, naming, design docs

- **Reconciled real status** against the full Sam chat (Jun 12–24) + both docs. Earlier "SHIPPED" was wrong → reclassified **BUILT & COMMITTED, NOT COMPLETE**. Avatar reclassified from "blocked" to **approved Phase-1 scope, ready for spec**.
- **Calendar-create bug FIXED in code** (`confirm_create_calendar_event`): now uses the approved preview's timezone-aware ISO + adds `"timeZone": self._business_timezone`. AST-parse clean; pending live verify (restart `sam-executive-agent`).
- **Default agent name decided: "Remi"** (persona). "Executive Agent" stays the product/page label.
- **Cards UI decisions** made (single active card + transcript breadcrumb; buttons+voice one path; 8-card Phase-1 set).
- **Scope classification** vs the approved overview doc: Phase 1 (3-state avatar, Gmail/Cal/Appt, billing toggle), Phase 2 (expressive face, personality settings, CRM, handoff), and **beyond-doc additions** (rich cards UI, personality/emotion polish).
- **Process agreed with user:** each concern is its own workstream — verify → spec → implementation → commit, kept separate/trackable (no bundling).
- **New docs:** `docs/executive-agent-personality-and-flows.md`, `docs/executive-agent-cards-design.md`. New memory: `reference_executive_avatar.md`, `feedback_dev_process.md`.
- **Timeline:** Executive Agent estimate given to Sam = 2 weeks from Mon Jun 22 → ~Jul 3–6.

### 4. Files updated

- `TODO.md` — Two-way GCal sync backlog; Sales/Outbound Calling Employee split; full Executive Agent reconciliation + WS breakdown + scope classification + calendar-fix status
- `docs/CLIENT_COMMS_LOG.md` — Jun 22→23 chat, Executive Agent decision lineage (Jun 12→22), Jun 24 sales questions sent
- `memory/project_blockers.md`, `memory/project_voice_agent.md`, `memory/project_feature_sales_agent.md`, `memory/MEMORY.md` — reconciled
- `agent/executive_agent.py` — calendar-create timezone fix (WS0)

### 5. Executive Agent hardening — WS1/WS2/WS5/WS6 (implemented + verified)
- **WS1 naming → "Remi"** (live-verified). **WS2 personality** — persona/emotion prompt rewrite + `voice="cedar"`/`temp=0.9` + English-lock + `generate_reply(user_input=text)` fix (all live-verified: "I'm Remi", in-character, English).
- **WS5 Gmail location** — `/executive/session` passes `location_id`; FE sends `selectedLocationId`. **WS6 Gmail read scope** — added `gmail.readonly` (reads were 403 scope-insufficient); needs reconnect + CASA-for-launch.
- New specs: `2026-06-24-executive-agent-{naming-remi,personality,cards-phase-a,location-gmail-fix}.md`. New docs: `executive-agent-{personality-and-flows,cards-design}.md`.
- Files touched: `agent/executive_agent.py`, `backend/app/routers/executive.py`, `backend/app/services/email_service.py`, `ai-employees-app/src/{lib/voiceAgentApi.ts,hooks/useExecutiveSession.ts,components/executive/AgentStatusHeader.tsx,components/executive/AgentDisplay.tsx}`.

### 6. Sam — Sales Employee answers + build-sequence change + 5 PDFs (logged)
- **Sequence:** Executive Assistant → Sales Employee → Outbound Calling Employee (Outbound DEFERRED). Marketing Employee being designed.
- **Sales Employee answers:** Apify API for data; no Push-to-CRM yet; defined pipeline + report sections; CASL via lawyer. Requirements now confirmed (build after Exec Assistant).
- **5 reference PDFs** in `/home/lap-68/Downloads/`: Executive Assistant (HeyGen avatar picker = Phase-2 avatar), Branding (expanded Branding tab), Sales Employee (4 modules), Outbound Caller + Marketing Employee (not yet reviewed).

### 7. OPEN QUESTIONS FOR SAM (drafted, not yet sent)
1. Gmail: current OAuth verification status? + CASA commit-or-narrow for launch? + `readonly` vs `modify` (will Remi manage the inbox)?
2. Avatar: confirm abstract Phase-1 avatar OK, HeyGen as Phase 2 (so we build a swappable placeholder)?
3. Rich cards in this release (extra time) or text-first now, cards later?
4. Billing toggle now vs free-during-beta, and the price?
5. Sales Employee (later): Apify scraping LinkedIn still risks LinkedIn ToS (lawyer should cover); does Sam have an Apify account/budget?

---

## What Was Done This Session (Session 51, 2026-06-22)

**Executive Agent fully built — backend worker, all frontend components, layout fixed, text streaming fixed.**

### 1. Executive Agent — complete build

**Backend (`sam-backend`):**
- `agent/executive_agent.py` — full LiveKit Agents v1.5.1 worker: Gmail tools (list/read/draft_reply), Google Calendar tools (get_schedule/create_event/find_free_slots), Appointments tools (list/cancel/reschedule). State signalling via `_set_state(room, state)` publishing `{state}` data messages. Preview-approve flow: agent sends `{type: "preview", kind: "email_draft"|"calendar_event", ...}` → user approves/rejects → agent acts.
- `backend/app/routers/executive.py` — `POST /executive/session`: verify business access, create LiveKit room with `executive-` prefix, dispatch executive agent, return `{room_name, token, livekit_url}`.
- `backend/app/services/livekit_service.py` — `create_executive_agent_dispatch(room_id, *, metadata)`.
- `backend/app/main.py` — registered executive router.
- `docker-compose.yml` — added `sam-executive-agent` service on port 8002.
- Commits: `cdccacf` (backend build), `075d722` (streaming fix)

**Frontend (`ai-employees-app`):**
- `src/pages/dashboard/ExecutiveAgent.tsx` — split-pane layout. Always renders AgentDisplay + InputBar (not gated on isConnected). `currentAgentText = streamingAgentText ?? lastAgentEntry?.text ?? ""`.
- `src/hooks/useExecutiveSession.ts` — connects Room, listens on `RoomEvent.TranscriptionReceived` for word-by-word streaming, `RoomEvent.DataReceived` for state signals + preview items. Exposes `streamingAgentText`.
- `src/components/executive/AgentStatusHeader.tsx` — animated state indicators: pulse dot (listening), three-dot bounce (thinking), waveform bars (speaking), static dot (idle). ⓘ button toggles transcript.
- `src/components/executive/AgentDisplay.tsx` — 3 states: fresh-empty (briefcase placeholder), session-ended-with-history (dim message), connected (live/last agent text). Preview panel for email draft / calendar event approval.
- `src/components/executive/TranscriptPanel.tsx` — collapsible right panel with chat bubbles. Shows streaming bubble with blinking cursor while agent is mid-sentence.
- `src/components/executive/InputBar.tsx` — auto-resize textarea, mic toggle (glows when enabled), send button.
- `src/components/layout/DashboardLayout.tsx` — added `FULL_HEIGHT_ROUTES = ["/dashboard/executive"]`; full-height routes skip `p-8` wrapper and use `h-screen overflow-hidden flex flex-col min-h-0`.
- `tailwind.config.ts` — added `thinking-dot`, `waveform`, `pulse-slow` keyframes + animations.
- `src/App.tsx` — wired `<Route path="executive" element={<ExecutiveAgent />} />`.
- Commits: `3f15a87` (main build), `52264d4` (layout + disconnected state fix), `7630cd0` (streaming fix)

### 2. Runtime bugs fixed

- **Exit code 0 restart loop** — missing `if __name__ == "__main__": agents.cli.run_app(server)` at end of `executive_agent.py`. Docker ran the module, found no entrypoint, exited cleanly. Fix: added entrypoint block. Required `docker compose build sam-executive-agent`.
- **`ValueError: expected RoomOptions, got NoneType`** — `session.start()` was called with `room_options=None` explicitly. Fix: changed to `room_options=room_io.RoomOptions()` and added `room_io` import.
- **Left panel showed disconnected state mid-session** — `AgentDisplay` + `InputBar` only rendered when `isConnected === true`. After session ends, left snaps to briefcase but right transcript persists. Fix: always render both; `AgentDisplay` has 3 internal states.
- **Right panel vertical stretch / page scroll** — `DashboardLayout` used `min-h-screen overflow-y-auto`. `h-full` in child resolved to content height, not viewport. Fix: `h-screen overflow-hidden` root; `FULL_HEIGHT_ROUTES` skips padding wrapper; `min-h-0` throughout flex chain.
- **Text only appears after full sentence** — `conversation_item_added` fires once per complete utterance. `text_output=True` (default in `RoomOptions`) already streams via `RoomEvent.TranscriptionReceived` with `TranscriptionSegment.final`. Fix: added `TranscriptionReceived` listener in `useExecutiveSession`; removed manual relay from `executive_agent.py`.

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
