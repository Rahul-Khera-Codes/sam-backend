# SAM Voice Agent (LiveKit Agents)

This service is the **LiveKit Agents**–based voice assistant for SAM. It joins LiveKit rooms when dispatched, uses the OpenAI Realtime API for speech-to-speech, and greets callers with the company name and location when available.

## Architecture

- **FastAPI backend** (`backend/`): Creates calls, LiveKit rooms, and issues tokens. When `USE_LIVEKIT_AGENT` is set, it does not spawn the legacy `worker.voice_agent`; the agent in this directory is used instead (dispatched by LiveKit Cloud or your agent server).
- **This agent**: Registers as `voice-agent`, connects when assigned to a room, reads `participant.metadata` (set by the backend token: `call_id`, `business_id`, `location_id`), fetches business/location from Supabase, and runs an `AgentSession` with OpenAI Realtime and a branded welcome.

## Requirements

- Python >= 3.10
- LiveKit Cloud project (or self-hosted LiveKit server)
- OpenAI API key
- Supabase URL + service role key (for business/location lookup)

## Setup

1. From this directory, create a virtualenv and install deps:

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` or `.env.local` and set:

   - `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (from LiveKit Cloud)
   - `OPENAI_API_KEY`
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (for company/location)

## Run

- **Dev** (connects to LiveKit and waits for jobs):

  ```bash
  uv run agent.py dev
  ```
  Or with pip: `python agent.py dev`

- **Production**: `python agent.py start` or deploy via `lk agent create` from this directory.

## Backend integration

- Set `USE_LIVEKIT_AGENT=1` in the backend env when you want to use this agent instead of the legacy worker. The backend will then omit spawning `worker.voice_agent` and will still include `call_id`, `business_id`, and `location_id` in the user token metadata so this agent can personalize the greeting.

## Transcripts and summaries (phase 2)

Today this agent does not write transcripts or call summaries to Supabase. Options for later:

- **Option A**: From this process, call Supabase (or the FastAPI API) to append transcript utterances and, on disconnect, write a call summary.
- **Option B**: Add an HTTP callback from the agent to the FastAPI backend (e.g. `POST /calls/{id}/transcript-events`) and have the backend write to Supabase.

Until then, use the legacy worker (do not set `USE_LIVEKIT_AGENT`) if you need transcript and summary in the DB.
