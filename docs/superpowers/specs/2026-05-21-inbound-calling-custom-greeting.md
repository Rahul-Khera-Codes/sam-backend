# Custom Greeting Message for Inbound Calling — Design Spec

**Date:** 2026-05-21
**Status:** Approved

---

## What We're Building

Add a pencil/edit button next to the "Inbound Calling" toggle in Agent Settings so a custom greeting message can be saved and used by the agent at the start of every inbound call.

---

## Current Behaviour

`prompt_builder.build_instructions()` always generates this hardcoded welcome block:

```
You are the AI phone receptionist for {business_name} in {city, province}.
Always start the call with a short, friendly welcome that includes the business name and the location.
Example: "Thank you for calling {business_name} in {city, province}, how can I help you today?"
Then continue the conversation following these rules:
```

The agent uses the example as a style guide. There is no way for the client to customise it.

---

## Desired Behaviour

- When no custom greeting is set → current behaviour unchanged.
- When a custom greeting is saved → replace the entire welcome instruction block with:
  ```
  You are the AI phone receptionist for {business_name}.
  Start the call with this greeting: "{custom_greeting}"
  Then continue the conversation following these rules:
  ```
  The persona line stays. The generic instruction and the hardcoded example are dropped entirely.

---

## Data Storage

No DB migration needed. The `agent_settings` table already has a `config_value JSONB` column per feature key.

The custom greeting is stored as:

```json
{ "greeting_message": "Hey, thanks for calling Downtown Barber Shop — how can I help?" }
```

…under feature key `inbound_calling`.

Clearing the field (empty string or null) reverts to the default behaviour.

---

## Layers Touched

| Layer | File | Change |
|---|---|---|
| Agent — prompt | `agent/prompt_builder.py` | Accept optional `custom_greeting` param; swap welcome block when set |
| Agent — session start | `agent/agent.py` | Read `inbound_calling` config_value before calling `build_instructions`; pass `custom_greeting` |
| Frontend — settings page | `ai-employees-app/src/pages/dashboard/customer-service/AgentSettings.tsx` | Add greeting dialog state + Dialog UI; wire `onEdit` on inbound_calling row |

---

## Frontend Dialog Design

- Separate dialog from the existing SMS/call template dialog (different state vars, different description text)
- Title: **"Custom Greeting Message"**
- Description: *"Write the exact greeting your agent will say at the start of every inbound call. Leave blank to use the default."*
- Single `<Textarea>` — no days input, no placeholder reference table (greeting is freeform)
- Save button calls `updateAgentSettings` with `config_value: { greeting_message: text.trim() || null }`
- Cancel / X resets to the last saved value

---

## Constraints

- `build_instructions` already creates its own `supabase` client internally. Rather than threading the client up, `agent.py` will read config_value using its own already-initialised `supabase` client before calling `build_instructions`, then pass the string in.
- The greeting is location-scoped: stored per `(business_id, location_id)` like all other agent settings.
- The agent persona line (`You are the AI phone receptionist for {business_name}`) is always preserved — the custom greeting only replaces the instruction/example portion.

---

## Out of Scope

- Placeholder substitution in the greeting (e.g. `{{business_name}}`) — not in this release
- Outbound call greeting — separate feature key, not touched here
- Audit log entry for config_value changes — audit log only fires on is_enabled changes (existing behaviour, not changed)
