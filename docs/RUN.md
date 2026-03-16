# Running the SAM Backend

Use the **same Supabase project** (sam-supabase) as your frontend. Ensure `backend/.env` is filled from `backend/.env.example` with your project’s values.

---

## Setting up the voice agent (LiveKit)

The voice agent uses **LiveKit** for real-time audio rooms. You can use **LiveKit Cloud** (easiest) or a self-hosted LiveKit server.

### 1. Get LiveKit credentials

- Go to [LiveKit Cloud](https://cloud.livekit.io) and sign in (or create an account).
- Create a project (or use an existing one).
- In the project: **Settings** → **Keys** (or **API Keys**). You’ll see:
  - **LiveKit URL** — e.g. `wss://your-project.livekit.cloud`
  - **API Key**
  - **API Secret**

### 2. Add them to `backend/.env`

In `sam-backend/backend/.env` set:

```env
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret
```

Use the exact URL and key/secret from the LiveKit dashboard. The **API** (rooms, tokens) and the **worker** (AI joining the room) both read these from the same `.env`.

### No rooms / no logs in the LiveKit dashboard?

- **Check the project** — In the dashboard, open the project whose **LiveKit URL** matches your `LIVEKIT_URL` (e.g. `wss://**myproject**.livekit.cloud` → same project in the dropdown). If you have several projects, it’s easy to look at the wrong one.
- **Rooms vs Logs** — Use the **Rooms** (or **Room usage**) view for created rooms. “Logs” often show agent/egress or errors, not every room create.
- **Rooms are short-lived if empty** — Rooms use `empty_timeout=300` (5 min). If **no participant joins** (no frontend join, no worker), the room is removed after 5 minutes and may not show up prominently. To see activity: start the **worker** for that call (or join from the app once that’s wired). When at least one participant connects, the room and usage appear in the dashboard.
- **Confirm creation in your API logs** — When you call `POST /calls/initiate`, the backend logs: `LiveKit room created: name=call-xxx sid=...`. If you see that, the room was created in the project implied by `LIVEKIT_URL`; then check the matching project in the dashboard.

### 3. What else the voice agent needs

- **Supabase** — same project as the frontend (calls, transcripts, auth).
- **OpenAI** — `OPENAI_API_KEY` for GPT-4o Realtime (the AI voice).
- **CORS** — `CORS_ORIGINS` including your frontend origin (e.g. `http://localhost:5173`).

Once these are set, you can run the API (and optionally the worker) as below.

---

## Option 1: Docker (recommended)

From the **sam-backend** repo root:

```bash
cd /path/to/sam-backend
docker compose up --build
```

Use `--build` when you’ve changed `backend/requirements.txt` (e.g. after upgrading `openai` for the Realtime API) so the image is rebuilt and new deps are installed.

- API is available at **http://localhost:8003**
- Uses `backend/.env`
- Hot reload: code changes restart the server

To run in the background:

```bash
docker-compose up -d
```

---

## Option 2: Local Python (uvicorn)

1. **Go to the backend directory:**

   ```bash
   cd /path/to/sam-backend/backend
   ```

2. **Create and use a virtual environment:**

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Linux/macOS
   # or:  venv\Scripts\activate   # Windows
   ```

3. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

4. **Ensure `.env` exists** in `backend/` (copy from `.env.example` and set your Supabase, LiveKit, OpenAI, and CORS values).

5. **Run the API:**

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
   ```

- API is at **http://localhost:8003**
- `--reload` restarts the server when you change code

---

## Check that it’s running

- **Health:** open http://localhost:8003/health → `{"status":"ok","service":"ai-voice-agent-api"}`
- **Docs:** open http://localhost:8003/docs for Swagger UI

---

## CORS

The frontend (e.g. Vite on http://localhost:5173) must be allowed in `CORS_ORIGINS` in `backend/.env`, for example:

```env
CORS_ORIGINS=http://localhost:5173
```

If your app runs on another origin, add it comma-separated.

---

## Voice agent worker (optional)

The **API** creates LiveKit rooms and returns tokens. The **worker** is the process that joins the room as the AI and handles the conversation. It runs as a separate process and uses the same `backend/.env` (LiveKit, OpenAI, Supabase).

From `sam-backend/backend` (with venv activated or Docker context):

```bash
python -m worker.voice_agent --call-id <call-uuid> --room-id <livekit-room-id> --business-id <business-uuid>
```

You get `call_id` and `livekit_room_id` from `POST /calls/initiate`. In production you’d typically start one worker process per active call (e.g. a dispatcher that watches for new calls and spawns the worker).

---

## How the voice agent is used (end-to-end)

This section explains how a user actually talks to the AI voice agent and how the pieces fit together.

### High-level flow

1. **User** starts a call (e.g. clicks “Test with Web Call” in the dashboard, or later: a real phone call / web call).
2. **Frontend** calls the SAM backend: `POST /calls/initiate` with `business_id` (and optional `location_id`, `caller_name`, etc.).
3. **Backend** creates a **call** row in Supabase, creates a **LiveKit room**, and returns `call_id`, `livekit_room_id`, and `livekit_token`.
4. **Frontend** uses the LiveKit SDK to **join the room** with `livekit_token` so the user’s microphone and speakers are in that room. *(Right now the UI has a TODO here: the button initiates the call but doesn’t yet join the room; that’s the next step to finish “Test with Web Call”.)*
5. **Worker** is started with that `call_id`, `livekit_room_id`, and `business_id`. It joins the **same LiveKit room** as the AI participant.
6. **In the room**: the user speaks (audio goes to LiveKit). The worker subscribes to that audio, sends it to **OpenAI GPT-4o Realtime**, gets back AI speech and text. It publishes the AI’s audio back into the room (so the user hears it) and writes transcript lines to Supabase.
7. When the call ends, the worker marks the call completed, generates a summary, and disconnects.

So: **the voice agent is “used” by having the user and the AI in the same LiveKit room; the worker is the bridge between LiveKit (real-time audio) and OpenAI (GPT-4o Realtime).**

### Where each part runs

| Part | Role |
|------|------|
| **Frontend (browser)** | User clicks “Test with Web Call” → calls API → should join LiveKit room with the returned token so the user can talk and hear the AI. |
| **SAM Backend API** | Creates the call and LiveKit room, issues tokens. Does not handle audio. |
| **Voice agent worker** | Joins the LiveKit room as the AI, streams user audio to OpenAI and AI audio back into the room, saves transcript and summary to Supabase. |
| **LiveKit** | Real-time audio room (user + AI in the same “call”). |
| **OpenAI** | GPT-4o Realtime: turns user speech into AI speech and text. |

### What you need to do to “use” it

1. **Configure** LiveKit (and Supabase, OpenAI) in `backend/.env` as in “Setting up the voice agent (LiveKit)”.
2. **Run the API** (Docker or uvicorn) so the frontend can call `POST /calls/initiate`.
3. **Run the worker** when a call is active:  
   `python -m worker.voice_agent --call-id <id> --room-id <room> --business-id <id>`  
   (In production, a small dispatcher or job queue would start the worker automatically when a call is created.)
4. **Frontend**: Complete the “Test with Web Call” flow by using the LiveKit JS SDK to join the room with `livekit_token` and `livekit_room_id` (and optionally `LIVEKIT_URL` from env) so the user can speak and hear the AI in the browser.

---

## Test the voice agent locally (no Twilio)

You can test the AI agent and your prompt locally using LiveKit + OpenAI only. No phone or Twilio needed.

### 1. Edit the agent prompt

The worker uses a fixed system prompt. Edit it in code:

- **File:** `backend/worker/voice_agent.py`
- **Variable:** `SYSTEM_PROMPT` (near the top, after the imports)

Change the text to whatever you want the agent to say and how it should behave. Restart the worker after editing.

### 2. Start the API

Make sure the backend is running (Docker or uvicorn) so you can call `POST /calls/initiate`.

### 3. Get a room and token

- **From the app:** Log in, go to **Customer Service Employee**, click **Test with Web Call**. In the browser Network tab, inspect the response of the request to `/calls/initiate` and copy `call_id`, `livekit_room_id`, `livekit_token`, `livekit_ws_url`, and your `business_id`.
- **Or with curl:** Call the API with a valid Supabase JWT and your `business_id`; use the JSON response fields as above.

### 4. Start the worker

From `sam-backend/backend` (with the same `.env` as the API):

```bash
python -m worker.voice_agent --call-id <call_id> --room-id <livekit_room_id> --business-id <business_id>
```

Leave this terminal running.

### 5. Join the room and talk

Open **`sam-backend/tools/test-voice-agent.html`** in your browser (double-click or open via file://). Paste **LiveKit WebSocket URL** (`livekit_ws_url`) and **LiveKit token** (`livekit_token`), then click **Connect**. Allow microphone access. Speak into your mic; the AI should reply with voice. This tests your agent and prompt locally without Twilio.
