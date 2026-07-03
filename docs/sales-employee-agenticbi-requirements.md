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
A list of competitors the business owner is tracking (added by pasting their website URL). Each competitor row also shows small icons for their **LinkedIn, Facebook, Instagram, and YouTube** presence — these are four separate platforms we'd be pulling data from, not one generic "social media" feed (see the integration requirements section below — each has its own cost and setup). "View Report" opens the full intelligence on that specific competitor: pricing changes, feature launches, news, and activity across those platforms. New competitors are added just by dropping in a website link, and there's a "Schedule Report" shortcut on this screen too, for a report about competitors specifically.

### 3. Market Agent
A feed of market intelligence, laid out as cards from different "analyst" angles — think of it like getting a briefing from several specialists at once, each looking at a different piece of the puzzle:
- **Trend Analyst** — growth patterns (e.g. "Rise of micro-SaaS acquisitions")
- **Futurist** — longer-term predictions (e.g. "Zero-UI interfaces by 2026")
- **Cultural Analyst** — social/cultural shifts affecting how people buy
- **Market Research Analyst** — competitor and market data synthesis
- **Consumer Insights Analyst** — buyer behavior and preference trends
- **Innovation Strategist** — early signals of new ideas/technologies worth watching
- **Business Intelligence Analyst** — patterns across the business's own operational data

Each card shows a confidence score, an impact level, or a timeframe, so the owner can judge how seriously to take it, plus a bookmark and share icon on each. There's also a top-of-page "What's Changing" summary auto-generated from all of the above, and an **"Add Custom Report" tile** — the owner can define their own tailored analyst beyond the 7 built-in ones (e.g., something specific to their industry). This screen also has a "Schedule Report" shortcut, same as Competitor Agent.

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

## What's Actually Required to Connect Each Platform (and what it costs as usage grows)

This wasn't spelled out clearly before, so here it is platform by platform. The short version: **none of these need us to apply for official developer access from LinkedIn, Facebook, Instagram, or a news outlet** — we go through Apify (a third-party data platform) instead, which is faster to set up but is also exactly where the legal gray area already flagged to Sam comes from. Costs below are all **pay-as-you-go — they grow with how much the product is actually used**, not a flat fee.

### LinkedIn (Lead Researcher + Competitor Agent)
- **What's needed:** An Apify account + API key. Several LinkedIn data tools on Apify work **without ever logging into a LinkedIn account** (no "cookie," no risk of a personal LinkedIn account getting banned) — trading a bit of data depth for safety. This is the option we'd use.
- **Cost:** roughly **$4–$10 per 1,000 LinkedIn profiles looked up.** Scales directly with how many leads customers research and how many competitors' LinkedIn pages get checked.
- **Nothing to apply for.** No waiting on LinkedIn's approval — this is exactly why it's fast to build, and exactly why it's the item Sam is running by his lawyer.

### Facebook (Competitor Agent)
- **What's needed:** Same Apify account, a different tool within it. No Facebook Developer app or approval needed for this — that's a separate, stricter process for a different kind of access we're not using here.
- **Cost:** roughly **$2 per 1,000 posts pulled.** Scales with number of competitors tracked and how often we check them.

### Instagram (Competitor Agent)
- **What's needed:** Same Apify account, another tool within it. No official Instagram API approval needed.
- **Cost:** roughly **$1.50 per 1,000 posts, $2.30 per 1,000 comments.**

### YouTube (Competitor Agent)
- **What's needed:** Same Apify account, another tool within it. **Alternative:** YouTube also has its own official, free data API from Google with a daily usage cap — worth considering as a cheaper/safer option for YouTube specifically, since it's an approved, ToS-compliant path (unlike the others).
- **Cost via Apify:** roughly **$2.40 per 1,000 videos pulled.**

### News Aggregation (Market Agent + the pipeline's "News aggregation" step)
- **This one is different — it's not an Apify product, it needs its own separate subscription.** This wasn't mentioned before and is a real, additional monthly cost on top of everything else.
- The best-known option (NewsAPI.org) requires a **$449/month** plan for any real production use — their free tier is explicitly blocked from commercial/live apps.
- **Cheaper alternatives exist and are worth evaluating first:** Currents API (~$69/month for 75,000 requests/month), TheNewsAPI (~$40–49/month), Mediastack (~$25/month), GNews (~$84/month). These trade off coverage/freshness for price — needs real testing (same "don't just pick the cheapest number" principle from the cost breakdown doc) before picking one.
- **Cost scales differently than Apify** — it's usually a flat monthly tier with a request cap, not pay-per-record, so as more customers use the Market Agent, we may need to upgrade tiers rather than pay smoothly per use. Worth designing some caching/sharing of news lookups across customers so we're not paying for the same article search repeatedly.

