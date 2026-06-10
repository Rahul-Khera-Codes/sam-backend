# Google OAuth Verification Guide — AI Employees Inc.

**Purpose:** Prepare Sam Maisuria for Google's OAuth app verification process, including what to show in the demo video, what to say, and what to submit.

---

## Good News First

Both `gmail.send` and `calendar.events` are **sensitive scopes** — NOT restricted scopes. This means:
- ❌ No expensive third-party CASA security assessment ($15k–$75k) — that's only for restricted scopes like `gmail.readonly`
- ✅ Google reviews it internally — up to 10 business days
- ✅ No annual re-certification required

---

## Scopes We Use

| Scope | Type | Used for |
|---|---|---|
| `https://www.googleapis.com/auth/gmail.send` | Sensitive | Send emails from business Gmail |
| `https://www.googleapis.com/auth/calendar.events` | Sensitive | Create/update/delete staff calendar events |
| `https://www.googleapis.com/auth/userinfo.email` | Non-sensitive | Read connected email address |
| `openid` | Non-sensitive | Basic authentication |

⚠️ **Fix before submitting:** Remove `https://www.googleapis.com/auth/calendar` from the OAuth consent screen — we only need `calendar.events`. Having both declared will prompt a "why do you need both?" from Google's review team.

---

## Timeline

| Stage | Duration |
|---|---|
| Brand verification | 2–3 business days |
| Sensitive scope review | Up to 10 business days |
| **Total (clean submission)** | **2–4 weeks** |
| Total (if back-and-forth needed) | 4–6 weeks |

Brand verification must complete before scope review begins. Submit the video and justifications at the same time as brand verification.

---

## What to Prepare

### 1. Privacy Policy (must be on aiemployeesinc.com)

The privacy policy must specifically mention Google user data. Add this exact paragraph:

> **Google User Data:** AI Employees Inc. accesses Google user data to provide core product features. We use `https://www.googleapis.com/auth/gmail.send` to send appointment confirmations, cancellations, rescheduling notifications, and PDF documents to customers on behalf of connected businesses. We use `https://www.googleapis.com/auth/calendar.events` to create, update, and delete Google Calendar events for staff members when appointments are booked. We do not read, store, or process the contents of any Gmail inbox. We do not read existing calendar events. Google user tokens are stored securely and used only for the connected business that authorised them. Users may revoke access at any time via their Google Account settings or via our app's Integrations page.
>
> AI Employees Inc.'s use and transfer of information received from Google APIs to any other app will adhere to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

### 2. Written Justification for Each Scope (entered in Cloud Console)

**For `gmail.send`:**
> AI Employees Inc. uses `gmail.send` to send transactional emails from business Gmail accounts connected to our platform. Emails sent include: appointment confirmations (with .ics calendar attachments), reschedule/cancellation notifications to customers, PDF documents sent to customers on request during AI voice agent calls, and staff notifications for new bookings. The app constructs and sends these emails without reading, storing, or processing any existing email data in the mailbox. `gmail.send` is the narrowest scope that enables outbound sending — broader scopes such as `gmail.modify` would grant unnecessary access to existing email data, which this app does not require.

**For `calendar.events`:**
> AI Employees Inc. uses `calendar.events` to create, update, and delete Google Calendar events for staff members when appointments are booked, rescheduled, or cancelled via our AI voice agent. When a customer books during a call, the agent creates a calendar event on the relevant staff member's Google Calendar. If the appointment is rescheduled, the event is updated. If cancelled, the event is deleted. The app does not read existing calendar events or sync personal calendar data. `calendar.events` is the minimum scope required — narrower alternatives are insufficient for creating events on a connected account.

---

## The Demo Video

### Format Requirements
- **Platform:** YouTube — set to **Unlisted** (not Private, not Public)
- **Language:** English narration throughout — mandatory
- **Length:** 5–7 minutes
- **Quality:** 1080p screen recording with voice narration (Loom, OBS, QuickTime)
- **What must be visible:** browser address bar at all times (especially during the OAuth consent screen)

---

### Video Structure & Script

#### Part 1 — Introduction (30 seconds)

**Show:** Your desktop/app homepage

**Say:**
> "Hi, I'm recording this demo for the Google OAuth verification of AI Employees Inc. Our platform is a B2B SaaS product that provides AI voice agents for service businesses. The agent handles inbound phone calls and books appointments. Today I'll demonstrate how we use the `gmail.send` scope and the `calendar.events` scope, and why each one is necessary."

---

#### Part 2 — OAuth Consent Screen Setup (45 seconds)

**Show:** Google Cloud Console → APIs & Services → OAuth Consent Screen. Scroll through the configuration showing the app name, scopes listed, and the developer contact email.

**Say:**
> "Here is our OAuth consent screen configuration in Google Cloud Console. The app name is 'AI Employees Inc.' You can see we've declared `gmail.send`, `calendar.events`, `userinfo.email`, and `openid`. These are the only scopes our app requests."

---

#### Part 3 — Full OAuth Grant Flow (1.5 minutes)

**Show:** Go to the app's Business Settings → Integrations page. Click "Connect Gmail". You'll be redirected to Google's account picker. Select the test Gmail account.

**Critical: Make sure the browser address bar is clearly visible on the Google consent screen. It must show the `client_id=` parameter.**

