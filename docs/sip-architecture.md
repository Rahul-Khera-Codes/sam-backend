# Multi-Tenant SIP Architecture

## Overview

SAM uses a **shared trunk, per-tenant dispatch rule** model. A single Twilio Elastic SIP Trunk and a single LiveKit inbound SIP trunk handle calls for **all businesses on the platform**. Per-business routing is achieved through LiveKit **dispatch rules** — one per provisioned phone number — which carry the `business_id` and `location_id` as metadata into the agent session.

---

## Infrastructure (Created Once, Shared)

```
┌─────────────────────────────────────────────────────────────┐
│                    SHARED INFRASTRUCTURE                     │
│                                                              │
│  Twilio Elastic SIP Trunk (TWILIO_TRUNK_SID)                 │
│    ├── Origination URI → ai-front-desk-xxx.sip.livekit.cloud │
│    └── Termination Domain → sam-xxx.pstn.twilio.com          │
│                                                              │
│  LiveKit Inbound SIP Trunk (LIVEKIT_SIP_INBOUND_TRUNK_ID)    │
│    ├── Allowed addresses: Twilio IP ranges                   │
│    └── Auth: SIP_AUTH_USERNAME / SIP_AUTH_PASSWORD           │
│                                                              │
│  LiveKit Outbound SIP Trunk (LIVEKIT_SIP_OUTBOUND_TRUNK_ID)  │
│    └── Created when first phone number is provisioned        │
└─────────────────────────────────────────────────────────────┘
```

---

## Per-Business Resources (Created at Provisioning Time)

When a business purchases a phone number, three things are created:

| Resource | Where | Purpose |
|---|---|---|
| Twilio phone number | Twilio | The actual PSTN number |
| Twilio assignment | Twilio | Assigns number to the shared SIP trunk |
| LiveKit dispatch rule | LiveKit | Routes calls to the right business agent |

The dispatch rule is the key to multi-tenancy:

```python
# Created once per phone number at provisioning time
await lk.sip.create_sip_dispatch_rule(
    CreateSIPDispatchRuleRequest(
        rule=SIPDispatchRuleInfo(
            name=f"Business {business_id} — {phone_number}",
            # Match inbound calls whose To: header == this number
            rule=SIPDispatchRule(
                dispatch_rule_direct=SIPDispatchRuleDirect(
                    room_prefix="call",
                    pin=""
                )
            ),
            trunk_ids=[LIVEKIT_SIP_INBOUND_TRUNK_ID],
            attributes={
                "business_id": str(business_id),
                "location_id": str(location_id),
            },
        )
    )
)
```

---

## Inbound Call Flow

```
Caller (PSTN)
    │
    │  dials +1-555-Business-A
    ▼
Twilio PSTN Network
    │
    │  Twilio sees the number belongs to "SAM Voice Agent" trunk
    │  Sends SIP INVITE to origination URI
    ▼
LiveKit SIP Inbound Trunk  (shared)
    │
    │  LiveKit inspects To: header → matches +1-555-Business-A
    │  Finds dispatch rule for that number
    │  Reads attributes: { business_id: "uuid-A", location_id: "uuid-L" }
    ▼
LiveKit Room  (new room per call, e.g. "call-<uuid>")
    │
    │  LiveKit launches the agent worker
    │  Job metadata contains: { "business_id": "uuid-A", "location_id": "uuid-L" }
    ▼
SAM Agent Worker
    │
    │  Reads ctx.job.metadata["business_id"]
    │  Fetches business config, services, staff, availability from Supabase
    │  Builds system prompt specific to Business A
    ▼
Conversation with caller using Business A's context
```

### Key point
LiveKit performs the dispatch rule matching automatically — no webhook, no database lookup needed at call-answer time. The `business_id` arrives pre-loaded in the job metadata.

---

## Outbound Call Flow

```
SAM Backend (API call from frontend or automation)
    │
    │  POST /calls/outbound
    │  { business_id, location_id, to_number, from_number }
    ▼
Backend creates a LiveKit Room + calls CreateSIPParticipant API
    │
    │  LiveKit uses outbound SIP trunk (LIVEKIT_SIP_OUTBOUND_TRUNK_ID)
    │  Sends SIP INVITE to sam-xxx.pstn.twilio.com (termination domain)
    │  Auth: TWILIO_TERM_SIP_USERNAME / TWILIO_TERM_SIP_PASSWORD
    ▼
Twilio PSTN Network
    │
    │  Routes call to destination number via PSTN
    ▼
Called party's phone rings
    │
    │  When answered → audio bridged back through LiveKit Room
    ▼
SAM Agent in the room handles the conversation
```

