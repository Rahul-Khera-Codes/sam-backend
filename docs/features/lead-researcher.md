# Sales Employee: Lead Researcher AI Agent

## What it does
Given a LinkedIn profile URL, scrapes the profile via an Apify actor and enriches it with an
LLM (OpenAI `gpt-4o-mini`) into a lead report — job-role insights, pain points/sales angles,
personal interests, best time to reach, and a draft outreach email. It's one module of the
"Sales Employee" (`ai-employees-app/src/pages/dashboard/sales/LeadResearcher.tsx`, route
`/dashboard/sales/lead-researcher`), with three tabs: New Analysis, History, Saved Leads.

## Key files
**Backend** (`sam-backend/backend/app/routers/sales.py`, prefix `/sales/lead-researcher`):
- `POST /lookup` — starts an Apify actor run, inserts a `lead_lookups` row (`status: "pending"`
  → `"running"`), returns immediately with the row id. Does not block on the scrape/enrichment.
- `POST /webhook` — called by Apify's own infrastructure (not the browser) when the actor run
  finishes. Fetches the scraped dataset, runs `_enrich_lead()` (the LLM call), and writes the
  final `status`/`enriched_result_json` to the same `lead_lookups` row.
- `GET /lookup/{id}` — reads one row's current status/result.
- `GET /history` — lists a business's lookups (used by History/Saved Leads tabs).

**Frontend** (`ai-employees-app`):
- `src/pages/dashboard/sales/LeadResearcher.tsx` — the three-tab page.
- `src/components/sales/NewAnalysisTab.tsx` — URL input + "Generate Report" + in-progress/result
  display for the lookup the user just started.
- `src/components/sales/LeadHistoryTab.tsx` — used for both History and Saved Leads; self-polls
  `GET /history` every 8s while any lookup is `"running"`.
- `src/hooks/useLeadLookupPolling.ts` — polls `GET /lookup/{id}` every 12s until a terminal
  status (`completed`/`failed`).
- `src/contexts/LeadResearchContext.tsx` — see below.

## Why processing is backend-driven, not request-driven
The scrape + enrichment work happens entirely inside the Apify webhook handler, triggered by
Apify's servers, not inside any request initiated by the browser. There is no
`request.is_disconnected()` logic and none is needed — a lookup keeps running and its result
gets persisted to Supabase regardless of whether the user's browser is even open.

## State architecture (AIE-59 fix, 2026-09-08)
The active `lookupId` and its polling (`useLeadLookupPolling`) live in
`src/contexts/LeadResearchContext.tsx` (`LeadResearchProvider` / `useLeadResearchState`), not in
local `useState` inside `NewAnalysisTab`. The provider is mounted once in
`src/components/layout/DashboardLayout.tsx`, wrapping the `<Outlet />` that swaps between every
`/dashboard/*` page — not just Sales Employee's own tabs.

**Why:** `NewAnalysisTab` unmounts whenever the user switches to History/Saved Leads (Radix
`TabsContent` without `forceMount`) or navigates to a different AI employee entirely. Before
this fix, `lookupId` was local `useState`, so the backend job kept running fine but the New
Analysis view lost all memory of it — looking to the user like "the agent stopped" (AIE-59 bug
report), even though `LeadHistoryTab` already had its own self-poll (added 2026-07-10,
`ai-employees-app/docs/specs/2026-07-10-lead-researcher-history-polling.md`) that correctly
showed completed results in History. Lifting `lookupId` + the poll to a context mounted above
the whole dashboard `<Outlet />` means the New Analysis tab also reflects the completed result
no matter what page the user navigated to in the meantime.

The provider resets `lookupId` to `null` whenever the effective `businessId` changes (including
starting/ending impersonation), so a report from one business can't leak into another business's
New Analysis view.

**Known limitation:** this covers in-app navigation within the same browser tab. A hard page
reload or opening the app in a separate browser tab/window still loses the in-flight
`lookupId` — the user falls back to the History tab in that case, same as before this fix.

**How to apply:** any future state that should survive Sales Employee page navigation belongs in
`LeadResearchProvider`, not local `useState` in a tab component — same convention as
`MarketingCreatePostContext` (see `marketing-create-post.md`).
