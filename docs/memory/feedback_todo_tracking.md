---
name: Always track TODO.md — update after EVERY commit
description: Update TODO.md immediately after each feature/fix commit, never batch. User flagged this twice in session 28.
type: feedback
originSessionId: cc057c43-e7e5-4341-8ce4-dba7c41b2ce6
---
Update TODO.md after EVERY feature/fix commit, not in batches. The user flagged this twice in session 28: "before are updating the todo list on regular basis" and "are you updating todo regularly?" — both times 2-3 features had accumulated without an update.

**Why:** The user uses TODO.md as the source of truth for what's done, what's open, and what needs manual action (migrations, deploys). Stale TODO means they don't know what to run or test.

**How to apply:**
- Session start: read TODO.md + `docs/SESSION_HANDOFF.md` before doing anything
- After EVERY `git commit` that ships a feature or fix: update TODO.md in the same or next commit
- Don't wait for the user to ask — do it proactively
- When starting a task: mark it as in progress
- When finishing a task: mark as completed, move to Done section
- When discovering new bugs or tasks: add them immediately
- Session end: update the "Last updated" line with the date and session summary
