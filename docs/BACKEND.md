# SAM Backend — Documentation

This document describes the **SAM (AI Voice Agent) backend**: what it does, how it aligns with the existing frontend (AI Employees App), and how the **voice agent** fits as the first integration for the Customer Service agent.

---

## 1. Purpose

The backend is the **AI Voice Agent API** for the AI Employees product. It powers:

- **Voice calls** — LiveKit rooms, call records, transcripts, summaries, and (optionally) recordings.
- **Customer Service agent settings** — Feature flags, agent on/off state, and communication scripts (call/email/SMS reminders and follow-ups).
- **Call forwarding** — Contacts and rules for forwarding calls.
- **Analytics** — Call volume, duration, success rate, and distribution by status.

It is built to work with the same **Supabase** project the frontend uses: same auth (JWT), same businesses/locations model. The frontend today talks only to Supabase; this API is the layer the frontend will call for voice and customer-service features, starting with the **voice agent** integration.

---

## 2. Tech Stack

| Area | Technology |
|------|------------|
| Framework | FastAPI |
| Runtime | Python 3.11+, Uvicorn |
| Auth | Supabase JWT (validated with `supabase_jwt_secret`) |
| Data | Supabase (Postgres + Storage if used) |
| Voice | LiveKit (rooms, tokens), OpenAI GPT-4o Realtime (worker) |
| Config | pydantic-settings, `.env` |

---

## 3. Project Structure

```
sam-backend/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, router includes
│   │   ├── core/
│   │   │   ├── config.py        # Settings (Supabase, LiveKit, OpenAI, CORS)
│   │   │   ├── auth.py         # get_current_user, get_user_id (JWT)
│   │   │   └── supabase.py     # supabase (anon), supabase_admin (service role)
│   │   ├── routers/
│   │   │   ├── calls.py        # Calls CRUD, initiate, transcript, summary, recording
│   │   │   ├── settings.py     # Agent settings, state, audit, communication
│   │   │   ├── forwarding.py  # Forwarding contacts and rules
│   │   │   └── analytics.py   # Summary, volume trends, distribution
│   │   ├── schemas/
│   │   │   ├── calls.py        # Call, transcript, initiate request/response
│   │   │   └── settings.py     # Agent, forwarding, communication DTOs
│   │   └── services/
│   │       └── livekit_service.py   # Room create, user/agent tokens, end room
│   ├── worker/
│   │   └── voice_agent.py      # LiveKit + GPT-4o Realtime worker per call
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env                    # Not committed; see Config section
├── docker-compose.yml         # API on port 8003 → 8000
└── docs/
    └── BACKEND.md             # This file
```

---

## 4. API Overview

All protected routes require:

- **Header**: `Authorization: Bearer <supabase_access_token>`
- The token is the same one the frontend gets from `supabase.auth.getSession()`.

Query/body parameters use **business_id** (and often **location_id**) to scope data. The frontend already has `business_id` from `useBusiness()` (from the user’s `user_roles`) and `location_id` from `useSelectedLocation()`.

### 4.1 Calls (`/calls`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/calls` | List calls (paginated), filter by status, direction, search. Query: `business_id`, `status`, `direction`, `search`, `page`, `limit`. |
| GET | `/calls/recent-activity` | Recent call activity for dashboard. Query: `business_id`, `limit`. |
| GET | `/calls/{call_id}` | Get one call. |
| GET | `/calls/{call_id}/transcript` | Get transcript utterances. |
| GET | `/calls/{call_id}/summary` | Get call summary (AI-generated). |
| GET | `/calls/{call_id}/recording` | Get signed URL for recording (Supabase Storage). |
| POST | `/calls/initiate` | Create call record, create LiveKit room, return `call_id`, `livekit_room_id`, `livekit_token` for the client. Body: `business_id`, `location_id?`, `caller_phone?`, `caller_name?`, `direction` (inbound/outbound). |
| PUT | `/calls/{call_id}/status` | Update call status (e.g. completed, missed). Body: `{ "status": "..." }`. |

### 4.2 Settings (`/settings`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings/agent` | Get agent feature-flag settings. Query: `business_id`. |
| PUT | `/settings/agent` | Update agent settings (with audit log). Query: `business_id`. Body: `{ "settings": [{ "feature_key", "is_enabled", "config_value?" }] }`. |
| POST | `/settings/agent/reset` | Reset agent settings to defaults. Query: `business_id`. |
| GET | `/settings/agent/state` | Get agent on/off state. Query: `business_id`. |
| PUT | `/settings/agent/state` | Set agent on/off. Query: `business_id`. Body: `{ "is_active": true/false }`. |
| GET | `/settings/agent/audit-log` | Last 50 settings changes. Query: `business_id`. |
| GET | `/settings/communication` | Get communication scripts (call/email/SMS, reminder/follow-up). Query: `business_id`. |
| PUT | `/settings/communication` | Save communication scripts. Query: `business_id`. Body: `{ "settings": [{ "channel", "type", "is_enabled", "days_offset", "script?" }] }`. |

