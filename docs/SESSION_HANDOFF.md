# Session Handoff — 2026-04-01 (Session 11)

This document captures the full state of the system after session 11 so the next session can pick up immediately without re-investigation.

---

## System Status (as of 2026-04-01)

**Working end-to-end:**
- Inbound SIP call → agent answers → books appointment → transcript + summary saved → shows in UI ✅
- Confirmation email → customer ✅
- Staff notification email → assigned staff ✅
- Call records appear in website Call Recordings & Transcripts page ✅
- Analytics dashboard shows real data ✅
- Agent Settings page loads feature flags on refresh (RLS fix) ✅
- Calendar Appointment Details modal shows client phone + email ✅
- Calendar Edit Appointment modal has phone + email fields ✅
- Outbound call UI (OutboundCallDialog) — frontend complete ✅
- Outbound trunk architecture — per-number in DB (not shared env var) ✅

**NOT yet tested end-to-end:**
- Outbound call flow (`POST /calls/outbound`) — backend code complete but requires manual DB migration first

---

## Infrastructure

### Docker Containers (docker-compose.yml in repo root)
| Container | Port | Notes |
|---|---|---|
| `sam-backend-sam-backend-1` | 8003 | FastAPI, volume-mounted `./backend:/app`, hot reload via uvicorn |
| `sam-backend-sam-agent-1` | 8001 | LiveKit agent, volume-mounted `./agent:/app`, `python agent.py dev` (hot reload) |
| `sam-frontend` | — | React/Vite app, volume-mounted `../src:/app/src` |
| `postgres-local` | — | Local postgres |

### Key env files
- `backend/.env` — all backend secrets
- `agent/.env.local` — agent secrets (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, LIVEKIT_*, OPENAI_API_KEY, TWILIO_*, GOOGLE_CLIENT_ID/SECRET)

---

## Mirage Banquets Test Business

**business_id:** `da9fc4fb-2b16-48ab-8856-696870d0a18a`

### Staff
| Name | user_id | Role | Email |
|---|---|---|---|
| Rahul Khera | `14a3739a-8e89-486c-aefc-ac8ad4d61038` | super_admin | rahul.excel2011@gmail.com |
| Sam Maisuria | `1bc53b7c-8af6-406b-a2bb-b03dc27f182d` | user | sam@aiemployeesinc.com |

**Note:** Sam Maisuria's `profiles.first_name`/`last_name` are NULL → shows as "Staff" in agent. No `user_services` entries for Sam — can't be booked as service provider.

### Locations
- `fd7d1823-3d86-44cf-8039-cbaca6bfdd01` — "Mirage", 8170 50 St NW, Edmonton, AB

### Services
- `7d504795-5825-4d7a-a60b-6b5e4940843d` — "banquet hall space", 60 min, active

### Phone Numbers
| Number | Outbound Trunk | Dispatch Rule | Status |
|---|---|---|---|
| +14152555624 | ❌ none | SDR_YX8xQkwDQUMb | active |
| +14157077538 | ST_WZ95dtKEntty | SDR_s6FZouinFiun | active |

### Gmail Integration
- Connected: `rahul.excel2011@gmail.com`
- Token auto-refreshes on each send — working fine

---

## MANUAL ACTIONS REQUIRED (blocking outbound calls)

These must be done by the user before outbound calls will work:

1. **Run migration in Supabase SQL editor:**
   ```sql
   ALTER TABLE business_phone_numbers
   ADD COLUMN IF NOT EXISTS livekit_outbound_trunk_id TEXT DEFAULT '';

   -- Backfill for +14157077538
   UPDATE business_phone_numbers
   SET livekit_outbound_trunk_id = 'ST_WZ95dtKEntty'
   WHERE phone_number = '+14157077538';
   ```

2. **Delete orphaned LiveKit trunk** `ST_htrEWVP2hm6P` from LiveKit dashboard
   - This belonged to released number +14159935287 and was never cleaned up

3. **+14152555624 has no outbound trunk** — either:
   - Re-provision the number via app (will auto-create trunk), or
   - Create a trunk manually in LiveKit and update the DB row

---

## Session 11 Changes Summary