### The bottom line on cost scaling
Apify-based platforms (LinkedIn, Facebook, Instagram, YouTube) cost **more, the more this product is actually used** — more leads researched, more competitors tracked, more often the reports refresh. News aggregation costs **jump in steps** (subscription tiers) rather than smoothly. Both are separate from — and additional to — the AI "brain" costs already covered in the voice agents cost doc (Sales Employee doesn't use voice, but does still use an AI model to turn the raw scraped data into the actual report text).

---

## What Is NOT Included in This Version

- **No CRM integration.** The "Push to CRM" button appears in the mockup, but there is nowhere for it to actually push to yet — no CRM has been chosen or connected. Confirmed by Sam: skip for now.
- **No cold-calling or outbound phone calls.** This is a research tool only. Making actual outbound sales calls is a *different, separate* product ("Outbound Calling Employee"), which is deliberately on hold until this one and the Executive Assistant are both done.
- **No legal sign-off yet on how leads are sourced.** Scraping LinkedIn profiles through a third-party tool like Apify can raise LinkedIn Terms-of-Service concerns, and Canada's anti-spam law (CASL) may apply to how leads are then contacted. Sam has confirmed this will be run by his lawyer before this goes live for real customer use — this is not blocking the build, but it is blocking a public launch.

---

## Known Technical Risks (for the team, in plain terms)

- **Scraping LinkedIn, Facebook, Instagram, and YouTube is a legal gray area on all four, not just LinkedIn.** Apify offers all of these as a service, but each platform's own terms discourage automated scraping of their site. This is exactly the item Sam is running by his lawyer — worth confirming it covers all four platforms, not just LinkedIn specifically, since Competitor Agent touches all of them.
- **The AI-generated reports (predicted email, pain points, icebreakers) are inherently a best guess, not a guarantee.** The confidence scores shown in the mockup (e.g. "92%") reflect this — they should be understood by the sales rep as "AI's best estimate," not verified fact.
- **The Market Agent's 7 analyst cards need a real data source behind them**, not just an AI making things up from general knowledge. This will draw on the same pipeline (website/news/competitor data via Apify) rather than being invented by the AI with no grounding.
- **The "Add Custom Report" feature is open-ended by nature.** The 7 built-in analyst cards are a fixed, known scope. A user-defined custom report could ask for almost anything, which is harder to guarantee quality/data-grounding for. Worth scoping as a later addition rather than day-one, unless Sam wants it in the first release.

---

## Build Sequence

Confirmed order: **Executive Assistant (done) → Sales Employee (this one, starting now) → Outbound Calling Employee (deferred, after this)**. Yuvraj is building the UI for this product; Rahul is building the backend/AI pipeline.

Given the size of this (4 real screens, each needing real data pulled from Apify and processed through several AI steps), the fastest path to something usable is to ship **Lead Researcher first** as a standalone piece — it's the most self-contained of the four and doesn't depend on the other three being done.

---

## Sources (platform integration costs, researched 2026-07-02)

- [Best LinkedIn Scrapers on Apify 2026](https://use-apify.com/docs/best-apify-actors/best-linkedin-scrapers)
- [Apify LinkedIn Profile Scraper — No Cookies](https://apify.com/data-slayer/linkedin-profile-scraper)
- [Best Social Media Scrapers on Apify 2026](https://use-apify.com/docs/best-apify-actors/best-social-media-scrapers)
- [Apify Facebook Posts Scraper](https://apify.com/apify/facebook-posts-scraper)
- [Apify Instagram Scraper](https://apify.com/apidojo/instagram-scraper)
- [Apify Pricing](https://apify.com/pricing)
- [NewsAPI.org Pricing](https://newsapi.org/pricing)
- [Currents API Pricing](https://currentsapi.services/en/pricing)
- [TheNewsAPI Pricing](https://www.thenewsapi.com/pricing)
