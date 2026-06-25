# Sales Agent — Product Overview

**Prepared by:** Rahul Khera
**Date:** June 20, 2026
**For:** Sam Maisuria

---

## What Is the Sales Agent?

The Sales Agent makes outbound calls to a list of leads on the business owner's behalf. It introduces the business, qualifies each lead to see if they're interested, and immediately notifies the owner by email when someone wants to move forward.

The owner uploads a list, sets a pitch, and the agent works through it automatically — no manual dialling, no missed follow-ups.

---

## How It Works (User Flow)

1. **Upload a lead list** — CSV file with lead names and phone numbers (email optional). The system validates and imports the list as a campaign.

2. **Configure the campaign** — Set the business introduction, what the agent says, and what counts as "interested" (e.g. "yes, tell me more", "can we schedule a meeting", "send me pricing").

3. **Launch the campaign** — Agent starts calling leads one at a time via the existing outbound SIP infrastructure. Each call is logged with transcript and outcome.

4. **Agent qualifies the lead** — On each call:
   - Introduces the business
   - Explains the offering briefly
   - Asks if they'd like to learn more or schedule a meeting
   - Handles common objections politely

5. **If interested** — Agent thanks the lead, tells them the owner will be in touch, then immediately sends a notification email to the business owner's platform account email with the lead's name, phone, what they said, and a transcript snippet.

6. **If not interested** — Marks the lead as not interested. No follow-up unless the owner re-activates it.

7. **No answer / voicemail** — Marks as no answer. Owner can configure a retry (e.g. try again tomorrow, up to 2 attempts).

---

## Lead List Format

CSV upload with these columns:

| Column | Required | Example |
|---|---|---|
| `name` | Yes | John Smith |
| `phone` | Yes | +14165551234 |
| `email` | No | john@example.com |
| `notes` | No | Met at trade show |

The system normalises phone numbers to E.164 format on import. Duplicate phone numbers within a campaign are flagged and skipped.

---

## Agent Call Flow

```
Agent: "Hi, is this [Lead Name]?"
Lead:  "Yes"
Agent: "Hi [Lead Name], my name is [Agent Name] calling on behalf of 
        [Business Name]. We [brief pitch — configured by owner]. 
        I was wondering if you'd have a moment to hear more about 
        what we offer?"

— If YES —
Agent: "Great! [Short value proposition]. Would you be open to 
        a quick conversation with our team, or would you prefer 
        we send you some information first?"
→ Mark as INTERESTED → send owner notification email

— If NOT INTERESTED —
Agent: "No problem at all, I appreciate your time. Have a great day!"
→ Mark as NOT INTERESTED

— If CALLBACK REQUESTED —
Agent: "Of course, when would be a good time to call back?"
→ Capture preferred time → Mark as CALLBACK REQUESTED

— If NO ANSWER / VOICEMAIL —
→ Mark as NO ANSWER → retry logic applies
```

---

## Owner Notification Email

When a lead says yes, the owner's platform account email receives:

**Subject:** `New Interested Lead — [Lead Name] ([Business Name])`

**Body:**
- Lead name + phone number
- What they said (transcript snippet)
- Campaign name
- Timestamp
- Call transcript attached or linked

The owner can then follow up directly. No further action is taken by the agent unless configured.

---

## Lead Status Tracking

Each lead in a campaign has one of these statuses:

| Status | Meaning |
|---|---|
| `pending` | Not yet called |
| `calling` | Call in progress |
| `interested` | Said yes — owner notified |
| `not_interested` | Declined |
| `no_answer` | No answer / voicemail (retry pending if configured) |
| `callback_requested` | Asked for a callback at a specific time |
| `failed` | Call could not connect (bad number, error) |

---

## UI Overview

New page: **Sales Agent** under the portal sidebar.

**Campaigns list** — each campaign shows: name, total leads, breakdown by status (pending / interested / not_interested / no_answer), date created.

**Campaign detail:**
- Lead table with name, phone, status, last called timestamp
- Filter by status
- Export results as CSV
- Pause / Resume campaign
- Re-activate not_interested leads if owner wants a second round

**Create campaign:**
- Upload CSV
- Campaign name
- Agent pitch (text area — what the agent says to introduce the business)
- Retry settings (how many attempts for no-answer leads, how many hours between retries)
- Launch button

---

## Billing Integration

Sales Agent calls consume outbound call minutes from the existing plan, the same as reminder and follow-up calls. No separate billing mechanism needed for Phase 1.

If campaign volume becomes large (hundreds of leads), a separate "Sales Agent" add-on could be introduced in Phase 2 — similar to the Executive Agent model — with a monthly fee and a call minute bucket specifically for outreach campaigns.

| Plan | Included | Notes |
|---|---|---|
| Starter | Uses existing call minutes | Same pool as reminders/follow-ups |
| Growth | Uses existing call minutes | Same pool |
| Pro | Uses existing call minutes | Same pool |
| Sales Agent Add-on *(Phase 2)* | Dedicated minute bucket | Separate Stripe line item |

---

## Build Plan

### Phase 1 — Core Campaign Engine (3–4 weeks)

| Feature | Details |
|---|---|
| **Lead list upload** | CSV import, validation, E.164 normalisation, duplicate detection |
| **Campaign management** | Create, pause, resume, view status per lead |
| **Outbound calling** | Uses existing LiveKit SIP outbound infrastructure |
| **Agent call flow** | Configurable pitch; handles yes / no / callback / no-answer |
| **Status tracking** | Per-lead status updated in real time |
| **Owner notification email** | Instant email to platform account email when lead is interested |
| **Retry logic** | Configurable attempts + delay for no-answer leads |
| **Results export** | CSV export of campaign results |

### Phase 2 — Post-Launch

| Feature | Details |
|---|---|
| **Custom call scripts** | Full script editor with variables (lead name, business name, etc.) |
| **Voicemail drop** | Leave a pre-recorded message if no answer |
| **CRM sync** | Push interested leads directly to a connected CRM |
| **Scheduling** | Run campaign during specific hours (e.g. weekdays 10 AM – 5 PM only) |
| **A/B pitch testing** | Test two different pitches, compare interest rates |
| **Sales Agent billing add-on** | Dedicated minute bucket for high-volume campaigns |

---

## Database (New Tables)

**`sales_campaigns`**
- `id`, `business_id`, `location_id`, `name`, `pitch`, `retry_attempts`, `retry_delay_hours`, `status` (active/paused/completed), `created_at`

**`sales_leads`**
- `id`, `campaign_id`, `business_id`, `name`, `phone`, `email`, `notes`, `status`, `call_id` (FK to calls), `last_called_at`, `callback_time`, `created_at`

---

*Happy to jump on a call to walk through this in more detail.*
