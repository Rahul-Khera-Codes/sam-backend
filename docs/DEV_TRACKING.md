# Development Tracking System

This document explains how development progress, decisions, bugs, and context are tracked across sessions for this project.

---

## The Problem It Solves

Claude Code has no persistent memory between conversations by default. Every new session starts cold — no knowledge of what was built, what broke, what the client said, or what's next. This tracking system is the solution: a structured set of files that give any new session full context within the first few minutes.

---

## Overview of the System

```
sam-backend/
├── TODO.md                          ← authoritative task list
├── docs/
│   ├── SESSION_HANDOFF.md           ← full current state (read every session)
│   ├── CLIENT_COMMS_LOG.md          ← client decisions + bug reports
│   └── superpowers/plans/           ← implementation plans for multi-step features
│
└── (sibling) ai-employees-app/      ← frontend repo

~/.claude/projects/.../memory/
├── MEMORY.md                        ← index of all memory files
├── project_voice_agent.md           ← architecture, what's working, branches
├── project_blockers.md              ← what's blocked, who owns it, what's next
├── feedback_todo_tracking.md        ← how Claude should behave (session rules)
└── feedback_api_performance.md      ← performance observations
```

---

## Layer 1: Session Handoff (`docs/SESSION_HANDOFF.md`)

**What it is:** The single most important file. Read at the start of every session.

**What it contains:**
- Quick start commands (docker, logs)
- Current active branches and their status
- System status — what's working end-to-end, what's blocked
- Infrastructure (ports, env file locations)
- Test business IDs (business_id, location_ids, staff user_ids)
- Architecture overview (agent context resolution, key patterns)
- Key file map (which file does what)
- Pending manual steps (migrations to run, deploys to do)
- Applied migrations log
- **"What Was Done This Session"** block — rewritten at the end of every session to summarise the current session's work

**Who updates it:** Claude, at the end of every session (required).

**Example of what gets logged:**
```
## What Was Done This Session (Session 42, 2026-05-12)
Code review of feature/billing-section. 3 critical issues found and fixed:
- Pro/Professional naming mismatch
- .env.example wrong variable names
- Billing metric was call count not minutes
```

---

## Layer 2: TODO Tracker (`TODO.md`)

**What it is:** The authoritative task list covering both repos.

**Structure:**
- `✅ Done` — completed work, organised by feature/session
- `🔄 In Progress` — active work + manual steps still needed
- `📋 TODO` — planned but not started

**Rules:**
- Mark tasks **in progress** when starting them
- Mark tasks **completed** immediately when done
- Add new tasks as bugs or work are discovered
- Update `Last updated` line at end of every session

**Why it matters:** It's the record of what was built and when. Without it, it's impossible to know if a feature was intentionally skipped or just forgotten.

---

## Layer 3: Persistent Memory (`~/.claude/projects/.../memory/`)

Memory files persist across all conversations. They're loaded automatically at session start via `MEMORY.md` (the index).

### `MEMORY.md` — Index
One-line entry per memory file. Always loaded into context. Tells Claude what memories exist and what each one is about.

### `project_voice_agent.md` — Project Overview
- Current active branches and their status
- What's working end-to-end
- Open bugs
- Blocked items
- Test business IDs
- Key architecture decisions
- Pending manual steps

Updated every session to reflect current state.

### `project_blockers.md` — Blockers & Pending Actions
The most action-oriented file. Answers: *what should I work on next and what's in the way?*

Sections:
- **Blocked on client/external** — things waiting on Sam or third parties
- **Pending code work** — features/fixes in progress
- **Pending QA** — tests that require a live environment
- **Future** — planned but not started

Updated to remove resolved blockers and add new ones every session.

### `feedback_todo_tracking.md` — Behavioural Rules
Rules for how Claude should behave in this project:
- Always check TODO.md + SESSION_HANDOFF.md at session start
- Mark tasks in progress when starting, completed when done
- Update docs before ending the session

