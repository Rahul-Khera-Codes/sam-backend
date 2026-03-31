# Session Handoff — 2026-03-31

This document captures the full state of the system after sessions 9-10 so the next session can pick up immediately without re-investigation.

---

## System Status (as of 2026-03-31)

**Everything is working end-to-end for inbound SIP calls:**
- Inbound SIP call → agent answers → books appointment → transcript + summary saved → shows in UI ✅
- Confirmation email → customer ✅
- Staff notification email → assigned staff ✅
- Call records appear in website Call Recordings & Transcripts page ✅
- Analytics dashboard shows real data ✅
- Frontend hot reload via Docker volume mounts ✅

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
| Number | Dispatch Rule | location_id in DB | Status |
|---|---|---|---|
| +14152555624 | SDR_YX8xQkwDQUMb | null | active |
| +14157077538 | SDR_s6FZouinFiun | fd7d1823 | active |

**ACTION NEEDED:** Both dispatch rules still have stale `location_id` in LiveKit attributes. User needs to edit them in LiveKit dashboard to remove `location_id` (leave only `business_id`). The agent code no longer reads `location_id` from dispatch rule attributes so this is cosmetic cleanup only.

### Gmail Integration
- Connected: `rahul.excel2011@gmail.com`
- Token auto-refreshes on each send — working fine
- `google_email` field was empty (fixed manually to `rahul.excel2011@gmail.com` in `gmail_tokens` table)

---

## Key Bugs Fixed (Sessions 9-10)

### Session 9
1. **`inbound_numbers` in dispatch rule** — caused calls to ring forever. Removed from `phone_number_service.py`.
2. **SIP calls not in DB** — agent now auto-creates `calls` row at session start.
3. **RLS blocking reads** — `calls.py` and `analytics.py` switched to `supabase_admin`.
4. **Transcript bubbles all "Customer"** — fixed `msg.role`/`msg.content` → `msg.speaker`/`msg.text` in frontend.

### Session 10
5. **FK violation on `calls.location_id`** — dispatch rules had stale `location_id` (`9174e86b...`) that no longer exists in `locations` table. Root cause: location was deleted but dispatch rule retained old attribute.
   - **Fix:** `phone_number_service._create_dispatch_rule` now only puts `business_id` in attributes (no `location_id`).
   - **Fix:** Agent Source 3 no longer reads `location_id` from participant attributes.
   - `location_id` in agent now only comes from Source 4 (DB lookup) or job/participant metadata.
6. **Location missing from greeting** — removing `location_id` from Source 3 meant `location_phrase` was empty in `build_instructions`. Fixed: `prompt_builder.py` now falls back to `locations[0]` when `location_id` is None.
7. **Fallback call record creation** — if initial INSERT fails (e.g. transient error), a second attempt is made at finalization time.
8. **Phone number normalization** — `sip.phoneNumber` from Twilio SIP returns `6987-321-540` (non-E.164). Added `_normalize_phone_e164()` in `agent.py`.
9. **`gmail_tokens.google_email` was empty** — fixed manually in DB. Should be populated automatically during OAuth flow (bug in OAuth callback).

---

## Agent Architecture (`agent/agent.py`)

### Context Resolution (priority order)
1. `ctx.job.metadata` — JSON with `business_id`, `location_id`, `call_id` (set by LiveKit dispatch rule)
2. `participant.metadata` — same JSON (set by backend token for web calls)
3. `participant.attributes` — SIP attrs: only reads `business_id` now (NOT `location_id` — removed to prevent stale FK)
4. DB lookup by `sip.trunkPhoneNumber` in `business_phone_numbers` table (last resort)

### Call Record Creation (SIP calls)
- Created at session start if `is_sip_call and not call_id and business_id`
- Fallback: if initial INSERT fails, retried at finalization before saving transcript
- `location_id` validated against DB before INSERT (guards against stale FK)

### Post-call Finalization
`_finalize_call()`: saves transcripts → updates call status/duration → generates GPT-4o summary → sends missed-call SMS if applicable.

---

## Files Changed This Session (uncommitted changes)

| File | Change |
|---|---|
| `agent/agent.py` | Phone normalization, Source 3 no longer reads location_id, fallback call record creation, better error logging |
| `agent/prompt_builder.py` | Falls back to `locations[0]` when `location_id` is None |
| `backend/app/services/phone_number_service.py` | `_create_dispatch_rule` only puts `business_id` in attributes (removed location_id) |

**These changes are NOT committed. Commit them before starting new work.**

---

## Known Issues / Next Tasks

### High Priority
- [ ] **Commit uncommitted changes** — `agent/agent.py`, `agent/prompt_builder.py`, `backend/app/services/phone_number_service.py`
- [ ] **Update LiveKit dispatch rules** — remove `location_id` from both SDR_YX8xQkwDQUMb and SDR_s6FZouinFiun in LiveKit dashboard (user said they'll do it manually)
- [ ] **Location name is "Mirage"** → greeting says "Mirage Banquets in Mirage" (redundant). Rename location to "Edmonton" or full address in app settings.
- [ ] **Sam Maisuria profile missing name** — `profiles.first_name`/`last_name` are NULL → agent calls them "Staff". Update via app or Supabase.

### Medium Priority
- [ ] **Call recording** — not implemented. Requires LiveKit Egress integration.
- [ ] **`.ics` calendar attachment** in confirmation emails
- [ ] **Reminder emails/SMS** — needs scheduler/cron
- [ ] `Communication Settings` save button not wired up

### Lower Priority
- [ ] Backend API endpoints for appointments/services (frontend queries Supabase directly now)
- [ ] Business authorization check in backend (currently trusts frontend)
- [ ] CS3 Scheduler — `GET/PUT /settings/agent/schedule` endpoint needed
- [ ] Marketing / Sales / HR / Exec employee pages (stubs)
- [ ] HTTPS setup for production mic access

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