### Caller ID on outbound calls
The `From:` number in the SIP INVITE is set to the business's provisioned number. This means:
- The called party sees the business's number on caller ID
- If they call back, the inbound flow above routes it to the same business

---

## Phone Number Provisioning Flow

```
Business admin clicks "Get a Phone Number" in frontend
    │
    ▼
Frontend: GET /phone-numbers/search?area_code=415&country=US
    │  → Calls Twilio to list available numbers
    ▼
Frontend: POST /phone-numbers/provision { number_sid, business_id, location_id }
    │
    ▼
Backend steps (atomic):
    1. twilio.incoming_phone_numbers(number_sid).update(trunk_sid=TWILIO_TRUNK_SID)
       → Assigns number to shared Twilio trunk

    2. If no outbound LiveKit trunk yet:
       lk.sip.create_sip_outbound_trunk(...)  with this number
       → Creates the outbound trunk (first time only)
       Else:
       lk.sip.update_sip_outbound_trunk(...)  add number to existing trunk

    3. lk.sip.create_sip_dispatch_rule(...)  with To: = this number
       attributes = { business_id, location_id }
       → Creates the per-tenant routing rule

    4. INSERT INTO business_phone_numbers
       { business_id, location_id, phone_number, twilio_number_sid,
         livekit_dispatch_rule_id, status: "active" }
    │
    ▼
Done — inbound calls to this number now route to the correct business agent
```

---

## Database Table: `business_phone_numbers`

```sql
CREATE TABLE business_phone_numbers (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id             UUID NOT NULL REFERENCES businesses(id),
    location_id             UUID REFERENCES locations(id),
    phone_number            TEXT NOT NULL UNIQUE,   -- E.164 e.g. +14155551234
    twilio_number_sid       TEXT NOT NULL UNIQUE,   -- PNxxxxxxxx
    livekit_dispatch_rule_id TEXT,                  -- DR_xxxxxxxxxx
    status                  TEXT DEFAULT 'active',  -- active | released
    created_at              TIMESTAMPTZ DEFAULT now(),
    released_at             TIMESTAMPTZ
);
```

---

## Security Layers

| Layer | Mechanism |
|---|---|
| Twilio → LiveKit | IP allowlist (Twilio CIDR ranges on inbound trunk) + SIP digest auth |
| LiveKit → Twilio | Credential list on Twilio termination domain |
| Tenant isolation | Dispatch rule attributes carry `business_id` — agent never trusts caller input |
| API endpoints | Supabase JWT auth on all provisioning endpoints |

---

## Environment Variables Reference

```bash
# ── Shared Trunk IDs (filled by scripts/setup_sip_trunks.py) ──
TWILIO_TRUNK_SID=TKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LIVEKIT_SIP_INBOUND_TRUNK_ID=ST_xxxxxxxxxxxxxxxx
LIVEKIT_SIP_OUTBOUND_TRUNK_ID=ST_xxxxxxxxxxxxxxxx   # filled at first provisioning

# ── SIP Auth ──────────────────────────────────────────────────
SIP_AUTH_USERNAME=sam-sip-user           # Twilio → LiveKit inbound digest auth
SIP_AUTH_PASSWORD=<secret>

TWILIO_TERM_SIP_USERNAME=sam-outbound-user  # LiveKit → Twilio outbound auth
TWILIO_TERM_SIP_PASSWORD=<secret>
TWILIO_TERM_DOMAIN=sam-xxx.pstn.twilio.com
```

---

## Summary

| Question | Answer |
|---|---|
| How many Twilio trunks? | **One** — shared across all businesses |
| How many LiveKit inbound trunks? | **One** — shared across all businesses |
| How many LiveKit dispatch rules? | **One per phone number** (per business/location) |
| How does LiveKit know which business? | Dispatch rule matched by `To:` number → attributes `{business_id, location_id}` |
| How does the agent know which business? | `ctx.job.metadata["business_id"]` injected by LiveKit |
| What triggers outbound trunk creation? | First phone number provisioned |
| What happens when a number is released? | Delete dispatch rule + release Twilio number + update DB status |
