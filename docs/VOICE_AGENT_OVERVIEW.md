# SAM Voice Agent — What We Added for Customer Assistance & Current Flow

This document summarizes **everything the voice agent uses to assist customers** and the **current end-to-end flow** from call start to conversation.

---

## 1. What the Agent Has for Assisting Customers

The agent builds a single **instruction prompt** per call from the following. All of it is loaded at session start from **participant metadata** (`business_id`, optional `location_id`) and **Supabase**.

### 1.1 Business & Location (Welcome)

| Source | What we add | Purpose |
|--------|-------------|--------|
| **businesses** (row by `business_id`) | Company **name** | Greeting: “Thank you for calling [Company Name]…” |
| **locations** (row by `location_id` when provided) | Location **name**, city, state, country | Optional “in [Location]” in the welcome so the agent knows which location the call is for |

- **Welcome block**: “You are the AI phone receptionist for [Company Name] [in Location]. Always start the call with a short, friendly welcome that includes the business name [and the location]. Example: ‘Thank you for calling [Company Name] [in Location], how can I help you today?’”

### 1.2 Global Settings (Language & Region)

| Source | What we add | Purpose |
|--------|-------------|--------|
| **businesses** | `language`, `country`, `date_format`, `time_format` | How to speak and how to say dates/times |

- **Instruction block**: “Use the business language and region: [language and country]. Speak in that language unless the caller uses another. When stating dates use this format: [date_format]. When stating times use [time_format] format.”

(From the app’s **Global Settings** → Language & Region.)

### 1.3 Brand Voice

| Source | What we add | Purpose |
|--------|-------------|--------|
| **brand_voice_profiles** (active row for `business_id`) | `tone`, `style`, `vocabulary`, `do_not_say`, `sample_responses` | How the brand should sound and what to say/avoid |

- **Tone & style**: e.g. “Tone: professional and warm. Style: concise and helpful.”
- **Vocabulary**: preferred phrases (“Prefer saying: …”) and avoid phrases (“Avoid saying: …”) from the vocabulary list.
- **Do not say**: “Never say these words or phrases: …”
- **Sample responses**: up to 3 example (scenario, response) pairs: “Follow the style of these example responses: …”

(From the app’s **Global Settings** → Brand Voice.)

### 1.4 Locations & Staff (Booking / Rescheduling)

| Source | What we add | Purpose |
|--------|-------------|--------|
| **locations** (all for `business_id`) | For each: **id**, **name**, **address**, **phone** | So the agent can list locations and say addresses/phones |
| **user_roles** + **user_locations** + **profiles** | Per location: list of **staff names** (first + last) | So the agent can say “At [Location]: [Staff A], [Staff B]” for booking |

- **Instruction block**: “Locations and staff (use for booking and rescheduling): Location: [Name]; address: …; phone: …; staff: [names] | …” (one segment per location).

So the agent knows **all locations** and **who works where** for that business.

### 1.5 Default Behavior (Always Present)

- Be a helpful, friendly, professional customer service assistant.
- Be concise.
- If you cannot help, offer to transfer to a human agent.
- Always confirm appointments or bookings back to the caller clearly.

### 1.6 Booking & Rescheduling Instructions (Always Present)

- **New booking**: Ask for preferred location (if multiple), date, time, and service or staff preference if relevant; repeat back to confirm.
- **Reschedule**: Ask for name or phone to look up the appointment, then new date and time; confirm back.
- Do **not** make up availability; offer to create or update the appointment and say you will confirm shortly or transfer to the front desk to finalize.

*(Actual create/update of `appointments` in the DB is not implemented in the agent yet; the agent is instructed to collect info and confirm, or hand off.)*

---

## 2. Supabase Tables the Agent Reads

| Table | Used for |
|-------|----------|
| **businesses** | Name, language, country, date_format, time_format |
| **locations** | Single location (welcome phrase) + all locations (list + booking context) |
| **brand_voice_profiles** | Tone, style, vocabulary, do_not_say, sample_responses (active profile per business) |
| **user_roles** | Which users belong to the business |
| **user_locations** | Which users work at which location |
| **profiles** | First/last name for staff listed per location |

The agent does **not** read or write **appointments**; it only has instructions to help with booking/rescheduling and to use the locations and staff context above.

---

## 3. Current Flow of the Agent

### 3.1 How a Call Reaches the Agent

1. **Call creation**
   - **Test with Web Call**: Frontend calls `POST /calls/initiate` with `business_id`, optional `location_id`; backend creates a call row and a LiveKit room, returns `livekit_room_id` and `livekit_token`.
   - **Real inbound (future)**: Inbound number is resolved to `business_id` (and optional `location_id`); backend creates call and room the same way and returns token/room for the telephony stack.

