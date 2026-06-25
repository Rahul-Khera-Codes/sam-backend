# Executive Agent — Build Plan

**Date:** 2026-06-22  
**Status:** Ready to build — UI layout confirmed, all decisions locked  
**Reference doc:** `docs/executive-agent-overview.md` (product overview sent to Sam)

---

## What It Is (in one sentence)

A browser-based AI assistant the business owner talks to inside the portal — takes real actions on their Gmail, Google Calendar, and appointments via voice or text.

---

## How It Works End-to-End

```
Owner opens /dashboard/executive-agent
        ↓
Browser calls POST /executive/session → gets LiveKit room + token
        ↓
Browser joins LiveKit room via WebRTC (text-only by default)
        ↓
Executive Agent (Python, LiveKit Agents) joins the same room
        ↓
Owner types or speaks → agent transcribes / reads message
        ↓
Agent decides: tool call or verbal reply
        ↓
Tool actions hit Gmail API / Calendar API / Supabase directly
        ↓
Agent sends state signal via LiveKit data message (thinking/speaking/idle)
        ↓
Agent speaks result → UI updates avatar state in real time
        ↓
For writes/sends: agent shows preview in left panel, waits for approval
```

---

## UI Layout — Confirmed

### Split layout: left fixed, right collapsible

```
┌────────────────────────────────────┬─────────────────────┐
│  Agent Name  ···  [transcript ⓘ]  │  Transcript          │
│────────────────────────────────────│─────────────────────│
│                                    │  You                │
│                                    │  "Book Friday 2pm"  │
│  Agent's current response          │                     │
│  displayed here as it streams.     │  Agent              │
│                                    │  "Done — Friday     │
│  (No user bubbles — left side is   │   2–3 PM created"   │
│   agent-focused display only)      │                     │
│                                    │  You                │
│                                    │  "Show my emails"   │
│────────────────────────────────────│                     │
│  [ Message...           ]  🎤  ▶  │                     │
└────────────────────────────────────┴─────────────────────┘
                                           ↑ collapsible
                                    toggle via ⓘ icon in header
```

### Left panel — agent interface
- **Header:** Agent name + animated status indicator + transcript toggle icon (top-right)
- **Main area:** Agent's responses displayed as they stream in. Clean, focused — no user bubbles cluttering it.
- **Input bar (bottom):**  `[ Message...  ]  🎤  ▶`
  - Text field (primary, always active)
  - Mic toggle icon — enables/disables voice in the same session. No reconnect. Uses `localParticipant.setMicrophoneEnabled(true/false)` on existing LiveKit room.
  - Send button

### Right panel — transcript (collapsible)
- Full back-and-forth conversation: both user turns and agent turns as chat bubbles
- Streams in real-time as the conversation happens
- Toggle: ⓘ icon in the left panel header slides the panel in/out
- When collapsed: panel disappears, more space for agent display

---

## Agent State Machine — Confirmed

State is driven by **LiveKit data messages** from the agent (not inferred from audio).  
The agent calls `room.local_participant.publish_data({state: "thinking"})` etc.

| State | Header indicator | Main area behavior |
|---|---|---|
| **Idle** | `Agent Name` (static) | Last response stays visible |
| **Listening** | `Agent Name 🎤` (mic pulse) | Subtle "Listening…" hint |
| **Thinking** | `Agent Name ···` (animated dots, like Dex) | Typing/thinking animation |
| **Speaking** | `Agent Name ▌▌▌` (waveform bars) | Text streams in as agent speaks |

Agent sends state messages at these exact transitions:
- Before processing a tool call → `{state: "thinking"}`
- Before speaking a reply → `{state: "speaking"}`
- After reply finishes → `{state: "idle"}`

---

## Mic Toggle — No Reconnection

Default mode: **text only**. LiveKit session starts with mic disabled.  
Mic click: `localParticipant.setMicrophoneEnabled(true)` on the existing room — same connection, no new token.  
Mic toggle again: `setMicrophoneEnabled(false)` — returns to text-only mode.  
When mic is ON: mic icon glows/pulses, agent state switches to "Listening" while local audio detected.

