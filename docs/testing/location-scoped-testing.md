# Location-Scoped Architecture — Test Checklist

Tests to verify that location-based context and filtering work correctly end-to-end.
Run all tests with at least two locations active (e.g. **Mirage** and **Downtown office**).

---

## 1. UI Data Isolation (Frontend → Supabase)

### 1.1 Business Hours
- [o] Select **Mirage** → go to Business Settings → Business Hours → set Mon–Fri 9 AM–5 PM
- [o] Switch to **Downtown office** → set Mon–Fri 8 AM–6 PM
- [o] Switch back to **Mirage** → confirm hours show 9 AM–5 PM (no bleed from Downtown)
- [o] Refresh page while on Mirage → hours persist correctly

### 1.2 Services
- [o] Select **Mirage** → add a service "Fade Cut"
- [o] Switch to **Downtown office** → confirm "Fade Cut" does NOT appear
- [o] Add a different service "Beard Trim" on Downtown
- [o] Switch back to Mirage → confirm only "Fade Cut" is listed

### 1.3 Knowledge Base
- [o] Select **Mirage** → add a KB entry "Mirage parking info"
- [o] Switch to **Downtown office** → confirm entry does NOT appear
- [o] Add "Downtown parking info" on Downtown
- [o] Switch back to Mirage → only Mirage entry shows

### 1.4 Agent Settings (Feature Flags)
- [o] Select **Mirage** → disable "Send Texts During or After Calls"
- [o] Switch to **Downtown office** → confirm the toggle is independent (its own state)
- [o] Enable "Missed Call Text-Back" on Downtown only
- [o] Switch back to Mirage → "Missed Call Text-Back" is off

### 1.5 Custom Schedules
- [ ] Select **Mirage** → create a one-time schedule "Mirage Holiday" for a future date
- [ ] Switch to **Downtown office** → schedule does NOT appear
- [ ] Create "Downtown Holiday" on Downtown
- [ ] Switch back to Mirage → only "Mirage Holiday" shows

### 1.6 Call Forwarding Contacts
- [ ] Select **Mirage** → add contact "Mirage Manager" with a forwarding rule
- [ ] Switch to **Downtown office** → contact does NOT appear
- [ ] Add "Downtown Manager" on Downtown
- [ ] Switch back to Mirage → only "Mirage Manager" shows

### 1.7 Analytics
- [ ] Make 2–3 test calls to Mirage's number, 1 call to Downtown's number
- [ ] Select **Mirage** → analytics show only Mirage call counts
- [ ] Switch to **Downtown office** → analytics show only Downtown call counts
- [ ] Check call recordings list — Mirage shows only Mirage calls

### 1.8 Gmail Integration
- [ ] Select **Mirage** → connect Gmail account A
- [ ] Switch to **Downtown office** → Gmail shows "Connect" (not Account A)
- [ ] Connect Gmail account B on Downtown
- [ ] Switch back to Mirage → still shows Account A (no bleed)
- [ ] Disconnect on Mirage → Downtown still shows Account B

### 1.9 Appointments (Calendar)
- [ ] Select **Mirage** → create appointment for client "Alice"
- [ ] Switch to **Downtown office** → Alice's appointment does NOT appear
- [ ] Create appointment for "Bob" on Downtown
- [ ] Switch back to Mirage → only Alice's appointment shows

### 1.10 Phone Numbers
- [ ] Phone Numbers page groups numbers by location
- [ ] Each location shows only its own number
- [ ] Numbers without a location are flagged as "legacy"

---

## 2. Agent Context — Inbound SIP Call

