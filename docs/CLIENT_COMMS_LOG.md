# Client Communications Log

Ongoing log of decisions, requests, and issues raised by the client (Sam Maisuria).
Most recent entry at top.

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