---

## What Needs to Be Built

### 1. Backend — session endpoint (`backend/app/routers/executive.py`)

```python
POST /executive/session
  body: { business_id: str }
  → verify_business_access(user_id, business_id)
  → create LiveKit room: "executive-{business_id}-{uuid4()[:8]}"
  → generate participant token (identity="owner-{user_id}")
  → return { room_name, token, livekit_url }
```

Room metadata: `{business_id, session_type: "executive"}`  
Agent picks this up on room join — knows it's an executive session, not a customer call.

Register in `main.py`: `app.include_router(executive_router.router, prefix="/executive", tags=["executive"])`

---

### 2. Agent — `agent/executive_agent.py` (new file)

Separate from `agent.py` (customer-facing) — different tools, different prompt, different session type.

**Session start:**
- Read `business_id` from room metadata
- Fetch: business name, Gmail token for location, Calendar tokens, business timezone
- Send state: `{state: "idle"}`
- Greet: *"Hi [name], I'm ready. What would you like to do?"*

**State signalling helper:**
```python
async def _send_state(ctx, state: str):
    await ctx.room.local_participant.publish_data(
        json.dumps({"state": state}).encode(),
        reliable=True
    )
```
Called before every tool execution and reply.

**Tools — Gmail:**
- `list_emails(limit=10, from_filter=None)` — Gmail API `messages.list` + `messages.get` for each; returns subject/from/date/snippet
- `read_email(email_id)` — full body decode (multipart text/plain first, fallback html stripped)
- `draft_reply(email_id, body)` — stores draft in agent memory, sends to frontend as a preview data message `{type: "preview", kind: "email_draft", ...}`. Does NOT send. Waits for owner to say "yes" / "send it" / "go ahead".
- `send_email(to, subject, body)` — only called after owner approves a draft. Uses existing `email_service.py` Gmail send.

**Tools — Google Calendar:**
- `get_schedule(date_range="today")` — Calendar API events.list for date range; returns title/time/attendees
- `create_event(title, date, time, duration_minutes, description=None)` — creates on owner's primary calendar. Shows preview first.
- `reschedule_event(event_id_or_title, new_date, new_time)` — patches existing event
- `find_free_slots(date, duration_minutes=60)` — fetch all events for day, compute gaps

**Tools — Appointments:**
- `list_appointments(date_range="upcoming", status=None)` — reads `appointments` table for business
- `cancel_appointment(appointment_ref)` — reuses existing cancel logic from `agent.py`
- `reschedule_appointment(appointment_ref, new_date, new_time)` — reuses existing reschedule logic

**Approval flow:**
When draft_reply or create_event is called, agent:
1. Sends `{type: "preview", ...}` via data channel → frontend shows preview panel in left area
2. Says verbally: *"I've drafted a reply — take a look and let me know if I should send it."*
3. Waits for owner: "yes / send it / looks good" → executes send. "Change X" → modifies and re-previews. "Cancel" → discards.

---

### 3. Frontend — `ExecutiveAgent.tsx`

**Route:** `/dashboard/executive-agent` (replaces existing Coming Soon placeholder)

**Files:**
- `src/pages/dashboard/ExecutiveAgent.tsx` — main page
- `src/components/executive/AgentStatusHeader.tsx` — name + state indicator + transcript toggle
- `src/components/executive/AgentDisplay.tsx` — streaming response display + preview panel
- `src/components/executive/TranscriptPanel.tsx` — right collapsible panel
- `src/components/executive/InputBar.tsx` — text field + mic toggle + send
- `src/hooks/useExecutiveSession.ts` — LiveKit connection, state tracking, transcript

