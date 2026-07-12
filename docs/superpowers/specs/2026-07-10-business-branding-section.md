# Business Branding section — spec

*Requested by Sam (Jul 10, 2026): build out the Branding tab per the attached
mockup (`Branding (2).pdf`), then use that data to give Market Agent real
industry/business context instead of the generic `businesses.type` field.*

## Background / why now

Sam has shared this Branding PDF multiple times before; it's now clear why —
it's meant to be the real source of business/industry context for the Sales
Employee agents (starting with Market Agent's relevance problem), not just a
cosmetic branding page.

Checked the mockup against the current build: only **Company Logo** exists
today (`businesses.logo_url`). Everything else in the PDF — Color Palette,
Typography, Core Brand, Communication Strategy, Competitive Analysis, Market
Insights — is net new.

## Data model

New table `business_branding`, 1:1 with `businesses` via `business_id`
(matches the `business_documents` pattern — dedicated table rather than more
columns on the already-wide `businesses` table):

| Column | Type | Notes |
|---|---|---|
| `business_id` | UUID, unique, FK → businesses | |
| `primary_color` / `secondary_color` / `accent_color` | TEXT | hex values |
| `heading_font` / `body_font` | TEXT | |
| `mission` | TEXT | "What you do / Mission" |
| `unique_value_claims` | TEXT[] | |
| `extra_guidelines` | TEXT | tone/voice notes |
| `use_emojis` | BOOLEAN | default true |
| `competitors` | TEXT[] | names only — branding context, NOT the same list as Competitor Agent (see below) |
| `competitor_strengths` / `competitor_weaknesses` | TEXT | |
| `key_differentiator` | TEXT | |
| `emerging_trends` | TEXT | |
| `target_niche` | TEXT | |

RLS: members read their own business's row (via `user_roles` join, same as
`business_documents`); writes only via service role (backend-mediated).

`logo_url` stays on `businesses` — not duplicated here.

## Backend

New router (or extend an existing settings router) — CRUD matching the
`business_documents` convention:
- `GET /business/branding` — fetch (or empty defaults if no row yet)
- `PATCH /business/branding` — upsert

**Market Agent change:** `market_agent.py` currently builds `{industry}` from
`biz.get("type") or "their industry"` (line ~272).

**Implementation note (found while building, corrects the original plan
above):** every analyst query embeds this value as "...in the `{industry}`
industry" — both in the Exa query text and the system prompt — so it has to
stay a short noun phrase. Concatenating `mission` (a full sentence) into that
slot reads as broken grammar ("...in the we help local restaurants book more
events industry"). Implemented instead: prefer `business_branding.target_niche`
alone (already written as a short, specific market segment — a much closer
grammatical and semantic match for "industry" than `mission`), falling back to
the current `businesses.type`-based string when Branding data doesn't exist
yet. `mission` isn't used in the industry-context string for now — a good
place to revisit later if we want to enrich the prompt further.

## Frontend

Extend the Branding tab in `BusinessSettings.tsx` (currently only renders
Company Logo) with 4 new sections per the mockup: Visual Identity (color
palette + typography, logo already exists), Core Brand, Communication
Strategy, Competitive Analysis, Market Insights. New API calls in
`voiceAgentApi.ts` for the GET/PATCH endpoints above.

## Explicit decision: Competitors list stays separate from Competitor Agent

The Branding "Competitors" field is a lightweight name-only list for context.
Competitor Agent's tracked competitors require a real website URL (it
actually scrapes them). Merging the two would force a URL requirement into
what's meant to be quick branding context, or produce incomplete Competitor
Agent entries. Keeping them separate avoids that mismatch. (Possible small
future nicety: Competitor Agent's "add competitor" could suggest names
already listed here — not in scope now.)

## Impact / risk

- New table + RLS — no impact on existing tables/flows.
- Market Agent's industry-context change has a safe fallback (existing
  `type`-based string) for any business that hasn't filled in branding yet —
  won't regress current behavior for businesses without this data.
- Frontend is purely additive to the existing Branding tab — no existing
  UI removed or changed structurally, just new sections added below Logo.
