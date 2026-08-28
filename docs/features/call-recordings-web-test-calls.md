# Call Recordings — Web Test Calls (AIE-37, AIE-38)

## What it does
The Customer Service Employee (CSE) "Call Recordings" page lists calls by direction
(Inbound/Outbound) and status (active/completed/missed/etc.). Real phone calls get both of these
"for free" from LiveKit's SIP integration — direction comes from the `sip.callDirection`
participant attribute set by the trunk, and call teardown is driven by an actual SIP BYE the
carrier sends, which LiveKit turns into a real, server-observed participant disconnect.

The "Test with Web Call" button (Phone Numbers page) has neither guarantee — it's a generic
browser-to-LiveKit-room flow (`POST /calls/initiate`), not a SIP call, so both direction and
disconnect had to be handled correctly by application code instead. They weren't:

- **AIE-37** — every web test call was hardcoded to `direction: "outbound"`, so it always showed
  under the Outbound tab even though a test call simulates a customer calling in.
- **AIE-38** — if the browser's microphone was denied/disabled, the frontend left the LiveKit room
  connection open with no client-side handle to close it. Since nothing server-side was watching
  for this, the call stayed `status: "active"` forever with an empty transcript.

## Key files
**Frontend (ai-employees-app)**
- `src/hooks/useWebAgentCall.ts` — `startWebCall`/`joinRoom`. `startWebCall` builds the
  `InitiateCallRequest` sent to the backend (now `direction: "inbound"`, previously hardcoded
  `"outbound"`). `joinRoom`'s catch block (triggered when `setMicrophoneEnabled(true)` throws on
  mic denial) now calls `room.disconnect()` before dropping the `roomRef` handle, so LiveKit sees
  a genuine participant disconnect instead of an orphaned room.
- `src/pages/dashboard/PhoneNumbers.tsx` — "Test with Web Call" button, calls `startWebCall`.
- `src/pages/dashboard/customer-service/CallRecordings.tsx` — Inbound/Outbound tab filtering on
  `calls.direction`.

**Backend (sam-backend)**
- `backend/app/schemas/calls.py` — `InitiateCallRequest.direction` default changed from
  `CallDirection.outbound` to `CallDirection.inbound`.
- `backend/app/routers/calls.py`
  - `POST /calls/initiate` — writes `body.direction` verbatim to the `calls` row and into the
    agent-dispatch metadata (`call_direction`), unchanged; the fix is upstream of this endpoint.
  - `POST /calls/webhook` (new) — LiveKit Cloud webhook receiver, verified via
    `livekit.api.WebhookReceiver`/`TokenVerifier` (same `livekit_api_key`/`livekit_api_secret`
    pair used everywhere else in `livekit_service.py`; confirmed against the installed
    `livekit-api==1.1.0` SDK — no new secret needed). Listens for `room_finished` and
    force-finalizes any `calls` row still in a non-terminal status for that room: looks up
    whether any `transcripts` rows exist for the call to decide `missed` vs `completed` (same
    rule as `agent.py::_finalize_call`), then sets `status`/`ended_at`/`duration_seconds`. No-ops
    if the call is already terminal (`completed`/`forwarded`/`failed`/`missed`).
- `agent/agent.py`
  - `_finalize_call` (~line 1415) — the **primary** finalize path, unchanged. Runs when the
    agent's own `participant_disconnected` room listener fires (`caller_left.wait()` at
    ~line 1878). This is what normally finalizes a call within moments of the user actually
    disconnecting.
  - `call_direction`-based branching (~line 1862: greet-first vs. outbound framing; ~line 1443:
    `is_missed = direction == "inbound" and not transcript_log`) — no code change, but both now
    behave correctly for web test calls now that `direction` is `"inbound"`.

## Decisions / tradeoffs
- **`direction` default changed in place rather than made required.** Considered making
  `InitiateCallRequest.direction` a required field (no default) so no future caller of
  `/calls/initiate` could silently default to the wrong value. Went with changing the default to
  `inbound` instead, since only one caller of this endpoint was found (`useWebAgentCall.ts`) and
  a required field would be a breaking change for any other untracked caller.
- **Webhook is a backstop, not a replacement for `agent.py`'s in-process finalize.** The normal
  path (user disconnects → LiveKit fires `participant_disconnected` → agent finalizes
  immediately) is unchanged and still does the real work, including transcript persistence and
  missed-call SMS. The webhook only exists to bound how long a call can be stuck `active` when
  that in-process path never fires for any reason (agent crash, network partition, a future
  client bug) — it fires on `room_finished`, which LiveKit emits once the room has been empty for
  `empty_timeout` (300s, `livekit_service.py::create_room`). The webhook does **not** duplicate
  transcript persistence or missed-call SMS — by the time `room_finished` fires, either the agent
  already finalized normally (webhook no-ops), or there's nothing left to persist (agent died
  before writing anything).
- **No new secret added.** LiveKit Cloud signs webhook payloads with the same API key/secret pair
  already used for every other LiveKit API call in this backend — `TokenVerifier` just reuses
  `settings.livekit_api_key`/`settings.livekit_api_secret`.
- **Route has no `Depends(get_user_id)`.** Confirmed no global auth middleware exists (auth is
  per-route only, `app/main.py`), so `/calls/webhook` is intentionally public — LiveKit
  authenticates itself via the signed `Authorization` header, verified inside the handler.
  Verified live: an unsigned POST returns `401 Invalid webhook signature` rather than crashing.

## Outstanding manual step
The webhook endpoint (`POST /calls/webhook`) still needs to be registered in the LiveKit Cloud
dashboard (Settings → Webhooks → Add endpoint) pointing at the deployed backend's public URL —
this can't be done from the codebase/CLI, requires LiveKit Cloud dashboard access, and needs the
production backend's public URL (only `localhost:8003` exists in the dev `.env`).
