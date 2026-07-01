# Executive Agent — Personality / Emotion Plan + Test Flows

**Date:** 2026-06-24 (session 52)
**Repo:** `sam-backend` · file: `agent/executive_agent.py`
**Purpose:** (1) how to make the Executive Agent personality-driven with emotion/expressions on the OpenAI Realtime model, and (2) the end-to-end flows for testing.

**Default agent name: Remi** (decided 2026-06-24). The overview doc makes the name owner-customizable in Phase 2; "Remi" is the default. "Executive Agent" remains the product/page label; "Remi" is the persona shown in the agent-identity UI and how it introduces itself.

**Scope note:** The overview doc Sam approved places **Personality Settings in Phase 2**; the Phase-1 avatar is just "3 states." So the persona/emotion polish below pulls personality *forward* of where the doc placed it — treat as internal quality polish or flag to Sam. (Picking the default name Remi is squarely fine.)

---

## Current State (verified in code)

- Both agents call `openai.realtime.RealtimeModel()` **bare** (no args).
- In `livekit-agents 1.4.5` that resolves to defaults: `model="gpt-realtime"` (GA, expressive-capable), `voice="alloy"`, `temperature=0.8`, `modalities=["text","audio"]`.
- The "robotic / instruction-based" feel is **NOT the model** — `gpt-realtime` does emotion well. It's the **prompt**: `EXECUTIVE_INSTRUCTIONS` says *"Be concise and business-like"* with zero persona or emotional direction.
- State signalling exists (`_set_state` → `idle/listening/thinking/speaking`) but there is **no emotion/expression signal** for the avatar.

---

## Making it Personality-Driven (ordered by impact)

### Lever 1 — Persona + emotional direction in the system prompt (≈80% of the effect)
`gpt-realtime` follows voice/emotion stage-direction in the prompt. Add a persona block to `EXECUTIVE_INSTRUCTIONS`:

```
## Personality
Your name is Remi. You're a warm, sharp, upbeat executive assistant — think a
trusted chief-of-staff who genuinely likes the owner and their business.

## Voice & emotion
- Sound natural and human: vary your pace, use light fillers ("hmm", "okay so…"),
  react genuinely — pleased at good news ("Oh, nice!"), empathetic at problems
  ("Ugh, that's frustrating — let's sort it").
- Warm and encouraging, never robotic or monotone. Personality, not a script.
- Still efficient: the owner is busy, so be expressive but don't ramble.
```

### Lever 2 — Expressive voice
`RealtimeModel(voice="cedar")` or `"marin"` (newest, most steerable). `ash`, `coral`, `ballad`, `sage`, `verse` are also far more expressive than the default `alloy`.

### Lever 3 — Temperature
`temperature=0.9` (valid range 0.6–1.2) for more expressive variation. Keep ≤1.0 for a task agent so it doesn't wander.

**Combined config:**
```python
openai.realtime.RealtimeModel(voice="cedar", temperature=0.9)  # model defaults to gpt-realtime
```

### Lever 4 — Visual "expressions" (avatar emotion) — additive feature
Realtime conveys emotion through **voice**, but emits **no emotion signal** for the on-screen avatar. To make the avatar *show* emotion:
- Add a small `set_mood(emotion)` function-tool the model calls (e.g. `happy` / `neutral` / `concerned` / `thinking`).
- It publishes to the frontend exactly like the existing `_set_state` does.
- The avatar renders that mood.

This is the bridge between voice-emotion and visible expression, and the natural on-ramp to the **Phase-2 expressive avatar**. Work = one agent tool + frontend rendering. Recommend scoping it together with the Phase-2 avatar so emotion + expression land together.

### Recommendation
Do **Levers 1–3 now** (small, high-impact). Scope **Lever 4** with the Phase-2 avatar.

---

## Test Flows

**Prereqs:** business has Gmail connected + superadmin Google Calendar connected; timezone set (migration `20260618000000` applied); `sam-executive-agent` restarted after the calendar-create fix.

**Session:** open the Executive Agent page → agent greets → type in the box or toggle the mic to speak → ⓘ toggles the transcript panel.

### Gmail
1. **List** — "Show my recent emails" / "Any emails from John?"
2. **Read** — "Read the one from Sarah"
3. **Draft → approve → send** — "Reply to John that I'll call him tomorrow" → preview appears → "yes, send it" (or "cancel")

### Calendar
4. **Schedule** — "What's on my calendar today?" / "…this week?"
5. **Free slots** — "When am I free Thursday for 30 minutes?"
6. **Create event → approve → confirm** — "Block off Friday 10am for a team meeting" → preview → "yes, go ahead" → creates. *(This is the path fixed session 52 — primary thing to verify.)*

### Appointments (customer bookings)
7. **List** — "What appointments do we have tomorrow?"
8. **Cancel** — "Cancel appointment ABC12345"
9. **Reschedule** — "Move ABC12345 to June 28 at 2pm"

**Approve/reject words:** "yes" / "send it" / "go ahead" to confirm; "cancel" / "no" to discard.

### Known limits while testing (expected, not bugs)
- No Google Calendar *reschedule-event* tool yet (only customer-appointment reschedule).
- No no-show flagging / client-history tools yet.
- Avatar is the minimal status indicator, not an on-screen character (see TODO + overview doc).

---

## Sources
- [LiveKit — OpenAI Realtime API plugin guide](https://docs.livekit.io/agents/models/realtime/plugins/openai/)
- [LiveKit — RealtimeModel Python API reference](https://docs.livekit.io/reference/python/livekit/plugins/openai/realtime/realtime_model.html)
