# Call Forwarding Runtime — Implementation Plan (Option C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **STATUS:** This plan documents the FULL Option C implementation (real SIP transfer). Only **Option B** (UI + agent reads rules in prompt and verbally directs) is being shipped now. Option C will be picked up later — most likely once the client has confirmed the forwarding UX in production with verbal-direction (Option B).

**Goal:** Real call transfer — when an inbound caller asks for a specific person/department, the agent invokes a `forward_call` tool that uses LiveKit's `TransferSIPParticipant` (SIP REFER) to hand the live call off to that contact's phone number. The decision of when/who to forward is driven by per-contact natural-language rules.

**Architecture:** Each `forwarding_contact` row gets a `forwarding_rule TEXT` column (free-form natural language). The agent's system prompt lists all enabled contacts for the called location, with their rules and IDs. A new `forward_call(contact_id)` agent tool calls our backend `POST /calls/{call_id}/forward`, which uses LiveKit's `SipClient.transfer_sip_participant()` to issue a SIP REFER — Twilio handles the rest. After REFER, the caller leaves the LiveKit room and finalization records the call as `forwarded`.

**Tech Stack:** FastAPI, LiveKit Agents (Python), LiveKit SIP API, Twilio Elastic SIP Trunking (REFER-enabled), Supabase

---

## What Has to Be True Before This Plan Can Be Executed

1. **Option B is shipped first** — UI and DB column exist. Without it the agent has no rules to read and no UI to manage them.
2. **Twilio trunk has Call Transfer enabled** — Twilio Console → Elastic SIP Trunks → your trunk → General Settings → "Call Transfers" toggled ON. Without this, REFER messages from LiveKit get rejected with `405 Method Not Allowed` or silently dropped.
3. **Caller ID for Transfer Target choice** — Twilio Console → same trunk → "Caller ID for Transfer Target" — recommended setting **"Transferee"** so the forwarded contact sees the original caller's number (better UX). Setting "Transferor" sends our Twilio number, which is fine but less informative.
4. **livekit-api Python SDK ≥ 1.0** is already in use in the agent (we upgraded in earlier work). `SipClient.transfer_sip_participant` is in this version.
5. **Outbound trunk per location is configured** — already done as part of the location-scoped phone work.
6. **Test phone number to forward to** — a real phone you can answer for E2E testing.

If any of the above is missing, this plan blocks — fix before starting.

---

## Design Decisions Locked In

