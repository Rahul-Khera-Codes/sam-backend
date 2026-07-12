# Market Agent — Meeting Brief

*Reference doc covering what Market Agent is, how it works, its current status, and the open issue from Sam's feedback (Jul 9, 2026).*

---

## 1. What it is

Market Agent is one of the 4 Sales Employee modules ("AgenticBI"). It's a market-intelligence feed: a set of AI "analyst" cards that each research a different angle on trends relevant to the business, refreshed daily (or on manual trigger).

## 2. How it works

**7 cards per refresh:**

| Card | What it researches |
|---|---|
| Trend Analyst | Recent, concrete growth patterns and trend shifts in the business's industry |
| Futurist | Credible predictions for the next 1-3 years in the industry |
| Cultural Analyst | Social/cultural shifts affecting how people buy in the industry |
| Market Research Analyst | Market and competitive landscape analysis for the industry |
| Consumer Insights Analyst | Buyer behavior and preference trends in the industry |
| Innovation Strategist | Early signals of new technology/ideas worth watching in the industry |
| Business Intelligence | Reads the business's own real call-volume analytics (not the web) |

The first 6 run through Exa.ai (a search API built for AI agents — returns grounded, cited results, not free-form generation). Each one's search is templated as *"[topic] in the `{industry}` industry"* — `{industry}` is filled in from the business's own record.

**Custom Analysts:** a business can also add their own analyst with a free-text prompt (e.g., "Pricing Watchdog" — watch for pricing changes among competitors). Already shipped and working today, independent of anything below.

**Refresh:** daily automatic (APScheduler job) + manual "Refresh" button. All 6 Exa searches run concurrently (~40s worst case); no webhook infra needed (Exa is synchronous, unlike Apify).

## 3. Current status

- All 4 Sales Employee modules (Lead Researcher, Competitor Agent, Market Agent, Report Scheduler) shipped and live-verified on the deployed production site as of session 59 (2026-07-09).
- Market Agent specifically: live-tested clean on first try during initial build (no bugs found then) — the issue below only surfaced once Sam tested against his own real business.

## 4. The open issue (Sam's feedback, Jul 9)

Sam's exact feedback: *"Market Intelligence Feed: How can you see the report and what is the prompt? This report needs to be relevant to the business, its own industry and market. Lets discuss this."*

**Root cause (confirmed, not guessed):** `{industry}` above comes from a single dropdown field on the business record (`businesses.type`). Its options are shallow (Restaurant, Professional, Landscaping, Other, etc.), and many real businesses don't have a matching option — Sam's own business, Divinity DJs, is set to **"Other."** So every one of the 6 built-in cards is literally searching for e.g. *"trend shifts in the Other industry"* — meaningless, hence generic-feeling reports.

This isn't a bug in the search/prompt logic — it's that the system has never been given a real industry description for a lot of real businesses.

## 5. Proposed fix (full write-up: `docs/market-agent-industry-relevance-proposal.md`)

1. **Transparency** — per-card (i) info icon showing exactly what that card searched for, industry value included, so it's obvious when it's using something generic vs. specific.
2. **A real field to fill in** — add a free-text "describe your business/industry" field (the dropdown alone can't cover every business), and use that instead of the dropdown for Market Agent's `{industry}`. Show an on-page notice when it's missing/generic, telling the user exactly what to add and why.
3. **Already available today** — Custom Analysts don't depend on any of this; worth pointing Sam at that as a partial answer he can use right now.

## 6. Questions to resolve in the meeting

- Does Sam agree with this approach, or does he have a different idea of what "relevant" should look like?
- Should the same industry-description field also feed Competitor Agent (which currently doesn't use industry context at all — it's purely URL-based discovery)?
- Any real example report Sam found unhelpful, to sanity-check the fix against once built?
- Priority vs. the other 2 items from the same feedback batch: Lead Researcher tab-switch (already fixed), Competitor Agent "Discovery Failed" (root-caused to a bad OpenAI key on the deployed server — awaiting a retry to confirm it's resolved).

## 7. Related docs

- `docs/market-agent-api-contract.md` — full technical API contract
- `docs/superpowers/specs/2026-07-07-sales-market-agent.md` — original build spec
- `docs/market-agent-industry-relevance-proposal.md` — the Sam-facing proposal for this issue
- `docs/QA_FINDINGS.md` — Session 59 production QA results (all 4 modules)