This prevents Claude from forgetting session discipline across conversations.

### `feedback_api_performance.md` — Performance Notes
Observations like "backend creation ops take >2–3s — Playwright tests need ≥5s waits." Prevents re-discovering the same issues.

---

## Layer 4: Client Communications Log (`docs/CLIENT_COMMS_LOG.md`)

**What it is:** A running log of everything the client (Sam Maisuria) says — decisions, requests, bug reports, and clarifications.

**Format:** One entry per date, newest at top. Each entry has:
- Context (what prompted the message)
- What was said / decided
- Status (✅ Done / ⏳ Pending / 🔄 In Progress)

**Why it matters:** Decisions made in Slack or voice calls get forgotten. This log means we never have to re-ask "did Sam confirm this?" or "what did he say about billing?"

**Example entry:**
```
## 2026-05-12
Bug: AI cannot tell the difference between Voice AI Scheduler and Business Hours.
Root cause confirmed: both read/write the same business_hours table.
Status: ⏳ Awaiting Sam's demo videos.
```

---

## Layer 5: Implementation Plans (`docs/superpowers/plans/`)

**What it is:** Detailed step-by-step plans for multi-step features, created before writing any code.

**Naming:** `YYYY-MM-DD-feature-name.md`

**What a plan contains:**
- Goal (one sentence)
- Architecture decisions
- Exact files to create/modify with line numbers
- Step-by-step tasks with actual code (no placeholders)
- Verification commands with expected output
- Commit instructions

**How it's used:** Plans are executed by subagents (one per task) with spec compliance + code quality review after each task. This prevents context pollution and catches issues early.

**Current plans:**
- `2026-05-12-billing-section-fixes.md` — 3 critical billing fixes (completed this session)

---

## Session Start Checklist

Every session begins with:
1. Read `TODO.md` — what's done, in progress, pending
2. Read `docs/SESSION_HANDOFF.md` — full current system state
3. Read memory files — blockers, project state, behavioural rules

This takes ~2 minutes and means no time is wasted re-investigating things already resolved.

---

## Session End Checklist

Every session ends with:
1. Update `docs/SESSION_HANDOFF.md` — rewrite "What Was Done This Session"
2. Update `memory/project_voice_agent.md` — keep "What's Working" and branches current
3. Update `memory/project_blockers.md` — remove resolved, add new
4. Update `TODO.md` — mark completed tasks, add new discoveries

---

## How a Bug Gets Tracked

1. **Discovered** — added to `TODO.md` under 🔄 In Progress or 📋 TODO
2. **Client-reported** — logged in `CLIENT_COMMS_LOG.md` with root cause notes
3. **Blocking** — added to `memory/project_blockers.md`
4. **Fixed** — marked ✅ in `TODO.md`, removed from blockers, noted in SESSION_HANDOFF

---

## How a Feature Gets Built

1. **Client request** → logged in `CLIENT_COMMS_LOG.md`
2. **Plan written** → `docs/superpowers/plans/YYYY-MM-DD-feature.md`
3. **Subagents execute tasks** → one subagent per task, reviewed after each
4. **Tests pass** → committed to feature branch
5. **Branch reviewed** → code review before merge
6. **Merged** → SESSION_HANDOFF + TODO + memory updated

---

## File Ownership Summary

| File | Updated by | Frequency |
|---|---|---|
| `TODO.md` | Claude | Every session + as tasks complete |
| `docs/SESSION_HANDOFF.md` | Claude | End of every session |
| `docs/CLIENT_COMMS_LOG.md` | Claude | When client sends messages |
| `memory/project_voice_agent.md` | Claude | End of every session |
| `memory/project_blockers.md` | Claude | End of every session |
| `memory/feedback_*.md` | Claude | When user corrects behaviour |
| `docs/superpowers/plans/*.md` | Claude | Before implementing a feature |
