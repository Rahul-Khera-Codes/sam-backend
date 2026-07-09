# Sales Employee — Market Agent (backend, MVP)
**Date:** 2026-07-07
**Branch:** `feature/sales-lead-researcher` (continuing same branch — same module family)
**Status:** Implemented and verified end-to-end — live-tested against a real business, all 7 cards (6 Exa-backed + Business Intelligence) completed successfully on the first real test, genuinely grounded and honest output (Business Intelligence card correctly reported "zero call activity" rather than inventing a pattern). No bugs found, unlike Lead Researcher and Competitor Agent which each surfaced a real bug on first live test. RLS applied and confirmed enforcing.

---

## Request
Third module of Sales Employee. A "Market Intelligence Feed" — 7 AI analyst cards (Trend, Futurist, Cultural, Market Research, Consumer Insights, Innovation Strategist, Business Intelligence) plus user-defined custom analysts, each grounded in real data (not the AI inventing plausible-sounding trends). Per today's scoping resolution: scheduled refresh + manual "refresh now," background job (no voice/chat component in this product), on Exa.ai.

## Phase 1 — Verified

**Exa.ai is a synchronous search API, not an async job platform like Apify.** Confirmed from Sam's setup-prompt doc: `POST /search` with `type` ranging from `instant` (~250ms) to `deep-reasoning` (12-40s worst case). This is a real architectural difference from Lead Researcher/Competitor Agent — **no webhook infrastructure needed for Exa itself.** Multiple analyst queries can run concurrently via `asyncio.gather`, bounded by the slowest single call (~40s worst case), well within a background job's tolerance.

**`outputSchema` + grounding is the key feature for this module.** Passing a JSON schema to `/search` returns synthesized, structured JSON directly in `output.content`, with per-field citations in `output.grounding` — this maps directly to what Sam described ("evidence, context, sources") and means Exa itself does the synthesis step, unlike Competitor Agent's separate scrape-then-GPT-synthesize two-step pipeline.

**"Business Intelligence Analyst" is a different beast from the other 6.** Per the original spec, it's about "patterns across the business's own operational data" — not external web research at all. Exa can't help here; this needs to read from *our own* database. Confirmed `backend/app/routers/analytics.py` already computes call-volume trends and summary metrics — reusable as the input for this one card instead of an Exa call.

**Scheduled-job precedent:** `backend/app/services/scheduler_service.py` (APScheduler, `AsyncIOScheduler`) already runs 3 hourly jobs (reminder/reschedule/no-show calls). Adding a new interval job here follows the exact existing pattern — no new scheduling infrastructure needed.

**Industry/business context for Exa queries:** `businesses.type` + `businesses.name` + `businesses.website` are the available fields to scope each analyst's query to the right industry — confirmed via schema check.

## Phase 2 — Architecture

### Data model (3 new tables)
1. **`market_custom_analysts`** — `id`, `business_id`, `name`, `prompt_description`, `created_at`, `updated_at`. User-defined analysts beyond the 7 built-in ones ("Add Custom Report" tile).
2. **`market_analysis_runs`** — `id`, `business_id`, `status` (`pending`/`running`/`synthesizing`/`completed`/`failed`), `triggered_by` (`scheduled`/`manual`), `whats_changing_summary`, `error_message`, `created_at`, `updated_at`. One row per refresh cycle.
3. **`market_analysis_cards`** — `id`, `run_id`, `business_id`, `analyst_type` (`trend`/`futurist`/`cultural`/`market_research`/`consumer_insights`/`innovation_strategist`/`business_intelligence`/`custom`), `analyst_name`, `headline`, `insight`, `confidence`, `timeframe_or_impact`, `sources_json`, `is_bookmarked`, `status`, `error_message`, `created_at`, `updated_at`. One row per analyst per run — persists across refreshes so bookmarking a specific insight and viewing history both work naturally, same reasoning as Competitor Agent's separate platform-runs table.

### Runtime flow
1. **Trigger** (scheduled job or `POST /market-agent/refresh`): create a `market_analysis_runs` row (`status=running`), then `asyncio.gather` across all 6 Exa-backed analysts (+ any custom analysts for the business) concurrently, plus the Business Intelligence card (reads `analytics.py`'s summary internally, no Exa call).
2. Each analyst call: tuned `systemPrompt` + `outputSchema` (fields: `headline`, `insight`, `confidence`, `timeframe`) scoped to the business's `type`/`name`. Write one `market_analysis_cards` row per analyst as each resolves (not waiting for all — cards can populate incrementally, matching the "feed" UX).
3. Once all analysts resolve (success or failure), synthesize `whats_changing_summary` (one more `gpt-4o-mini` call over all card headlines) and mark the run `completed`.
4. Reuse the dedupe-in-flight guard (skip starting a new run if one's already active for this business) and a stale-timeout guard (shorter than Competitor Agent's 15 min, given Exa's own worst case is ~40s — propose 5 min).
5. `GET /market-agent/cards?business_id=...` returns the **latest completed card per analyst type** — the main feed view.
6. `PATCH /market-agent/cards/{id}/bookmark` toggles bookmark on a specific card instance.
7. `POST` / `GET /market-agent/custom-analysts` — manage custom analyst definitions.
8. New APScheduler job (`run_market_agent_refresh`, daily) in `scheduler_service.py` — refreshes every business with an active custom-analyst or prior-run record. (Interval config — daily vs weekly — flagged as an open item below.)

### Analyst definitions (6 Exa-backed)
| Analyst | Query focus |
|---|---|
| Trend | Recent, concrete growth-pattern/trend shifts in the business's industry |
| Futurist | Credible 1-3 year predictions for the industry |
| Cultural | Social/cultural shifts affecting how people buy in this space |
| Market Research | Broader market/competitive landscape synthesis |
| Consumer Insights | Buyer behavior/preference trends |
| Innovation Strategist | Early signals of new ideas/technology worth watching |

**Business Intelligence** (7th, not Exa-backed): summarizes the business's own recent call-volume/appointment patterns via `analytics.py`'s existing summary logic + one `gpt-4o-mini` call to phrase it as an insight.

### New config
- `exa_api_key: str = ""` — header `x-api-key`, per the setup-prompt doc.

### Files
- `ai-employees-app/supabase/migrations/<timestamp>_market_agent.sql` — 3 tables + RLS from the start.
- `backend/app/core/config.py` — `exa_api_key`.
- `backend/.env.example` — `EXA_API_KEY=`.
- `backend/app/schemas/market_agent.py` (new).
- `backend/app/routers/market_agent.py` (new).
- `backend/app/services/scheduler_service.py` — add the new interval job.
- `backend/app/main.py` — register router.

## Real cost note (from Yuvraj's estimate, cross-checked against current Exa pricing)
~$0.02-0.05 per card × 7 cards ≈ **$0.15-0.35 per refresh, per business.** At a daily refresh, that's roughly **$4.50-10.50/month per business** in Exa costs alone, before the OpenAI synthesis calls on top. Worth confirming refresh frequency (daily vs weekly) with Sam given this is a real recurring per-business cost, not a one-time build cost.

## Not in scope for this spec
- Custom analyst UI (Yuvraj's scope) — backend just stores/uses the definitions.
- Any cross-module tie-in with Report Scheduler (not built yet).

## Open items
- Refresh interval — daily or weekly? Affects both cost and how "fresh" the feed feels. Proposing daily as the default, adjustable per business later if needed.
- Exact wording/tone for each analyst's `systemPrompt` — will tune once live-tested against a real business.
