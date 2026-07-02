# Exec Agent — Remove Business Name from Greeting
**Date:** 2026-07-02
**Branch:** `feature/exec-agent-improvements`
**Status:** Spec approved — pending implementation

---

## Request (Sam, Jul 1, item #2)

"When you start a session change the first message to only say 'Hi, I'm Remi—how can I help you today?' Remove the company name from the hello message."

---

## Phase 1 — Verified

`agent/executive_agent.py:1224-1231` — the greeting is generated via `session.generate_reply(instructions=...)` at session start, with a model-instruction template that includes `{business_name}`:

```python
await session.generate_reply(
    instructions=(
        f"Greet the business owner warmly and introduce yourself by name. Say something like: "
        f"'Hi, I'm Remi — how can I help you with {business_name} today?' "
        "Keep it very short — one sentence."
    )
)
```

This is the only greeting instruction in the file — no other path generates the opening line.

---

## Phase 2 — Spec

### File changed
Only `agent/executive_agent.py`, the greeting instruction string (L1228). Drop `with {business_name}` from the example line.

### Not changed
`EXECUTIVE_INSTRUCTIONS`'s identity rule (L200: `"I'm Remi, your assistant for {business_name}"`) — that's the answer to "what's your name," a separate, already-correct behavior. Sam's request is specifically about the opening hello, not identity questions in general.

### Impact
Cosmetic prompt change only. No other flow touches this instruction.

### Risk
None identified.

---

## Commit Plan

| # | Commit | Files |
|---|---|---|
| 1 | `fix(exec-agent): drop business name from the opening greeting` | `executive_agent.py` |