### Backend (committed as "outbound: code only not tested")
- `backend/app/services/livekit_service.py` — `create_sip_participant()` accepts explicit `outbound_trunk_id` param
- `backend/app/services/phone_number_service.py` — per-number outbound trunk creation + DB storage; release also deletes outbound trunk
- `backend/app/routers/calls.py` — fetches `livekit_outbound_trunk_id` from DB for outbound calls
- `backend/app/core/config.py` — removed `livekit_sip_outbound_trunk_id` field
- `backend/.env` — removed `LIVEKIT_SIP_OUTBOUND_TRUNK_ID`, added comment

### Backend (committed as "settings sync fix")
- `backend/app/routers/settings.py` — `GET /settings/agent`, `GET /settings/agent/audit-log`, `GET /settings/communication` all switched to `supabase_admin`

### Frontend (in `ai-employees-app/`)
- `src/hooks/useAppointments.ts` — added `client_phone`, `client_email` to `Appointment` interface; fixed TS deep instantiation error
- `src/pages/dashboard/Calendar.tsx` — phone/email in Details modal; editable phone/email in Edit modal
- `src/components/OutboundCallDialog.tsx` — NEW: full outbound call dialog with type selector, filtered appointment list, phone auto-fill, purpose preview
- `src/pages/dashboard/customer-service/CallRecordings.tsx` — "New Call" button added

### Docs (uncommitted)
- `docs/ARCHITECTURE.md` — NEW: comprehensive 12-section architecture documentation

### Frontend migration (in `ai-employees-app/`)
- `supabase/migrations/20260331000000_bpn_outbound_trunk.sql` — adds `livekit_outbound_trunk_id` column

---

## Key Bugs Fixed (Session 11)

1. **Agent Settings RLS** — `GET /settings/agent` used anon `supabase` client → RLS blocked reads → page showed "0 of 0 features" on refresh
2. **Calendar phone/email** — `Appointment` interface was missing `client_phone`/`client_email` columns
3. **Orphaned outbound trunk** — `release_phone_number()` didn't clean up outbound trunk; now it does
4. **Wrong outbound trunk architecture** — was a single shared env var; now per-number in DB

---

## Agent Architecture (`agent/agent.py`)

### Context Resolution (priority order)
1. `ctx.job.metadata` — JSON with `business_id`, `location_id`, `call_id` (set by LiveKit dispatch rule)
2. `participant.metadata` — same JSON (set by backend token for web calls)
3. `participant.attributes` — SIP attrs: only reads `business_id` now (NOT `location_id` — removed to prevent stale FK)
4. DB lookup by `sip.trunkPhoneNumber` in `business_phone_numbers` table (last resort)

### Call Direction
- Inbound: customer speaks first, agent waits and responds
- Outbound: agent introduces itself and states purpose (reads `call_purpose` from room metadata)

---

## Known Issues / Next Tasks

### High Priority
- [ ] **Run migration + manual trunk setup** (see MANUAL ACTIONS REQUIRED above)
- [ ] **Test outbound call end-to-end** after migration is run

### Medium Priority
- [ ] **CS3 Scheduler** — "Save Schedule" button is mock (fake delay, no API call); needs `GET/PUT /settings/agent/schedule` backend endpoint backed by `business_hours` table
- [ ] **Communication Settings** — "Save All Settings" button not wired to `PUT /settings/communication`
- [ ] **Call recording** — not implemented; requires LiveKit Egress integration
- [ ] **`.ics` calendar attachment** in confirmation emails
- [ ] **Reminder emails/SMS** — needs scheduler/cron

### Lower Priority
- [ ] Backend API endpoints for appointments/services (frontend queries Supabase directly now)
- [ ] Business authorization check in backend (currently trusts frontend)
- [ ] Marketing / Sales / HR / Exec employee pages (stubs)
- [ ] HTTPS setup for production mic access
- [ ] Sam Maisuria profile missing name (NULL in DB)
- [ ] Location named "Mirage" → greeting says "Mirage Banquets in Mirage" (redundant)

---

## How to Run

```bash
# Start all services
docker compose up -d

# View agent logs
docker logs -f sam-backend-sam-agent-1

# Restart agent (needed when subprocess-level changes don't hot-reload)
docker compose restart sam-agent
```

Agent uses `dev` mode with file watching — most changes hot-reload without container restart. Exception: changes to top-level module imports may need a restart.
