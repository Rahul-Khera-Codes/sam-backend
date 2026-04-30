# Call Forwarding Option C — Full Technical Documentation

**Date:** 2026-04-17  
**Status:** Shipped (session 32)  
**Scope:** How Option C call forwarding works end-to-end — Twilio config, LiveKit config, agent data flow, and the full runtime call sequence.

---

## Overview

When a caller asks to speak to a specific person or department, the AI agent can **live-transfer** the call to that person's phone number. The caller's phone is handed off — they hear a brief hold, and then the destination phone rings. The agent drops out of the call entirely.

This uses a SIP mechanism called **SIP REFER** — the agent sends a "please transfer yourself to this new number" instruction to the caller's SIP leg, which Twilio then executes by bridging the caller to the destination.

---

## Infrastructure Components

### 1. Twilio (PSTN carrier)

Twilio is the telephone carrier. It owns the phone numbers (e.g., +14157077538 for Mirage) and handles PSTN connectivity — turning phone calls into SIP packets and vice versa.

**Trunk:** `SAM Voice Agent` (Elastic SIP Trunk, US1 region)

**Settings that enable call transfer** (configured session 32):
| Setting | Value | Why |
|---|---|---|
| Call Transfer (SIP REFER) | **Enabled** | Allows Twilio to accept a SIP REFER from LiveKit and bridge the caller to a new number |
| Caller ID for Transfer Target | **Set caller ID as Transferee** | The destination phone sees the original caller's number, not Twilio's number — so if you forward to a staff member's cell, they see who's actually calling |
| Enable PSTN Transfer | **Checked** | Allows the REFER to target a regular phone number (not just another SIP endpoint). Without this, REFER only works between SIP devices |

Without these settings, Twilio would reject the SIP REFER with a 603 Declined and the transfer would fail.

---

### 2. LiveKit (media/session layer)

LiveKit sits between Twilio and the AI agent. When a call comes in:

- Twilio delivers the SIP call to LiveKit's SIP trunk
- LiveKit creates a **Room** (a virtual meeting room)
- LiveKit places two participants in that room:
  - The **SIP participant** — the caller's audio leg, bridged from Twilio
  - The **Agent participant** — the AI agent process

The agent talks to the caller by exchanging audio through this LiveKit room.

When the agent wants to transfer the call, it tells LiveKit: "Send a SIP REFER to that SIP participant, targeting this phone number." LiveKit sends the REFER to Twilio via the existing SIP leg.

---

### 3. The Agent (Python, `agent/agent.py`)

The agent is a Python process running in Docker (`sam-backend-sam-agent-1`). It connects to LiveKit as a participant. It:
- Builds a system prompt from Supabase data (services, staff, hours, forwarding contacts)
- Uses OpenAI Realtime API for voice-to-voice conversation
- Calls Supabase directly when it needs to read/write data (appointments, call records, etc.)
- Calls the LiveKit API directly when it needs to transfer a call

---

## How the Agent Knows Which Contacts to Forward To

This is the key question. Here is the full data flow from database → agent → transfer decision.

### Step 1: Database (Supabase `forwarding_contacts` table)

Each business stores its forwarding contacts here. Relevant columns:

| Column | Example | Purpose |
|---|---|---|
| `id` | `abc123-...` | UUID — the agent passes this to `forward_call()` to identify the contact |
| `business_id` | `da9fc4fb-...` | Which business owns this contact |
| `location_id` | `fd7d1823-...` | Which location this contact belongs to (NULL = all locations) |
| `name` | `"John Smith"` | Human-readable name |
| `phone` | `"+17805551234"` | Phone number to transfer to (E.164 format) |
| `department_tag` | `"Manager"` | Role/department label shown in prompt |
| `forwarding_rule` | `"If caller is upset or asks for a manager"` | Natural-language rule — when should the agent forward to this person? |
| `is_active` | `true` | Only active contacts are loaded |

The forwarding rule is the critical piece. It tells the agent **when** to forward, not just **who** to forward to.

---

### Step 2: `supabase_helpers._fetch_forwarding_contacts()` (called at session start)

At the start of every call, `prompt_builder.build_instructions()` is called. Inside it, this function fetches forwarding contacts from Supabase:

