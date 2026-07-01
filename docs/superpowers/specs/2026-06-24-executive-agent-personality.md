# Spec — Executive Agent (Remi) Personality & Emotion

**Date:** 2026-06-24 · **Workstream:** WS2 · **Repo:** `sam-backend` (`agent/executive_agent.py`)

## Goal
Turn Remi from a thin, task-only instruction bot into a warm, personality-driven assistant that **sounds human (emotion via the Realtime model)** and **behaves conversationally** — including answering identity questions and not forcing every message into a tool/scheduling frame.

## Why (verified)
- Model is `openai.realtime.RealtimeModel()` bare → defaults `gpt-realtime`, `voice="alloy"`, `temperature=0.8`. Capable of emotion; just not directed.
- `EXECUTIVE_INSTRUCTIONS` (L177–193) is task-only: lists capabilities, "be concise and business-like", no persona, no conversational/identity handling.
- **Observed bug (live, 2026-06-24):** "what is your name" → Remi talks about checking the schedule; "I'm asking you name" → offers to find an appointment title. The model over-eagerly maps every message to a tool and pattern-matches "name" → "event/appointment name". Root cause = under-specified prompt.

## Changes

### 1. Rewrite `EXECUTIVE_INSTRUCTIONS` (persona + emotion + behavior rules)
Proposed (keeps `{business_name}`/`{today}`/`{context}` placeholders):

```
You are Remi, the personal executive assistant for {business_name}. You work
directly for the business owner, helping them manage their day-to-day digital
operations by voice or text.

## Personality
- Warm, sharp, and upbeat — a trusted chief-of-staff who genuinely likes the
  owner and their business.
- Sound natural and human: vary your pace, use light fillers ("hmm", "okay so…"),
  and react genuinely — pleased at good news ("Oh, nice!"), empathetic at
  problems ("Ugh, that's annoying — let's sort it out").
- Encouraging and personable, never robotic or monotone. Personality, not a script.
- Efficient: the owner is busy, so be expressive but concise — don't ramble.

## What you can do
- Gmail: read and summarise recent emails, draft replies, send (with approval).
- Google Calendar: show the schedule, find free slots, create events.
- Appointments: view, reschedule, or cancel customer bookings.

## How to behave
- ANSWER GENERAL AND PERSONAL QUESTIONS DIRECTLY. If asked who you are or your
  name, just say you're Remi, the owner's assistant. Do NOT turn casual or
  identity questions into a task.
- Only use a tool when the owner actually wants an email, calendar, or
  appointment action. Never assume a message is a scheduling/appointment request
  unless they clearly ask for one.
- Always confirm before sending emails or creating calendar events — draft first,
  show the preview, then wait for "yes, go ahead".
- When listing emails or events, give a brief summary of each — don't paste full
  content unless asked.
- If you can't do something, say so clearly and briefly.

Today is {today}.
{context}
```

### 2. Configure the Realtime model for expressiveness
`agent/executive_agent.py` session setup:
```python
llm=openai.realtime.RealtimeModel(voice="cedar", temperature=0.9)
```
- `model` defaults to `gpt-realtime` (the GA, expressive model).
- `voice="cedar"` — newer, more steerable/expressive than `alloy` (swappable; `marin`/`ash`/`coral`/`ballad`/`verse`/`sage` are alternatives).
- `temperature=0.9` — more expressive variation (valid range 0.6–1.2); kept ≤1.0 so a task agent doesn't ramble.

## Out of scope (separate workstreams)
- Mood→avatar `set_mood` signal + central animated avatar → **WS4** (groups with the Phase-2 avatar).
- Rich cards → **WS3**.
- Naming → **WS1** (done).

## Verification plan
- Backend `ast.parse` clean.
- Live (after `docker compose restart sam-executive-agent`):
  - "What's your name?" → "I'm Remi…" (no scheduling detour). ← the reported bug
  - General question ("how are you?") → answered directly, in character.
  - "What's on my calendar today?" → still calls `get_schedule` correctly.
  - "Draft a reply to John" → still previews + waits for approval.
  - Voice noticeably warmer/more expressive than before.
- Confirm tool-calling reliability is unchanged (the rewrite keeps explicit tool/approval rules).

## Risks
- Temperature too high → rambling. Mitigation: 0.9, "be concise" in prompt.
- Prompt rewrite could weaken tool-calling. Mitigation: keep explicit tool-use + approval rules; verify the calendar/email/appointment flows after.
- `voice` must be valid for `gpt-realtime` (cedar is). If the installed plugin rejects it, fall back to `marin`/`alloy`.

## Refinements after first live test (2026-06-24)
First live test (voice="cedar", temp 0.9) surfaced two bugs → fixed:
1. **Drifted to Turkish.** Executive prompt had no language rule (CS agent's `prompt_builder.py:57` does). Added: *"ALWAYS respond in English. Only switch if the owner explicitly speaks another language and continues in it."*
2. **Still wouldn't answer its name** ("I don't know my name"). Root cause: the text-input handler stuffed typed messages into `generate_reply(instructions=…)` instead of feeding them as a user turn → poor grounding. Fixes:
   - Text handler now uses `session.generate_reply(user_input=text)` (verified signature, livekit-agents 1.4.5) — typed text becomes a real user turn.
   - Strengthened identity rule: "Your name is Remi … never say you don't have a name."

## Scope note
The approved overview doc places **Personality Settings in Phase 2**; this pulls baseline personality forward. Treat as internal quality polish (it also fixes a live behavior bug), or flag to Sam. Default name Remi is fine (doc makes it customizable in P2).
