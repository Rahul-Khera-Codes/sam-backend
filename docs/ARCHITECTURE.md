# SAM — AI Voice Agent Platform: Architecture Documentation

> **Audience:** Developers joining the project, or anyone who needs to understand how the system works without reading the source code.
> **Last updated:** 2026-03-31

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Infrastructure & Deployment](#4-infrastructure--deployment)
5. [Backend API](#5-backend-api)
6. [Voice Agent](#6-voice-agent)
7. [Frontend](#7-frontend)
8. [Database Schema](#8-database-schema)
9. [Key Flows End-to-End](#9-key-flows-end-to-end)
10. [External Integrations](#10-external-integrations)
11. [Authentication & Security](#11-authentication--security)
12. [Environment Variables Reference](#12-environment-variables-reference)

---

## 1. System Overview

SAM is a **multi-tenant AI voice agent SaaS** that allows businesses to deploy an AI receptionist that:

- Answers inbound phone calls via PSTN (Twilio → LiveKit SIP)
- Makes outbound calls (appointment reminders, feedback, follow-ups)
- Books, reschedules, and cancels appointments in real-time during the call
- Sends confirmation emails (Gmail) and SMS (Twilio) after bookings
- Syncs appointments to Google Calendar for both the client and staff
- Provides a management dashboard: call recordings, transcripts, analytics, feature settings, call forwarding

Each **business** is a tenant. A business can have multiple **locations**, multiple **staff members** (users), and multiple **phone numbers**. The AI agent is fully configurable per business: brand voice, business hours, services, staff availability, knowledge base, and 10 feature flag toggles.

---

## 2. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                        BROWSER (Staff)                             │
│            React + TypeScript + Vite (ai-employees-app)            │
│   Dashboard / Calendar / Call Recordings / Settings / Phone Mgmt   │
└──────────────┬────────────────────────────────┬───────────────────-┘
               │ REST API (JWT Bearer)           │ Supabase JS SDK
               ▼                                ▼
┌──────────────────────┐          ┌─────────────────────────┐
│   FastAPI Backend    │          │        Supabase          │
│   (sam-backend)      │◄────────►│  PostgreSQL + Auth + RLS │
│   Port 8003          │          │  Storage + Realtime      │
└──────────┬───────────┘          └─────────────────────────┘
           │ LiveKit SDK                    ▲
           ▼                               │ service role (bypass RLS)
┌──────────────────────┐          ┌────────┴────────────────┐
│   LiveKit Cloud      │          │    LiveKit Agent         │
│  (Rooms, SIP, Trunks)│◄────────►│    (sam-agent)           │
│                      │          │    Port 8001             │
└──────────┬───────────┘          │    GPT-4o Realtime       │
           │ SIP PSTN             └─────────────────────────-┘
           ▼
┌──────────────────────┐
│   Twilio             │
│  (Phone numbers,     │
│   SIP Trunking)      │
└──────────────────────┘
```

### Two Repos

| Repo | Description |
|---|---|
| `sam-backend/` | FastAPI backend + LiveKit agent. **This repo.** |
| `ai-employees-app/` | React/TypeScript frontend. Sibling directory. |

### Two Key Principles

1. **All Supabase reads in backend routers use `supabase_admin`** (service role key) to bypass Row Level Security. Auth is still enforced via the JWT dependency `Depends(get_current_user)` — so the user must be authenticated, but the DB read goes through service role to avoid RLS blocking.

2. **The agent reads Supabase directly** using its own service role key (from `agent/.env.local`). The agent never calls the FastAPI backend — it queries Supabase tables directly for business data, availability, and appointments.

---

## 3. Tech Stack

| Layer | Technology |
|---|---|
| Frontend framework | React 18 + TypeScript + Vite |
| Frontend UI | shadcn/ui + Tailwind CSS |
| Frontend state | React hooks + Context (no Redux) |
| Backend framework | FastAPI (Python 3.11) |
| Backend validation | Pydantic v2 |
| Database | Supabase (PostgreSQL + Auth + RLS) |
| Voice AI | LiveKit Agents + OpenAI GPT-4o Realtime |
| SIP / PSTN | Twilio Elastic SIP Trunking + LiveKit SIP |
| Email | Gmail API (OAuth 2.0) |
| Calendar sync | Google Calendar API (OAuth 2.0) |
| SMS | Twilio REST API |
| Containerisation | Docker + Docker Compose |
| Python dependency manager | uv (agent) / pip (backend) |

---

## 4. Infrastructure & Deployment

### Docker Services

All services are defined in `docker-compose.yml` at the repo root:

| Service | Port | Source | Hot Reload |
|---|---|---|---|
| `sam-backend` | 8003 | `./backend/` | Yes (uvicorn --reload) |
| `sam-agent` | 8001 | `./agent/` | Yes (python agent.py dev) |
| `sam-frontend` | varies | `../ai-employees-app/` | Yes (volume mount) |

### Starting the Stack

```bash
docker compose up -d                       # start all services
docker logs -f sam-backend-sam-agent-1     # watch agent logs
docker logs -f sam-backend-sam-backend-1   # watch backend logs
docker compose restart sam-agent           # restart agent after deep changes
```

### Key Files

```
sam-backend/
├── backend/
│   ├── .env                   ← backend secrets (never commit)
│   ├── app/
│   │   ├── main.py            ← FastAPI app, routers, CORS
│   │   ├── core/
│   │   │   ├── auth.py        ← JWT validation
│   │   │   ├── config.py      ← Settings (pydantic-settings)
│   │   │   └── supabase.py    ← supabase + supabase_admin clients
│   │   ├── routers/           ← one file per router
│   │   ├── schemas/           ← Pydantic request/response models
│   │   └── services/          ← business logic (LiveKit, email, phone, calendar)
│   └── requirements.txt
├── agent/
│   ├── .env.local             ← agent secrets (never commit)
│   ├── agent.py               ← LiveKit agent entrypoint
│   ├── prompt_builder.py      ← system prompt generation
│   ├── sms_helpers.py         ← Twilio SMS
│   ├── supabase_helpers.py    ← DB queries + availability logic
│   ├── gcal_helpers.py        ← Google Calendar API
│   └── gmail_helpers.py       ← Gmail API
├── docs/                      ← this documentation lives here
└── docker-compose.yml
```

---

## 5. Backend API

**Base URL:** `http://localhost:8003` (dev) / configured via `VITE_VOICE_AGENT_API_URL` in frontend

**Authentication:** All endpoints (except `/health`) require `Authorization: Bearer <supabase_access_token>` header.

**business_id:** Most endpoints require `?business_id=<uuid>` as a query parameter. The backend validates the JWT but currently trusts the `business_id` from the query param (authorization check is a future TODO).

---

### 5.1 Calls Router — `/calls`

Manages call records, transcripts, summaries, recordings.

| Method | Path | Description |
|---|---|---|
| GET | `/calls` | List calls with filters |
| GET | `/calls/recent-activity` | Last N calls formatted for activity feed |
| GET | `/calls/{call_id}` | Single call record |
| GET | `/calls/{call_id}/transcript` | All utterances for a call |
| GET | `/calls/{call_id}/summary` | GPT-4o generated summary |
| GET | `/calls/{call_id}/recording` | Signed S3 URL for audio (1h expiry) |
| POST | `/calls/initiate` | Start a web (browser) call |
| POST | `/calls/outbound` | Initiate an outbound PSTN call |
| PUT | `/calls/{call_id}/status` | Update call status |

#### `POST /calls/initiate` — Web Call Flow

Used when a staff member clicks "Test Agent" in the browser:

1. Create LiveKit room (`call-{random}`)
2. Insert `calls` row with `status=initiating`
3. Generate LiveKit JWT for user (includes `{call_id, business_id, location_id}` in metadata)
4. If `USE_LIVEKIT_AGENT=1`: dispatch agent via `create_agent_dispatch()` + update status to `active`
5. Return `{call_id, livekit_room_id, livekit_token, livekit_ws_url}`

Frontend uses the `livekit_token` to connect its mic to the room. The agent joins automatically.

#### `POST /calls/outbound` — Outbound PSTN Call Flow

Used when staff initiates a call to a customer's phone number:

1. Look up business's phone number + `livekit_outbound_trunk_id` from `business_phone_numbers`
2. Create LiveKit room
3. Insert `calls` row with `direction=outbound, status=initiating`
4. Dispatch agent with metadata `{call_id, business_id, call_direction: "outbound", call_purpose}`
5. Call `create_sip_participant()` — LiveKit dials the customer via Twilio SIP
6. Update call status to `active`

---

### 5.2 Settings Router — `/settings`

Manages AI agent configuration for a business.

#### Feature Flags (`/settings/agent`)

10 feature toggles stored in `agent_settings` table. All changes are logged to `settings_audit_log`.

| Feature Key | Default | Description |
|---|---|---|
| `inbound_calling` | ✓ | Agent answers inbound calls |
| `outbound_calling` | ✓ | Agent makes outbound calls |
| `call_forwarding` | ✓ | Forward calls to contacts |
| `send_texts_during_after_calls` | ✓ | SMS confirmations after booking |
| `missed_call_text_back` | ✓ | SMS when caller hangs up without help |
| `callback_scheduling` | ✓ | Schedule callback calls |
| `reschedule_cancel_appointments` | ✓ | Agent can modify appointments |
| `confirmation_reminder_calls` | ✓ | Reminder call before appointments |
| `multi_language_support` | ✗ | Multilingual (Pro feature) |
| `feedback_after_call` | ✓ | Ask for rating at end of call |

| Method | Path | Description |
|---|---|---|
| GET | `/settings/agent` | Load all feature flags |
| PUT | `/settings/agent` | Save feature flag changes (+ audit log) |
| POST | `/settings/agent/reset` | Reset all to defaults |
| GET | `/settings/agent/state` | Is agent active? (global on/off) |
| PUT | `/settings/agent/state` | Toggle agent on/off |
| GET | `/settings/agent/audit-log` | Last 50 setting changes |
| GET | `/settings/communication` | Call/email/SMS script templates |
| PUT | `/settings/communication` | Save communication templates |

---

### 5.3 Forwarding Router — `/forwarding`

Manage who calls get forwarded to and under what conditions.

| Method | Path | Description |
|---|---|---|
| GET | `/forwarding/contacts` | List forwarding contacts |
| POST | `/forwarding/contacts` | Add contact |
| PUT | `/forwarding/contacts/{id}` | Update contact |
| DELETE | `/forwarding/contacts/{id}` | Delete contact |
| PUT | `/forwarding/contacts/{id}/toggle` | Enable/disable contact |
| PUT | `/forwarding/contacts/bulk/toggle` | Enable/disable all contacts |
| GET | `/forwarding/rules` | List forwarding rules |
| POST | `/forwarding/rules` | Add rule |
| PUT | `/forwarding/rules/{id}` | Update rule |
| DELETE | `/forwarding/rules/{id}` | Delete rule |

> **Note:** The bulk toggle route is registered *before* `/{contact_id}/toggle` to prevent FastAPI matching `"bulk"` as a UUID.

---

### 5.4 Analytics Router — `/analytics`

All analytics compute from the `calls` table. Comparisons calculate % change vs the previous equivalent period.

| Method | Path | Description |
|---|---|---|
| GET | `/analytics/summary` | KPI cards (total calls, avg duration, success rate) |
| GET | `/analytics/call-volume-trends` | Time-series inbound/outbound chart data |
| GET | `/analytics/call-distribution` | Donut chart: completed/missed/forwarded/failed |

**Period params:** `7d`, `30d`, `90d` for summary/distribution; `daily`, `weekly`, `monthly` for trends.

---

### 5.5 Integrations Router — `/integrations`

#### Google Calendar (`/integrations/google`)

OAuth 2.0 flow for syncing appointments to staff Google Calendars.
Scope: `https://www.googleapis.com/auth/calendar.events`

| Method | Path | Description |
|---|---|---|
| GET | `/integrations/google/auth-url` | Get OAuth consent URL |
| POST | `/integrations/google/callback` | Exchange code for tokens, save to DB |
| GET | `/integrations/google/status` | Is connected? Which email? |
| DELETE | `/integrations/google/disconnect` | Revoke + delete tokens |

State passed through OAuth: `{user_id, business_id, return_to}` — allows returning to the originating page.

#### Gmail (`/integrations/gmail`)

Same OAuth flow but for sending emails.
Scope: `https://www.googleapis.com/auth/gmail.send`

| Method | Path | Description |
|---|---|---|
| GET | `/integrations/gmail/auth-url` | Get OAuth consent URL |
| POST | `/integrations/gmail/callback` | Exchange code, save tokens |
| GET | `/integrations/gmail/status` | Is connected? Which email? |
| DELETE | `/integrations/gmail/disconnect` | Revoke + delete tokens |

---

### 5.6 Phone Numbers Router — `/phone-numbers`

Manages Twilio phone number provisioning. Admin-only for write operations.

| Method | Path | Description |
|---|---|---|
| GET | `/phone-numbers/search` | Search available Twilio numbers by area code |
| POST | `/phone-numbers/provision` | Purchase + wire a number end-to-end |
| GET | `/phone-numbers` | List active numbers for the business |
| DELETE | `/phone-numbers/{id}` | Release number + clean up all LiveKit resources |

#### `POST /phone-numbers/provision` — Full Provisioning Flow

This single endpoint does everything needed to make a phone number work:

1. **Twilio:** Purchase the phone number, assign to shared SIP trunk
2. **LiveKit:** Create a per-number **inbound SIP trunk** (security: only accept calls to this number)
3. **LiveKit:** Create a **dispatch rule** — routes calls from the inbound trunk to the agent, carrying `{business_id}` in attributes
4. **LiveKit:** Create a per-number **outbound SIP trunk** (Twilio termination credentials)
5. **DB:** Insert row in `business_phone_numbers` with all IDs

#### `DELETE /phone-numbers/{id}` — Release Flow

1. Delete LiveKit dispatch rule
2. Delete LiveKit inbound trunk
3. Delete LiveKit outbound trunk  ← Added to prevent orphaned trunks
4. Release Twilio number
5. Soft-delete DB row (`is_active=False, released_at=now()`)

---

### 5.7 Services Layer

#### `livekit_service.py`

Wraps LiveKit Python SDK. All methods are async.

| Function | Description |
|---|---|
| `generate_room_id()` | Returns `"call-{12 hex chars}"` |
| `create_room(room_id)` | Creates LiveKit room (empty_timeout=300s, max_participants=2) |
| `end_room(room_id)` | Deletes room |
| `generate_user_token(room_id, name, metadata?)` | JWT for browser user |
| `generate_agent_token(room_id)` | JWT for agent worker |
| `create_agent_dispatch(room_id, metadata?)` | Explicitly dispatch named agent to room |
| `create_sip_participant(room_id, to_number, from_number, outbound_trunk_id)` | Dial PSTN number into room |

**Important:** `outbound_trunk_id` is passed explicitly from the DB (not from a global env var). Each number has its own trunk stored in `business_phone_numbers.livekit_outbound_trunk_id`.

#### `phone_number_service.py`

Twilio + LiveKit SIP lifecycle management. All provisioning is async.

#### `email_service.py` (Gmail)

Sends HTML emails via Gmail API. Handles token auto-refresh before each send.

Email template: styled HTML with dark header, appointment detail card, confirmation reference number.

#### `google_calendar_service.py`

Creates/updates/deletes Google Calendar events. Handles token refresh automatically.

---

## 6. Voice Agent

The agent lives in `agent/agent.py` and is a **LiveKit Agents** process. It connects to LiveKit Cloud as a persistent worker and is automatically dispatched to rooms.

### 6.1 Agent Lifecycle

```
LiveKit detects new room (from dispatch rule or explicit dispatch)
  → Agent worker receives job
  → entrypoint() called
    → Resolve business_id, location_id, call_id (4 sources, see below)
    → Load business data from Supabase
    → Build system prompt (prompt_builder.py)
    → Create VoicePipelineAgent (OpenAI GPT-4o Realtime)
    → Start agent session
    → If outbound call: agent speaks first (introduce + state purpose)
    → If inbound call: wait for customer to speak
    → [CONVERSATION — tools available]
    → On session end: _finalize_call()
      → Save transcripts to `transcripts` table
      → Update call record (status, ended_at, duration_seconds)
      → Generate GPT-4o summary → save to `call_summaries`
      → Update calls.sentiment
      → If missed call + feature enabled: send missed-call SMS
```

### 6.2 Context Resolution (Priority Order)

The agent resolves `business_id`, `location_id`, `call_id` from 4 sources in order:

| Priority | Source | Used For |
|---|---|---|
| 1 | `ctx.job.metadata` | Dispatch rule attributes (SIP inbound + explicit dispatch) |
| 2 | `participant.metadata` | Backend token metadata (web browser calls) |
| 3 | `participant.attributes` | SIP participant attrs — only reads `business_id`, NOT `location_id` |
| 4 | DB lookup by `sip.trunkPhoneNumber` | Last resort: look up business from `business_phone_numbers` |

> **Why Source 3 doesn't read `location_id`:** Dispatch rule attributes can have stale `location_id` values that no longer exist in the `locations` table, causing FK violations on insert. The location is now determined from the DB.

### 6.3 System Prompt Builder (`prompt_builder.py`)

The `build_instructions(business_id, location_id)` function assembles a comprehensive system prompt from Supabase data:

1. **Global settings** — language, country, date/time format
2. **Business details** — name, type, phone, email, address, website, payment methods, policies, service area
3. **Business hours** — from `business_hours` table, formatted by day
4. **Services list** — name, duration, price, description (preloaded so agent doesn't need tool call for "what do you offer?")
5. **Brand voice** — tone, style, vocabulary preferences, do-not-say list, sample responses
6. **Location(s) + staff** — which staff are at which location
7. **Knowledge base** — free-text Q&A entries from `knowledge_base` table
8. **Booking instructions** — the standard booking workflow the agent must follow

**Fallback:** If `location_id` is None, the prompt builder uses `locations[0]` so the greeting always includes a location name.

### 6.4 Agent Tools

The agent has 6 function tools available during a call:

| Tool | Description |
|---|---|
| `get_services()` | Lists active services with duration and price |
| `get_staff_for_service(service_name)` | Staff at the current location who can perform a service |
| `get_available_slots(...)` | Computes free time slots from `user_availability` + `user_availability_overrides` minus existing `appointments` |
| `book_appointment(...)` | Inserts into `appointments` table; triggers emails, SMS, Google Calendar |
| `find_appointments(client_name)` | Searches upcoming appointments by client name (ilike) |
| `update_appointment(...)` | Reschedules appointment; availability check; sends reschedule emails to customer + staff |
| `cancel_appointment(...)` | Soft-cancels (`status='cancelled'`); sends cancellation emails; deletes Google Calendar events |

**Preloading:** At session start, the agent preloads locations, services, staff, and user_service_ids into memory. Tools use these in-memory lookups — no per-tool DB round trips.

### 6.5 Post-Call Actions

After every call, `_finalize_call()` executes:

1. **Transcripts:** Bulk-saves all conversation turns to `transcripts` table
2. **Call record:** Updates `status=completed`, `ended_at`, `duration_seconds`
3. **Summary:** Sends full transcript to GPT-4o chat endpoint → receives structured JSON `{summary, key_topics, insights, sentiment}` → saves to `call_summaries` + updates `calls.sentiment`
4. **Missed call SMS:** If `inbound` call + empty transcript + `missed_call_text_back` feature enabled → sends text-back SMS to caller

### 6.6 After Booking — Triggered Actions

When `book_appointment` tool is called:

| Action | Condition |
|---|---|
| Confirmation email to customer | Always (if `client_email` provided) |
| Notification email to assigned staff | Always |
| Confirmation SMS to customer | If `send_texts_during_after_calls` feature enabled |
| Google Calendar event (staff) | If staff has Google Calendar connected |
| Google Calendar event (super_admin) | If super_admin has Google Calendar connected |

Emails are sent via Gmail API (business's connected Gmail account). SMS via Twilio (business's provisioned number).

### 6.7 Call Direction

The agent detects whether it's an inbound or outbound call from SIP attributes (`sip.callDirection`).

- **Inbound:** Agent waits for the customer to speak first, then greets normally per brand voice
- **Outbound:** Agent speaks first: introduces itself, states the call purpose, asks how it can help

---

## 7. Frontend

**Framework:** React 18 + TypeScript + Vite
**UI:** shadcn/ui components + Tailwind CSS
**Router:** React Router v6
**Auth:** Supabase Auth (via `@supabase/supabase-js`)

### 7.1 Route Structure

```
/                       → Redirect to /login
/login                  → Login
/signup                 → Signup
/forgot-password        → Password reset request
/reset-password         → New password form
/onboarding             → Business + location + phone setup (3 steps)
/select-location        → Choose location for session
/dashboard
  /                     → Main dashboard
  /calendar             → Calendar (month/week/day/list views, full CRUD)
  /customer-service
    /dashboard           → AgentPerformance (analytics, charts, activity feed)
    /recordings          → CallRecordings (list, transcript, summary, audio)
    /scheduler           → AI Agent Scheduler
    /call-forwarding     → CallForwarding (contacts + rules)
    /settings            → AgentSettings (10 feature toggles)
  /settings
    /global             → Global settings (language, region, formats)
    /business           → Business profile settings
    /account            → User profile + Google Calendar connect
    /integrations        → Google Calendar OAuth + Gmail OAuth
    /phone-numbers       → Phone number provisioning + management
    /brand-voice         → 5-step brand voice wizard
  /team                 → Team management (invite, roles, location assignments)
/integrations/google/callback  → OAuth callback handler
/integrations/gmail/callback   → Gmail OAuth callback handler
```

### 7.2 Authentication Flow

1. User logs in via Supabase Auth (`supabase.auth.signInWithPassword`)
2. `AuthContext` stores `session` (includes JWT `access_token`)
3. `ProtectedRoute` component checks session; redirects to `/login` if missing
4. Backend API calls include `Authorization: Bearer {access_token}`
5. Backend validates JWT using `SUPABASE_JWT_SECRET`

### 7.3 Key Hooks

| Hook | Where | Purpose |
|---|---|---|
| `useAuth()` | `contexts/AuthContext.tsx` | Current user session, login/logout |
| `useBusiness()` | `hooks/useBusiness.ts` | Current `businessId` + `locationId` from localStorage |
| `useAppointments()` | `hooks/useAppointments.ts` | CRUD for `appointments` table (direct Supabase) |
| `useTeamManagement()` | `hooks/useTeamManagement.ts` | Staff list, roles, location assignments |
| `useServices()` | `hooks/useServices.ts` | CRUD for `services` table |
| `useUserServices()` | `hooks/useUserServices.ts` | Staff ↔ service mapping |
| `useTeamMemberAvailability()` | `hooks/useTeamMemberAvailability.ts` | Staff working hours |
| `useDebounce()` | `hooks/useDebounce.ts` | Debounced search inputs |

> **Pattern:** Appointments, services, staff availability are written **directly to Supabase** from the frontend (no backend API layer). The agent also reads these tables directly. The backend API only handles calls, settings, forwarding, analytics, integrations, and phone numbers.

### 7.4 Customer Service Pages

#### AgentPerformance (`/dashboard`)
- Stat cards: total calls, avg duration, success rate, missed calls (from `/analytics/summary`)
- Area chart: inbound vs outbound call volume over time (from `/analytics/call-volume-trends`)
- Donut chart: call distribution by status (from `/analytics/call-distribution`)
- Activity feed: last 10 calls with status + sentiment (from `/calls/recent-activity`)

#### CallRecordings (`/recordings`)
- Left panel: scrollable call list with search + filter (all/inbound/outbound)
- Right panel: selected call detail — metadata grid, transcript chat bubbles, summary/insights tabs, audio player
- **"New Call" button:** Opens `OutboundCallDialog` — select call type, pick appointment (auto-filtered), auto-fills phone, shows agent purpose preview, triggers `POST /calls/outbound`
- Calls loaded from `GET /calls`, transcript from `GET /calls/{id}/transcript`, summary from `GET /calls/{id}/summary`

#### Scheduler (`/scheduler`)
- Agent toggle: calls `GET/PUT /settings/agent/state`
- Weekly schedule UI: shows days/times — **not yet wired to backend** (save button is currently a mock — TODO)

#### CallForwarding (`/call-forwarding`)
- Forwarding contacts list (from `GET /forwarding/contacts`)
- Toggle/delete/add contacts (wired to API)
- Forwarding rules panel (from `GET /forwarding/rules`)
- Today's stats from `GET /analytics/summary`

#### AgentSettings (`/settings`)
- All 10 feature toggles loaded from `GET /settings/agent`
- Save wired to `PUT /settings/agent`
- Reset wired to `POST /settings/agent/reset`
- Quick actions panel: Enable All, Disable All, agent toggle
- Recent changes from `GET /settings/agent/audit-log`
- Configuration presets: Basic Setup, Standard Business, Full Featured

### 7.5 Outbound Call Dialog (`components/OutboundCallDialog.tsx`)

Reusable dialog for initiating outbound calls. Used from the Call Recordings header.

**Call types:**
- **Appointment Reminder** → filters appointments to future dates only
- **Appointment Feedback** → filters appointments to past dates only
- **Follow-up Call** → filters to past appointments
- **General Outreach** → no appointment filter, manual phone entry

**Behavior:**
- Selecting an appointment auto-fills the phone from `client_phone`
- If appointment has no phone on record → falls back to manual entry
- Shows a preview of the instruction string the agent will receive
- On submit: calls `POST /calls/outbound` via `initiateOutboundCall()`
- On success: reloads call list

### 7.6 Calendar Page (`/calendar`)

Full calendar implementation (824 lines) with:
- Month / week / day / list views
- Create / edit / delete appointments (writes directly to Supabase `appointments` table)
- Filter by team member
- Search appointments
- Appointment details modal: shows client name, service, date, time, staff, duration, notes, **phone**, **email**
- Edit modal: all fields editable including phone + email (saves `client_phone`, `client_email` to DB)

### 7.7 Phone Numbers Page (`/settings/phone-numbers`)

- Lists active numbers with status badge
- Area code search → results list → provision button
- Release button with confirmation dialog
- Wired to `/phone-numbers/search`, `/phone-numbers/provision`, `/phone-numbers`, `/phone-numbers/{id}`

### 7.8 Integrations Page (`/settings/integrations`)

- **Google Calendar card:** Connect (OAuth redirect) / Disconnect / shows connected email
- **Gmail card:** Same flow
- **Twilio card:** Status display (not yet wired)

---

## 8. Database Schema

All tables live in Supabase PostgreSQL. The frontend reads most tables directly via Supabase JS SDK. The backend uses `supabase_admin` (service role) to bypass RLS.

### Core Business Tables

```sql
businesses          -- tenant root: name, type, address, phone, email, website, etc.
locations           -- business locations: name, address, timezone
profiles            -- user profiles: first_name, last_name, avatar_url (extends auth.users)
user_roles          -- role assignments: user_id, business_id, role (super_admin|admin|user)
user_locations      -- which locations a staff member works at
```

### Call Tables

```sql
calls               -- call records: business_id, location_id, caller_name, caller_phone,
                    --   direction (inbound|outbound), status, sentiment,
                    --   duration_seconds, livekit_room_id, handled_by,
                    --   started_at, ended_at, created_at

transcripts         -- call_id, speaker (agent|customer), text,
                    --   timestamp_seconds, sequence_order

call_summaries      -- call_id, summary_text, key_topics (jsonb),
                    --   insights (jsonb), generated_at

recordings          -- call_id, storage_bucket, storage_path,
                    --   duration_seconds, file_size_bytes
```

### Appointment Tables

```sql
appointments        -- business_id, location_id, assigned_user_id,
                    --   client_name, client_phone, client_email,
                    --   service, appointment_date, appointment_time, duration,
                    --   notes, status (confirmed|cancelled),
                    --   google_event_id, google_event_id_admin,
                    --   do_not_contact, created_by

services            -- business_id, name, description, duration_minutes, price, is_active
user_services       -- user_id, service_id (staff ↔ service mapping)
user_availability   -- user_id, day_of_week (0-6), start_time, end_time, is_available
user_availability_overrides -- user_id, override_date, is_available, start_time, end_time
```

### Settings Tables

```sql
agent_settings      -- business_id, feature_key, is_enabled, config_value, updated_by
agent_state         -- business_id, is_active, toggled_at, toggled_by
settings_audit_log  -- business_id, feature_key, old_value, new_value, changed_by, changed_at
communication_settings -- business_id, channel, type, is_enabled, days_offset, script
business_hours      -- business_id, day_of_week, open_time, close_time, is_open
brand_voice_profiles -- business_id, tone, style, vocabulary, do_not_say, sample_responses, is_active
knowledge_base      -- business_id, title, content, content_type (text|url|file)
```

### Forwarding Tables

```sql
forwarding_contacts -- business_id, location_id, name, phone, department_tag, priority, is_active
forwarding_rules    -- business_id, name, condition_type, condition_value, action,
                    --   is_active, priority_order
```

### Integration Tokens

```sql
google_calendar_tokens -- staff_id, business_id, google_email,
                       --   access_token, refresh_token, token_expiry
gmail_tokens           -- business_id, google_email,
                       --   access_token, refresh_token, token_expiry, updated_at
```

### Phone / SIP Tables

```sql
business_phone_numbers -- business_id, location_id, phone_number (E.164),
                       --   twilio_number_sid, twilio_trunk_sid,
                       --   livekit_inbound_trunk_id,   ← per-number inbound trunk
                       --   livekit_dispatch_rule_id,   ← per-number dispatch rule
                       --   livekit_outbound_trunk_id,  ← per-number outbound trunk
                       --   is_active, created_at, released_at
```

### RLS Policy Pattern

- `supabase` anon client → respects RLS → used only in frontend
- `supabase_admin` service role → bypasses RLS → used in **all** backend routers and agent
- The backend enforces auth via `Depends(get_current_user)` independently of RLS

---

## 9. Key Flows End-to-End

### 9.1 Inbound SIP Call Flow

```
Customer dials business number (+14157077538)
  → Twilio SIP trunk (TK83cb7...) receives call
  → Twilio sends SIP INVITE to LiveKit SIP endpoint
  → LiveKit matches inbound trunk (ST_7UYZrjxvwhm8) → dispatch rule (SDR_s6FZouinFiun)
  → Dispatch rule carries {business_id} in attributes
  → Dispatch rule auto-dispatches agent worker to new room

Agent (agent.py):
  → Reads business_id from ctx.job.metadata
  → Queries Supabase for all business data
  → Builds system prompt
  → Starts VoicePipelineAgent (GPT-4o Realtime)
  → Creates call record in DB (status=active, caller_phone from SIP attrs)
  → Waits for customer to speak

Conversation happens...

Agent detects hangup:
  → _finalize_call()
  → Save transcripts, update call status, generate summary
  → Send missed-call SMS if applicable
```

### 9.2 Outbound Call Flow

```
Staff selects appointment → clicks "Start Call" in OutboundCallDialog
  → POST /calls/outbound {business_id, to_phone_number, call_purpose}

Backend:
  → SELECT phone_number, livekit_outbound_trunk_id FROM business_phone_numbers
      WHERE business_id=X AND is_active=true AND livekit_outbound_trunk_id != ''
  → create_room()
  → INSERT calls (direction=outbound, status=initiating, caller_phone=to_phone_number)
  → create_agent_dispatch(room, {call_id, business_id, call_direction=outbound, call_purpose})
  → create_sip_participant(room, to_number, from_number, outbound_trunk_id)
      → LiveKit → Twilio termination domain → PSTN → rings customer
  → UPDATE calls SET status=active

Agent:
  → Receives dispatch with call_direction=outbound
  → Loads business data, builds prompt
  → Speaks first: introduce self + state call_purpose
  → Conversation with customer
  → _finalize_call() on hangup
```

### 9.3 Phone Number Provisioning Flow

```
Staff searches area codes → selects number → clicks "Provision"
  → POST /phone-numbers/provision {phone_number, location_id?}

Backend:
  → Twilio: purchase number, assign to shared trunk
  → LiveKit: create inbound trunk (security: numbers=[phone_number])
  → LiveKit: create dispatch rule (carries business_id, auto-dispatches agent)
  → LiveKit: create outbound trunk (Twilio termination credentials)
  → DB: INSERT business_phone_numbers with all 3 LiveKit IDs + twilio SIDs

Number is now live:
  → Inbound: calls to this number → agent answers
  → Outbound: POST /calls/outbound uses this number's outbound trunk
```

### 9.4 Booking an Appointment (During a Call)

```
Customer: "I'd like to book a massage on Friday"

Agent (book_appointment tool):
  1. get_available_slots(location_id, staff_id, service_id, "2026-04-04")
     → supabase_helpers._compute_available_slots()
     → Reads user_availability (weekly hours)
     → Reads user_availability_overrides (time off)
     → Reads appointments WHERE assigned_user_id=X AND date=Friday AND status!=cancelled
     → Returns: ["09:00", "10:00", "11:00", "14:00"]

  2. Customer confirms: "10 AM works"

  3. book_appointment(client_name, client_email, client_phone, service_id, ...)
     → INSERT appointments (status=confirmed, client_email, client_phone, ...)
     → send_appointment_confirmation_sms() if feature enabled
     → _gmail_send_confirmation() if client_email provided
     → _gmail_send_staff_notification() to assigned staff
     → _gcal_create_event() on staff calendar + super_admin calendar if connected
```

### 9.5 Post-Call Summary Generation

```
Agent session ends (customer hangs up)
  → _finalize_call()
  → Collect all transcript turns from memory (conversation_item_added events)
  → INSERT transcripts (bulk)
  → UPDATE calls SET status=completed, ended_at=now(), duration_seconds=X
  → Build prompt: "Summarise this call in JSON: {summary, key_topics, insights, sentiment}"
  → POST to OpenAI chat/completions with full transcript
  → Parse JSON response
  → INSERT call_summaries
  → UPDATE calls SET sentiment=X
```

---

## 10. External Integrations

### 10.1 Twilio

**Used for:**
- Purchasing and managing PSTN phone numbers
- Elastic SIP trunking (inbound: Twilio → LiveKit; outbound: LiveKit → Twilio → PSTN)
- Sending SMS (appointment confirmations, reminders, missed-call text-backs)

**Key env vars:** `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_TRUNK_SID`, `TWILIO_TERM_DOMAIN`, `TWILIO_TERM_SIP_USERNAME`, `TWILIO_TERM_SIP_PASSWORD`

### 10.2 LiveKit Cloud

**Used for:**
- Real-time audio rooms (browser mic + agent audio)
- SIP participant management (inbound + outbound PSTN bridge)
- Agent dispatch (auto-dispatch to rooms via dispatch rules)

**Key resources per phone number:**
- 1 inbound SIP trunk (accepts calls to that number)
- 1 dispatch rule (routes to agent with business_id attribute)
- 1 outbound SIP trunk (dials out via Twilio)

**Key env vars:** `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_SIP_HOST`, `LIVEKIT_SIP_INBOUND_TRUNK_ID` (shared), `SIP_AUTH_USERNAME`, `SIP_AUTH_PASSWORD`

### 10.3 OpenAI

**Used for:**
- GPT-4o Realtime API: real-time voice conversation in the agent
- GPT-4o Chat API: post-call summary generation

**Key env var:** `OPENAI_API_KEY`

### 10.4 Google Calendar

**Used for:** Creating/updating/deleting calendar events on staff + admin calendars when appointments are booked/rescheduled/cancelled.

**OAuth:** Per-user (each staff member connects their own Google account). Tokens stored in `google_calendar_tokens` table.

**Key env vars:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`

### 10.5 Gmail

**Used for:** Sending transactional emails (appointment confirmation, staff notification, reschedule, cancellation).

**OAuth:** Per-business (one Gmail account per business). Tokens stored in `gmail_tokens` table.

**Key env vars:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GMAIL_REDIRECT_URI`

> The same Google OAuth app handles both Calendar and Gmail — same client credentials, different scopes and different redirect URIs.

---

## 11. Authentication & Security

### JWT Validation (Backend)

```python
# app/core/auth.py
token = extract_bearer_token(request)
payload = jwt.decode(
    token,
    settings.supabase_jwt_secret,
    algorithms=["HS256"],
    options={"verify_aud": False}  # Supabase doesn't use aud claim
)
# payload = {sub: user_uuid, email, role, ...}
```

Both `get_current_user()` and `get_user_id()` are FastAPI dependencies used with `Depends()`.

### Supabase RLS

Row Level Security is enabled on all tables. The anon client (used by the frontend browser SDK) is restricted to only seeing rows the authenticated user is allowed to see. The service role key (used by backend + agent) bypasses all RLS.

**Pattern in all backend routers:**
```python
# Auth enforced by JWT dependency:
current_user = Depends(get_current_user)

# But DB reads use admin client to bypass RLS:
result = supabase_admin.table("calls").select("*").eq("business_id", business_id).execute()
```

### Role-Based Access

User roles in `user_roles` table: `super_admin`, `admin`, `user`

- Phone number provisioning/release: `admin` or `super_admin` only
- All other endpoints: any authenticated user (business_id filter provides tenant isolation)

---

## 12. Environment Variables Reference

### `backend/.env`

```bash
# Supabase
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=

# LiveKit
LIVEKIT_URL=wss://xxx.livekit.cloud
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
LIVEKIT_SIP_INBOUND_TRUNK_ID=    # shared inbound trunk (from setup_sip_trunks.py)
LIVEKIT_SIP_HOST=                # e.g. xxx.sip.livekit.cloud

# OpenAI
OPENAI_API_KEY=

# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_TRUNK_SID=                # shared elastic SIP trunk SID
TWILIO_TERM_DOMAIN=              # e.g. xxx.pstn.twilio.com
TWILIO_TERM_SIP_USERNAME=
TWILIO_TERM_SIP_PASSWORD=

# SIP Auth (LiveKit ↔ Twilio digest auth)
SIP_AUTH_USERNAME=
SIP_AUTH_PASSWORD=

# Google OAuth (shared for Calendar + Gmail)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8080/integrations/google/callback
GMAIL_REDIRECT_URI=http://localhost:8080/integrations/gmail/callback

# AWS S3 (optional, for call recordings)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
S3_BUCKET_NAME=

# App
ENVIRONMENT=development
CORS_ORIGINS=http://localhost:5173
AGENT_NAME=ai-employee-agent
USE_LIVEKIT_AGENT=1
```

### `agent/.env.local`

Same Supabase, LiveKit, OpenAI, Twilio vars. Plus:
```bash
AGENT_NAME=ai-employee-agent     # must match dispatch rule + backend AGENT_NAME
```

### `ai-employees-app/.env`

```bash
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_VOICE_AGENT_API_URL=http://localhost:8003  # no trailing slash, no backtick!
```

---

## Appendix: Known Limitations & TODOs

| Area | Status | Notes |
|---|---|---|
| Call recording | Not implemented | Requires LiveKit Egress integration |
| Scheduler weekly schedule save | Mock only | Backend endpoint `GET/PUT /settings/agent/schedule` not built yet |
| `.ics` attachment in emails | Not implemented | Calendar file not attached to confirmation emails |
| Reminder emails/SMS | Not implemented | Needs a scheduler/cron job |
| Business authorization check | Weak | Backend trusts `business_id` from query param; no cross-check against user_roles |
| HTTPS for production | Not configured | `getUserMedia` (mic) requires secure context |
| Marketing / Sales / HR / Exec pages | Stubs | Not yet implemented |
| +14152555624 outbound trunk | Missing | No LiveKit outbound trunk linked for this number |
