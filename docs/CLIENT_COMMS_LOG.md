# Client Communications Log

Ongoing log of decisions, requests, and issues raised by the client (Sam Maisuria).
Most recent entry at top.

---

## 2026-07-06 — Sales Employee requirements doc sent to the group

**Rahul → Yuvraj/Sam/Charles:** converted `docs/sales-employee-agenticbi-requirements.md` (re-verified against the PDF mockups, 2026-07-02) to docx and sent it to the group. Covers all 4 modules, the confirmed Apify pipeline, what's NOT included, and the platform-integration cost breakdown for LinkedIn/Facebook/Instagram/YouTube/news sources.

Billing add-on live-test (Stripe test-mode price for Executive Agent) put on hold at Rahul's request — he'll provide test details later rather than picking a placeholder value now.

---

## 2026-07-02 (evening) — Sam sent the ChatGPT-scope questions, reported a calendar bug, asked about billing add-on

**Rahul → Sam (07:02 PM):** sent the 4 drafted questions on ChatGPT scope + cost/value (see 2026-07-02 entry below). No reply yet as of this log.

**Sam → Rahul (08:40 PM): "I tried to setup an appointment, but got error message 'was not able to setup an appointment, google calendar is not connected.' I checked and it is connected."**
- **Root cause (confirmed by Rahul independently, same day):** local dev environment and the production server use **different** Google OAuth client credentials, but both read/write the **same** Supabase DB (same `google_oauth_tokens`-type rows). Whichever environment last refreshed a token stamps it with that environment's client — so the *other* environment's calendar/Gmail calls fail with an `invalid_client`-class error until someone reconnects (Integrations → Manage → disconnect/reconnect), which just re-issues a fresh token under whichever environment did the reconnecting. **This is a known, previously-flagged, never-fully-fixed risk** — see `docs/SESSION_HANDOFF.md` "Project/client-id discrepancy" note. Reconnecting is a workaround, not a fix — it will keep recurring as long as local dev shares the production DB with different credentials.
- **Not yet replied to Sam** — no fix applied yet, root cause understood but structural decision needed (see TODO.md).

**Sam → Rahul (08:43 PM): "Also, under the billing section where is the toggle to addon the executive assistant?"**
- **Rahul → Sam (09:54 PM): "The billing section need to be updated, I'm working on it currently."** Matches the already-tracked "Billing UI update" blocker (`memory/project_blockers.md`) — Executive Agent isn't wired into billing yet (still free during beta).

---

## 2026-07-02 — Questions drafted for Sam (NOT yet sent) — ChatGPT scope + cost/value

