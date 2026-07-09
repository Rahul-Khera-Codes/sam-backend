# Market Agent — API Contract (for frontend/UI work)

**Date:** 2026-07-07
**Backend status:** implemented + verified end-to-end (real refresh against a real business, all 7 cards completed cleanly). See `docs/superpowers/specs/2026-07-07-sales-market-agent.md` for full backend detail.

All endpoints require the normal `Authorization: Bearer <supabase-jwt>` header.

---

## 1. Trigger a refresh

```
POST /sales/market-agent/refresh?business_id=uuid
```

**No request body.** In real testing this completed in well under a minute (Exa's own worst case is ~40s, and most cards resolve much faster), but still treat this as async: it's a background job under the hood, and a scheduled daily refresh runs automatically for any business that's used this feature before, independent of what the UI does. If you call this while a refresh is already active for the business, it returns the *same* in-progress run instead of starting a duplicate — safe to call again if unsure.

**Response (200):**
```json
{ "id": "uuid", "status": "completed" }
```

`status` can be `running`/`synthesizing`/`completed`/`failed`. On `failed`, check the run via endpoint 2 for `error_message`.

**Error (503):** Exa not configured yet for this environment.

---

## 2. Poll a specific run

```
GET /sales/market-agent/runs/{run_id}
```

**Response (200):**
```json
{
  "id": "uuid",
  "business_id": "uuid",
  "status": "completed",
  "triggered_by": "manual",
  "whats_changing_summary": "2-3 sentence top-of-page summary across all cards",
  "error_message": null,
  "cards": [
    {
      "id": "uuid",
      "run_id": "uuid",
      "business_id": "uuid",
      "analyst_type": "trend",
      "analyst_name": "Trend Analyst",
      "headline": "...",
      "insight": "...",
      "confidence": "high",
      "timeframe_or_impact": "Happening now (2026)",
      "sources": [ { "url": "...", "title": "..." } ],
      "is_bookmarked": false,
      "status": "completed",
      "error_message": null,
      "created_at": "...",
      "updated_at": "..."
    }
    /* one entry per analyst — 6 built-in + Business Intelligence + any custom analysts */
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

`analyst_type` is one of: `trend`, `futurist`, `cultural`, `market_research`, `consumer_insights`, `innovation_strategist`, `business_intelligence`, `custom`. The **Business Intelligence** card has an empty `sources` array — it's generated from this business's own call analytics, not external search, so there's nothing to cite.

---

## 3. Get the feed (latest card per analyst)

```
GET /sales/market-agent/cards?business_id=uuid
```

**This is the main "Market Intelligence Feed" view** — returns the most recent *completed* card for each analyst type (not the full history), one per analyst. If a business has multiple custom analysts, each gets its own entry (keyed by name).

**Response (200):**
```json
{ "cards": [ /* array of the same card shape as above */ ] }
```

For the "What's Changing" top-of-page summary, use the `whats_changing_summary` from the most recent run (endpoint 2) — it's not duplicated onto this endpoint.

---

## 4. Bookmark a card

```
PATCH /sales/market-agent/cards/{card_id}/bookmark
```

**Request body:**
```json
{ "is_bookmarked": true }
```

**Response (200):** the updated card, same shape as above.

---

## 5. Custom analysts ("Add Custom Report")

```
POST /sales/market-agent/custom-analysts
```
```json
{ "business_id": "uuid", "name": "My Custom Analyst", "prompt_description": "What this analyst should research, in plain English" }
```

```
GET /sales/market-agent/custom-analysts?business_id=uuid
```
Returns `{ "custom_analysts": [...] }`. Any custom analyst defined here automatically gets included in every future refresh (manual or scheduled) — no separate step needed to "activate" it.

---

## Not built yet
- Deleting/editing a custom analyst.
- News integration (this was the original "News aggregation" pipeline step — Exa's general web search covers a lot of the same ground for Market Agent, but nothing here is scoped as strictly "news").
