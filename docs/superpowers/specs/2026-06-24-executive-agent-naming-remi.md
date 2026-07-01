# Spec — Executive Agent Persona Name: "Remi"

**Date:** 2026-06-24 · **Workstream:** WS1 (Naming) · **Repos:** `sam-backend`, `ai-employees-app`

## Goal
Give the Executive Agent persona a name — **Remi** — shown consistently wherever the agent represents itself. Keep **"Executive Agent"** as the product/page label.

## Rule
- **Persona "Remi"** → conversational self-identity + agent-identity UI.
- **Product "Executive Agent"** → page chrome, nav, billing, internal/dispatch names (unchanged).

## Verified touchpoints (traced session 52)

**Change → "Remi":**
| File | Line | From | To |
|---|---|---|---|
| `agent/executive_agent.py` | 178 | "You are the Executive Assistant for {business_name}." | "You are Remi, the executive assistant for {business_name}." |
| `agent/executive_agent.py` | 817–823 | greeting "Good morning! How can I help…" | introduces itself as Remi |
| `ai-employees-app/.../executive/AgentStatusHeader.tsx` | 29 | `Executive` | `Remi` |
| `ai-employees-app/.../executive/AgentDisplay.tsx` | 43 | `Executive Agent` (empty-state title) | `Remi` |

**Keep as-is (do NOT change):**
- `ExecutiveAgent.tsx:40` page `<h1>Executive Agent</h1>` — product/nav label.
- `executive_agent.py:647` cancel-note "Cancelled via Executive Agent" — audit record; product label is clearer.
- `EXECUTIVE_AGENT_NAME = "executive-agent"`, `class ExecutiveAssistant`, `async def executive_agent`, module docstring, log lines — internal; renaming `EXECUTIVE_AGENT_NAME` would break dispatch (`/executive/session` + `create_executive_agent_dispatch` reference the exact string).

## Out of scope
Persona prose / emotion / voice / temperature (WS2), cards (WS3), avatar (WS4). This WS is name strings only.

## Verification after implement
- Backend: `ast.parse` clean.
- Frontend: TypeScript still compiles (no type changes — string literals only).
- Manual: status header shows "Remi"; empty state shows "Remi"; greeting says "Remi"; page H1 still "Executive Agent".

## Notes
Default name; the overview doc makes it owner-customizable in Phase 2.
