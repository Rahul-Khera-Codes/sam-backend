# Appointment Status Buttons — Design Spec

**Date:** 2026-05-21
**Status:** Approved

---

## What We're Building

Add a "Appointment Status" section to the Edit Appointment dialog in Calendar with 3 one-click buttons: **Checked In**, **No Show**, **Cancelled Appointment**. Staff tap the button that matches what happened — no form save required.

When a client is marked **No Show**, the existing `noshow_followup` cron infrastructure automatically calls them N days later (N from Agent Settings config, default 1 day) to offer rescheduling.

---

## Status Values

The `appointments.status` column already exists (TEXT, default `'confirmed'`). We add two new values:

| Value | Meaning | Triggered by |
|---|---|---|
| `confirmed` | Booked, not yet happened | Default on creation |
| `checked_in` | Client arrived | "Checked In" button |
| `no_show` | Client didn't show | "No Show" button |
| `cancelled` | Appointment cancelled | "Cancelled Appointment" button |

The status buttons are for **logging what happened** — not the booking pipeline. No emails, no GCal changes. (Full cancellation with emails is still available via deleting the appointment.)

---

## Data

**New column:** `noshow_called_at TIMESTAMPTZ DEFAULT NULL` on `appointments` — same pattern as `reminder_called_at` / `reschedule_called_at`. Prevents the scheduler from calling the same client twice.

**No other DB changes needed.** `status` column already exists.

---

## Layers

### 1. DB Migration
`noshow_called_at TIMESTAMPTZ DEFAULT NULL` added to `appointments`.

### 2. Backend — `PATCH /appointments/{id}/status`
Lightweight endpoint — updates only the `status` column. No GCal, no emails, no availability check.

```
PATCH /appointments/{id}/status
Body: { business_id: str, status: str }
Auth: verify_business_access
```

Validates `status` is one of: `confirmed`, `checked_in`, `no_show`, `cancelled`.

### 3. Scheduler — `run_noshow_calls()`
Follows the exact same pattern as `run_reschedule_calls()`:
- Query: `status = 'no_show'` AND `noshow_called_at IS NULL` AND `appointment_date = today - N days`
- Config read from `agent_settings` where `feature_key = 'noshow_followup'` (`days`, `message_template`)
- Default template: `"Hi, we noticed you missed your recent appointment. We'd love to help you reschedule — would any of our available times work for you?"`
- Stamps `noshow_called_at` before triggering (prevents double-call)
- Registered in `start_scheduler()` on `hours=1` interval

### 4. Frontend API (`voiceAgentApi.ts`)
New function `updateAppointmentStatus(token, appointmentId, businessId, status)` → `PATCH /appointments/{id}/status`.

### 5. Frontend UI (`Calendar.tsx`)
New **"Appointment Status"** section at the **top** of the Edit Appointment dialog, above the form fields.

- 3 buttons in a row: Checked In (green), No Show (amber/orange), Cancelled (red/destructive)
- The button matching the current `appointment.status` appears **active/filled**; others appear outlined
- Clicking a button calls `updateAppointmentStatus()` immediately — no form save needed
- Local appointment state updated on success so the active button reflects the new status
- Buttons disabled while a status update is in flight (loading state)

---

## Appointment Status in Calendar Views

- Appointments with `status = 'checked_in'` → green tint in calendar
- Appointments with `status = 'no_show'` → amber tint in calendar
- Appointments with `status = 'cancelled'` → already filtered out (existing `.neq("status", "cancelled")` filter stays)

Optional — out of scope for this spec unless trivially implementable.

---

## Out of Scope

- Sending emails on status change via these buttons
- Google Calendar event updates on status change
- Displaying `noshow_called_at` timestamp in the UI
- Status history / audit log
