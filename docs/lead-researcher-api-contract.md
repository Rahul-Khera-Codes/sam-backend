# Lead Researcher — API Contract (for frontend/UI work)

**Date:** 2026-07-06
**Backend status:** implemented + verified end-to-end (real Apify runs + webhook, 3x live-tested). See `docs/superpowers/specs/2026-07-06-sales-lead-researcher.md` for full backend detail.

This covers the 4 endpoints the Lead Researcher UI needs. All require the normal `Authorization: Bearer <supabase-jwt>` header, same as every other endpoint in this API.

---

## 1. Start a lookup

```
POST /sales/lead-researcher/lookup
```

**Request body:**
```json
{
  "business_id": "uuid",
  "linkedin_url": "https://linkedin.com/in/some-profile"
}
```

**Response (200):**
```json
{ "id": "uuid", "status": "running" }
```

**Important:** this call returns immediately — it does **not** wait for the result. The actual lookup takes **~2-3 minutes** (real measured time, includes an email-verification step). Design the UI as async: show a "researching..." state and poll `GET /lookup/{id}` (below) every ~10-15 seconds until `status` is `completed` or `failed`. Don't build this as a blocking spinner-then-result flow — it will look broken if the UI just hangs for 2+ minutes.

If you call this twice in a row for the same `business_id` + `linkedin_url` while one is still running, it returns the **same** `id` instead of starting a second lookup — safe to call again if you're not sure whether one's already in flight (e.g. after a page refresh).

**Error responses:**
- `403` — user doesn't have access to this business, or Apify isn't configured yet for this environment
- `503` — Apify token/webhook URL not configured

---

## 2. Poll for status/result

```
GET /sales/lead-researcher/lookup/{id}
```

**Response (200) — while running:**
```json
{
  "id": "uuid",
  "business_id": "uuid",
  "linkedin_url": "https://linkedin.com/in/some-profile",
  "status": "running",
  "error_message": null,
  "is_saved": false,
  "result": null,
  "created_at": "2026-07-06T08:53:11.683446+00:00",
  "updated_at": "2026-07-06T08:53:11.683446+00:00"
}
```

**Response (200) — completed:**
```json
{
  "id": "uuid",
  "business_id": "uuid",
  "linkedin_url": "https://linkedin.com/in/some-profile",
  "status": "completed",
  "error_message": null,
  "is_saved": false,
  "result": {
    "full_name": "Jane Doe",
    "job_title": "VP of Engineering",
    "company_name": "Example Corp",
    "predicted_email": "jane@example.com",
    "email_confidence": "catch_all",
    "job_role_insights": "...",
    "pain_points_and_sales_angles": "...",
    "personal_interests": "Not enough data to infer.",
    "best_time_to_reach": "Weekday mornings, based on typical work hours for their timezone.",
    "outreach_email_draft": "Subject: ...\n\nHi Jane, ..."
  },
  "created_at": "...",
  "updated_at": "..."
}
```

**`status` values:** `pending` → `running` → `completed` | `failed`. On `failed`, `error_message` explains why (Apify error, no profile data returned, AI enrichment error, or a timeout if Apify's webhook never arrived after ~10 min).

**On `email_confidence`:** this is a status string (e.g. `"catch_all"`), not a percentage/score. `catch_all` means the email domain accepts any address — it's a plausible guess, not a verified deliverable mailbox. **Please don't show this as "Verified"** in the UI — something like "Unverified guess" or showing the raw status with a tooltip is more honest. Can be `null` if no email was found at all.

---

## 3. History (past lookups for a business)

```
GET /sales/lead-researcher/history?business_id=uuid
```

**Response (200):**
```json
{ "lookups": [ /* array of the same object shape as endpoint 2, newest first */ ] }
```

---

## 4. Save / unsave a lookup

```
PATCH /sales/lead-researcher/lookup/{id}/save
```

**Request body:**
```json
{ "is_saved": true }
```

**Response (200):** same shape as endpoint 2, with `is_saved` updated. This is what backs the "Saved Leads" list in the mockup — same `history` list, filtered client-side (or query param later if needed) by `is_saved: true`.

---

## Not built yet (don't build UI for these)
- Export PDF / Push to CRM buttons from the mockup — backend doesn't do either yet.
- Retry button for a `failed` lookup — not built; for now a failed lookup needs a fresh `POST /lookup` call with the same inputs.
