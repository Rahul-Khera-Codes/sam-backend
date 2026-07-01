# Executive Agent — Product Overview

**Prepared by:** Rahul Khera
**Date:** June 19, 2026
**For:** Sam Maisuria

---

## What Is the Executive Agent?

The Voice Agent answers your customers' calls. The Executive Agent works directly for you — a live AI character you talk to face-to-face in the browser, that takes real actions on the services already connected to your account.

Think of it as a personal AI employee you can have a conversation with. You speak, it listens, it acts.

---

## The Character

The Executive Agent has a visual identity — an animated character that lives on the screen while you talk. It reacts in real time:

| State | What It Looks Like | What's Happening |
|---|---|---|
| **Listening** | Softly pulsing avatar | Microphone is active, waiting for your command |
| **Thinking** | Spinning animation | Processing your request, checking connected services |
| **Speaking** | Wave animation | Responding out loud; results or previews appear alongside |

> **Phase 1** ships with a clean animated avatar showing these three states.
> **Phase 2** adds a more expressive face, customisable appearance, and personality settings the business owner can configure.

---

## How It Works

1. **Open a session** — Click the Executive Agent page in the portal. Your microphone activates and the agent is ready — no setup, no phone number needed.

2. **Speak or type a command** — Describe what you need in plain English. *"Draft a reply to the last email from John." "What appointments did we miss this week?" "Block off Friday morning."*

3. **Review before it acts** — For anything that sends or changes data, the agent shows you a preview first. You approve, tweak the wording, or cancel — nothing goes out without your say.

4. **Done — next task** — The action completes and a log entry is saved to your session history. Keep going or close the tab.

---

## What It Can Do

No new logins. The Executive Agent uses the same Gmail and Google Calendar integrations your business already has set up in the portal.

### Gmail
- Read and summarise recent emails
- Draft replies in your voice
- Send with your approval
- Find emails from a specific person

### Google Calendar
- Show today's or this week's schedule
- Create and reschedule events
- Find free slots for a meeting
- Block focus time

### Appointments
- View upcoming and past bookings
- Cancel or reschedule
- Flag no-shows and cancellations
- Look up a client's history

### CRM / More *(Phase 2)*
- Log client notes
- Pull up contact history
- Trigger follow-up sequences

---

## Voice Agent vs Executive Agent

|  | Voice Agent | Executive Agent |
|---|---|---|
| **Talks to** | Your customers | You — the owner or manager |
| **Where** | Phone / SIP call | Browser, inside the portal |
| **Does** | Books appointments, answers questions | Drafts, schedules, manages tasks |
| **When** | When a customer calls in | Whenever you open a session |
| **Billing** | Included in plan (call minutes) | Monthly add-on (see below) |

---

## Billing Integration

The Executive Agent sits on top of any existing subscription — it doesn't replace the Voice Agent or require a separate account. Owners toggle it on from the Billing page and it appears as a new line item on their Stripe invoice, the same way future AI employees will be billed.

| Plan | Price | Includes |
|---|---|---|
| Starter | $99/mo | 150 calls · 1 location |
| Growth | $149/mo | 400 calls · 3 locations · **+ Executive Agent add-on available** |
| Pro | $299/mo | 800 calls · 5 locations · **+ Executive Agent add-on available** |

**How the add-on works:**

- A single "Enable Executive Agent" toggle appears in the Billing section
- Turning it on adds a fixed monthly charge to the next invoice — suggested **$49–$79/mo** (TBD)
- Usage (sessions and minutes) is shown in the Billing page alongside the existing call usage bar
- Turning it off cancels the add-on at the end of the billing period with no penalty
- All handled through Stripe subscription items — the same infrastructure already powering existing plans

---

## Build Plan

### Phase 1 — Launch (3–4 weeks)

Complete, usable product. Everything below ships together.

| Feature | Details |
|---|---|
| **Animated Avatar** | Live character with Listening, Thinking, and Speaking states. Reacts in real time. |
| **Voice + Text Input** | Speak or type commands. Microphone activates on session open. |
| **Gmail** | Read recent emails, draft replies, send with your approval. No auto-send. |
| **Google Calendar** | View schedule, create and reschedule events, find free slots. |
| **Appointments** | View, cancel, and reschedule bookings from the portal. |
| **Billing Toggle** | Add-on toggle in Billing page, Stripe line item, session usage tracking. |

### Phase 2 — Post-Launch

Makes it exceptional. Nothing here is required for launch.

| Feature | Details |
|---|---|
| **Expressive Avatar** | More detailed face, richer animations, mood expressions during conversation. |
| **Personality Settings** | Business owner can set the agent's name, tone, and communication style. |
| **CRM Integration** | Log client notes, look up contact history, trigger follow-up sequences. |
| **Multi-Agent Handoff** | Executive Agent delegates tasks to Voice Agent or other future agents. |

---

*Happy to jump on a call to walk through this in more detail.*