**`useExecutiveSession` hook:**
```typescript
// Calls POST /executive/session, connects to LiveKit room
// Manages: agentState, transcript[], previewItem, isMicEnabled
// Listens for:
//   - data messages → {state} updates agentState; {type:"preview"} shows preview
//   - transcription segments → appends to transcript[]
//   - remote audio track → drives isSpeaking
// Exposes:
//   - sendMessage(text: string) — sends via LiveKit chat
//   - toggleMic() — setMicrophoneEnabled(true/false), no reconnect
//   - agentState: "idle" | "listening" | "thinking" | "speaking"
//   - transcript: {role, text, timestamp}[]
//   - previewItem: EmailDraft | CalendarEvent | null
//   - approvePreview() / rejectPreview(feedback?)
```

**State indicator animations (CSS only, no library):**
- **Idle:** static dot
- **Listening:** dot pulses gently (scale 1 → 1.2 → 1, 1.5s loop)  
- **Thinking:** three dots animate in sequence (···, like iMessage typing indicator)
- **Speaking:** 3 vertical bars animate height (waveform, staggered timing)

**Preview panel** (inside left main area, above input bar, shown when `previewItem` is set):
```
┌──────────────────────────────────────┐
│ 📧 Draft reply to: john@example.com  │
│ "Hi John, thanks for reaching out…"  │
│                                      │
│  [Cancel]          [Send Reply ▶]    │
└──────────────────────────────────────┘
```

---

### 4. voiceAgentApi.ts additions

```typescript
export interface ExecutiveSessionResponse {
  room_name: string;
  token: string;
  livekit_url: string;
}

export async function createExecutiveSession(
  token: string,
  businessId: string,
): Promise<ExecutiveSessionResponse>
```

---

### 5. Billing toggle (deferred — free during beta)

- Add "Executive Agent" card to Billing page — Phase 2
- For now: feature accessible to all admins, no gate

---

## Build Sequence

| Step | Task | Est. |
|---|---|---|
| 1 | `POST /executive/session` backend endpoint | 0.5 day |
| 2 | `createExecutiveSession()` in voiceAgentApi.ts + `useExecutiveSession` hook skeleton | 0.5 day |
| 3 | `ExecutiveAgent.tsx` page + layout + `AgentStatusHeader` + `TranscriptPanel` + `InputBar` | 1 day |
| 4 | State indicator animations (CSS, 3 states) | 0.5 day |
| 5 | `executive_agent.py` — session start, state signalling, Gmail read tools | 1.5 days |
| 6 | Gmail draft/send + preview panel (frontend + agent) | 1.5 days |
| 7 | Calendar tools (get_schedule, create_event, find_free_slots) | 1 day |
| 8 | Appointments tools (list, cancel, reschedule) | 0.5 day |
| **Total** | | **~7 days** |

**Milestone after Step 4:** Page opens, agent connects, text input works, mic toggle works, state animates — no tools yet but fully demo-able.

---

## Key Decisions — All Confirmed

| Decision | Choice |
|---|---|
| Avatar style | Chat-style interface (like Dex sample) — agent name + status indicator. No 3D avatar for Phase 1. |
| Mic default | Text-only. Mic toggle enables voice in same session — no reconnect. |
| State signalling | Agent sends LiveKit data messages — not inferred from audio gaps. |
| Approval flow | Both verbal ("send it") and button click in preview panel. |
| Right panel collapse | Toggle via ⓘ icon in left panel header. Smooth slide. |
| Who can access | All admins on the business (no extra gate for Phase 1). |
| Billing | Free during development. Toggle added to Billing page in Phase 2. |
| Transcript persistence | Session-only for Phase 1. No cross-session history. |

---

## What We Reuse

| Existing piece | How used |
|---|---|
| `gmail_tokens` table + `email_service.py` | Same token refresh + send logic |
| `google_calendar_tokens` table + `gcal_helpers.py` | Same token refresh + event CRUD |
| LiveKit Agents framework (`agent.py` pattern) | Same session pattern, different tools |
| `@livekit/components-react` browser SDK | Already in project — used for web test calls |
| `verify_business_access()` | Same auth on `/executive/session` |
| `appointments` table Supabase reads | Direct reads, same as existing agent |
