# Sales Employee — Competitor Agent (backend, MVP)
**Date:** 2026-07-06
**Branch:** `feature/sales-lead-researcher` (continuing on the same branch as Lead Researcher — same module family)
**Status:** Implemented and verified end-to-end — live-tested against a real competitor (hubspot.com) with the actual fan-out (LinkedIn + Facebook + Instagram via Apify, YouTube via the official API), full synthesis produced a genuinely usable report. Two real bugs found and fixed during testing (see below).

## Bugs found during live testing (fixed)
1. **Footer truncation bug** — `content[:20_000]` silently dropped hubspot.com's social links, which sat at ~char 56,500 of a 60,510-char page (footer, as expected — but past the truncation cutoff). Every discovered URL came back `null`. Fixed with a head+tail keep (`_head_and_tail`) instead of a blind head-truncate.
2. **Legacy YouTube URL format** — HubSpot's own YouTube link is the old `/user/HubSpot` form, which the parser didn't handle (only `/@handle` and `/channel/UC...`). Confirmed `forUsername` is still live (not deprecated) on the current `channels.list` API and added support.
3. Also stripped tracking query strings (`?hubs_content=...`) from discovered URLs before they're used as scraper input — HubSpot appends these to every social link on their site.

## Real-world data quality note
Instagram's platform result came back "no recent activity found" for HubSpot, a very active brand — most likely the Instagram actor's data return is weak/limited (Instagram's anti-scraping is the strictest of the three platforms), not that they're actually inactive. This should be surfaced honestly in the UI (e.g. "limited data available") rather than presented as verified fact, same caveat class as Lead Researcher's `catch_all` email confidence.

## Usage note for the frontend
`POST /competitors/{id}/report` always starts a **new** report — it is not a "check status" call. To poll an existing report's progress, use `GET /competitors/{id}/reports/{report_id}` with the specific report ID returned from the POST. Calling POST repeatedly to "check progress" will keep starting new (paid) Apify runs instead of checking the existing one — confirmed this confusion is easy to hit during manual testing.

---

## Request
Second module of Sales Employee. Owner adds a competitor by pasting their website URL. Each tracked competitor shows presence icons for LinkedIn/Facebook/Instagram/YouTube. "View Report" pulls current activity across those platforms (pricing changes, feature launches, news, general activity) into one report. Per the confirmed scoping decision today: **build without the news component first** — news needs a vendor decision (Currents/TheNewsAPI/Mediastack/GNews, $25-90/mo) shared with Market Agent; add it once that's picked. "Schedule Report" is explicitly out of scope for this module — that's Report Scheduler's job, which doesn't exist yet.

---

## Phase 1 — Verified

- Website→social-link discovery: reuse the existing Jina AI Reader + GPT pattern from `knowledge_base.py` (`backend/app/routers/knowledge_base.py`) — synchronous, no new integration.
- Apify actors + exact input schemas confirmed against current docs (not assumed from training data):
  - LinkedIn company: `data-slayer~linkedin-company-scraper`, input `{"linkedin_url": "..."}`
  - Facebook: `apify~facebook-posts-scraper`, input `{"startUrls": [{"url": "..."}], "resultsLimit": N}`
  - Instagram: `apidojo~instagram-scraper`, input `{"startUrls": ["..."], "maxItems": N}`
- YouTube: **official YouTube Data API v3**, not Apify — free within quota, and the one ToS-compliant platform here. Use `channels.list` (resolve handle → uploads playlist ID) + `playlistItems.list` (recent videos) — NOT `search.list`, which costs 100 quota units/call vs ~1 for list calls (10,000/day budget).
- Async pattern precedent: Lead Researcher's Apify-run + webhook design (`backend/app/routers/sales.py`) — reused here, but this module needs **fan-out**: up to 3 concurrent Apify runs per report (LinkedIn/Facebook/Instagram) plus one synchronous YouTube call, and a join step that only synthesizes the final report once all platforms are done.

## Phase 2 — Architecture

### Data model (3 new tables)
1. **`competitors`** — `id`, `business_id`, `name`, `website_url`, `linkedin_url`/`facebook_url`/`instagram_url`/`youtube_url` (nullable, filled by discovery), `discovery_status` (`pending`/`completed`/`failed`), `created_at`, `updated_at`.
2. **`competitor_reports`** — `id`, `competitor_id`, `business_id`, `status` (`pending`/`running`/`synthesizing`/`completed`/`failed`), `report_json`, `error_message`, `created_at`, `updated_at`.
3. **`competitor_report_platform_runs`** — `id`, `report_id`, `platform` (`linkedin`/`facebook`/`instagram`/`youtube`), `status` (`skipped`/`running`/`completed`/`failed`), `apify_run_id` (null for youtube), `raw_data_json`, `error_message`, `created_at`, `updated_at`.

**Why a separate platform-runs table, not a JSONB column on `competitor_reports`:** up to 3 webhooks can arrive nearly simultaneously. A shared JSONB column would need read-modify-write per webhook, risking lost updates under concurrent delivery. Separate rows mean each webhook does an independent `UPDATE ... WHERE id=...` — no race.

### Runtime flow

**Add competitor:**
1. `POST /competitors` `{business_id, website_url}` → insert `competitors` row (`discovery_status=pending`) → scrape site via Jina Reader → GPT extracts social links → update row with discovered URLs, `discovery_status=completed`. Synchronous (matches the existing website-scrape convention's speed).

**Generate report:**
1. `POST /competitors/{id}/report` → insert `competitor_reports` row (`status=pending`) → for each platform URL that exists, insert a `competitor_report_platform_runs` row and kick off its Apify run + webhook (LinkedIn/Facebook/Instagram) or call the YouTube Data API inline (fast, synchronous — mark that row `completed` immediately). Flip `competitor_reports.status` to `running`.
2. `POST /competitor-agent/webhook` (one shared route, disambiguated by `apify_run_id` like Lead Researcher's) — on each platform's completion, update that platform's row, then check if all platform rows for the report are terminal. **Concurrency-safe claim:** attempt `UPDATE competitor_reports SET status='synthesizing' WHERE id=... AND status='running'` — only the webhook call that actually flips the row proceeds to synthesis; the others no-op. This prevents duplicate LLM synthesis calls if two webhooks land at nearly the same time.
3. Synthesis: one LLM call combining all `raw_data_json` from the platform runs into `report_json` (features, pricing signals, activity summary per platform) → `status=completed`.
4. Reuse Lead Researcher's dedupe-in-flight guard (don't start a second report while one's `pending`/`running`/`synthesizing` for the same competitor) and stale-timeout guard (mark `failed` if stuck past a reasonable window — needs to be longer than Lead Researcher's 10 min given up to 3 parallel runs, e.g. 15 min).

### New config
- `youtube_api_key: str = ""` — a plain API key (not OAuth, unlike the existing Google Calendar/Gmail client), enabled on the same Google Cloud project.

### Files
- `ai-employees-app/supabase/migrations/<timestamp>_competitor_agent.sql` — 3 tables + RLS (matching the `business_documents`/`lead_lookups` pattern from the start, not added after the fact this time).
- `backend/app/core/config.py` — `youtube_api_key`.
- `backend/.env.example` — `YOUTUBE_API_KEY=`.
- `backend/app/schemas/competitor_agent.py` (new).
- `backend/app/routers/competitor_agent.py` (new) — mirrors `sales.py`'s structure but with the fan-out/join logic.
- `backend/app/main.py` — register the new router.

## Not in scope for this spec
- News integration (deferred, shared decision with Market Agent).
- "Schedule Report" (Report Scheduler's job).
- Auto-discovery of competitors (this module is manually-curated per the mockup — "added by pasting their website URL").

## Open items
- Exact `report_json` shape for the synthesis LLM step — will define alongside the API contract doc once built, same as Lead Researcher's `LeadCardResult`.
- Stale-timeout duration for the multi-platform case (proposing 15 min, up for adjustment).