```python
def _fetch_forwarding_contacts(supabase, business_id, location_id) -> list[dict]:
    query = (
        supabase.table("forwarding_contacts")
        .select("id, name, phone, department_tag, forwarding_rule")
        .eq("business_id", business_id)
        .eq("is_active", True)
    )
    if location_id:
        query = query.eq("location_id", location_id)  # only contacts for this location
    return query.execute().data
```

This returns a list like:
```python
[
    {
        "id": "abc123-...",
        "name": "John Smith",
        "phone": "+17805551234",
        "department_tag": "Manager",
        "forwarding_rule": "If caller is upset or asks for a manager"
    },
    {
        "id": "def456-...",
        "name": "Billing Team",
        "phone": "+17809990001",
        "department_tag": "Billing",
        "forwarding_rule": "If caller has a billing question or payment dispute"
    }
]
```

---

### Step 3: `prompt_builder._format_forwarding_contacts()` (builds the prompt block)

This function converts the list into a text block that goes into the agent's system prompt:

```
Forwarding Contacts — when a caller asks to speak with a specific person or department
and their rule clearly matches the caller's request, confirm with the caller first, then
call forward_call(contact_id) with the contact_id shown below to transfer the call.
If no contact's rule clearly matches, offer to take a message instead.

- John Smith (Manager) [contact_id: abc123-...] — phone: +17805551234. Rule: If caller is upset or asks for a manager
- Billing Team (Billing) [contact_id: def456-...] — phone: +17809990001. Rule: If caller has a billing question or payment dispute
```

**Key:** The `contact_id` (the UUID) is embedded directly in the prompt text. The agent reads this and knows which ID to pass when calling the `forward_call` tool.

---

### Step 4: Agent runtime — the `forward_call` tool decision

During the call, the OpenAI Realtime model processes the conversation. When a caller says something like:

> "Can I speak to a manager please?"

The model:
1. Matches this against the forwarding contacts in its system prompt
2. Identifies that John Smith's rule ("If caller is upset or asks for a manager") matches
3. **Before transferring**, confirms with the caller: *"I'll transfer you to John Smith right away. Please hold."*
4. Calls the `forward_call` tool with `contact_id = "abc123-..."`

---

## The `forward_call` Tool — Step by Step

This tool runs inside the agent process. Here is exactly what happens when it is invoked:

### Phase 1: Look up the contact in Supabase

```python
r = supabase.table("forwarding_contacts")
    .select("id, name, phone")
    .eq("id", contact_id)           # the UUID from the prompt
    .eq("business_id", self._business_id)  # security: must belong to this business
    .limit(1)
    .execute()
```

Why look it up again? The phone number is confirmed fresh from the database, not trusted from the prompt (which was built at call start). This prevents any stale data issue.

### Phase 2: Normalize the phone number

```python
phone = _normalize_phone_e164(contact["phone"])
# e.g., "7805551234" → "+17805551234"
# e.g., "(780) 555-1234" → "+17805551234"
```

All phone numbers must be in E.164 format for SIP REFER to work.

### Phase 3: Send SIP REFER via LiveKit API

```python
from livekit.api import LiveKitAPI
from livekit.protocol.sip import TransferSIPParticipantRequest

api = LiveKitAPI(
    url=os.getenv("LIVEKIT_URL"),
    api_key=os.getenv("LIVEKIT_API_KEY"),
    api_secret=os.getenv("LIVEKIT_API_SECRET"),
)

req = TransferSIPParticipantRequest(
    room_name=self._room_name,                      # e.g., "call-a3f8bc..."
    participant_identity=self._sip_participant_identity,  # e.g., "sip_+14157077538"
    transfer_to="tel:+17805551234",                 # tel: URI format
)
await api.sip.transfer_sip_participant(req)
```

**`room_name`** — the LiveKit room for this specific call. Stored on the `Assistant` at session start from `ctx.room.name`.

