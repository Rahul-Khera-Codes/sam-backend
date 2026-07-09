# Report Scheduler — API Contract (for frontend/UI work)

**Date:** 2026-07-07
**Backend status:** implemented + verified end-to-end (real schedule created, previewed, and a real test email received via Gmail). See `docs/superpowers/specs/2026-07-07-sales-report-scheduler.md` for full backend detail.

All endpoints require the normal `Authorization: Bearer <supabase-jwt>` header. Unlike the other 3 Sales Employee modules, **everything here is synchronous** — no polling needed, no external API calls at request time.

---

## 1. Create a schedule

```
POST /sales/report-scheduler/schedules
```
```json
{
  "business_id": "uuid",
  "name": "Weekly Sales Digest",
  "frequency": "weekly",
  "recipients": ["owner@example.com", "sales@example.com"],
  "include_lead_researcher": true,
  "include_competitor_agent": true,
  "include_market_agent": true,
  "is_active": false
}
```

`frequency` must be `daily`, `weekly`, or `monthly` (the mockup's "custom" option isn't built — flag if that's actually needed). `recipients` entries are validated as email-format strings — malformed ones are rejected with a 422. New schedules default to `is_active: false` — nothing sends until the owner turns it on.

**Response (200):** the created schedule (same shape as the request, plus `id`, `last_sent_at: null`, timestamps).

---

## 2. List / update / delete schedules

```
GET    /sales/report-scheduler/schedules?business_id=uuid
PATCH  /sales/report-scheduler/schedules/{id}
DELETE /sales/report-scheduler/schedules/{id}
```

`PATCH` accepts any subset of the create fields — only send what changed. This is how the on/off toggle works: `PATCH { "is_active": true }`.

---

## 3. Live preview

```
GET /sales/report-scheduler/schedules/{id}/preview
```

**Response (200):**
```json
{ "subject": "Business Name — Sales Intelligence Digest", "html_body": "<!DOCTYPE html>..." }
```

Render `html_body` directly (e.g. in an iframe or sandboxed container) for the "what will this email look like" preview. This reflects live data — call it again after the underlying data changes to see an updated preview. No side effects, safe to call as often as needed.

---

## 4. Send test email

```
POST /sales/report-scheduler/schedules/{id}/send-test
```

**No request body.** Sends a real email to **your own address** (from your login), not the schedule's configured recipient list — this is intentional, so testing doesn't spam real recipients. Does **not** update `last_sent_at` — sending a test never causes a real scheduled send to be skipped.

**Response (200):**
```json
{ "sent": true, "detail": "Test email sent to you@example.com." }
```

If `sent: false`, `detail` explains why — almost always because Gmail isn't connected for that business yet (Business Settings → Integrations).

---

## How the real scheduled sends work (informational, not something the UI calls directly)
An hourly backend job checks every `is_active: true` schedule and sends if it's due per its `frequency` (daily: 24h since last send, weekly: 7 days, monthly: 30 days). If a schedule has no `recipients`, it's silently skipped — the UI should probably prevent turning `is_active` on with an empty recipient list, since it would otherwise just sit there doing nothing.

## Content notes
- If a business has no data for an included module (e.g. never used Competitor Agent), that section is simply omitted from the email — not shown as empty.
- All content is HTML-escaped before being embedded in the email, so any unusual characters in lead names, competitor summaries, etc. will render as literal text, not broken formatting.