| Decision | Choice | Why |
|---|---|---|
| Transfer type | **Cold transfer** (SIP REFER) for v1 | Simplest. Caller leaves the LiveKit room; agent does not stay on the line. Warm transfer is a follow-up. |
| Where the transfer is initiated | Backend endpoint, NOT directly from agent | Single source of truth, easier to audit, can record `status='forwarded'` + which contact in the call DB row. |
| How agent decides who | Agent system prompt lists every contact + rule. Agent picks based on conversation, calls `forward_call(contact_id)` tool. | Rules are free-form natural language — too varied to encode as filters. The LLM is good at this. |
| Multiple rules match | Agent picks the most specific (its own judgment). Tie-break implicit. | Don't over-engineer. If contacts overlap, the rule wording should disambiguate. |
| What if no rule matches caller's request | Agent says "I'll take a message" — does NOT transfer. | Safer than guessing. Caller is recorded as a normal completed call. |
| Caller ID seen by contact | "Transferee" mode (original caller's number) | More useful UX for the contact answering. |
| What happens to the LiveKit room after REFER | Room stays alive briefly until LiveKit notices the SIP participant is gone, then cleans up. Agent finalization writes `status='forwarded'`. | Standard LiveKit behavior. No special handling needed. |
| Forwarding rule storage format | Plain TEXT, free-form | Natural language input, no parsing on our side. The LLM consumes it as-is. |
| Rule visible to agent | Yes — included in system prompt under a "Forwarding Contacts" section. | Agent needs the rule to make the decision. |
| Audit / compliance | Append `forwarded_to=contact_id` and `status='forwarded'` to the `calls` row at transfer time | So we have a record of who got each transferred call. |
| Failure mode | If REFER fails (Twilio rejects, contact unreachable, etc.) → backend returns error, agent apologises and offers to take a message instead. | Agent never leaves the caller stuck. |
| Per-location scope | Forwarding is already location-scoped (`forwarding_contacts.location_id`); agent only sees contacts for the called location | Matches our location-scoped architecture |

---

## File Structure

### Backend Files (new)
- `backend/app/routers/calls.py` — add `POST /calls/{call_id}/forward` endpoint

### Backend Files (modify)
- `backend/app/services/livekit_service.py` — add `transfer_sip_participant(room, identity, dest_phone)` wrapper
- `backend/app/schemas/calls.py` — add `ForwardCallRequest` schema

### Agent Files (modify)
- `agent/prompt_builder.py` — add a "Forwarding Contacts" block to the system prompt listing each enabled contact: `{id, name, title, phone, rule}`
- `agent/supabase_helpers.py` — `_fetch_forwarding_contacts(supabase, business_id, location_id)` (already exists in spirit — if not, add it)
- `agent/agent.py` — add `forward_call(contact_id)` `@function_tool()` on the Assistant class. Implementation calls our backend `POST /calls/{call_id}/forward` with auth.

### DB Migrations (already done in Option B)
- `supabase/migrations/20260413000003_forwarding_contact_rule.sql` — adds `forwarding_rule TEXT` column. (See Option B section below.)

### Frontend Files (already done in Option B)
- Edit dialog with rule textarea
- Title field (renamed from department_tag in UI)
- Priority badge removed

---

## Phase 1 — Backend Transfer Plumbing

### Task 1: Add SIP transfer wrapper in `livekit_service.py`

**Files:**
- Modify: `backend/app/services/livekit_service.py`

- [ ] **Step 1: Add the wrapper function**

```python
async def transfer_sip_participant(
    room_id: str,
    participant_identity: str,
    destination: str,        # e.g. "tel:+15555550100"
    *,
    play_dialtone: bool = False,
) -> None:
    """
    Issue a SIP REFER to transfer the caller to another phone number.
    The caller leaves the LiveKit room once the transfer completes.
    Requires the Twilio inbound trunk to have Call Transfers enabled.
    """
    from livekit.protocol.sip import TransferSIPParticipantRequest

    api = LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        req = TransferSIPParticipantRequest(
            participant_identity=participant_identity,
            room_name=room_id,
            transfer_to=destination,
            play_dialtone=play_dialtone,
        )
        await api.sip.transfer_sip_participant(req)
        print(
            f"[LiveKit] SIP transfer issued — room={room_id} "
            f"identity={participant_identity} -> {destination}",
            flush=True,
        )
    finally:
        await api.aclose()
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/livekit_service.py
git commit -m "feat: add transfer_sip_participant wrapper (SIP REFER)"
```

---

### Task 2: Add `ForwardCallRequest` schema

**Files:**
- Modify: `backend/app/schemas/calls.py`

- [ ] **Step 1: Add the schema**

```python
class ForwardCallRequest(BaseModel):
    contact_id: str   # forwarding_contacts.id
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/calls.py
git commit -m "feat: add ForwardCallRequest schema"
```

---

### Task 3: Add `POST /calls/{call_id}/forward` endpoint

**Files:**
- Modify: `backend/app/routers/calls.py`

- [ ] **Step 1: Add the route**

```python
from app.schemas.calls import ForwardCallRequest

@router.post("/{call_id}/forward")
async def forward_call(
    call_id: str,
    body: ForwardCallRequest,
    current_user: dict = Depends(get_current_user),
):
    # 1. Look up the call (must be active)
    call_row = (
        supabase_admin.table("calls")
        .select("id, business_id, location_id, livekit_room_id, status")
        .eq("id", call_id)
        .limit(1)
        .execute()
    )
    if not call_row.data:
        raise HTTPException(status_code=404, detail="Call not found")
    call = call_row.data[0]
    if call["status"] not in ("active", "initiating"):
        raise HTTPException(status_code=409, detail=f"Cannot forward a {call['status']} call")
    if not call.get("livekit_room_id"):
        raise HTTPException(status_code=409, detail="Call has no LiveKit room (web call?)")

    # 2. Look up the contact (must belong to same business + location)
    contact_row = (
        supabase_admin.table("forwarding_contacts")
        .select("id, name, phone, business_id, location_id, is_active")
        .eq("id", body.contact_id)
        .limit(1)
        .execute()
    )
    if not contact_row.data:
        raise HTTPException(status_code=404, detail="Forwarding contact not found")
    contact = contact_row.data[0]
    if contact["business_id"] != call["business_id"]:
        raise HTTPException(status_code=403, detail="Contact does not belong to this business")
    if call.get("location_id") and contact.get("location_id") and contact["location_id"] != call["location_id"]:
        raise HTTPException(status_code=403, detail="Contact is not for this location")
    if not contact.get("is_active"):
        raise HTTPException(status_code=409, detail="Contact is disabled")

    # 3. Find the SIP caller participant identity in the room
    #    (sip-<digits> per our SIP participant naming convention)
    #    For inbound SIP, LiveKit auto-creates participant with identity starting "sip_" or "sip-".
    #    We need the identity of the caller, not the agent. Use the room's participant list.
    from livekit.api import LiveKitAPI
    from livekit.protocol.room import ListParticipantsRequest

    api = LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    caller_identity = None
    try:
        plist = await api.room.list_participants(
            ListParticipantsRequest(room=call["livekit_room_id"])
        )
        for p in plist.participants:
            if p.identity.startswith("sip_") or p.identity.startswith("sip-"):
                caller_identity = p.identity
                break
    finally:
        await api.aclose()

    if not caller_identity:
        raise HTTPException(status_code=409, detail="No SIP caller found in room")

    # 4. Issue the SIP REFER
    try:
        await livekit_service.transfer_sip_participant(
            room_id=call["livekit_room_id"],
            participant_identity=caller_identity,
            destination=f"tel:{contact['phone']}",
        )
    except Exception as e:
        logger.error("SIP transfer failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Transfer failed: {e}")

    # 5. Mark call as forwarded
    supabase_admin.table("calls").update({
        "status": "forwarded",
        "forwarded_to": contact["id"],
        "ended_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", call_id).execute()

    return {
        "forwarded": True,
        "contact_id": contact["id"],
        "contact_name": contact["name"],
        "destination": contact["phone"],
    }
```

NOTE: The `calls` table needs a `forwarded_to` column referencing `forwarding_contacts.id`. If it doesn't already exist, add a migration: `ALTER TABLE calls ADD COLUMN forwarded_to UUID REFERENCES forwarding_contacts(id) ON DELETE SET NULL;`

- [ ] **Step 2: Commit**

```bash
git add backend/app/routers/calls.py
git commit -m "feat: add POST /calls/{id}/forward endpoint (SIP REFER)"
```

---

## Phase 2 — Agent Tool

### Task 4: Add `forward_call` tool on the Assistant class

**Files:**
- Modify: `agent/agent.py`

- [ ] **Step 1: Add the tool**

```python
@function_tool()
async def forward_call(
    self,
    context: RunContext,
    contact_id: str,
) -> str:
    """
    Forward the active call to a forwarding contact by ID.
    Use this when the caller asks to be connected to a specific person
    or department, and you have a matching contact in the Forwarding
    Contacts list above. Read the contact's rule first to confirm
    they handle this kind of call right now.

    contact_id: the contact's ID exactly as shown in the Forwarding
    Contacts list. Do NOT make up an ID.
    """
    if not self._call_id:
        return "Cannot forward — this call has no record on the system."
    if not self._business_id:
        return "Cannot forward — business context missing."

    backend_url = os.getenv("BACKEND_URL", "http://sam-backend:8000")
    backend_token = os.getenv("AGENT_BACKEND_TOKEN", "")
    if not backend_token:
        return "Cannot forward — agent is not authorised to call the backend."

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{backend_url}/calls/{self._call_id}/forward",
                headers={
                    "Authorization": f"Bearer {backend_token}",
                    "Content-Type": "application/json",
                },
                json={"contact_id": contact_id},
            )
            if r.status_code == 200:
                data = r.json()
                return (
                    f"Connecting you to {data.get('contact_name')} now. "
                    f"Please hold."
                )
            else:
                logger.error("Forward call failed %s: %s", r.status_code, r.text)
                return (
                    "I'm sorry, I couldn't connect you right now. "
                    "Would you like me to take a message instead?"
                )
    except Exception as e:
        logger.error("Forward call exception: %s", e)
        return (
            "I'm sorry, I couldn't connect you right now. "
            "Would you like me to take a message instead?"
        )
```

NOTE: We need a service token the agent can use to call the backend. Two options:
- **A:** Service-role JWT (a long-lived token signed with `SUPABASE_JWT_SECRET` representing a service identity) — reuses existing auth
- **B:** Dedicated `AGENT_BACKEND_TOKEN` env var validated by a new dependency in `auth.py`

**Recommendation: B** — clearer separation of concerns. Define a `verify_agent_token` dependency that compares against `os.getenv("AGENT_BACKEND_TOKEN")` (HMAC-equal). Add it to `/calls/{id}/forward` as the auth dependency instead of `get_current_user`.

- [ ] **Step 2: Add the agent token verification in `backend/app/core/auth.py`**

```python
def verify_agent_token(authorization: str = Header(None)) -> None:
    expected = os.getenv("AGENT_BACKEND_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Agent backend token not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    provided = authorization[len("Bearer "):].strip()
    import hmac
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid agent token")
```

Update the forward endpoint to use this dep instead of `get_current_user`.

- [ ] **Step 3: Commit**

```bash
git add agent/agent.py backend/app/core/auth.py backend/app/routers/calls.py
git commit -m "feat: agent forward_call tool + agent-token auth on /calls/{id}/forward"
```

---

### Task 5: Inject Forwarding Contacts into agent prompt

**Files:**
- Modify: `agent/prompt_builder.py`

(Option B already adds the basic list; Option C extends it with the rule and contact_id so the agent can pick correctly.)

- [ ] **Step 1: Format contacts including ID and rule**

```python
def _format_forwarding_contacts(contacts: list[dict]) -> str:
    if not contacts:
        return ""
    lines = []
    for c in contacts:
        title = c.get("department_tag") or "Staff"
        rule = (c.get("forwarding_rule") or "").strip() or "(no rule specified)"
        lines.append(
            f"- contact_id={c['id']} | {c['name']} ({title}) | phone={c['phone']} | rule: {rule}"
        )
    block = (
        "Forwarding Contacts (use forward_call tool with the contact_id when "
        "the caller asks for one of these people, AND the contact's rule "
        "matches the caller's request):\n"
        + "\n".join(lines)
        + "\n\nIMPORTANT: only forward when a contact's rule clearly matches. "
          "If no contact matches, take a message and do NOT use forward_call.\n\n"
    )
    return block
```

Then in `build_instructions`:
```python
fwd_contacts = _fetch_forwarding_contacts(supabase, business_id, location_id) if business_id else []
fwd_block = _format_forwarding_contacts(fwd_contacts)

# ... include fwd_block in the returned prompt assembly
```

- [ ] **Step 2: Commit**

```bash
git add agent/prompt_builder.py
git commit -m "feat: include forwarding contacts + rules in agent prompt"
```

---

## Phase 3 — Configuration

### Task 6: Set `AGENT_BACKEND_TOKEN` env var

- [ ] Generate a strong random token: `openssl rand -hex 32`
- [ ] Add to `backend/.env`: `AGENT_BACKEND_TOKEN=<generated>`
- [ ] Add to `agent/.env.local`: `AGENT_BACKEND_TOKEN=<same value>` and `BACKEND_URL=http://sam-backend:8000`
- [ ] Restart both containers

### Task 7: Enable Call Transfers on Twilio Trunk

(One-time client task — see `docs/CALL_FORWARDING_SETUP.md`.)

- [ ] Twilio Console → Elastic SIP Trunks → your trunk
- [ ] General Settings → toggle **Call Transfers** ON
- [ ] Caller ID for Transfer Target → **Transferee**
- [ ] Save

---

## Phase 4 — Testing

- [ ] Inbound test call → ask agent "can I speak to John in Sales?" → verify agent calls `forward_call(contact_id=...)` with correct ID
- [ ] Verify your test phone rings within ~5s of agent saying "connecting you"
- [ ] Verify `calls` row is `status='forwarded'`, `forwarded_to=<contact id>`
- [ ] Verify rule mismatch: ask agent for John outside his rule's allowed window → agent should NOT transfer, takes a message instead
- [ ] Verify failure path: disable contact → ask for them → agent gets error → offers to take a message
- [ ] Verify caller ID at the receiving end: should be the original caller's number (Transferee mode)

---

## Risks / Gotchas

| Risk | Mitigation |
|---|---|
| Twilio doesn't have Call Transfers enabled → REFER returns 405 | Document as Step 0 prerequisite, fail loudly with clear error |
| Caller hangs up before transfer completes | LiveKit handles this — transfer simply doesn't happen, finalization marks the call normally |
| Contact's phone doesn't answer | Twilio routes per its own rules (voicemail if set up); we're out of the loop after REFER |
| Multiple contacts have overlapping rules | Agent's LLM picks the most specific. For ambiguous cases, agent should ask the caller to confirm. |
| Per-minute Twilio charges continue after transfer | This is normal — same as making any outbound call. Document for the client. |
| Caller ID restrictions in some regions | "Transferee" mode may be blocked by some carriers. If complaints arise, switch to "Transferor" in Twilio config. |
| What if call_id is missing (web call)? | Backend rejects with 409 — only SIP calls have a `livekit_room_id` with a SIP caller participant |

---

## Cost Estimate

| Item | Cost |
|---|---|
| LiveKit transfer API call | $0 |
| Twilio REFER processing | $0 |
| Continued PSTN minutes after transfer | Same as a regular Twilio outbound call (~$0.013/min for US) |

A 5-minute call that's transferred 1 minute in costs roughly: 1 min original inbound + 4 min outbound to the contact = ~$0.05.

---

## What This Plan Does NOT Cover

- **Warm transfer** — agent stays on briefly to introduce. Use `WarmTransferTask` from `livekit.agents.beta.workflows` when ready.
- **Voicemail / fallback if contact doesn't answer** — currently the contact's own carrier handles it. We don't loop back into the agent.
- **Forwarding analytics dashboard** — number of transfers per contact, success rate, etc. Could be added later by querying `calls.forwarded_to`.
- **Rule conflict UI** — if two contacts have rules that could both match the same call, we don't warn the admin in the UI. The LLM's judgment is the runtime tie-breaker.
- **Agent-side rate limit** — nothing prevents the agent from spamming `forward_call`. We trust the LLM. If abuse becomes a problem, add a per-call max-attempts counter.

---

## Reference: Researched APIs (from official docs as of 2026-04-13)

- **LiveKit Cold Transfer** — https://docs.livekit.io/sip/transfer-cold/
  - `SipClient.transferSipParticipant(room, identity, destination, { playDialtone })`
  - Destination format: `tel:+15105550100` or `sip:+15105550100@sip.telnyx.com`
  - Caller leaves the LiveKit session once transfer completes
- **LiveKit Warm Transfer** — https://docs.livekit.io/sip/transfer-warm/
  - Pre-built `WarmTransferTask` in `livekit.agents.beta.workflows` (Python)
- **Twilio Elastic SIP Trunking — Call Transfer** — https://www.twilio.com/docs/sip-trunking/call-transfer
  - Per-trunk toggle: **General Settings → Call Transfers**
  - Caller ID modes: Transferee (default) or Transferor
  - No charge for REFER; per-minute trunking charges continue for the transferred leg
  - Emergency numbers (911/933) not supported