Rahul decided to talk to Sam before scoping the remaining "ChatGPT-like" item (#1) or the persistent chat history item (#6) — both depend on what Sam actually wants Remi to be. Questions drafted, ready to send:

1. **What do you mean by "ChatGPT-like"?** Remi already answers general questions outside of email/calendar/appointments. What's missing — more casual chit-chat, business advice, help writing things, or something specific? An example would help.
2. **Should there be things Remi does NOT talk about?** To keep her focused (and cheaper to run) — limit her to business stuff (email, calendar, appointments, general work questions) and steer away from personal chit-chat/random topics? Or should she be open to anything, like ChatGPT?
3. **Is the cost worry about our running cost, or about convincing customers to pay instead of using free ChatGPT?** Different problems, different fixes. If it's running cost, we can keep trimming it (already cut some this week). If it's customer value, the fix is making it obvious what Remi does that ChatGPT can't (real email, real calendar, real bookings) — not adding more open-ended chat.
4. **If it's the customer-value problem — should we lean into showing what makes Remi different, instead of adding more general chat?** More general Q&A makes "why not just use ChatGPT" worse, not better — that's literally what ChatGPT already does for free.

---

## 2026-07-01 (evening) — Sam pushes back on cost/value, 7 new UI requests, ChatGPT-scope question raised

**Note on this whole exchange:** Rahul pushed `feature/exec-agent-improvements` and gave it to Sam for testing yesterday, but it's **unconfirmed whether Sam actually tested it** — he only added the 7-item task list and sent the cost-pushback message below, no explicit test feedback. Don't read Sam's silence on the fixes as approval or as a failed test — it's simply unverified either way.

**Rahul → Sam (06:19 PM):** sent the day's bug-fix summary for attach-document-to-email — three layered issues found and fixed in this session: (1) no attachment capability existed at all, (2) document library was cached once at session start instead of checked live, (3) the model answered "no documents" from its own earlier turn instead of re-checking. All three fixed, committed, agent restarted.

**Rahul (06:20 PM, internal):** raised the open question already tracked in TODO.md — the "ChatGPT-like" general Q&A has no defined scope or boundary. Without one, Remi can answer literally anything, with no limit. Needs a decision before building more of it. (This turned out to be directly related to Sam's message below.)

**Rahul → Sam (08:40 PM):** "Also, I've updated the Executive Agent visibility so it can be offered as a subscription add-on. I've implemented toggle-based availability for now, and later we can control access based on whether the user has purchased the subscription." — **Note:** what was actually built this session is the **avatar** on/off toggle (`avatar_enabled`), not a whole-Executive-Agent visibility/subscription gate. Worth clarifying with Sam so expectations match what's actually shipped — the avatar toggle does not currently gate access to the Executive Agent itself.

**Sam → Rahul (11:42 PM):** **"Rahul what is the cheapest way to run the executive assistant. People will not pay to use this when they can use ChatGPT for free."** Direct pushback on running cost and on value/differentiation versus free ChatGPT. Connects straight to Rahul's 06:20 PM note: Remi currently runs on OpenAI's Realtime API for every interaction (not a cheap text-only model), and the prompt has no topic boundary — the same lack of scope is both the expensive part and the undifferentiated part. **Needs a strategy conversation with Sam** — what Remi is actually *for* versus general chat, and the cheapest architecture that still delivers that — not a pure engineering fix.

**Sam — 7 new requests logged (kanban board), "check everything thoroughly first":**
1. Add more functionality "like ChatGPT" — blocked on the cost/scope conversation above.
2. Remove business name from the opening greeting — target: "Hi, I'm Remi—how can I help you today?"
3. Editable email **body** in the draft/preview card (fix a typo without re-dictating the whole email).
4. Editable **recipient address** in the draft/preview card.
5. Editable **subject** in the draft/preview card.
6. Persistent chat memory / sidebar — access previous conversations. Currently the transcript resets to empty on every new session; no history is saved anywhere.
7. Edit + copy buttons on the transcript/speech-to-text bubbles, to fix minor mistakes without repeating the whole utterance.

**Rahul verified against current code (2026-07-01) before scoping any of the above:**
- #2 — one-line fix, `agent/executive_agent.py:1188-1189`.
- #3/#4/#5 — all in `AgentCardView.tsx`'s `email_draft` card (L245-260): currently 100% read-only text, no input fields at all. One workstream.
- #6 — confirmed zero persistence anywhere: `useExecutiveSession.ts` wipes the transcript on every `connect()`; no DB table or endpoint stores exec-agent conversation history. The biggest of the 7 — new schema + save-on-message + history UI.
- #7 — `TranscriptPanel.tsx` bubbles are plain text, no buttons.

**Proposed sequencing (pending confirmation):** #2 now (trivial) → editable email draft fields (#3–5, one workstream) → transcript edit/copy (#7) → persistent chat history (#6, biggest, own workstream) → #1 blocked on the cost/scope conversation with Sam.

---

## SAM ITEMS — re-triaged 2026-06-25 (Sam is non-technical: only surface what he must ACT on, or build-and-demo for feedback)

**Build now, don't ask — show Sam for feedback when ready:**
- **Avatar** → abstract avatar now / HeyGen Phase 2 is already the approved plan (he approved the full overview doc, both phases). Build swappable, demo it. (WS4, in progress.)
- **Rich cards** → already BUILT + verified. Demo, not a question.

**Get feedback when convenient (not a blocker — sensible default already shipping):**
- **Billing price** → free-during-beta is the working default; ask his price ($49–79/mo TBD) when he's around. No build dependency.

**Genuine action item for Sam — raise at the right time, in plain language (NOT a build blocker; works in test mode now):**
- **Gmail go-live / CASA:** to let Remi read Gmail in the *public* product, Google requires a paid **annual third-party security review (CASA)** — costs money + a few weeks lead time. When we're ready to launch publicly he must approve that spend (and any Google-side verification steps he owns). Secondary: confirm whether Remi should ever *manage* the inbox (mark-read/archive/label) so we request `gmail.modify` once instead of re-verifying. Until then it runs fine in test mode for our test users.

**Deferred to the Sales Employee workstream (next product, not now):**
- **Apify / LinkedIn:** scraping LinkedIn via Apify carries LinkedIn-ToS risk (lawyer review, alongside CASL) + Sam needs to provide an Apify account/budget. Raise when Sales work starts.

_Prior Jun-24 draft (a flat 5-question list) superseded by the above — the old framing asked Sam technical decisions he doesn't need to make._

---

## 2026-06-25 → 06-30 — Team scaling, Exec-Agent tested OK, 4 requests + attach-doc bug, avatar=HeyGen, new HR product

**Team / process change (Upwork, Jun 25–26):**
- Sam wants the **whole agent suite done in ~2 months** (not end of year) and asked Rahul to bring on a second developer. Rahul proposed **Yuvraj** (8 yrs, fullstack + design, Upwork). Sam wants **Rahul as lead developer** guiding Yuvraj. Rahul showed Yuvraj the system; he's interested.
- **Meeting held (~Jun 29, Mon AM India time)** between Sam, Rahul, Yuvraj: agreed **Yuvraj works on UI**, Rahul on agent/backend core + lead.
- Sam asked: **can all THREE remaining agents be done in July?** "Three" = excluding Customer Service + Executive Assistant → **Marketing + Sales + Human Resources**. Rahul's answer (correct): **need exact feature details per agent to confirm feasibility.** → Action: get a spec (like the HR PDF) per agent, scope MVP-vs-full, give per-agent estimate. (Honest read: all three *complete* in one month w/ 2 devs is unrealistic; tight MVPs maybe.)

**Executive Agent — Sam tested it (Mon Jun 29): "the test was successful" ✅** (broad live-verification of the session-53 batch passed in Sam's hands). Then Sam raised:
1. Move **Start Session** button to center of screen. (UI)
2. Add **Unmute Mic** button to center of screen. (UI; Rahul: that centered layout was on the customer agent — will bring to executive agent too)
3. **Fix attach-document-to-email (BUG).** ⬇
4. Add **ChatGPT-like** general-question functionality. (scope — Remi already answers general Qs via the realtime model; clarify if Sam means open-ended Q&A/drafting [easy] vs file/data analysis [bigger])

**BUG — attach document to email (confirmed + root-caused):** Asking Remi to send an email with a Business-Settings/Documents attachment → no attachment; body shows a placeholder like "[Packages and pricing details will be inserted here]" (screenshot `{FF5E41F0…}.png` in ~/Downloads). **Root cause:** `executive_agent.py send_email_draft` only does `msg.attach(MIMEText(body))` — the exec agent has NO document-lookup/attach capability. The **CS agent already has it** (`email_document` in `agent/agent.py:716` → pulls `business-documents` storage, signs URL, downloads, attaches as `MIMEBase("application","pdf")`). **Fix = port that into the exec agent** (a tool to list business docs + attach the chosen PDF to the draft → through the existing preview→approve→send).

**Cost question (owed deliverable):** Sam asked how the Executive Assistant affects running costs. Rahul: same stack as CS agent (LiveKit + OpenAI), minus telephony; **will send a cost estimate.** Note: if the HeyGen avatar ships, it adds ~$0.10/min (LiveAvatar LITE) on top of OpenAI Realtime + LiveKit → material per-minute add; frame avatar-on vs optional in the estimate.

**Avatar decision — use HeyGen.** Sam (meeting) confirmed the Phase-2 avatar = **HeyGen**. Rahul researched + verified the integration (2026-06-30): HeyGen **LiveAvatar** plugin for LiveKit Agents, **LITE mode** (we keep our OpenAI-Realtime pipeline, HeyGen renders video), **realtime-compatible** (avatar consumes the AgentSession audio output), **version-aligned** (`livekit-plugins-liveavatar~=1.4` matches our `livekit-agents~=1.4`), **free sandbox** for POC, ≈$0.10/min LITE. Full tech notes in memory `reference_heygen_liveavatar_integration`. Our WS4 `AgentAvatar.tsx` already has the swap point; frontend adds a video-track render branch.

**NEW product — Human Resources Employee** (`Human Resources.pdf`, ~Jun 26, in ~/Downloads): a full AI recruiting/ATS suite (9 screens: recruitment dashboard + funnel, job postings, JD builder "Ava" + Talent Finder LinkedIn search, Interview Question Bank + AI video interviewer, candidates + AI scoring, interview analysis/feedback + hire recommendations, candidate detail, document library, onboarding chat with avatar). Big lift (LinkedIn/Indeed sync + AI video interviewer; same LinkedIn-ToS risk as Sales). Reuse: onboarding avatar = Remi pattern, doc library = business-documents/KB, interviewer = LiveKit realtime. Full breakdown in memory `project_feature_hr_employee`.

## 2026-06-24 — Sam answered Sales Employee questions + sent 5 reference PDFs + PRIORITY CHANGE

Rahul sent the 5 clarification questions (AM). Sam replied (7:33 PM):

1. **Data source** → use **Apify API** (https://apify.com/) for scraping/enrichment (instead of Apollo/Hunter/Clearbit).
2. **Push to CRM** → **Don't include this feature yet.**
3. **Market & Competitor intelligence** → use Sam's recommended pipeline:
   - `Company Input → Website scrape → LinkedIn enrichment → LLM industry classification → Competitor discovery → News aggregation → Sentiment analysis → Opportunity report`
   - Report output: Industry overview, Market trends, Competitor analysis, Pricing intelligence, Demand signals, Hiring signals, New opportunities, Risks, Lead opportunities, Recommended sales angles.
4. **Legal (CASL)** → **Agreed** (will run by lawyer).
5. **Priority** → **"Don't develop the Outbound Calling Employee now, wait until we finish the Executive Assistant, and Sales Employee."**
   - ⇒ Build sequence: **Executive Assistant (in progress) → Sales Employee → then Outbound Calling Employee.**

**5 reference PDFs sent** (in `/home/lap-68/Downloads/`): `Executive Assistant.pdf`, `Outbound Caller.pdf`, `Sales Employee.pdf`, `Branding.pdf`, `Marketing Employee.pdf`.

**PDF review (session 52):**
- **Executive Assistant.pdf** → a **HeyGen "Talking Avatar" picker** (100+ realistic avatars: Derek, Monica, Tyler, Zoey…). Confirms the Phase-2 avatar = HeyGen talking avatar + selection gallery. Matches his Jun 12 HeyGen reference.
- **Branding.pdf** → expanded **Branding tab** in Business Settings: logo, color palette, fonts, mission, unique value claims, "Use Emojis" toggle, **Competitive Analysis** + **Market Insights**. Feeds the Sales Employee market-intel pipeline.
- **Sales Employee.pdf** → the 4 modules (Lead Researcher / Competitor Agent / Market Agent / Report Scheduler) as portal sidebar modules; report email branded "AgenticBI".
- **Outbound Caller.pdf** + **Marketing Employee.pdf** → not yet reviewed (deprioritized / future). Review when those workstreams start.

---

## Executive Agent — decision lineage (Jun 12 → 22, reconciled session 52)

For full status see TODO.md + `memory/project_voice_agent.md`. Key decisions from the chat:

- **Jun 12:** Sam shared a Heygen/OpenClaw TikTok (realistic talking avatar) — *"Can we create something like this for our Executive Assistant?"* — **this is his visual reference for the animated character.** Link: https://www.tiktok.com/@shawn.kanungo/video/7628836652701584658 (by @shawn.kanungo, his brother-in-law). Saved in memory `reference_executive_avatar.md`.
- **Jun 16:** Sam clarified — wants a **live AI avatar face, separate from the Voice Agent**, that manages tasks on connected services (Gmail, Calendar) via voice. *"talk to the AI and ask it to do things."*
- **Jun 18–19:** Sam asked for a high-level explanation **including billing integration**. Rahul sent the overview doc (= `docs/executive-agent-overview.md`).
- **Avatar scope:** overview sets **Phase 1 = clean animated avatar with 3 states** (listening/thinking/speaking), **Phase 2 = expressive Heygen-style face**. The built status indicator satisfies Phase 1; the realistic face Sam admired is Phase 2.
- **Billing:** Sam specifically asked to include billing. Overview proposes an add-on toggle + Stripe line item, **price TBD ($49–79/mo)**. Built free-during-beta pending Sam's price decision.
- **Jun 19:** Sam asked for an **estimate** to check budget.
- **Estimate given:** **2 weeks**, starting **Mon Jun 22, 2026** → target completion **~Jul 3–6, 2026**.
- **Jun 22 (1:55 AM):** Sam: *"Continue to build the Executive Agent."* → green light. Rahul started same day (start of the 2-week window).
- **Note:** Sam is also designing a **Marketing Agent** (mentioned Jun 22) — not yet shared.

---

## 2026-06-22 → 06-23 — Chat (Outbound Calling Employee rename, two-way calendar, NEW Sales Employee product)

**From:** Sam Maisuria (with Rahul replies)

**1. New section: "Outbound Calling Employee"**
- Sam (Jun 22, 8:10 PM): *"Can you add another section called Outbound Calling Employee. The screenshots I sent you for Sales Employee will be named Outbound Calling Employee. I will give you some new screenshots to be used for the Sales Employee soon."*
- Effect: the original 7 mockups (`/home/lap-68/Downloads/Screen 1-7.png`) — the outbound cold-calling / lead-list VOICE product — are now branded **Outbound Calling Employee**.
- Status: ⏳ Pending clarification on functional spec + whether the legal hold (cold-call legality) still applies. Do NOT build yet.

**2. Two-way Google Calendar sync — direction clarified**
- Rahul asked (Jun 22, 9:14 PM): which direction + per-staff vs business-wide?
- Sam (Jun 23, 12:23 AM): *"yes INTO from clients calendar"*
- ✅ Direction confirmed: pull events FROM the client's connected Google Calendar INTO the portal Calendar view (currently we only push portal → GCal).
- ⏳ Still unclear: per-staff (each user sees their own GCal events) vs business-wide; whether pulled events are read-only overlays or editable; conflict handling against existing appointments.

**3. NEW "Sales Employee" product — 4 screenshots (this is NOT the cold-calling product)**
- Sam (Jun 23, 12:23 AM): *"I attached some screenshots of our Sales Employee. Please develop this one too."*
- Files: `Lead Research.png`, `Competitor Intelligence.png`, `Market Intelligence.png`, `Report Scheduler.png` (all in `/home/lap-68/Downloads/`)
- **This is a B2B sales-intelligence dashboard, branded "AgenticBI" — no voice/calling at all.** Completely different from the originally-scoped Sales Agent (CSV lead upload + outbound calls). Four modules:
  - **Lead Researcher AI Agent** — paste a LinkedIn profile URL → enriched lead card: predicted email + confidence score, best time to reach, job-role insights, pain points & sales angles, personal interests, and a generated outreach email template. Actions: Export PDF, Email Report, Push to CRM. Has History + Saved Leads.
  - **Competitor Agent (Competitor Intelligence)** — add competitors by website URL; real-time tracking of competitor features, sentiment, social media, market moves; per-competitor "View Report"; Schedule Report.
  - **Market Agent (Market Intelligence Feed)** — "What's Changing" feed with multiple AI analyst cards (Trend, Cultural, Market Research, Consumer Insights, Innovation Strategist, Business Intelligence). Add Custom Report.
  - **Report Scheduler** — automated email briefings combining the 3 modules; recipients list, frequency (daily/weekly/monthly/custom), module checkboxes, live email preview ("Weekly Intelligence Briefing").
- **Client has NOT shared written requirements** — only the 4 screens. Major unknowns: data sources for email prediction / competitor tracking / market feed (all require paid 3rd-party APIs + have legal/privacy implications), CRM targets, industry scoping, branding ("AgenticBI" vs AI Employees), priority vs Executive/Outbound/calendar work.
- Status: ⏳ Clarification message drafted for Sam (see below). Do NOT build until data sources + scope confirmed.

---

## 2026-06-16 — Chat messages (Executive Assistant idea + PDF bug)

**From:** Sam Maisuria
**Context:** Sam answered the Heygen clarification question + reported a new bug.

**Executive Assistant — new product idea**
- Sam wants a LIVE AI avatar (not pre-recorded video) — separate from the Voice Agent
- Concept: a browser-based conversational AI assistant that connects to services (Gmail, Google Calendar, etc.) and takes actions via voice commands
- Example: "Send an email to...", "Check my calendar for today's appointments"
- This is a **major new product scope** — not a feature, a second AI product line
- Status: ⏳ Logged for future scoping — do NOT build until properly scoped and agreed

**Bug: PDF send — "Email is not configured correctly"**
- Status: ⚠️ NOT VERIFIED FIXED
- Sam getting this error when agent tries to send a PDF
- Most likely cause: Gmail not connected for the new business account (info@canadastopdjs.com) set up after the database wipe
- Could also be a code bug — needs investigation
- Developer replied "I will fix all of them till tomorrow" (Jun 16, 11:02 PM) — not confirmed fixed

---

## 2026-06-15 — Email thread (Google OAuth + Calendar timezone bug)

**From:** Sam Maisuria
**Context:** Following up on Google OAuth verification response + new bug found during testing.

**Google OAuth reply sent ✅**
- Sam sent the detailed reply to Google on Jun 15 using our drafted response
- Test credentials provided: info@canadastopdjs.com / Sanjeev123#@!
- Testing instructions included for both gmail.send and calendar.events
- Waiting on Google's response

**Bug: Google Calendar events created at wrong timezone**
- Status: ⚠️ NOT YET FIXED
- Sam booked 9 AM MDT appointment → Google Calendar showed 3 AM (6 hours off)
- Root cause: appointment time is stored as local time but calendar event is created treating it as UTC
- Edmonton = MDT = UTC-6 → 9 AM local written as 9 AM UTC → displays as 3 AM locally
- Fix needed in `backend/app/services/google_calendar_service.py` — event datetime must include correct timezone

---

## 2026-06-08 — Pre-Launch Q&A (written doc)

**From:** Sam Maisuria
**Context:** Sam shared a written Q&A document with pre-launch questions. Answered async.

**Q5: Agent still answers when turned OFF — forward to business phone instead**
- Status: ✅ DONE (session 47)
- When agent OFF + real SIP call + business phone set → silent SIP REFER to `businesses.phone`
- Non-SIP / no phone set → existing unavailability message

**Q6: Can the AI agent play background office noise during calls?**
- Status: ⏳ Deferred to v2
- Technically possible (publish second audio track or mix at RTC frame level)
- Risk: STT could pick up ambient noise → false speech triggers → agent interrupts itself mid-sentence
- Decision: skip for launch, revisit post-launch when core system is stable
- Message sent to Sam recommending deferral

**Q2 (Developer 2): Delete old test accounts so Sam can re-register with same emails**
- Status: ⏳ Pending — need Sam to send list of email addresses to delete from Supabase auth

---

## 2026-05-15 — Google Meet

**From:** Sam Maisuria
**Context:** Weekly sync — final pre-launch testing round

**Decisions & Action Items:**

**1. Rename "Danger Zone" tab → "Deactivate"**
- Users are scared to touch the tab because of the name
- Just change the tab label in BusinessSettings.tsx from "Danger Zone" to "Deactivate"
- The functionality stays exactly the same

**2. Greeting says business name AND location name — confusing**
- Live test heard: *"Thank you for calling downtown in Mirage, located in Edmonton"*
- The business name is "Downtown Barber Shop", location is "Mirage" → agent says both, sounds weird
- Sam confirmed: Mirage IS the location name, Downtown is the business. Currently the DB has them mixed.
- Fix: prompt_builder generates "You are the AI for {business_name} in {location}" — review how it's phrased so it doesn't double-up awkwardly

**3. Remove weekly schedule grid from CS Scheduler — CONFIRMED**
- Sam confirmed explicitly: remove the entire weekly schedule grid from the CS Scheduler page
- Leave it: always-on by default + custom schedules for exceptions only
- Business hours (in Business Settings) are what the agent uses to answer "when are you open?" — completely separate
- Quote: "Just remove the whole thing. If the client wants custom schedule they create one."

**4. CRITICAL: Voice agent cannot retrieve available slots**
- Live test: AI said "we're having difficulty retrieving available time slots" twice
- Rahul suspects: `_validate_booking_datetime` added last week passes "00:00" as time when checking available slots → business opens at 9am → "00:00 outside business hours" → error returned before slots are computed
- Fix: `get_available_slots` in agent.py should only validate the date (not past, not closed day) — not the time, since we're computing all slots for the whole day
- Sam: "That's a big one" — must fix before Monday test

**5. AI sometimes speaks non-English**
- Background noise causes language detection to go off
- Fix: add explicit instruction in prompt to always respond in English regardless of detected language

**6. Deploy to Hostinger VPS — CONFIRMED GO-AHEAD**
- Sam wants live deployment ASAP — competitors appearing in Canada
- Plan: buy VPS on Hostinger, deploy frontend + backend + agent under subdomain (app.aiemployeesinc.com or similar)
- Sam: "Once we're done, I'll go through on Monday and do another test"

**7. Settings items still to verify**
- Sam still needs to check every individual item in CS Settings before sign-off
- Once confirmed working → go live

**Next milestone: Sam tests on Monday 2026-05-19**

---

## 2026-05-14

**From:** Sam Maisuria
**Context:** Testing feedback — 3 issues raised for tomorrow's meeting

**Issue 1: Appointment booking broken**
- "The system's calendar functions have broken down. You cannot make an appointment."
- Root cause identified: backend is on `main` (no `/appointments` endpoint), frontend is on `feature/appointment-pipeline` (calling `POST /appointments`) — branch mismatch causes 404.
- Fix: merge `feature/billing-section` → main, then `feature/appointment-pipeline` → main (in that order)
- **Status:** ⏳ Discuss in tomorrow's meeting

**Issue 2: Scheduler vs Business Hours confusion**
- "The scheduler for the voice agent is only used to turn on or off the AI. The system should always be on unless a custom schedule is turned on. Then always on will be deactivated."
- "I think the system is confused between the Customer Service Scheduler and the Business Hours. We need to simplify this."
- Sam's intended model:
  - CS Scheduler = ON/OFF toggle only + custom exceptions (closures/holidays)
  - Business Hours = what the AI tells callers about operating hours (set in Business Settings)
  - Default: AI always on; custom schedules deactivate it temporarily
- Fix: UI-only change — remove weekly hours grid from CS Scheduler page; keep only ON/OFF toggle + custom schedules. Add a link to Business Settings for hours.
- **Status:** ⏳ Discuss in tomorrow's meeting

**Issue 3: Custom Greeting Message**
- "We need to add a custom Greeting Message in the inbound calling area."
- Currently the greeting is auto-generated by `prompt_builder.py`: "Thank you for calling [Business] in [Location], how can I help?"
- Sam wants a custom text field to override it per location.
- Fix: new field in `agent_settings` or `communication_settings` + `prompt_builder.py` uses it when set.
- **Status:** ⏳ Discuss in tomorrow's meeting

---

## 2026-05-12

**From:** Sam Maisuria
**Context:** Bug report after testing the system

- **Bug:** AI cannot tell the difference between the Voice AI Scheduler and Business Hours
- Sam will send videos tomorrow demonstrating the issue
- **Root cause (confirmed via code review):** `GET/PUT /settings/agent/schedule` (CS Scheduler page) and `useBusinessHours` (Business Settings → Business Hours tab) both read/write the **same `business_hours` table**. They are identical data shown in two UI locations. The agent prompt also reads from `business_hours` — so there is no separation between "when the business is open" (what the agent tells callers) and "when the AI agent should be active" (when it picks up calls).
- **Fix options:**
  1. Add a separate `agent_schedule` table so AI active hours can differ from business open hours
  2. Consolidate the UI — remove one of the two views and clarify they are the same setting
- **Status:** ⏳ Awaiting Sam's video. Architecture decision needed before implementing fix.

---

## 2026-05-05

**From:** Sam Maisuria
**Context:** Follow-up on Resend DNS recurring failure

- Resend domain `aiemployeesinc.com` verification failing again
- Root cause: Sam sets up Google Workspace MX records for `sam@aiemployeesinc.com` and inadvertently wipes Resend TXT records (DKIM/SPF/DMARC)
- These two sets of records do NOT conflict — MX (Google) and TXT (Resend) can coexist
- SPF record must include both: `v=spf1 include:_spf.google.com include:amazonses.com ~all`
- **Action:** Sam needs to keep both sets of records in Hostinger at all times. When adding Google MX, do not delete existing TXT records.
- **Status:** Recurring — needs permanent DNS checklist for Sam

---

## 2026-05-01 (late night)

**From:** Sam Maisuria
**Context:** Billing architecture discussion

**Decision: Per-Agent Billing confirmed**
- Future agents (Sales, HR, Marketing, Executive) will be billed as monthly subscription add-ons
- Example: Growth plan ($149/mo) + Sales Agent (+$X/mo)
- Stripe handles as subscription line items; DB tracks `active_agents` per business
- Token-based billing ruled out — too complex to build and explain to customers

---

## 2026-04-30 (late night)

**From:** Sam Maisuria
**Context:** Billing page UI + pricing table update

**New pricing table shared (screenshots):**

| Plan | Price | AI Minutes | Est. Calls | Phone Numbers | Users | Google Cal | Multi-Location |
|---|---|---|---|---|---|---|---|
| Free Trial | Free | ~75 min | 25 calls | 1 | 2 | — | — |
| Starter | $99/mo | 200 min | ~65 calls | 1 | 5 | — | — |
| Growth | $149/mo | 600 min | ~200 calls | 1 | 15 | ✓ | Up to 3 |
| Professional | $299/mo | 1,500 min | ~500 calls | 2 | 30 | ✓ | Up to 5 |
| Enterprise | $599/mo | 4,000 min | ~1,300 calls | 5 | Unlimited | ✓ | Unlimited |

**Overage & Add-Ons:**
- Additional AI minutes: $0.30/minute
- Extra phone numbers: $25/month
- Extra locations: $49/month

**Clarifications from Sam:**
- Free/Starter tiers: limited to 1 location; extra locations require upgrade to Growth+
- Billing UI should be updated to reflect this table
- **Status:** ⏳ Pending — billing UI update not yet implemented

**DNS issue (same session):**
- Sam deleted MX records to add Google Workspace → broke Resend domain verification
- Sam re-added Resend DNS records manually
- **Status:** Fixed by Sam, but recurring (see 2026-05-05 entry)

---

## 2026-04-30 (evening)

**From:** Sam Maisuria
**Context:** Pre-launch check

**Asked about:**
- SMS 2FA status → still waiting on Sam to complete A2P 10DLC registration with Twilio
- Billing section status → Stripe integration now complete (built same day)

---