### 4.3 Forwarding (`/forwarding`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/forwarding/contacts` | List forwarding contacts. Query: `business_id`. |
| POST | `/forwarding/contacts` | Create contact. Query: `business_id`. Body: name, phone, department_tag?, priority, location_id?. |
| PUT | `/forwarding/contacts/{id}` | Update contact. |
| DELETE | `/forwarding/contacts/{id}` | Delete contact. |
| PUT | `/forwarding/contacts/{id}/toggle` | Toggle contact active. Body: `{ "is_active": true/false }`. |
| PUT | `/forwarding/contacts/bulk/toggle` | Bulk toggle. Query: `business_id`. Body: `{ "is_active": true/false }`. |
| GET | `/forwarding/rules` | List forwarding rules. Query: `business_id`. |
| POST | `/forwarding/rules` | Create rule. Body: name, condition_type, condition_value?, action?, priority_order. |
| PUT | `/forwarding/rules/{id}` | Update rule. |
| DELETE | `/forwarding/rules/{id}` | Delete rule. |

### 4.4 Analytics (`/analytics`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/analytics/summary` | Summary metrics (total calls, avg duration, success rate, etc.) and % change vs previous period. Query: `business_id`, `period` (7d, 30d, 90d). |
| GET | `/analytics/call-volume-trends` | Time-series inbound/outbound for charts. Query: `business_id`, `period` (daily, weekly, etc.). |
| GET | `/analytics/call-distribution` | Breakdown by status (donut). Query: `business_id`, `period`. |

### 4.5 Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `{ "status": "ok", "service": "ai-voice-agent-api" }`. |
| GET | `/` | Simple welcome message and link to `/docs`. |

---

## 5. Authentication and Multi-Tenancy

- **Auth**: `app/core/auth.py` validates the Supabase JWT using `supabase_jwt_secret` (same as frontend). No separate login; the frontend sends the Supabase session token.
- **User identity**: `get_user_id` returns `sub` from the JWT (Supabase user UUID). Used for `handled_by`, `updated_by`, `toggled_by`, etc.
- **Scoping**: All data is scoped by `business_id` (and often `location_id`). The backend does not re-check business membership; RLS or future middleware could enforce that the user’s `user_roles` include the given `business_id`.

**Alignment with frontend**: Same Supabase project, same JWT, same notion of user and business/location. The frontend already has `useBusiness()` and `useSelectedLocation()`; it only needs to send `business_id` and optional `location_id` when calling this API.

---

## 6. Voice Agent (First Integration for Customer Service)

The **voice agent** is the first concrete integration between the frontend and this backend for the Customer Service agent.

### 6.1 Flow

1. **Frontend** (e.g. “Test with Web Call” or “Start call” on Customer Service page):
   - Calls `POST /calls/initiate` with `business_id`, `location_id` (optional), `caller_name`/`caller_phone` (optional), `direction`.
   - Backend creates a **call** row, a **LiveKit room**, and returns `call_id`, `livekit_room_id`, `livekit_token`.
2. **Frontend** uses the LiveKit SDK to join the room with `livekit_token` (as the human participant).
3. **Backend** (or a separate orchestrator) starts the **voice agent worker** with `call_id`, `room_id`, `business_id`. The worker:
   - Joins the same LiveKit room as the AI participant.
   - Streams caller audio to **OpenAI GPT-4o Realtime**, and plays back the model’s audio to the room.
   - Writes **transcript** utterances to Supabase `transcripts` and, on call end, writes a **call_summaries** row and updates the **calls** row (status, duration, sentiment).
4. **Frontend** can then:
   - List calls via `GET /calls?business_id=...`.
   - Show recent activity via `GET /calls/recent-activity?business_id=...`.
   - Show transcript and summary via `GET /calls/{id}/transcript` and `GET /calls/{id}/summary`.

### 6.2 Worker

- **File**: `backend/worker/voice_agent.py`.
- **Run**: `python -m worker.voice_agent --call-id <uuid> --room-id <room> --business-id <uuid>` (typically started after `POST /calls/initiate`).
- **Stack**: LiveKit (join room, publish/subscribe audio), OpenAI GPT-4o Realtime (audio in/out, transcription), Supabase admin client (transcripts, call_summaries, call status).
- **System prompt**: Currently a fixed string; intended to be replaced with business-specific (or brand-voice) prompt from DB.

### 6.3 Supabase Tables Used by Voice and Calls

The backend expects (or creates) at least:

