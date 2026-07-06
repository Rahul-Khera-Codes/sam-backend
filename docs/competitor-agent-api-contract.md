# Competitor Agent — API Contract (for frontend/UI work)

**Date:** 2026-07-06
**Backend status:** implemented + verified end-to-end (real fan-out across LinkedIn/Facebook/Instagram/YouTube against a real competitor, hubspot.com). See `docs/superpowers/specs/2026-07-06-sales-competitor-agent.md` for full backend detail.

All endpoints require the normal `Authorization: Bearer <supabase-jwt>` header.

---

## 1. Add a competitor

```
POST /sales/competitor-agent/competitors
```

**Request body:**
```json
{ "business_id": "uuid", "website_url": "https://example.com" }
```

**Response (200):** returns immediately (a few seconds — this step is just a website scrape + one AI call, not a scraper job).
```json
{
  "id": "uuid",
  "business_id": "uuid",
  "name": "Example Inc",
  "website_url": "https://example.com",
  "linkedin_url": "https://www.linkedin.com/company/example",
  "facebook_url": "https://www.facebook.com/example",
  "instagram_url": "https://www.instagram.com/example/",
  "youtube_url": "https://youtube.com/@example",
  "discovery_status": "completed",
  "error_message": null,
  "created_at": "...",
  "updated_at": "..."
}
```

Any of the 4 platform URLs can be `null` if that platform wasn't found on the competitor's site — this is expected, not an error. `discovery_status` can be `pending`/`completed`/`failed`; if `failed`, `error_message` explains why (e.g. the website couldn't be read at all). This is the icon row shown per competitor in the mockup — a `null` URL means don't show that platform's icon (or show it greyed out).

---

## 2. List tracked competitors

```
GET /sales/competitor-agent/competitors?business_id=uuid
```

**Response (200):**
```json
{ "competitors": [ /* array of the same shape as endpoint 1, newest first */ ] }
```

---

## 3. Generate a report — ⚠️ important usage note

```
POST /sales/competitor-agent/competitors/{competitor_id}/report
```

**No request body needed.**

**This call ALWAYS starts a new report — it is not a status check.** Real measured time is **~10-60 seconds** typically (much faster than Lead Researcher's 2-3 min — these platform scrapers tend to resolve quickly), but treat it as async regardless: the response comes back immediately with a status, and the actual work happens in the background.

**Do not call this repeatedly to "check progress."** If you call it again while a report is still in flight for the same competitor, it correctly returns the *same* in-progress report (no duplicate work) — but once that report finishes, calling this endpoint again starts a **brand new** report and a **new round of paid scraping**. Use endpoint 4 below to poll an existing report by its ID instead.

**Response (200):**
```json
{ "id": "uuid", "status": "running" }
```

`status` can also come back `failed` immediately if the competitor has no discovered social platforms at all.

**Error (503):** Apify not configured yet for this environment.

---

## 4. Poll a report's status/result

```
GET /sales/competitor-agent/competitors/{competitor_id}/reports/{report_id}
```

**This is what you should poll** — every ~5-10 seconds is reasonable given the shorter typical runtime.

**Response (200) — while running:**
```json
{
  "id": "uuid",
  "competitor_id": "uuid",
  "business_id": "uuid",
  "status": "running",
  "error_message": null,
  "result": null,
  "created_at": "...",
  "updated_at": "..."
}
```

**Response (200) — completed:**
```json
{
  "id": "uuid",
  "competitor_id": "uuid",
  "business_id": "uuid",
  "status": "completed",
  "error_message": null,
  "result": {
    "overview": "2-3 sentence overall summary",
    "platforms": [
      {
        "platform": "linkedin",
        "summary": "...",
        "pricing_signals": "Nothing found. (or a real signal if found)",
        "feature_launches": "Nothing found. (or a real signal if found)",
        "general_activity": "..."
      }
      /* one entry per platform that had data — a platform with no discovered
         URL, or whose scrape failed, just won't appear in this array */
    ]
  },
  "created_at": "...",
  "updated_at": "..."
}
```

**`status` values:** `pending` → `running` → `synthesizing` → `completed` | `failed`. On `failed`, `error_message` explains why.

**Important UI note — data quality varies by platform.** In real testing, Instagram's scraper came back with much thinner data than LinkedIn/Facebook (Instagram's anti-scraping is the strictest of the three). If a platform's `general_activity`/`summary` reads as "no activity found," that may reflect scraper limitations rather than the competitor actually being inactive — consider showing something like "limited data available" for sparse platforms rather than presenting it as a confirmed fact.

---

## 5. List past reports for a competitor

```
GET /sales/competitor-agent/competitors/{competitor_id}/reports
```

**Response (200):**
```json
{ "reports": [ /* array of the same shape as endpoint 4, newest first */ ] }
```

---

## Not built yet (don't build UI for these)
- News integration in the report (deferred — shared vendor decision with Market Agent, not yet made).
- "Schedule Report" button from the mockup (that's Report Scheduler's job, not built yet).
- Auto-discovery of competitors — this module is manually-curated (add by pasting a website URL), not automatic.
