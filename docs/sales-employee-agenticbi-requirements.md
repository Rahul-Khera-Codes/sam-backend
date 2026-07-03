# Sales Employee ("AgenticBI") — Full Requirements

**Prepared by:** Rahul Khera
**Date:** July 2, 2026
**For:** Sam Maisuria, Charles, Yuvraj Singh

---

## What Is This?

The Sales Employee is a research and intelligence tool, not a talking AI agent — there's no voice involved. Think of it as a dashboard that does the homework a sales rep would normally spend hours on: researching a lead, watching competitors, and tracking market trends. It's built on 4 screens (modules), described below.

This is a separate product from the "Executive Assistant" (Remi) and separate from the older voice-based "Outbound Calling" concept (that one is deferred — see `docs/sales-agent-overview.md`).

---

## The 4 Screens

### 1. Lead Researcher
The core screen. The salesperson pastes in a LinkedIn profile URL and clicks "Generate Report." Within a short wait, they get:
- **Who this person is** — name, title, company, location, number of connections.
- **How to reach them** — a predicted email address with a confidence score (e.g. "High, 92%"), and a suggested best day/time to reach out.
- **What they're dealing with at work** — a few bullet points on what this person seems focused on right now (pulled from their recent activity/posts).
- **Their pain point and our angle** — what problem they seem to be struggling with, and a suggested way to pitch our product against that specific problem.
- **Something personal to break the ice** — a couple of interests/hobbies, plus one suggested icebreaker line based on something they recently posted.
- **A ready-to-send outreach email** — fully written, referencing the icebreaker and the pain point, with a "Copy to Clipboard" button.
- Buttons to **export as PDF**, **email the report**, or **push to a CRM** (see "Not Included" below — this button exists on the mockup but the CRM connection itself is not being built yet).
- A history of past lookups and a list of saved leads.

### 2. Competitor Agent
A list of competitors the business owner is tracking (added by pasting their website URL). For each competitor, there's a "View Report" button that opens intelligence on that specific competitor — pricing changes, feature launches, news, social media activity. New competitors are added just by dropping in a website link.

### 3. Market Agent
A feed of market intelligence, laid out as cards from different "analyst" angles — think of it like getting a briefing from several specialists at once, each looking at a different piece of the puzzle:
- **Trend Analyst** — growth patterns (e.g. "Rise of micro-SaaS acquisitions")
- **Futurist** — longer-term predictions (e.g. "Zero-UI interfaces by 2026")
- **Cultural Analyst** — social/cultural shifts affecting how people buy
- **Market Research Analyst** — competitor and market data synthesis
- **Consumer Insights Analyst** — buyer behavior and preference trends
- **Innovation Strategist** — early signals of new ideas/technologies worth watching
- **Business Intelligence Analyst** — patterns across the business's own operational data

Each card shows a confidence score, an impact level, or a timeframe, so the owner can judge how seriously to take it. There's also a top-of-page "What's Changing" summary auto-generated from all of the above.

### 4. Report Scheduler
Lets the owner set up an automatic weekly (or daily/monthly/custom) email digest that pulls together highlights from Lead Researcher, Competitor Agent, and Market Agent into one email, sent to a list of recipients (e.g. the exec team, the marketing team). There's a live preview of exactly what the email will look like, and a "Send Test Email" button before turning it on.

---

## How It Actually Works Behind the Scenes (confirmed with Sam)

This is the pipeline that powers all 4 screens above:

**Company Input → Website scrape → LinkedIn enrichment → AI industry classification → Competitor discovery → News aggregation → Sentiment analysis → Opportunity report**

In plain terms: start from a company or person, pull real data about them from the web and LinkedIn, have the AI figure out what industry/situation they're in, find out who their competitors are, gather recent news about them, judge whether that news is good or bad for them, and turn all of that into the report the owner actually reads.

**Where the data comes from:** [Apify](https://apify.com/) — a web-scraping/data platform. This is the confirmed data source; no other data provider is planned right now.

**The finished report is built from these sections:**
Industry overview, Market trends, Competitor analysis, Pricing intelligence, Demand signals, Hiring signals, New opportunities, Risks, Lead opportunities, Recommended sales angles.

---

## What Is NOT Included in This Version

- **No CRM integration.** The "Push to CRM" button appears in the mockup, but there is nowhere for it to actually push to yet — no CRM has been chosen or connected. Confirmed by Sam: skip for now.
- **No cold-calling or outbound phone calls.** This is a research tool only. Making actual outbound sales calls is a *different, separate* product ("Outbound Calling Employee"), which is deliberately on hold until this one and the Executive Assistant are both done.
- **No legal sign-off yet on how leads are sourced.** Scraping LinkedIn profiles through a third-party tool like Apify can raise LinkedIn Terms-of-Service concerns, and Canada's anti-spam law (CASL) may apply to how leads are then contacted. Sam has confirmed this will be run by his lawyer before this goes live for real customer use — this is not blocking the build, but it is blocking a public launch.

---

## Known Technical Risks (for the team, in plain terms)

- **LinkedIn scraping is a legal gray area.** Apify offers this as a service, but LinkedIn's own terms discourage automated scraping of their site. This is exactly the item Sam is running by his lawyer.
- **The AI-generated reports (predicted email, pain points, icebreakers) are inherently a best guess, not a guarantee.** The confidence scores shown in the mockup (e.g. "92%") reflect this — they should be understood by the sales rep as "AI's best estimate," not verified fact.
- **The Market Agent's 7 analyst cards need a real data source behind them**, not just an AI making things up from general knowledge. This will draw on the same pipeline (website/news/competitor data via Apify) rather than being invented by the AI with no grounding.

---

## Build Sequence

Confirmed order: **Executive Assistant (done) → Sales Employee (this one, starting now) → Outbound Calling Employee (deferred, after this)**. Yuvraj is building the UI for this product; Rahul is building the backend/AI pipeline.

Given the size of this (4 real screens, each needing real data pulled from Apify and processed through several AI steps), the fastest path to something usable is to ship **Lead Researcher first** as a standalone piece — it's the most self-contained of the four and doesn't depend on the other three being done.