- **calls** — id, business_id, location_id, caller_name, caller_phone, direction, status, livekit_room_id, handled_by, started_at, ended_at, duration_seconds, sentiment, created_at, etc.
- **transcripts** — call_id, business_id, speaker (agent|customer), text, timestamp_seconds, sequence_order.
- **call_summaries** — call_id, business_id, summary_text, key_topics, insights, generated_at.
- **recordings** (optional) — call_id, storage_bucket, storage_path, duration_seconds, file_size_bytes; used by `GET /calls/{id}/recording`.

### 6.4 Settings and Communication

- **agent_settings** — Feature flags (inbound_calling, outbound_calling, call_forwarding, send_texts_during_after_calls, missed_call_text_back, callback_scheduling, reschedule_cancel_appointments, confirmation_reminder_calls, multi_language_support, feedback_after_call).
- **agent_state** — Single row per business: is_active (global on/off).
- **communication_settings** — Scripts per channel (call, email, sms) and type (reminder, followup): is_enabled, days_offset, script. These align with the frontend’s Customer Service Settings (Call/Email/SMS, reminder vs follow-up, days before/after, script text).

---

## 7. Alignment With the Frontend

### 7.1 Matches

- **Auth**: Same Supabase JWT; frontend can send `session.access_token` as Bearer token.
- **Tenancy**: Frontend has `business_id` (from roles) and `location_id` (selected location); backend expects these on the relevant endpoints.
- **Customer Service concepts**:  
  - Calls list and recent activity → backend provides list and recent-activity endpoints.  
  - Communication settings (Call/Email/SMS, reminder/follow-up, scripts) → backend has GET/PUT `/settings/communication`.  
  - Forwarding contacts and rules → backend has full CRUD for `/forwarding/contacts` and `/forwarding/rules`.  
  - Agent on/off and feature flags → backend has `/settings/agent` and `/settings/agent/state`.
- **Voice**: Initiate call → get LiveKit token → join room; worker runs separately and writes transcripts/summaries. Frontend can later show transcript and summary and optionally recording.

### 7.2 Gaps / Not Yet Wired

- **Frontend does not call this API yet.** All current Customer Service UI (checklist, activity log, settings) uses local state or Supabase only. “Test with Web Call” and “Save All Settings” are not hooked to this backend.
- **Base URL**: Frontend needs a configurable base URL for this API (e.g. `VITE_VOICE_AGENT_API_URL=http://localhost:8003` in dev, or the deployed API URL in prod).
- **Worker lifecycle**: Something (orchestrator, queue, or serverless) must start `worker.voice_agent` after `POST /calls/initiate`; that flow is not described in the repo (only the worker entrypoint is).
- **RLS / authorization**: Backend trusts `business_id` and `location_id` from the client; you may want to add checks that the authenticated user has access to that business (e.g. via `user_roles`).

---

## 8. Configuration

Backend reads from environment (e.g. `.env` in `backend/` or docker-compose):

| Variable | Purpose |
|----------|---------|
| `supabase_url` | Supabase project URL |
| `supabase_anon_key` | Supabase anon key (RLS-aware client) |
| `supabase_service_role_key` | Supabase service role (worker, admin writes) |
| `supabase_jwt_secret` | JWT secret for validating Supabase tokens |
| `livekit_url` | LiveKit server URL |
| `livekit_api_key` | LiveKit API key |
| `livekit_api_secret` | LiveKit API secret |
| `openai_api_key` | OpenAI API key (worker) |
| `cors_origins` | Comma-separated origins (e.g. `http://localhost:5173`) |
| `aws_*`, `s3_bucket_name` | Optional, for recording storage if not using Supabase Storage |

---

## 9. Running the Backend

- **Local**: From `backend/`, `uvicorn app.main:app --reload --port 8000` (or 8003 if you prefer). Ensure `.env` is set.
- **Docker**: `docker-compose up`; API is exposed on host port 8003, mapped to container 8000.
- **Worker**: Run manually or via your process manager:  
  `python -m worker.voice_agent --call-id <uuid> --room-id <room> --business-id <uuid>`  
  after creating a call with `POST /calls/initiate`.

---

## 10. Summary

- The **SAM backend** is the **AI Voice Agent API** for the AI Employees app: calls, settings, forwarding, and analytics, using the same Supabase auth and business/location model as the frontend.
- It is **aligned** with the frontend’s auth, tenancy, and Customer Service concepts (calls, activity, communication scripts, forwarding, agent state). The frontend is **not yet integrated**: it does not call this API or pass a base URL.
- The **voice agent** is the **first integration** for the Customer Service agent: frontend calls `POST /calls/initiate`, gets a LiveKit token, joins the room; the **voice_agent** worker joins the same room, runs GPT-4o Realtime, and writes transcripts and summaries to Supabase. Next steps are: wire the frontend to this API (base URL, auth header, initiate + recent-activity + settings), and define how the worker is started (orchestrator/queue) after `POST /calls/initiate`.
