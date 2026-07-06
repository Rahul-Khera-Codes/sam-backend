# Sales Employee — Lead Researcher (backend, MVP)
**Date:** 2026-07-06
**Branch:** `feature/exec-agent-improvements` (or split to a new branch before implementing — TBD)
**Status:** Implemented and verified — Lead Researcher backend MVP complete on `feature/sales-lead-researcher` (both repos). Live-tested end-to-end 3x via curl against a real Apify actor run + real ngrok webhook round-trip; all 3 completed correctly (one was an accidental duplicate request, not a bug). Security review caught 2 secrets-in-URL issues (webhook secret, Apify API token) — both moved to headers and fixed before this was marked done.

---

## Request
First module of the Sales Employee ("AgenticBI") build: paste a LinkedIn profile URL → get back an enriched lead card (predicted email + confidence, job-role insights, pain points/sales angles, personal interests, best time to reach) + a generated outreach email draft. History + Saved Leads list. No CRM push yet (confirmed by Sam, deferred). Data source: Apify (confirmed by Sam 2026-06-24 — not revisited despite alternatives research, see `docs/lead-researcher-data-source-verification.md`).

---

## Phase 1 — Verified Current State

**Codebase:** genuinely greenfield — no sales/lead/apify code, DB tables, or migrations exist anywhere in `sam-backend` or `ai-employees-app` today. Frontend has only a generic "Coming Soon" placeholder at `/dashboard/sales` (`ai-employees-app/src/App.tsx:141`, `ComingSoonEmployee.tsx`) — nothing Lead-Researcher-specific to preserve.

**Router/schema convention** (from `executive.py`, `billing.py`): schemas in `backend/app/schemas/<name>.py` for multi-endpoint routers; every protected endpoint takes `user_id: str = Depends(get_user_id)` + `verify_business_access(user_id, business_id)` (`backend/app/core/auth.py:56`); reads use `supabase_admin` to bypass RLS.

**Async job precedent:** none in `backend/`. Zero `BackgroundTasks` usage anywhere. The only async-flow precedent in the whole system is `agent/agent.py:1910`'s fire-and-forget `asyncio.ensure_future` inside the long-running agent process — not a reusable request/response pattern. This build is the **first** async-job pattern in the FastAPI backend.

**API key config convention:** `Settings` field with empty-string default in `backend/app/core/config.py` (e.g. `stripe_exec_agent_price_id` at line 53) + matching `.env.example` line.

**Apify data source — live-verified 2026-07-06** (`docs/lead-researcher-data-source-verification.md`):
- Actor: `data-slayer/linkedin-profile-scraper`
- Base scrape: ~$0.015/profile, a few seconds, rich accurate data (work history, education, skills, headline, company)
- With "find verified work email": ~$0.03/profile, **2+ minutes latency**, confidence comes back as a weak status (`catch_all`) not a numeric score
- Apify supports webhooks on actor-run completion, passed directly in the Run Actor API call — confirmed via current docs (docs.apify.com/platform/integrations/webhooks), so no polling loop needed against Apify itself.
- Nothing in the raw scrape maps to "pain points/sales angles," "best time to reach," or "personal interests" — needs an LLM enrichment step on top.

**Deployment:** production backend is fully deployed on a stable subdomain (usable as the Apify webhook callback target). Local dev needs ngrok when testing the webhook round-trip specifically.

---

## Phase 2 — Architecture

### Runtime flow
1. `POST /sales/lead-researcher/lookup` — validates `business_id` via `verify_business_access`, inserts a `pending` row into `lead_lookups`, calls Apify's Run Actor API with a `webhooks` param pointing at our callback URL, returns the lookup `id` immediately (no blocking wait).
2. Apify runs the scrape + email lookup (2+ min), then POSTs to our webhook on completion.
3. `POST /sales/lead-researcher/webhook` — Apify's callback. Fetches the run's dataset, stores `raw_scrape_json`, runs an LLM enrichment step (`gpt-4o-mini` — text-only, not voice, so no Realtime cost) with structured JSON output to generate the card's derived fields + outreach email draft, writes `enriched_result_json`, sets `status=completed` (or `failed` with `error_message` on any error).
4. `GET /sales/lead-researcher/lookup/{id}` — frontend polls this for status + result.
5. `GET /sales/lead-researcher/history` — list past lookups for the business.
6. `PATCH /sales/lead-researcher/lookup/{id}/save` — toggles `is_saved`.

### Confidence honesty (product decision, not just technical)
Apify's `catch_all`-style status is a weak signal — the frontend/copy should present it as "unverified guess" rather than implying a verified deliverable email, to avoid over-promising accuracy the underlying data doesn't have.

---

## Files + Changes

### 1. `ai-employees-app/supabase/migrations/<timestamp>_lead_lookups.sql`
New table: `id`, `business_id`, `user_id`, `linkedin_url`, `status` (`pending`/`running`/`completed`/`failed`), `apify_run_id`, `raw_scrape_json` (jsonb), `enriched_result_json` (jsonb), `error_message`, `is_saved boolean default false`, `created_at`, `updated_at`.

### 2. `backend/app/core/config.py`
Add `apify_api_token: str = ""` (empty-string default, same pattern as Stripe fields).

### 3. `backend/.env.example`
Add `APIFY_API_TOKEN=` with a comment.

### 4. `backend/app/schemas/sales.py` (new)
`LeadLookupRequest`, `LeadLookupResponse`, `LeadCardResult` — card fields matching the mockup (predicted email + confidence, job-role insights, pain points/sales angles, personal interests, best time to reach) + outreach email draft.

### 5. `backend/app/routers/sales.py` (new)
The 5 endpoints described above (lookup, webhook, status, history, save-toggle). Registered in the app's router include list (wherever other routers are mounted — need to check `backend/app/main.py` at implementation time).

---

## Not in scope for this spec
- Frontend UI (Yuvraj's scope) — JSON contract will be handed off once endpoints exist.
- Competitor Agent, Market Agent, Report Scheduler (later modules).
- CRM push (explicitly deferred by Sam).
- Legal sign-off on scraped-lead outreach (Sam running by his lawyer — doesn't block build, blocks public launch).

## Open items — resolved
- Branch: created `feature/sales-lead-researcher` in both repos (not `feature/exec-agent-improvements`).
- Router registered in `backend/app/main.py` alongside the other routers (`app.include_router(sales_router.router)`).

## Remaining before this ships to real users
- Frontend UI (Yuvraj's scope) — needs the JSON contract for `POST /lookup`, `GET /lookup/{id}`, `GET /history`, `PATCH /lookup/{id}/save`.
- Production `.env` needs real values for `APIFY_API_TOKEN` (currently Rahul's personal/temporary key), `APIFY_WEBHOOK_BASE_URL` (a real deployed subdomain, not the ngrok tunnel used for local testing), `APIFY_WEBHOOK_SECRET`.
- Apify account is still Rahul's personal one — message to Sam about a company account still pending (see TODO.md).
- Legal sign-off on scraped-lead outreach — Sam running by his lawyer, doesn't block build.