**Say:**
> "Now I'll walk through the full OAuth authorization flow that a business owner experiences. I'll click 'Connect Gmail' on our integrations page. This redirects to Google's account selector. I'll select the test account."
>
> "You can see the Google consent screen clearly showing the app name 'AI Employees Inc.' and the requested permission — 'Send email on your behalf'. Notice the address bar shows the OAuth client ID: [read out the first few characters of the client ID]."
>
> "I'll click Allow to grant permission. The app now has authorization to send emails from this Gmail account."

**Do the same for Google Calendar:**
> "Now I'll connect Google Calendar for a staff member. This goes through the same OAuth flow. You can see the consent screen shows 'Manage your calendars' — specifically, this grants access to create, update, and delete calendar events."

---

#### Part 4 — Demonstrating `gmail.send` in Action (1.5 minutes)

**Show:** Use the app (or simulate a booking via the web UI / test call). Trigger an appointment confirmation. Then switch to Gmail (the receiving inbox — use a test customer account) to show the email arrived.

**Say:**
> "Now I'll demonstrate the `gmail.send` scope in action. I'll simulate a customer booking an appointment through the system. [make the booking] The booking is confirmed. Now let me switch to the customer's email inbox to show the confirmation email was sent."
>
> "Here you can see the appointment confirmation email arrived in the customer's inbox, sent from the connected business Gmail account. It includes the appointment details and an .ics calendar attachment."
>
> "This is the only way we use `gmail.send` — to send outbound transactional emails. We do not read any emails in the business's inbox, and we do not store email contents anywhere in our system."

**Also show:** If possible, trigger a document send — "Let me also show a PDF being sent. [trigger email_document tool or simulate it] Here the customer receives the information PDF as an email attachment, again sent from the business Gmail."

---

#### Part 5 — Demonstrating `calendar.events` in Action (1.5 minutes)

**Show:** After the booking is made in Part 4, switch to the staff member's Google Calendar to show the event was created.

**Say:**
> "Now I'll demonstrate the `calendar.events` scope. When the appointment was booked, our system automatically created a Google Calendar event on the assigned staff member's calendar. Let me open Google Calendar for the staff member to confirm this."
>
> "Here you can see the calendar event was created — it shows the appointment date, time, service name, and customer details. This gives the staff member a clear record in their own Google Calendar."

**Show a reschedule:**
> "Now I'll reschedule that appointment. [change the date/time] You can see the Google Calendar event was updated automatically — the time changed to match the new appointment."

**Show a cancellation:**
> "Finally, I'll cancel the appointment. [cancel it] And the Google Calendar event has been deleted from the staff member's calendar."

> "The `calendar.events` scope allows us to create, update, and delete these events. We do not read any other events on the staff member's calendar — only the events our system creates."

---

#### Part 6 — Data Handling Summary (30 seconds)

**Show:** App settings or integrations page showing the disconnect option.

**Say:**
> "To summarise: we use `gmail.send` exclusively to send outbound transactional emails from business Gmail accounts. We use `calendar.events` exclusively to manage appointment-related calendar events for staff. No email contents are read or stored. No existing calendar data is read. User tokens are stored securely in our database and are only used for the specific business that connected them. Users can disconnect access at any time from our integrations page, which immediately revokes the token."

---

## Where to Submit

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. **APIs & Services → OAuth Consent Screen**
3. Click **Edit App** → go to the **Data Access** tab
4. Remove `calendar` scope, keep only `calendar.events`
5. Click **Prepare for Verification** (or **Submit for Verification**)
6. Fill in:
   - Written justification for each sensitive scope (copy from above)
   - YouTube link (unlisted video)
   - Up to 3 documentation links (app feature page, help article, or screenshots)
7. Submit

Google will email the project owner. **Watch for emails from `noreply-oauth@google.com` — they sometimes go to spam.**

---

## Pre-Submission Checklist

- [ ] `calendar` scope removed from consent screen (only `calendar.events`)
- [ ] Privacy policy on `aiemployeesinc.com` with Google data disclosure + Limited Use statement
- [ ] Homepage publicly accessible (no login required to view)
- [ ] App name on consent screen matches name on website exactly: **"AI Employees Inc."**
- [ ] Developer contact email is monitored and correct in Cloud Console
- [ ] Domain `aiemployeesinc.com` verified in Google Search Console (by the same account as Cloud Console owner)
- [ ] Demo video recorded, 5–7 minutes, English narration, uploaded to YouTube as Unlisted
- [ ] Video shows: full OAuth flow, URL bar with client ID, email received in inbox, calendar event created/updated/deleted
- [ ] Written justifications copied into the verification form
- [ ] Spam folder monitored after submission

---

## Common Rejection Reasons (Avoid These)

1. **Vague justification** — "We use Gmail to send emails" is not enough. Be specific about every email type.
2. **No narration in video** — Silent screen recordings are rejected. Narrate in English throughout.
3. **Client ID not visible** — The address bar must be visible during the OAuth consent screen showing `client_id=` in the URL.
4. **Email/calendar not shown in action** — Show the email arriving in an inbox. Show the calendar event in Google Calendar. Screenshots of the app aren't enough.
5. **Privacy policy missing Limited Use statement** — Include the exact Google-approved language (provided above).
6. **Redundant scopes** — Having both `calendar` and `calendar.events` declared will trigger a follow-up asking why both are needed.
