# Spec: Forward Calls to Business Phone When Agent is OFF

**Date:** 2026-06-08  
**Requested by:** Sam Maisuria (Question 5 in pre-launch doc)  
**Status:** Ready to implement

---

## Problem

When the agent is turned OFF via Quick Agent Control, inbound SIP calls still "answer" — the agent picks up, plays an unavailability message ("Our AI assistant is currently unavailable. You can reach us at..."), then hangs up.

Sam wants: calls forwarded directly to the real business phone number (from Company Info) instead of the agent picking up at all.

---

## Desired Behaviour

| Condition | Behaviour |
|---|---|
| Agent OFF + business phone set + real SIP call | Brief hold message → SIP REFER to business phone |
| Agent OFF + no business phone set | Current behaviour: unavailability message + hang up |
| Agent OFF + web test call (not SIP) | Current behaviour: unavailability message + hang up |
| Agent ON | No change |

---

## Implementation

**File:** `agent/agent.py` — `agent_inactive` block (~line 1714)

**What changes:**
Replace the flat "unavailable" message+disconnect with a branch:

```
if agent_inactive:
    fetch business phone from DB (already done)
    normalize phone to E.164

    if is_sip_call AND _biz_phone:
        session.generate_reply("Thank you for calling [business name]. Please hold while we connect you.")
        await asyncio.sleep(2)   # let TTS finish
        TransferSIPParticipantRequest(
            room_name=ctx.room.name,
            participant_identity=participant.identity,
            transfer_to=f"tel:{_biz_phone_e164}"
        )
        await asyncio.sleep(1)
        ctx.room.disconnect()
        return

    else:
        # No phone set, or web test call — current behaviour
        session.generate_reply("unavailable message...")
        await asyncio.sleep(5)
        ctx.room.disconnect()
        return
```

**No new packages required.** Uses existing:
- `livekit.api.LiveKitAPI` (already imported in `forward_call`)
- `livekit.protocol.sip.TransferSIPParticipantRequest` (already imported in `forward_call`)
- `_normalize_phone_e164()` (module-level helper, already used elsewhere)

---

## What's Already Available in Scope

At the `agent_inactive` checkpoint, the entrypoint already has:
- `is_sip_call` — bool, set at line ~1441
- `participant.identity` — the SIP participant identity for the REFER
- `ctx.room.name` — room name for the REFER
- `supabase`, `business_id` — for fetching business phone
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` — in env

---

## Hold Message

```
"Thank you for calling [business name]. Please hold while we connect you."
```

Uses `_biz_name` fetched alongside `_biz_phone` (same DB query — already selects `name`).

---

## Error Handling

If the REFER fails (exception from LiveKit API):
- Log the error
- Fall back to: "Our AI assistant is unavailable. You can reach us directly at {phone}." + hang up

---

## What This Does NOT Change

- Agent ON behaviour — unchanged
- Web test call behaviour — unchanged  
- The "unavailability" path for locations with no business phone — unchanged
- Any DB writes / call records — no new writes needed (transfer for inactive call, not a tracked call)

---

## Testing

1. Set agent OFF in Quick Agent Control
2. Call the SIP number from a real phone
3. Expected: hear "Thank you for calling [name], please hold" → phone starts ringing on business number
4. Expected fallback: remove business phone from Company Info → agent says unavailability message instead
5. Web test call with agent OFF → should still get unavailability message (not a SIP call)
