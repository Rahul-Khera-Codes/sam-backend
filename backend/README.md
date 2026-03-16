# AI Voice Agent — FastAPI Backend

## What This Does

This backend handles **only** the voice agent logic. Everything else (auth, business data, team management) is handled directly by the Supabase frontend.

- **LiveKit** — creates rooms, generates tokens for callers and AI agent
- **GPT-4o Realtime API** — powers the AI voice conversation
- **Voice Agent Worker** — joins LiveKit room, runs the audio loop, writes transcripts to Supabase
- **REST API** — endpoints for calls, recordings, settings, forwarding, analytics

## Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI + Python 3.11 |
| Auth | Supabase JWT validation (reuses frontend tokens) |
| Database | Supabase (via service role key for worker writes) |
| Real-time audio | LiveKit Cloud |
| AI | OpenAI GPT-4o Realtime API |
| Storage | Supabase Storage (call-recordings bucket) |

## Setup

```bash
# 1. Copy env file
cp .env.example .env
# Fill in all values in .env

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run locally
uvicorn app.main:app --reload

# Or with Docker
docker-compose up
```

## API Docs

Once running, visit: http://localhost:8000/docs

## Project Structure

```
backend/
├── app/
│   ├── main.py                  # FastAPI app + CORS + routers
│   ├── core/
│   │   ├── config.py            # Settings from .env
│   │   ├── auth.py              # Supabase JWT verification
│   │   └── supabase.py          # Supabase clients (anon + service role)
│   ├── routers/
│   │   ├── calls.py             # Call CRUD + initiate + recordings
│   │   ├── settings.py          # Agent settings + state + communication scripts
│   │   ├── forwarding.py        # Forwarding contacts + rules
│   │   └── analytics.py         # Dashboard stats + charts
│   ├── schemas/
│   │   ├── calls.py             # Pydantic models for calls
│   │   └── settings.py          # Pydantic models for settings/forwarding
│   └── services/
│       └── livekit_service.py   # Room creation + token generation
├── worker/
│   └── voice_agent.py           # GPT-4o Realtime audio loop
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## How Auth Works

The frontend logs in via Supabase Auth and gets a JWT.
That same JWT is sent to this FastAPI backend in the `Authorization: Bearer` header.
FastAPI verifies it using the `SUPABASE_JWT_SECRET` — no second login needed.

## How the Voice Worker Works

1. Frontend calls `POST /calls/initiate`
2. API creates a LiveKit room + call record in Supabase
3. API returns a LiveKit token to the frontend (frontend joins the room)
4. API spawns the voice agent worker as a subprocess
5. Worker joins the same LiveKit room as a bot participant
6. Worker streams audio to GPT-4o Realtime API
7. GPT-4o returns audio responses + transcript
8. Worker saves transcript utterances to Supabase in real-time
9. On call end: worker generates AI summary + marks call completed
