# Voice Agent - TODO Tracker

Covers: `sam-backend` (backend + agent) and `ai-employees-app` (frontend)
Last updated: 2026-03-24 (session 4)

---

## ✅ Done

### Backend
- [x] FastAPI app with CORS, health check, JWT auth (Supabase)
- [x] `POST /calls/initiate` — creates LiveKit room, call record, returns token
- [x] `GET /calls`, `GET /calls/{id}`, `GET /calls/{id}/transcript`, `GET /calls/{id}/summary`, `GET /calls/{id}/recording`
- [x] `PUT /calls/{id}/status`
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
- [x] **`book_appointment`** tool — inserts into `appointments` table, links `call_id` in notes, stores phone in notes
- [x] **`find_appointments`** tool — finds upcoming appointments by client name (ilike search)
- [x] **`update_appointment`** tool — reschedules by appointment ref ID
- [x] **`cancel_appointment`** tool — deletes appointment by ref ID
- [x] Preloads locations, services, staff + user_service_ids at call start (no per-tool DB round trips for lookups)
- [x] Post-call: `conversation_item_added` event captures all transcript turns in memory
- [x] Post-call: bulk-saves transcript utterances to `transcripts` table on call end
- [x] Post-call: updates call record — `status=completed`, `ended_at`, `duration_seconds`
- [x] Post-call: GPT-4o chat generates JSON summary → saved to `call_summaries` with `key_topics`, `insights`
- [x] Post-call: updates `calls.sentiment` from summary result

### Bugs Fixed
- [x] `ai-employees-app/.env` — stray backtick on `VITE_VOICE_AGENT_API_URL` caused 404 on `/calls/initiate`
- [x] `user_services` RLS — staff could not select their own services; added policy `Users can manage their own service assignments` (migration `20260323000000_user_services_staff_rls.sql`)

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
- [x] **Calendar page** — fully implemented, month/week/day/list views, full CRUD (`Calendar.tsx`, 824 lines)
- [x] **Appointments** — `useAppointments.ts` full CRUD, saves to `appointments` table in Supabase
- [x] **Services** — `useServices.ts` full CRUD + `ServicesTab.tsx` UI, saves to `services` table
- [x] **Staff ↔ Services mapping** — `useUserServices.ts` full CRUD, saves to `user_services` table
- [x] **Staff working hours** — `useTeamMemberAvailability.ts` + `useUserAvailability.ts`, saves to `user_availability` table
- [x] **Staff time off / date overrides** — `user_availability_overrides` table, full CRUD + UI (TeamMemberHoursDialog, DateOverrideModal)

---

## 🔄 In Progress

_(nothing currently in progress)_

---

## 📋 TODO

### Backend — Appointment & Service API Endpoints
These don't exist yet on the backend (frontend queries Supabase directly — backend is unaware):
- [ ] `GET/POST /appointments` — list + create
- [ ] `GET/PUT/DELETE /appointments/{id}` — detail, update, cancel
- [ ] `GET /appointments/availability` — available slots for a staff member on a date
- [ ] `GET/POST/PUT/DELETE /services` — service CRUD
- [ ] `GET /services/{service_id}/staff` — staff who offer this service

### Backend — Business Authorization
- [ ] Add business_id authorization check — verify user has `user_roles` entry for requested `business_id` (currently trusts frontend)

### Communication Settings — Fix Frontend Save
- [ ] `CustomerServiceSettings.tsx` — "Save All Settings" button currently does nothing; wire up to `PUT /settings/communication` backend endpoint

### Phone / Twilio Integration (when Twilio access available)
- [ ] `business_phone_numbers` table — `(id, business_id, location_id, phone_number E.164, twilio_sid, is_active)`
- [ ] Phone number management UI (assign Twilio number per business)
- [ ] `POST /calls/inbound/twilio` webhook — look up `business_id` from Twilio `To` number, create LiveKit room, bridge call via LiveKit SIP, dispatch agent
- [ ] LiveKit SIP configuration — register LiveKit as SIP endpoint with Twilio
- [ ] Outbound call initiation — backend calls Twilio API to dial out, bridges into LiveKit room
- [ ] Update agent to handle `direction: inbound` vs `outbound` differently (inbound: wait and greet; outbound: initiate opener)

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

### Email Sending
- [ ] Choose provider: SendGrid or AWS SES
- [ ] Email service in backend (`backend/app/services/email_service.py`)
- [ ] Send appointment confirmation email on booking (include `.ics` attachment)
- [ ] Send reminder email N days before appointment
- [ ] Wire up `confirmation_reminder_calls` feature flag

### Frontend — Remaining Stubs
- [ ] Marketing Employee page
- [ ] Sales Employee page
- [ ] HR Employee page
- [ ] Executive Assistant page
- [ ] Billing page
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
- [ ] **CS3 Scheduler** — new backend endpoint `GET/PUT /settings/agent/schedule` (backed by `business_hours` table) + wire frontend
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