**`participant_identity`** — the identity of the SIP participant (the caller's audio leg). Stored on `Assistant` at session start from `participant.identity`. Only set if the call is a real SIP call (inbound phone call). For web test calls this is `None`, and the tool returns an error message instead.

**`transfer_to`** — the `tel:` URI format is the SIP standard for phone numbers. LiveKit converts this to a SIP REFER header.

### Phase 4: What Twilio does with the REFER

When LiveKit sends the SIP REFER to Twilio:
1. Twilio receives the REFER on the existing SIP call leg
2. Because "Call Transfer (SIP REFER)" is enabled on the trunk, Twilio accepts it
3. Twilio looks at the `Refer-To` header: `tel:+17805551234`
4. Because "Enable PSTN Transfer" is enabled, Twilio dials `+17805551234` on the PSTN
5. When the destination answers, Twilio bridges the original caller's audio to the new number
6. The caller is now talking to John Smith — the AI agent is no longer involved
7. The original SIP session between Twilio and LiveKit terminates

Because "Caller ID = Transferee" is set, John Smith's phone sees the original caller's phone number (e.g., +17801234567), not Twilio's number. This is important so staff can call back the customer if needed.

### Phase 5: Update the call record in Supabase

```python
supabase.table("calls").update({
    "status": "forwarded",
    "forwarded_to": contact_id,   # UUID of the forwarding_contact row
    "ended_at": datetime.now(timezone.utc).isoformat(),
}).eq("id", self._call_id).execute()
```

The call record is immediately marked as `forwarded` with a reference to which contact received the transfer.

### Phase 6: Caller disconnects from LiveKit

After the SIP REFER completes, Twilio terminates its SIP session with LiveKit. The SIP participant disconnects from the LiveKit room. This triggers the `participant_disconnected` event in the agent's session, which then runs `_finalize_call`.

### Phase 7: `_finalize_call` — status guard

`_finalize_call` saves the transcript and normally updates the call status. But because the call was already marked `forwarded` in Phase 5, it checks first:

```python
current = supabase.table("calls").select("status").eq("id", call_id).limit(1).execute()
if current.data[0]["status"] == "forwarded":
    # Don't overwrite — just save duration
    supabase.table("calls").update({"duration_seconds": duration_s}).eq("id", call_id).execute()
else:
    supabase.table("calls").update({
        "status": final_status,   # "completed" or "missed"
        "ended_at": ...,
        "duration_seconds": duration_s,
    }).eq("id", call_id).execute()
```

This ensures the call shows as `forwarded` in the UI, not incorrectly as `completed`.

---

## Full Call Sequence — Timeline

```
[Caller dials +14157077538]
        |
        v
[Twilio receives PSTN call]
[Twilio SIP → LiveKit inbound trunk]
        |
        v
[LiveKit matches phone number → looks up dispatch rule]
[Dispatch rule carries: business_id=da9fc..., location_id=fd7d...]
[LiveKit creates Room: "call-a3f8bc..."]
[LiveKit adds SIP participant (caller's audio leg) to room]
        |
        v
[LiveKit dispatches agent: "ai-employee-agent" to that room]
[Agent connects to room]
        |
        v
[Agent reads business_id + location_id from job metadata]
[Agent queries Supabase:]
  - build_instructions() → system prompt including forwarding contacts with IDs
  - _fetch_services_for_location()
  - _fetch_staff_with_ids()  (filtered to location)
[Agent stores: room_name="call-a3f8bc...", sip_participant_identity="sip_+14157077538"]
        |
        v
[Agent greets caller via OpenAI Realtime]
[Conversation happens...]
        |
        v
[Caller: "Can I speak to a manager?"]
[OpenAI model matches → John Smith (Manager) [contact_id: abc123-...]]
[Agent: "I'll transfer you to John Smith now. Please hold."]
        |
        v
[Agent calls forward_call(contact_id="abc123-...")]
  → Supabase lookup: confirms phone = +17805551234
  → E.164 normalize
  → LiveKit API: TransferSIPParticipantRequest
      room_name = "call-a3f8bc..."
      participant_identity = "sip_+14157077538"
      transfer_to = "tel:+17805551234"
  → Supabase update: calls.status = "forwarded", forwarded_to = "abc123-..."
        |
        v
[LiveKit sends SIP REFER to Twilio on the active SIP leg]
        |
        v
[Twilio receives REFER]
[Twilio dials +17805551234 on PSTN]
[John Smith's phone rings]
[John answers]
[Twilio bridges: Caller ↔ John Smith]
[Twilio terminates SIP session with LiveKit]
        |
        v
[LiveKit room: SIP participant disconnects]
[Agent: participant_disconnected event fires]
[_finalize_call runs: saves transcript, sees status=forwarded, skips status overwrite, saves duration]
[Agent process ends]
```

---

## What the Agent CANNOT Do

- **Transfer web test calls** — web calls (Test Web Call button in the UI) use a WebRTC participant, not SIP. There is no SIP leg to REFER. The tool returns an error message if `sip_participant_identity` is None.
- **Transfer outbound calls** — outbound calls where the agent initiated the call to the customer. The tool only works on inbound calls where the caller rang a business number.
- **Transfer to contacts from other locations** — `_fetch_forwarding_contacts` filters to the called location's contacts only.
- **Transfer without confirming** — the tool docstring instructs the model to always confirm with the caller verbally before calling the tool. The model will say "I'll transfer you to [Name] now. Please hold." first.

---

## Configuration Summary

### Twilio Console (`SAM Voice Agent` trunk)
| Setting | Required Value |
|---|---|
| Call Transfer (SIP REFER) | Enabled |
| Caller ID for Transfer Target | Set caller ID as Transferee |
| Enable PSTN Transfer | Checked |

### LiveKit (no changes needed)
LiveKit supports `TransferSIPParticipant` natively. No LiveKit dashboard changes are needed — it is controlled entirely via API from the agent.

### Supabase (`forwarding_contacts` table)
- Contacts must have `is_active = true`
- `phone` must be a valid phone number (agent normalizes to E.164 automatically)
- `forwarding_rule` should be a clear, natural-language description of when to forward
- `location_id` should be set to the correct location so contacts only appear for the right branch

### `calls` table
- `forwarded_to UUID REFERENCES forwarding_contacts(id)` — migration `20260416000001` applied

---

## Forwarding Contact Rules — Best Practices

The `forwarding_rule` text is shown directly in the agent's system prompt. Write it as a condition the agent can evaluate against what the caller is saying.

**Good rules:**
- `"If the caller is angry, upset, or specifically asks for a manager or supervisor"`
- `"If the caller has a question about an invoice, payment, or billing dispute"`
- `"If the caller asks for the owner or wants to discuss a complaint"`
- `"If the caller mentions they are calling about a wholesale or bulk order"`

**Avoid:**
- Rules that are too vague (`"For important calls"`) — the agent won't know when to apply it
- Rules that overlap with booking (`"If they want to book"`) — booking is handled by the agent, not forwarding
- Rules with "always" (`"Always forward after 6pm"`) — the agent cannot check the clock; use Custom Schedules to disable the agent instead

---

## Monitoring a Transfer in Logs

When a transfer happens, you will see this sequence in `docker logs sam-backend-sam-agent-1`:

```
INFO voice-agent  Context from job metadata: business_id=da9fc... location_id=fd7d...
INFO voice-agent  Loaded context — locations: 2, services: 8, staff: 2 (call_id=...)
...
INFO voice-agent  Forwarded call <call_id> to contact John Smith (+17805551234)
INFO voice-agent  Participant disconnected: sip_+14157077538 — triggering finalization
INFO voice-agent  Finalizing call <call_id> — duration=47s utterances=12
INFO voice-agent  Call <call_id> finalized status=forwarded duration=47s utterances=12
```

If the SIP REFER fails (e.g., network error, wrong phone number), you will see:
```
ERROR voice-agent  SIP REFER transfer failed for contact abc123-...: <error>
```
And the agent will tell the caller the direct phone number verbally instead.

---

## Files Changed (session 32)

| File | What Changed |
|---|---|
| `backend/app/services/livekit_service.py` | Added `transfer_sip_participant(room_name, participant_identity, transfer_to)` |
| `agent/prompt_builder.py` | `_format_forwarding_contacts` now includes `contact_id` per contact and updated instruction text for Option C |
| `agent/agent.py` | `Assistant.__init__` stores `room_name` + `sip_participant_identity`; new `forward_call(contact_id)` tool; `_finalize_call` skips status overwrite if already `forwarded`; `voice_agent()` passes `room_name` + `sip_participant_identity` to `Assistant` |
| `docs/migrations/20260416000001_calls_forwarded_to.sql` | Migration SQL — applied |