2. **Token metadata**
   - Backend puts in the **user token** metadata: `call_id`, `business_id`, `location_id` (optional). Same for test and inbound.

3. **Participant joins**
   - Frontend (or telephony client) joins the LiveKit room with that token. The participant’s metadata is thus `{ call_id, business_id, location_id }`.

4. **Agent dispatch**
   - We use **automatic dispatch** (no `agent_name` on the session). When a participant joins the room, LiveKit assigns this agent to the room; the agent process receives a job and runs the session.

### 3.2 Session Lifecycle (Inside the Agent)

1. **Connect**
   - `ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)` — connect to the room and subscribe to audio only.

2. **Wait for participant**
   - `participant = await ctx.wait_for_participant()` — get the first participant (the caller).

3. **Read metadata**
   - Read `participant.metadata` (JSON). Parse `business_id`, `location_id`, `call_id`. If not a string or invalid JSON, skip custom instructions and use defaults.

4. **Build instructions**
   - Call `build_instructions(business_id, location_id)`:
     - Fetch business → name + global settings.
     - Fetch single location (if `location_id`) → for welcome phrase.
     - Fetch brand voice (active profile for business).
     - Fetch all locations for business + employees by location.
     - Concatenate: welcome + global settings block + brand voice block + locations/staff block + default instructions (including booking/reschedule).

5. **Start session**
   - Create `AgentSession` with OpenAI Realtime model, `preemptive_generation=True`.
   - Create `Assistant(instructions=instructions)` and `session.start(room, agent, room_options)` with audio input options (noise cancellation: BVC for normal, BVCTelephony for SIP).

6. **First reply**
   - `await session.generate_reply()` — agent speaks the first greeting (e.g. “Thank you for calling [Company], how can I help you today?”).

7. **Ongoing conversation**
   - The session handles bidirectional audio: caller speaks → Realtime API → agent replies. This continues until the participant leaves or the room ends.

8. **End**
   - When the caller disconnects, the session ends. Transcripts and call summaries are not yet written by this agent (see README phase 2).

### 3.3 Flow Diagram (High Level)

```
[Frontend / Telephony]                    [Backend]                      [Agent process]
        |                                      |                                  |
        |  POST /calls/initiate               |                                  |
        |  (business_id, location_id)         |                                  |
        |------------------------------------->|                                  |
        |                                      |  create call, room               |
        |                                      |  token with metadata             |
        |  { call_id, livekit_room_id,         |  (call_id, business_id,           |
        |    livekit_token, livekit_ws_url }   |   location_id)                    |
        |<-------------------------------------|                                  |
        |                                      |                                  |
        |  room.connect(ws_url, token)        |                                  |
        |=========================================>|  participant joined           |
        |                                      |  (automatic dispatch)           |
        |                                      |  job -> voice_agent(ctx)         |
        |                                      |                         connect  |
        |                                      |                         wait_for_participant |
        |                                      |                         metadata  |
        |                                      |                         build_instructions |
        |                                      |                         Supabase: business, locations, brand_voice, staff |
        |                                      |                         session.start + generate_reply |
        |  <-------- audio (greeting) ---------|                         (Realtime) |
        |  ------- audio (caller) ----------->|                         (Realtime) |
        |  <-------- audio (agent) ------------|                         ...       |
        |  ...                                 |                         ...       |
        |  disconnect                          |                         session end |
```

---

## 4. What the Agent Does *Not* Do Yet

- **Write transcripts** to Supabase (phase 2 in agent README).
- **Write call summaries** to Supabase (phase 2).
- **Create or update appointments** in the DB (agent only collects info and confirms; actual booking can be added via tools or backend API later).
- **Look up existing appointments** by name/phone (no tool or API call yet).

---

## 5. One-Paragraph Summary

The SAM voice agent is a LiveKit Agents + OpenAI Realtime session that, on each call, reads `business_id` and optional `location_id` from participant metadata, then loads from Supabase: **business** (name, language, country, date/time format), **brand voice** (tone, style, vocabulary, do-not-say, sample responses), **all locations** (name, address, phone), and **staff per location** (from user_roles + user_locations + profiles). It builds one instruction string (welcome + global settings + brand voice + locations/staff + default and booking/reschedule instructions) and runs a single Realtime session that greets the caller and handles conversation. The flow is: backend creates call and room and puts metadata on the token; participant joins; LiveKit dispatches the agent; agent connects, waits for participant, builds instructions, starts session, and generates the first reply; then conversation continues until the caller leaves. Transcripts, summaries, and actual appointment create/update are not implemented in the agent yet.