### 2.1 Correct Location Resolved
- [ ] Call Mirage's number → agent greets using Mirage's business hours, services, and KB
- [ ] Call Downtown's number → agent greets using Downtown's hours/services/KB
- [ ] No cross-location data appears (e.g. Mirage services don't bleed into Downtown call)

### 2.2 Business Hours Enforcement
- [ ] During Mirage's open hours → agent handles call normally
- [ ] Call Mirage outside its configured hours → agent says "we're closed"
- [ ] Call Downtown outside its hours (but Mirage would be open) → Downtown agent still says closed

### 2.3 Services Scoped to Location
- [ ] Call Mirage → ask "what services do you offer?" → agent lists only Mirage services
- [ ] Call Downtown → same question → agent lists only Downtown services
- [ ] Ask Mirage agent about a Downtown-only service → agent does not know it / offers to transfer

### 2.4 Knowledge Base Scoped to Location
- [ ] Call Mirage → ask a question answered in Mirage's KB → agent answers correctly
- [ ] Call Downtown → same KB question → agent does not answer with Mirage's KB data

### 2.5 Staff Scoped to Location
- [ ] Call Mirage → ask for available staff → agent lists only Mirage staff
- [ ] Call Downtown → same question → agent lists only Downtown staff

### 2.6 Feature Flags Scoped to Location
- [ ] Enable SMS confirmation on Mirage, disable on Downtown
- [ ] Book appointment via Mirage call → SMS sent
- [ ] Book appointment via Downtown call → SMS NOT sent
- [ ] Enable "Missed Call Text-Back" on Downtown only → missed Downtown call sends text; missed Mirage call does not

### 2.7 SMS Sender Number
- [ ] SMS sent after Mirage booking uses Mirage's provisioned number as sender
- [ ] SMS sent after Downtown booking uses Downtown's number

### 2.8 Custom Schedule Active During Call
- [ ] Create an Agent-Disabled custom schedule active right now on Mirage
- [ ] Call Mirage → agent plays closure message and disconnects within ~6s
- [ ] Call Downtown (no active schedule) → agent handles normally

### 2.9 Gmail Emails
- [ ] Book an appointment via Mirage call → confirmation email sent FROM Mirage's connected Gmail
- [ ] Book via Downtown call → email sent FROM Downtown's connected Gmail
- [ ] If a location has no Gmail connected → no email sent (no error, no bleed to other location's Gmail)

### 2.10 Call Forwarding (Option B — Verbal Direction)
- [ ] Call Mirage → ask to speak with "Mirage Manager" → agent verbally directs caller
- [ ] Call Downtown → "Mirage Manager" contact is NOT offered

### 2.11 Call Forwarding (Option C — SIP REFER Transfer)
- [ ] Call Mirage → ask to transfer to forwarding contact → agent calls `forward_call()` → caller is bridged
- [ ] Check DB: `calls.status = forwarded`, `calls.forwarded_to` = correct contact UUID
- [ ] `calls.location_id` = Mirage's location ID

---

## 3. Agent Context — Outbound Call (Scheduler)

### 3.1 Reminder Call Uses Correct Location
- [ ] Enable "Reminder Calls" for Mirage only (not Downtown)
- [ ] Create appointment at Mirage for tomorrow
- [ ] Advance to the hourly tick (or temporarily lower interval) → outbound call is made FROM Mirage's number
- [ ] `calls` record has `location_id` = Mirage

### 3.2 Reschedule Call Uses Correct Location
- [ ] Enable "Reschedule Calls" for Downtown only
- [ ] Cancel an appointment at Downtown N days ago (per config)
- [ ] Scheduler fires → outbound call FROM Downtown's number
- [ ] Mirage's cancelled appointments are NOT called

### 3.3 Message Template Is Location-Specific
- [ ] Set different message templates for Mirage and Downtown reminder calls
- [ ] Agent opening script matches the configured template for the called location

---

## 4. New Location Seed

- [ ] Create a new location "Test Branch"
- [ ] Frontend calls `POST /locations/{id}/seed` after creation
- [ ] Navigate to Business Hours for "Test Branch" → default hours exist (copied from business-wide defaults)
- [ ] Agent Settings for "Test Branch" → default feature flags exist
- [ ] Services for "Test Branch" → seeded services visible

---

## 5. Authorization / Security

- [ ] Log in as User A (business X) → cannot read/write data for business Y via API (returns 403)
- [ ] Admin user can CRUD custom schedules; regular user cannot (RLS blocks)
- [ ] Agent tool `forward_call(contact_id)` with a contact from a different business → returns error, no transfer
- [ ] `book_appointment` during a call to Mirage cannot book into Downtown's staff availability

---

## 6. Regression — Cross-Location Bleed

- [ ] After switching locations in UI, no previous location's data leaks into network requests
- [ ] All API calls include the correct `location_id` query param for the selected location
- [ ] `useAppointments` does not fetch when no location is selected (returns empty, not all-business)
- [ ] `useServices` returns empty for a location with no services mapped (not all-business services)

---

*Last updated: 2026-04-17 (session 33)*
